# -*- coding: utf-8 -*-
"""Regression for the premature-convergence gate.

Three agents holding three opposed stances closing the discussion while agreeing
with each other is the "converged by turn 5" failure. The moderator may now only
move the group INTO Convergence once some substantive disagreement is on record
(has_disagreement over the agent turns); otherwise it is held at Structuring with
a goal telling them to surface the conflict.

  - agents never disagree  -> Convergence withheld, state stays Structuring
  - agents do disagree     -> Convergence goes through as before
"""
import builtins, io, json, os, sys

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_convgate_")
_ck = Checker(); check = _ck.check

AGREEABLE = "这个方向听起来不错，我也这么想，补充一点细节"
DISAGREEING = "我不同意这个方向，问题在于它牺牲了另一边的核心诉求"


def _run(agent_body):
    def fake(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        sysc = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if sysc.startswith("You are Admin-2"):
            return "A"
        if sysc.startswith("You are Admin-1"):
            return "NEXT = A"
        if "deliberation moderator" in sysc:      # moderator always votes Convergence
            return "[Moderator]\nmode: S\nstate: Convergence\nstall: false\ngoal: g\n[/Moderator]"
        if messages[0]["role"] == "user" and "Distill" in messages[-1]["content"]:
            return "stub."
        return f"[MESSAGE]\n{agent_body}\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
    aw.create_response = fake

    with open("info3.jsonl", "w", encoding="utf-8") as f:
        json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)
    inputs = iter([f"u{i}" for i in range(1, 6)] + ["/exit"])
    builtins.input = lambda prompt="": next(inputs)
    sys.argv = ["x", "--info", "info3.jsonl", "--prefer_agents", "0",
                "--novelty_threshold", "0", "--max_user_gap", "3", "--log_dir", "lg"]
    cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    out = cap.getvalue()
    room = [l for l in out.splitlines() if l.startswith("Chat room id:")][0].split()[-1]
    mod = [json.loads(l) for l in open(f"lg/{room}_moderator.jsonl", encoding="utf-8")]
    return [m["character"] for m in mod]


# --- no disagreement: the gate must hold the group back --------------------
chars = _run(AGREEABLE)
check("agreeable session: Convergence is withheld by the gate",
      "admin3_convergence_gated" in chars, str(chars[:8]))
check("agreeable session: never latches to Concluded",
      "admin3_concluded" not in chars, str(chars[:8]))

# --- with disagreement: Convergence proceeds as before ---------------------
chars = _run(DISAGREEING)
check("disagreeing session: Convergence is NOT gated",
      "admin3_convergence_gated" not in chars, str(chars[:8]))

_ck.finish("CONVERGENCE GATE CHECKS PASSED")
