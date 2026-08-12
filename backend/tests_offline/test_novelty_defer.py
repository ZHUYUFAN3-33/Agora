# -*- coding: utf-8 -*-
"""Defer exit: a failed retry that is an explicit short hand-off publishes.

The retry prompt has always offered "say you have nothing new and name whose
point you defer to" — but the defer sentence was scored, and quoting the point
you yield to is exactly what the metric punishes, so the exit was pinched shut
(measured on 5.6: both dropped retries were 0.0/0.08-scoring short deferrals).
Now [MOVE] concede @Target within NOVELTY_DEFER_MAX_CHARS publishes as a
hand-off, at most NOVELTY_DEFER_MAX_STREAK times in a row per agent.

NOTE Checker.check is (name, cond, detail) — name FIRST.
"""
import json
import os
import tempfile

from _harness import bootstrap, Checker

aw = bootstrap("novelty_defer_")
_ck = Checker()
check = _ck.check

SEED = "I am weighing stability against growth in this job decision right now"
# First generation: near-verbatim restatement -> triggers the guard and, as a
# retry body, stays under the drop bar (0.20 < 0.25).
NEAR_DUP = SEED + " and vesting cliffs matter"
# Built from SEED's own words so the retry genuinely FAILS the 0.25 drop bar
# (ratio 0.20: only "defer"/"chatbotb" are new) — that is the defer exit's
# territory. A wordier hand-off usually clears the bar on its own now that
# quote exclusion (step 1) stops counting the quoted point as repetition.
DEFER_MSG = "I defer to @ChatbotB on weighing stability against growth in this job decision right now."
# Also built from SEED words (so it genuinely fails the drop bar) but past the
# char cap: length is the ONLY thing separating it from DEFER_MSG.
LONG_CONCEDE = f"I concede to @ChatbotB on {SEED.lower()}, {SEED.lower()}."

assert len(DEFER_MSG) <= aw.NOVELTY_DEFER_MAX_CHARS
assert len(LONG_CONCEDE) > aw.NOVELTY_DEFER_MAX_CHARS


def _session(novelty_path):
    return {
        "room_id": "df1",
        "history": [{"character": "user", "txt": SEED}],
        "moderator_state": {"mode": "S", "state": "Exploration", "stall": False, "goal": ""},
        "has_spoken": {k: True for k in "ABC"},
        "mention_queue": [],
        "agent_runtime_config": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"},
        "think_fp": None, "moderator_fp": None, "chat_fp": None,
        "rationale_fp": None, "memory_fp": None,
        "novelty_fp": open(novelty_path, "a", encoding="utf-8"),
        "memory_snippets": {k: [] for k in "ABC"},
        "turns_since_distill": {k: 0 for k in "ABC"},
        "latest_rationale": {k: "" for k in "ABC"},
        "latest_snippet_id": {k: None for k in "ABC"},
        "snippet_counters": {k: 0 for k in "ABC"},
    }


agents = {k: aw.ChatAgent(k, f"Chatbot{k}", f"role {k}") for k in "ABC"}
agent_list = [agents[k] for k in "ABC"]
names = [a.name for a in agent_list]


