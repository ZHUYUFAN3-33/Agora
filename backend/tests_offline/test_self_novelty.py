# -*- coding: utf-8 -*-
"""Regression for the cross-turn SELF-repetition scope of the novelty guard.

The original guard compared a reply only against transcript_lines[-novelty_window:]
— the last N lines from ALL speakers. An agent's own earlier turns fall out of
that window (with 3 agents its turns are every third line), so it could re-serve
its own earlier argument in new wording and never be flagged. That is the
observed "cross-turn self-repetition".

Setup here makes the two scopes disagree on purpose: --novelty_window 1 means the
group scope sees only the immediately preceding line (another agent's), so it
CANNOT see ChatbotA's earlier message; only the self scope can. A passes a
reworded copy of its own earlier point, and the guard must flag it as `self`.

Also checks the master off switch (--novelty_threshold 0 disables both scopes).
"""
import builtins, io, json, os, sys

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_selfnov_")
_ck = Checker(); check = _ck.check

# Same content tokens, different wording/order -> low self-novelty, and NOT
# visible to a 1-line group window when another agent spoke in between.
X = "长期来看孩子的自主性和内在兴趣最重要，这决定了他将来是否愿意主动学习"
X_REWORDED = "孩子的自主性与内在兴趣，从长期看最重要，将来他是否主动学习由此决定"
FILLER = "换个角度说，报名截止时间下周就到了，接送安排也要先定下来"
NOVEL = "具体比较一下：周末编程班占掉两个上午，而线上课只占一小时，接送成本差三倍"


def _run(extra_argv):
    a_calls = {"n": 0}
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
        last_user = messages[-1]["content"]
        if messages[0]["role"] == "user" and "Distill" in last_user:
            return "stub."
        # the corrective retry: answer with something genuinely new so the turn
        # is kept and the test asserts on the DETECTION, not on the drop path.
        if "Replace it entirely" in last_user:
            return f"[MESSAGE]\n{NOVEL}\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
        if sysc.startswith("You are ChatbotA"):
            a_calls["n"] += 1
            body = X if a_calls["n"] == 1 else X_REWORDED
            return f"[MESSAGE]\n{body}\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
        return f"[MESSAGE]\n{FILLER}\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
    aw.create_response = fake

    with open("info3.jsonl", "w", encoding="utf-8") as f:
        json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)
    inputs = iter(["我们再聊聊这个决定", "/exit"])
    builtins.input = lambda prompt="": next(inputs)
    sys.argv = (["x", "--info", "info3.jsonl", "--prefer_agents", "0",
                 "--novelty_window", "1", "--max_user_gap", "20", "--log_dir", "lg"]
                + extra_argv)
    cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    out = cap.getvalue()
    room = [l for l in out.splitlines() if l.startswith("Chat room id:")][0].split()[-1]
    think = [json.loads(l) for l in open(f"lg/{room}_thinking.jsonl", encoding="utf-8")]
    return [t for t in think if t.get("character") == "novelty_retry"
            or t.get("event") == "novelty_retry" or "novelty" in str(t.get("txt", ""))]


# --- guard ON: the self scope must catch the reworded self-repeat -----------
events = _run([])
texts = [str(e.get("txt", "")) for e in events]
blob = " | ".join(texts)
# Only ChatbotA's lines matter here: B and C both emit the same filler, so they
# legitimately trip the GROUP scope on each other — unrelated to what's tested.
a_first = next((t for t in texts if t.startswith("A: novelty")), "")
check("self scope fires on a reworded repeat of the agent's OWN earlier point",
      "failed on self" in a_first, a_first or "(no ChatbotA novelty event)")
check("the group scope did NOT see it — only the new self scope did",
      "group=1.00" in a_first and "failed on group" not in a_first, a_first)

# --- master off switch: --novelty_threshold 0 disables BOTH scopes ----------
events = _run(["--novelty_threshold", "0"])
blob = " | ".join(str(e.get("txt", "")) for e in events)
check("--novelty_threshold 0 disables the whole guard (self scope included)",
      "failed on" not in blob, blob[:300])

_ck.finish("SELF-NOVELTY CHECKS PASSED")
