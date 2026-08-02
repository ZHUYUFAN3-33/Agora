# -*- coding: utf-8 -*-
"""Regression: admin_choose_next() never hands the floor to the same agent twice
in a row, even when Admin-2 keeps naming the same key or the prefer_agents random
override fires. Without the "exclude last speaker" guard, an agent could speak,
get re-picked immediately, and have its restatement dropped by the novelty guard
(the '[SYSTEM] ... had nothing new to add this turn.' artifact)."""
import builtins, io, json, os, sys

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_norepeat_")

_ck = Checker(); check = _ck.check


# Admin-2 ALWAYS names "A": the worst case for repeats. Moderator stays in a
# plain state (no stall, no conclusion). Agents emit unique text so nothing is
# dropped for reasons other than the guard under test (novelty is off anyway).
_agent_calls = {"n": 0}
def fake_create_response(model, messages, temperature, max_output_tokens, meta=None):
    if meta is not None:
        meta["status"] = "completed"
    sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
    if sys_c.startswith("You are Admin-2"):
        return "A"                       # always try to re-pick A
    if sys_c.startswith("You are Admin-1"):
        return "analysis. NEXT = A"
    if "deliberation moderator" in sys_c:
        return "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n[/Moderator]"
    if messages[0]["role"] == "user" and "Distill" in messages[-1]["content"]:
        return "stub stance."
    _agent_calls["n"] += 1
    return f"[MESSAGE]\nunique point number {_agent_calls['n']}\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"

aw.create_response = fake_create_response

os.makedirs("roles", exist_ok=True)
for k in "ABC":
    with open(f"roles/{k}.txt", "w", encoding="utf-8") as f:
        f.write(f"Role {k}.")
with open("info3.jsonl", "w", encoding="utf-8") as f:
    json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)

# prefer_agents 1.0 => every "U" verdict is overridden to a random agent, so the
# random-override path is exercised on top of Admin-2 always saying "A".
inputs = iter(["go on", "go on", "go on", "/exit"])
builtins.input = lambda prompt="": next(inputs)
sys.argv = ["x", "--info", "info3.jsonl", "--roles-dir", "roles",
            "--start_order", "ABCU", "--prefer_agents", "1",
            "--novelty_threshold", "0", "--log_dir", "dry_logs"]

cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
try:
    aw.main()
finally:
    sys.stdout = real
out = cap.getvalue()

room = [l for l in out.splitlines() if l.startswith("Chat room id:")][0].split()[-1]
chat = [json.loads(l) for l in open(f"dry_logs/{room}.jsonl", encoding="utf-8")]
speakers = [r["character"] for r in chat]

# 1. No two ADJACENT chat lines share the same agent speaker (user lines separate
#    turns, so an agent right after a user line is fine).
repeats = [(speakers[i - 1], i) for i in range(1, len(speakers))
           if speakers[i] == speakers[i - 1] and speakers[i] != "user"]
check("no agent speaks twice in a row", not repeats, f"repeats at {repeats} in {speakers}")

# 2. The novelty guard never had to drop a turn (the visible symptom is gone).
check("no 'nothing new to add' artifact printed",
      "nothing new to add" not in out, out)

# 3. Sanity: agents other than A actually got the floor (reroute really spreads it),
#    so the test isn't vacuously passing by never letting agents speak.
agent_speakers = {s for s in speakers if s != "user"}
check("floor was shared beyond ChatbotA",
      {"ChatbotB", "ChatbotC"} & agent_speakers != set(), str(sorted(agent_speakers)))

_ck.finish("NO-REPEAT SPEAKER CHECKS PASSED")