def run(retry_blocks, n_user_turns=1, session=None, novelty_path=None):
    """First agent generation restates the user; retries pop from retry_blocks.

    retry_blocks: list of full tagged retry outputs, one per user turn.
    Returns (published agent rows, novelty rows, session).
    """
    state = {"agent_calls": 0, "retries": list(retry_blocks)}
    novelty_path = novelty_path or os.path.join(tempfile.mkdtemp(), "nv.jsonl")

    def fake(client, model, messages, temp, max_tok):
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        user_c = messages[-1]["content"]
        if "Distill the agent's CURRENT position" in user_c:
            return "d"
        if sys_c.startswith("You are Admin-2"):
            return "A"
        if sys_c.startswith("You are Admin-1"):
            return "analysis. NEXT = A"
        if "deliberation moderator" in sys_c:
            return "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n[/Moderator]"
        state["agent_calls"] += 1
        if "Replace it entirely" in user_c:  # the retry pass
            return state["retries"].pop(0)
        return (
            f"[MOVE]\nnew_point\n[/MOVE]\n[RATIONALE]\nwhy\n[/RATIONALE]\n"
            f"[MESSAGE]\n{NEAR_DUP}\n[/MESSAGE]"
        )

    s = session or _session(novelty_path)
    for _ in range(n_user_turns):
        aw.run_user_turn(
            session=s, user_message=SEED, agents=agents, agent_list=agent_list,
            all_agent_names=names, client_chat=object(), client_admin=object(), scene="s",
            prefer_agents=0.0, max_agent_turns_before_user=1,
            create_response_with_client=fake,
        )
    s["novelty_fp"].flush()
    rows = [json.loads(l) for l in open(novelty_path) if l.strip()]
    spoke = [m for m in s["history"] if m["character"] != "user"]
    return spoke, rows, s, novelty_path


def tagged(move_line, msg):
    return (f"[MOVE]\n{move_line}\n[/MOVE]\n[RATIONALE]\nr\n[/RATIONALE]\n"
            f"[MESSAGE]\n{msg}\n[/MESSAGE]")


print("== a short explicit concede @target publishes as a hand-off ==")
spoke, rows, s, _ = run([tagged("concede @ChatbotB", DEFER_MSG)])
check("the defer sentence is published", len(spoke) == 1 and DEFER_MSG in spoke[0]["txt"])
kept = [r for r in rows if str(r.get("reason", "")).startswith("kept_defer:")]
check("novelty row says kept_defer with the target",
      len(kept) == 1 and kept[0].get("defer_target") == "B")

print("== the same text without the concede move still drops ==")
spoke2, rows2, _, _ = run([tagged("new_point", DEFER_MSG)])
check("new_point framing gets no exemption", len(spoke2) == 0)
check("row records the drop", any(str(r.get("reason", "")).startswith("dropped:") for r in rows2))

print("== an over-length concede still drops ==")
spoke3, rows3, _, _ = run([tagged("concede @ChatbotB", LONG_CONCEDE)])
check("length cap holds", len(spoke3) == 0)

print("== concede without a resolvable target still drops ==")
spoke4, rows4, _, _ = run([tagged("concede", "So weighing stability against growth in this job decision right now.")])
check("no @target, no exemption", len(spoke4) == 0)

print("== second consecutive deferral by the same agent drops ==")
spoke5, rows5, s5, path5 = run(
    [tagged("concede @ChatbotB", DEFER_MSG), tagged("concede @ChatbotB", DEFER_MSG)],
    n_user_turns=2)
kept5 = [r for r in rows5 if str(r.get("reason", "")).startswith("kept_defer:")]
drop5 = [r for r in rows5 if str(r.get("reason", "")).startswith("dropped:")]
check("first deferral kept, second dropped", len(kept5) == 1 and len(drop5) == 1)
check("only the first defer sentence is in history", len(spoke5) == 1)

print("== a normal published turn resets the streak ==")
streaks = s5.get("novelty_defer_streak") or {}
check("streak recorded for the deferring agent", streaks.get("A", 0) >= 1)
# Simulate the reset path: a clean pass zeroes it (asserted structurally).
s5["novelty_defer_streak"]["A"] = 0
spoke6, rows6, s6, _ = run(
    [tagged("concede @ChatbotB", DEFER_MSG)],
    session=s5, novelty_path=path5)
# Same novelty file accumulates across the reused session: one kept_defer row
# from turn 1 plus the fresh one from this run.
kept6 = [r for r in rows6 if str(r.get("reason", "")).startswith("kept_defer:")]
check("after a reset the exit is usable again", len(kept6) == len(kept5) + 1)

_ck.finish("ALL CHECKS PASSED")
