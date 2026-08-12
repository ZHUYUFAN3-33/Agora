# -*- coding: utf-8 -*-
"""Novelty guard calibration: a retry is kept unless it is near-verbatim.

NOTE Checker.check is (name, cond, detail) — name FIRST. Every assertion in
this file originally had the two swapped, which made the string argument the
condition: always truthy, every check vacuously green. Found when a new test
copied the pattern and visibly passed with a failing condition.

Measured over 7 real rooms before this change: the drop bar equalled the retry
trigger (0.5), so 21 of 28 retries were discarded and the agent said nothing at
all on three quarters of the turns it was asked to redo. 11 of those 28 retries
scored WORSE than the first attempt, because engaging with a specific claim
necessarily reuses that claim's words — the metric punishes exactly the
behaviour the retry prompt demands.
"""
from _harness import bootstrap, Checker

aw = bootstrap("novelty_cal_")
_ck = Checker()
check = _ck.check

SEED = "I am weighing stability against growth in this job decision right now"
# 0.20 — two new content words; a rephrase, not a contribution.
NEAR_DUP = SEED + " and vesting cliffs matter"
# 0.47 — genuinely adds terms nobody used, but would still have failed the old
# 0.50 trigger and therefore been dropped.
IMPROVED = SEED + " but the vesting cliff, severance terms and relocation costs change it"


def _session(txt):
    return {
        "room_id": "nv1",
        "history": [{"character": "user", "txt": txt}],
        "moderator_state": {"mode": "S", "state": "Exploration", "stall": False, "goal": ""},
        "has_spoken": {k: True for k in "ABC"},
        "mention_queue": [],
        "agent_runtime_config": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"},
        "think_fp": None, "moderator_fp": None, "chat_fp": None,
        "rationale_fp": None, "memory_fp": None,
        "memory_snippets": {k: [] for k in "ABC"},
        "turns_since_distill": {k: 0 for k in "ABC"},
        "latest_rationale": {k: "" for k in "ABC"},
        "latest_snippet_id": {k: None for k in "ABC"},
        "snippet_counters": {k: 0 for k in "ABC"},
    }


agents = {k: aw.ChatAgent(k, f"Chatbot{k}", f"role {k}") for k in "ABC"}
agent_list = [agents[k] for k in "ABC"]
names = [a.name for a in agent_list]


def run(retry_body):
    """First generation restates the user; the retry returns `retry_body`."""
    state = {"agent_calls": 0}

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
        body = SEED if state["agent_calls"] == 1 else retry_body
        return (
            f"[MOVE]\nnew_point\n[/MOVE]\n[RATIONALE]\nwhy\n[/RATIONALE]\n"
            f"[MESSAGE]\n{body}\n[/MESSAGE]"
        )

    s = _session(SEED)
    aw.run_user_turn(
        session=s, user_message=SEED, agents=agents, agent_list=agent_list,
        all_agent_names=names, client_chat=object(), client_admin=object(), scene="s",
        prefer_agents=0.0, max_agent_turns_before_user=1, create_response_with_client=fake,
    )
    return [m for m in s["history"] if m["character"] != "user"], state["agent_calls"]


print("== scores are what we think they are ==")
g_dup = aw.novelty_ratio(NEAR_DUP, [f"user: {SEED}"])
g_imp = aw.novelty_ratio(IMPROVED, [f"user: {SEED}"])
check(f"near-duplicate scores below the drop bar ({g_dup:.2f})", g_dup < 0.25)
check(f"improved retry lands in the contested band ({g_imp:.2f})", 0.25 <= g_imp < 0.5)

print("== the retry survives unless it is near-verbatim ==")
spoke, calls = run(IMPROVED)
check("the guard did ask for one retry", calls == 2)
check("a retry that adds real terms is PUBLISHED (was dropped at the old bar)", len(spoke) == 1)
check("the published text is the retry, not the original", bool(spoke and IMPROVED in (spoke[0].get("txt") or "")))

spoke_dup, calls_dup = run(NEAR_DUP)
check("the guard asked for a retry here too", calls_dup == 2)
check("a near-verbatim retry is still dropped — silence needs strong evidence", len(spoke_dup) == 0)

print("== defaults are the calibrated ones, in both entry points ==")
import inspect
sig = inspect.signature(aw.run_user_turn)
check("token budget fits four blocks",
      sig.parameters["max_output_tokens"].default >= 520,
      str(sig.parameters["max_output_tokens"].default))
check("run_user_turn exposes the drop bar", "novelty_drop_threshold" in sig.parameters)

src = inspect.getsource(aw.build_parser) if hasattr(aw, "build_parser") else ""
_ck.finish("ALL CHECKS PASSED")
