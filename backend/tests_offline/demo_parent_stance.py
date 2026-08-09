# -*- coding: utf-8 -*-
"""
demo_parent_stance.py  —  parent_child / parent_centered（agent B）条件下的演示 & 断言

跑法（无需 API key、不联网，LLM 全部被 stub）：
    python tests_offline/demo_parent_stance.py

演示两件事：
  1) 用户说到 parent_centered 关键词（"冲突"）时，B 的 system prompt 里出现
     === 背景知识（仅供参考）=== 单卡（parent_power_struggle）。
  2) 同一张卡第二次命中 -> 追加 [相关背景]（一跳关联卡）。
文件名以 demo_ 开头，不会被 run_all.py（只收 test_*.py）纳入回归。
"""
import builtins, io, json, os, sys, tempfile

# 定位 agora_backend（含 agentwake_new.py 的目录），无论本脚本放在哪都能跑
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = HERE if os.path.exists(os.path.join(HERE, "agentwake_new.py")) else os.path.dirname(HERE)
os.chdir(BACKEND)                      # KB / scenes 是 cwd 相对路径
sys.path.insert(0, BACKEND)
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")

import agentwake_new as aw


def run(user_inputs, moderator_state="Exploration"):
    """驱动一场 parent_child 会话，全程把发言权交给 B（parent_centered）。
    返回 B 的 system prompt 列表（按出现顺序）。"""
    b_prompts = []

    def fake_create_response(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        sysc = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if sysc.startswith("You are Admin-2"):
            return "B"                       # 下一位固定选 B
        if sysc.startswith("You are Admin-1"):
            return "NEXT = B"
        if "deliberation moderator" in sysc:
            return f"[Moderator]\nmode: S\nstate: {moderator_state}\nstall: false\ngoal: g\n[/Moderator]"
        if messages[0]["role"] == "user" and "Distill" in messages[-1]["content"]:
            return "stub."
        if sysc.startswith("You are ChatbotB"):
            b_prompts.append(sysc)
        return "[MESSAGE]\nok\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"

    aw.create_response = fake_create_response

    log_dir = tempfile.mkdtemp(prefix="demo_parent_")
    info_path = os.path.join(log_dir, "info.jsonl")
    with open(info_path, "w", encoding="utf-8") as f:
        # A/B/C 三个 agent；B 是 parent_centered
        json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)

    it = iter(user_inputs)
    builtins.input = lambda prompt="": next(it)
    sys.argv = ["x", "--scenario_type", "parent_child", "--skip_intake",
                "--info", info_path, "--lang", "zh",
                "--prefer_agents", "0", "--novelty_threshold", "0",
                "--max_user_gap", "1", "--log_dir", log_dir]
    cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    return b_prompts


def extract_block(prompt):
    """从 system prompt 里截出 === 背景知识 ... === 到下一个 === 之前的内容。"""
    key = "=== 背景知识"
    i = prompt.find(key)
    if i == -1:
        return "(本轮无背景知识区块)"
    tail = prompt[i:]
    j = tail.find("\n===", 1)          # 下一个区块标题
    return tail if j == -1 else tail[:j]


print("=" * 70)
print("演示 1：parent_centered（B）命中关键词『冲突』-> 单卡")
print("=" * 70)
# 用户第一句带 parent_power_struggle 关键词『冲突』
b = run(["我们俩总是有冲突", "/exit"], moderator_state="Exploration")
hits = [p for p in b if "背景知识" in p]
assert hits, "期望 B 命中 parent_power_struggle 单卡，但没有背景知识区块"
assert "相关背景" not in hits[0], "第一次命中不应出现 [相关背景]"
print(extract_block(hits[0]))

print("\n" + "=" * 70)
print("演示 2：同一张卡第二次命中 -> 追加 [相关背景]（一跳关联）")
print("=" * 70)
b = run(["我们俩总是有冲突", "我们俩总是有冲突", "/exit"], moderator_state="Exploration")
hits = [p for p in b if "背景知识" in p]
assert len(hits) >= 2, f"期望至少两次命中，实际 {len(hits)}"
assert "相关背景" not in hits[0], "第一次不应出现 [相关背景]"
assert "相关背景" in hits[1], "第二次（重复命中）应出现 [相关背景]"
print(extract_block(hits[1]))

print("\n[OK] parent 条件下：单卡命中 + 重复命中的一跳关联展开，均符合预期。")
