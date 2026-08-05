# -*- coding: utf-8 -*-
"""Acceptance for the Task 1 extension (preloaded hint -> setup-time background):

  1. hint hits a keyword -> that agent's EVERY turn carries a fixed
     `=== BACKGROUND (from setup) ===` block, identical all session.
  2. hint empty / absent  -> no such block.
  3. hint set but matches nothing -> no such block (no generic fallback).
  4. Independent of the per-turn dynamic channel: both blocks can co-exist in
     one prompt (setup from the hint + dynamic from the latest user message).

Plus a unit check on agent_assembly.build_agent_spec's new hint handling.
All LLM calls stubbed; KB is cwd-relative so it's copied into the temp cwd.
"""
import builtins, io, json, os, shutil, sys

from _harness import bootstrap, Checker

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
aw = bootstrap("agentwake_hint_")
shutil.copytree(os.path.join(BACKEND, "background_templates"), "background_templates")
# stance_templates/ holds the stance definitions (assignment, prompt text,
# per-phase focus, labels) that stance.py reads at cwd-relative paths.
shutil.copytree(os.path.join(BACKEND, "stance_templates"), "stance_templates")
shutil.copytree(os.path.join(BACKEND, "scenes"), "scenes")
# decision/emotion presets are needed for the build_agent_spec unit check.
shutil.copytree(os.path.join(BACKEND, "decision"), "decision")
shutil.copytree(os.path.join(BACKEND, "emotion"), "emotion")

_ck = Checker(); check = _ck.check

SETUP_HDR = "=== BACKGROUND (from setup) ==="
DYNAMIC_HDR = "背景知识"                       # header of the per-turn channel (zh)

# ------------------------------------------------- unit: build_agent_spec (hint)
import agent_assembly as aa
import stance_knowledge as sk
_kb = sk.load_stance_knowledge()
# A is child_centered; "不听话" is a child_defiance keyword.
_spec_hit = aa.build_agent_spec("A", "Rational", "Joy", scenario_type="parent_child",
                                lang="zh", hint="孩子最近很不听话", stance_knowledge=_kb)
check("spec: matching hint -> non-empty preloaded_knowledge (body, no header)",
      _spec_hit["preloaded_knowledge"] and SETUP_HDR not in _spec_hit["preloaded_knowledge"]
      and DYNAMIC_HDR not in _spec_hit["preloaded_knowledge"],
      repr(_spec_hit["preloaded_knowledge"][:40]))
_spec_none = aa.build_agent_spec("A", "Rational", "Joy", scenario_type="parent_child",
                                 lang="zh", hint=None, stance_knowledge=_kb)
check("spec: no hint -> ''", _spec_none["preloaded_knowledge"] == "")
_spec_miss = aa.build_agent_spec("A", "Rational", "Joy", scenario_type="parent_child",
                                 lang="zh", hint="今天天气不错", stance_knowledge=_kb)
check("spec: non-matching hint -> '' (no fallback)", _spec_miss["preloaded_knowledge"] == "")


# --------------------------------------------------------- integration: full run
def _run(info_agents, user_msg):
    """Drive one parent_child session; return {agent_name: [system_prompts]}."""
    by_agent = {}
    def fake(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        sysc = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if sysc.startswith("You are Admin-2"):
            return "A"                       # keep routing to A -> many A prompts
        if sysc.startswith("You are Admin-1"):
            return "NEXT = A"
        if "deliberation moderator" in sysc:
            return "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n[/Moderator]"
        if messages[0]["role"] == "user" and "Distill" in messages[-1]["content"]:
            return "stub."
        if sysc.startswith("You are Chatbot"):
            name = sysc.split()[2]           # "You are ChatbotA in ..."
            by_agent.setdefault(name, []).append(sysc)
        return "[MESSAGE]\nok\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
    aw.create_response = fake

    with open("info3.jsonl", "w", encoding="utf-8") as f:
        json.dump({"agents": info_agents}, f, ensure_ascii=False)
    inputs = iter([user_msg, "/exit"])
    builtins.input = lambda prompt="": next(inputs)
    sys.argv = ["x", "--scenario_type", "parent_child", "--skip_intake", "--info", "info3.jsonl",
                "--lang", "zh", "--prefer_agents", "0", "--novelty_threshold", "0", "--log_dir", "lg"]
    cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    return by_agent


# A (child_centered) has a matching hint; B none; C a non-matching hint.
info = {
    "A": {"decision": "Rational", "emotion": "Joy", "hint": "孩子最近很不听话"},
    "B": {"decision": "Avoidant", "emotion": "Sadness"},                       # no hint key
    "C": {"decision": "Spontaneous", "emotion": "Anger", "hint": "今天天气不错"},  # no match
}
# The user message hits a child_social_withdrawal keyword -> A's DYNAMIC channel.
by_agent = _run(info, "孩子在学校交友困难没朋友")
a_prompts = by_agent.get("ChatbotA", [])
b_prompts = by_agent.get("ChatbotB", [])
c_prompts = by_agent.get("ChatbotC", [])

# 1. every A turn carries the setup block, with identical content ("自主性" is
#    unique to the child_defiance card the hint matched).
check("hint hit: A carries setup block every turn",
      len(a_prompts) >= 2 and all(SETUP_HDR in p and "自主性" in p for p in a_prompts),
      f"{sum(SETUP_HDR in p for p in a_prompts)}/{len(a_prompts)} A prompts had it")
_setup_slices = [p.split(SETUP_HDR, 1)[1].split("===", 1)[0] for p in a_prompts]
check("hint hit: setup block content is identical all session",
      len(set(_setup_slices)) == 1, f"{len(set(_setup_slices))} distinct setup bodies")

# 2 & 3. no setup block for the agent with no hint / a non-matching hint.
check("no hint: B has no setup block", b_prompts and not any(SETUP_HDR in p for p in b_prompts))
check("non-matching hint: C has no setup block", c_prompts and not any(SETUP_HDR in p for p in c_prompts))

# 4. independence: at least one A prompt (post user message) carries BOTH the
#    setup block AND the dynamic block, with distinct headers.
both = [p for p in a_prompts if SETUP_HDR in p and DYNAMIC_HDR in p and "内向" in p]
check("channels independent: setup + dynamic co-exist in one prompt",
      len(both) >= 1, f"{len(both)} A prompts had both channels")

_ck.finish("STANCE HINT CHECKS PASSED")
