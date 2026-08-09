# -*- coding: utf-8 -*-
"""Acceptance for Task 2 (cross-session memory in agentwake_new.py + session_memory.py):

  1. session end  -> memory/{user_id}__{scenario_type}.jsonl gains one APPENDED
                     record (a second session grows the file to 2 lines, it is
                     never overwritten).
  2. next session -> the first-round agent system prompts carry the previous
                     session's summary text.
  3. placement    -> the PREVIOUS SESSION MEMORY block sits right after
                     DOMAIN BACKGROUND (same level as KNOWN USER CONTEXT).
  4. formatting   -> build_session_memory_text is language-linked and returns ""
                     for no records.

All LLM calls are stubbed (the summariser included), so no key / network.
"""
import builtins, io, json, os, re, shutil, sys

from _harness import bootstrap, Checker

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
aw = bootstrap("agentwake_sessmem_")
shutil.copytree(os.path.join(BACKEND, "background_templates"), "background_templates")
# stance_templates/ holds the stance definitions (assignment, prompt text,
# per-phase focus, labels) that stance.py reads at cwd-relative paths.
shutil.copytree(os.path.join(BACKEND, "stance_templates"), "stance_templates")
shutil.copytree(os.path.join(BACKEND, "scenes"), "scenes")

_ck = Checker(); check = _ck.check

# ------------------------------------------------------ unit: text builder (4)
import session_memory as sm
check("empty records -> ''", sm.build_session_memory_text([], "zh") == "")
_recs = [{"date": "2026-07-28", "summary": "上次聊到甲乙取舍", "open_threads": ["通勤成本"]}]
_zh = sm.build_session_memory_text(_recs, "zh")
_en = sm.build_session_memory_text(_recs, "en")
check("zh header language-linked", "上次会话记忆" in _zh and "上次聊到甲乙取舍" in _zh, _zh)
check("en header language-linked", "PREVIOUS SESSION MEMORY" in _en, _en)

# ------------------------------------------------------ unit: placement (3)
_sp = aw.ChatAgent("A", "ChatbotA", "(role)").system_prompt(
    scene="(s)", name_map={"A": "ChatbotA"},
    phase_context="=== DELIBERATION STATE ===\nx",
    known_context="=== 已知用户信息（用户提供，勿重复询问）===\nk",
    domain_background="=== 领域背景（系统提供，非用户所说，仅供参考）===\nd",
    session_memory_text="=== 上次会话记忆（前几次讨论的摘要，非本次用户输入）===\nm",
    lang="zh")
_headers = re.findall(r'^===.*===$', _sp, flags=re.M)
_i_dom = next(i for i, h in enumerate(_headers) if "领域背景" in h)
_i_mem = next(i for i, h in enumerate(_headers) if "上次会话记忆" in h)
_i_phase = next(i for i, h in enumerate(_headers) if "DELIBERATION STATE" in h)
check("memory block sits after DOMAIN BACKGROUND and before phase context",
      _i_dom < _i_mem < _i_phase, str(_headers))

# ------------------------------------------------- integration: append + carry
SUMMARY = "用户在甲乙两家公司间权衡，倾向甲但担心加班强度，未就通勤达成结论。"
def _fake_factory(capture):
    def fake(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        sysc = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if "conversation-archival assistant" in sysc:   # the summariser call
            return json.dumps({"summary": SUMMARY, "open_threads": ["通勤成本", "试用期条款"]},
                              ensure_ascii=False)
        if sysc.startswith("You are Admin-2"):
            return "A"
        if sysc.startswith("You are Admin-1"):
            return "NEXT = A"
        if "deliberation moderator" in sysc:
            return "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n[/Moderator]"
        if messages[0]["role"] == "user" and "Distill" in messages[-1]["content"]:
            return "stub."
        if sysc.startswith("You are Chatbot"):
            capture.append(sysc)
        return "[MESSAGE]\nok\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
    return fake

with open("info3.jsonl", "w", encoding="utf-8") as f:
    json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)

def _run(session_no):
    caps = []
    aw.create_response = _fake_factory(caps)
    inputs = iter(["我担心加班强度太大身体吃不消", "/exit"])
    builtins.input = lambda prompt="": next(inputs)
    sys.argv = ["x", "--scenario_type", "employment", "--skip_intake", "--user_id", "demo_user",
                "--info", "info3.jsonl", "--lang", "zh", "--prefer_agents", "0",
                "--novelty_threshold", "0", "--log_dir", f"lg{session_no}"]
    _cap = io.StringIO(); real = sys.stdout; sys.stdout = _cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    return caps

mem_file = os.path.join("memory", "demo_user__employment.jsonl")

_run(1)
check("session 1: memory file created", os.path.exists(mem_file))
check("session 1: one record", sum(1 for _ in open(mem_file, encoding="utf-8")) == 1)

caps2 = _run(2)
check("session 2: record appended (file grows to 2, not overwritten)",
      sum(1 for _ in open(mem_file, encoding="utf-8")) == 2)
carry = [p for p in caps2 if SUMMARY[:12] in p]
check("session 2: agent prompts carry the previous session's summary",
      len(carry) >= 1, f"{len(carry)}/{len(caps2)} prompts carried it")

_ck.finish("SESSION MEMORY CHECKS PASSED")
