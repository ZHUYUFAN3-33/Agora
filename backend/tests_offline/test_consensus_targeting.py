# -*- coding: utf-8 -*-
"""The consensus warning nudges ONE speaker at a time, and [MOVE] silences it.

Old behavior: once the last-6-lines window held 4+ agent lines with no marker
phrase, EVERY subsequent speaker got the full "state your disagreement plainly"
warning until someone happened to use marker vocabulary — producing a chain of
near-identical formal objections (synchronized objection reads as fake as
synchronized agreement). Now:

  - agreeable session, no move blocks -> the warning fires, but never on two
    consecutive agent generations (>=3-line spacing between nudges)
  - same session but every turn self-reports [MOVE] challenge -> the tracker
    sees pushback (even without marker wording) and the warning never fires
"""
import builtins, io, json, sys

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_consensus_")
_ck = Checker(); check = _ck.check

AGREEABLE = "这个方向听起来不错，我也这么想，补充一点细节"


def _run(move=""):
    """Returns, per agent generation call, whether its system prompt carried
    the CONSENSUS WARNING."""
    warned = []

    def fake(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        sysc = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if sysc.startswith("You are Admin-2"):
            return "A"
        if sysc.startswith("You are Admin-1"):
            return "NEXT = A"
        if "deliberation moderator" in sysc:
            return "[Moderator]\nmode: S\nstate: Structuring\nstall: false\ngoal: g\n[/Moderator]"
        if messages[0]["role"] == "user" and "Distill" in messages[-1]["content"]:
            return "stub."
        # An agent generation (system prompt starts with "You are ChatbotX ...").
        warned.append("CONSENSUS WARNING" in sysc)
        tail = f"\n[MOVE]\n{move}\n[/MOVE]" if move else ""
        return f"[MESSAGE]\n{AGREEABLE}\n[/MESSAGE]{tail}\n[RATIONALE]\nr\n[/RATIONALE]"

    aw.create_response = fake
    with open("info_ct.jsonl", "w", encoding="utf-8") as f:
        json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)
    inputs = iter([f"u{i}" for i in range(1, 7)] + ["/exit"])
    builtins.input = lambda prompt="": next(inputs)
    sys.argv = ["x", "--info", "info_ct.jsonl", "--prefer_agents", "1.0",
                "--novelty_threshold", "0", "--max_user_gap", "20", "--log_dir", "lg"]
    cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    return warned


# --- agreeable, no self-report: nudge fires, but one speaker at a time -------
warned = _run()
check("smooth consensus still triggers the warning at least once",
      any(warned), str(warned))
check("warning is never issued to two consecutive speakers",
      not any(a and b for a, b in zip(warned, warned[1:])), str(warned))

# --- every turn self-reports a challenge: tracker sees pushback, no nagging --
warned = _run(move="challenge @ChatbotB")
check("[MOVE] challenge suppresses the warning even without marker wording",
      not any(warned), str(warned))

_ck.finish("CONSENSUS TARGETING CHECKS PASSED")
