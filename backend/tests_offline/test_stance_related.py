# -*- coding: utf-8 -*-
"""Acceptance for one-hop related_cards expansion (the [相关背景] block), driven
by an A-OR-B trigger on the DYNAMIC stance-knowledge channel:

  A. same agent hits the SAME card twice in a session -> 2nd hit expands, 1st
     does not.
  B. moderator_state is in Convergence -> any hit expands, even a first hit.
  neither -> single card only, no [相关背景].

peek_matched_card_id() is also unit-checked. All LLM calls are stubbed.
--max_user_gap 1 keeps exactly one agent turn between user inputs, so the hit
sequence is deterministic.
"""
import builtins, io, json, os, shutil, sys

from _harness import bootstrap, Checker

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
aw = bootstrap("agentwake_related_")
shutil.copytree(os.path.join(BACKEND, "background_templates"), "background_templates")
# stance_templates/ holds the stance definitions (assignment, prompt text,
# per-phase focus, labels) that stance.py reads at cwd-relative paths.
shutil.copytree(os.path.join(BACKEND, "stance_templates"), "stance_templates")
shutil.copytree(os.path.join(BACKEND, "scenes"), "scenes")

_ck = Checker(); check = _ck.check

DYN_HDR = "背景知识"        # dynamic block header (zh)
RELATED = "相关背景"        # the one-hop expansion sub-block

# ------------------------------------------------------ unit: peek_matched_card_id
import stance_knowledge as sk
_kb = sk.load_stance_knowledge()
check("peek: keyword hit -> card id",
      sk.peek_matched_card_id("parent_child", "child_centered", "孩子很不听话", "zh", knowledge=_kb)
      == "child_defiance")
check("peek: no keyword -> None",
      sk.peek_matched_card_id("parent_child", "child_centered", "你好呀", "zh", knowledge=_kb) is None)
check("peek: no stance -> None",
      sk.peek_matched_card_id("parent_child", None, "孩子很不听话", "zh", knowledge=_kb) is None)


# --------------------------------------------------------------- driver
def _run(inputs, moderator_state):
    """Drive a parent_child session routing to A (child_centered). moderator_state
    is what the moderator stub reports ('Exploration' or 'Convergence'). Returns
    A's system prompts in order."""
    a_prompts = []
    def fake(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        sysc = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if sysc.startswith("You are Admin-2"):
            return "A"
        if sysc.startswith("You are Admin-1"):
            return "NEXT = A"
        if "deliberation moderator" in sysc:
            return f"[Moderator]\nmode: S\nstate: {moderator_state}\nstall: false\ngoal: g\n[/Moderator]"
        if messages[0]["role"] == "user" and "Distill" in messages[-1]["content"]:
            return "stub."
        if sysc.startswith("You are ChatbotA"):
            a_prompts.append(sysc)
        # "我不同意" is a _DISAGREEMENT_MARKERS hit. The Convergence gate holds the
        # group at Structuring until some disagreement is on record, and trigger B
        # below needs the session to actually be in Convergence.
        return "[MESSAGE]\n我不同意，理由如下\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
    aw.create_response = fake

    with open("info3.jsonl", "w", encoding="utf-8") as f:
        json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)
    it = iter(inputs)
    builtins.input = lambda prompt="": next(it)
    sys.argv = ["x", "--scenario_type", "parent_child", "--skip_intake", "--info", "info3.jsonl",
                "--lang", "zh", "--prefer_agents", "0", "--novelty_threshold", "0",
                "--max_user_gap", "1", "--log_dir", "lg"]
    cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    return a_prompts


# ---- trigger A: repeat hit of the same card, staying in Exploration ----
# "不听话" -> child_defiance (which has related_cards). Two user turns hit it.
a = _run(["孩子很不听话", "孩子很不听话", "/exit"], moderator_state="Exploration")
knf = [p for p in a if DYN_HDR in p]           # A prompts carrying the dynamic card
check("A: at least two card hits captured", len(knf) >= 2, f"{len(knf)} hits")
check("A: FIRST hit shows single card, NO [相关背景]", RELATED not in knf[0])
check("A: a LATER (repeat) hit shows [相关背景]", any(RELATED in p for p in knf[1:]),
      f"{sum(RELATED in p for p in knf)}/{len(knf)} hits had related")

# ---- trigger B: Convergence makes even a FIRST hit expand ----
# "你好" (no card) then /next forces the moderator -> Convergence, THEN the first
# child_defiance hit happens under Convergence.
a = _run(["你好", "/next", "孩子很不听话", "/exit"], moderator_state="Convergence")
knf = [p for p in a if DYN_HDR in p]
check("B: the (first) card hit under Convergence shows [相关背景]",
      len(knf) >= 1 and all(RELATED in p for p in knf),
      f"{sum(RELATED in p for p in knf)}/{len(knf)} hits had related")

_ck.finish("STANCE RELATED-CARDS CHECKS PASSED")
