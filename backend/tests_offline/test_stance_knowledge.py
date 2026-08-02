# -*- coding: utf-8 -*-
"""Acceptance for Task 1 (Stance Knowledge wiring in agentwake_new.py):

  1. keyword hit   -> the matching stance agent's system prompt carries the
                      specific `=== 背景知识 ... ===` card for that keyword.
  2. no keyword    -> NO 背景知识 block appears (the module's generic fallback is
                      suppressed at the integration layer, per agreed behavior).
  3. legacy / no KB-> get_stance_knowledge_block returns "" (no scenario_type,
                      no stance, or a scenario with no knowledge base).

All LLM calls are stubbed. The stance knowledge base lives under cwd-relative
background_templates/, so it is copied into the throwaway test cwd.
"""
import builtins, io, json, os, shutil, sys

from _harness import bootstrap, Checker

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
aw = bootstrap("agentwake_stanceknow_")
# Bring the cwd-relative data the run reads (KB + scene files) into the temp cwd.
shutil.copytree(os.path.join(BACKEND, "background_templates"), "background_templates")
shutil.copytree(os.path.join(BACKEND, "scenes"), "scenes")

_ck = Checker(); check = _ck.check

# ----------------------------------------------------------------- unit: case 3
from stance_knowledge import load_stance_knowledge, get_stance_knowledge_block as _g
_k = load_stance_knowledge()
check("legacy: scenario_type=None -> ''",
      _g(None, "parent_centered", "我们俩总是有冲突", "zh", knowledge=_k) == "")
check("legacy: stance=None -> ''",
      _g("parent_child", None, "我们俩总是有冲突", "zh", knowledge=_k) == "")
check("no KB: unknown scenario -> ''",
      _g("foobar", "parent_centered", "冲突", "zh", knowledge=_k) == "")


# ------------------------------------------------------- integration: cases 1&2
def _run(user_msg):
    """Drive one parent_child session; return the list of agent system prompts."""
    captured = []
    def fake(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if sys_c.startswith("You are Admin-2"):
            return "B"                       # route to agent B (parent_centered)
        if sys_c.startswith("You are Admin-1"):
            return "NEXT = B"
        if "deliberation moderator" in sys_c:
            return "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n[/Moderator]"
        if messages[0]["role"] == "user" and "Distill" in messages[-1]["content"]:
            return "stub."
        if sys_c.startswith("You are Chatbot"):
            captured.append(sys_c)
        return "[MESSAGE]\nok\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
    aw.create_response = fake

    with open("info3.jsonl", "w", encoding="utf-8") as f:
        json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)
    inputs = iter([user_msg, "/exit"])
    builtins.input = lambda prompt="": next(inputs)
    sys.argv = ["x", "--scenario_type", "parent_child", "--skip_intake", "--info", "info3.jsonl",
                "--lang", "zh", "--prefer_agents", "0", "--novelty_threshold", "0", "--log_dir", "lg"]
    cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    return captured


# case 1: "冲突" is a parent_centered (agent B) keyword -> specific card injected.
caps = _run("我们俩总是有冲突")
hit_specific = [p for p in caps if "谁来做决定" in p]   # text unique to that card
check("keyword hit: specific card reaches the parent_centered agent's prompt",
      len(hit_specific) >= 1, f"{len(hit_specific)}/{len(caps)} prompts had the card")

# case 2: no keyword anywhere -> no 背景知识 block on any agent prompt.
caps = _run("嗯嗯我知道了谢谢你")
with_block = [p for p in caps if "背景知识" in p]
check("no keyword: no 背景知识 block appears on any agent prompt",
      not with_block, f"{len(with_block)}/{len(caps)} prompts unexpectedly had a block")

_ck.finish("STANCE KNOWLEDGE CHECKS PASSED")
