# -*- coding: utf-8 -*-
"""Offline verification that the phase machine can actually reach Convergence.

The freeze this protects against: a stall re-check (allow_state_change=False)
used to zero user_turns_since_moderator, and past MODERATOR_STALL_TURNS the
re-checks fired every MODERATOR_STALL_RECHECK turns — eating the user-turn
count before it could reach MODERATOR_USER_TURN_INTERVAL. due_user then never
fired again, so every proposed state change was suppressed forever (rooms
954660 / 894275 / 434276 in the production logs; 5 consecutive suppressed
Convergence verdicts in one live eval run).

Also covered: request_recommendation fast-tracks a real moderator run (the
user asking for the verdict must not wait on cadence luck), and the
convergence gate still blocks a premature close on a disagreement-free record.

All LLM calls are stubbed — no API key, no network.
"""
import json
import os
import random

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_progress_")

_ck = Checker()
check = _ck.check

# Agent replies carry an explicit disagreement marker so the convergence gate
# (has_disagreement over agent lines) lets a proposed Convergence through in
# the tests that expect it.
DISAGREE = ("[MOVE]\nchallenge\n[/MOVE]\n[RATIONALE]\nwhy\n[/RATIONALE]\n"
            "[MESSAGE]\nI disagree with that: unique alpha{n} beta{n} gamma{n}\n[/MESSAGE]")
AGREE = ("[MOVE]\nextend\n[/MOVE]\n[RATIONALE]\nwhy\n[/RATIONALE]\n"
         "[MESSAGE]\nsounds right to me: unique alpha{n} beta{n} gamma{n}\n[/MESSAGE]")


def make_fake(admin3_state, agent_tpl, admin4_reply="progress"):
    state = {"n": 0, "admin3_calls": 0, "admin4_calls": 0}

    def fake(client, model, messages, temp, max_tok):
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        user_c = messages[-1]["content"]
        if sys_c.startswith("You are Admin-4"):
            state["admin4_calls"] += 1
            return admin4_reply
        if sys_c.startswith("You are Admin-2"):
            return "A"
        if sys_c.startswith("You are Admin-1"):
            return "analysis. NEXT = A"
        if "deliberation moderator" in sys_c:
            state["admin3_calls"] += 1
            return (f"[Moderator]\nmode: S\nstate: {admin3_state}\n"
                    f"stall: false\ngoal: g\n[/Moderator]")
        if "Distill" in user_c:
            return "stub."
        state["n"] += 1
        return agent_tpl.format(n=state["n"])

    return fake, state


def make_session(phase, turns_in_state):
    mod_path = os.path.abspath(f"mod_{random.randint(0, 10**9)}.jsonl")
    return {
        "room_id": "prog1",
        "history": [],
        "moderator_state": {"mode": "S", "state": phase, "stall": False, "goal": "g"},
        "has_spoken": {k: False for k in "ABC"},
        "mention_queue": [],
        "agent_runtime_config": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"},
        "think_fp": None,
        "moderator_fp": open(mod_path, "a", encoding="utf-8"),
        "chat_fp": None,
        "rationale_fp": None,
        "memory_fp": None,
        "memory_snippets": {k: [] for k in "ABC"},
        "turns_since_distill": {k: 0 for k in "ABC"},
        "latest_rationale": {k: "" for k in "ABC"},
        "latest_snippet_id": {k: None for k in "ABC"},
        "snippet_counters": {k: 0 for k in "ABC"},
        "turns_in_current_state": turns_in_state,
    }, mod_path


def user_turn(sess, fake, txt):
    agents = {k: aw.ChatAgent(k, f"Chatbot{k}", f"role {k}") for k in "ABC"}
    sess["history"].append({"character": "user", "txt": txt})
    return aw.run_user_turn(
        session=sess,
        user_message=txt,
        agents=agents,
        agent_list=[agents[k] for k in "ABC"],
        all_agent_names=[f"Chatbot{k}" for k in "ABC"],
        client_chat=object(),
        client_admin=object(),
        scene="s",
        prefer_agents=0.0,
        max_agent_turns_before_user=3,
        novelty_threshold=0.0,
        create_response_with_client=fake,
    )


def mod_rows(sess, path):
    sess["moderator_fp"].flush()
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


# ---- 1. the freeze: stalled state must still advance on real user turns ----
random.seed(11)
fake, st = make_fake("Convergence", DISAGREE)
sess, mp = make_session("Narrowing", turns_in_state=7)  # already past stall threshold
r1 = user_turn(sess, fake, "first real user question")
credit_after_t1 = int(sess.get("user_turns_since_moderator") or 0)
r2 = user_turn(sess, fake, "second real user question")
rows = mod_rows(sess, mp)
check("P1 stall re-check does NOT eat user-turn credit",
      credit_after_t1 == 1, f"user_turns_since_moderator={credit_after_t1}")
check("P1 phase advances to Convergence by user turn 2",
      sess["moderator_state"]["state"] == "Convergence", sess["moderator_state"]["state"])
check("P1 an ALLOWED state change is on record",
      any(x["character"] == "admin3_state_change" for x in rows),
      str([x["character"] for x in rows]))
check("P1 agent-only re-checks still suppress (by design)",
      any(x["character"] == "admin3_state_change_suppressed" for x in rows))

# ---- 2. request_recommendation fast-tracks a real moderator run -----------
os.environ["AGORA_USER_MOVE_LAYER"] = "1"
random.seed(12)
fake, st = make_fake("Convergence", DISAGREE, admin4_reply="request_recommendation")
sess, mp = make_session("Narrowing", turns_in_state=0)  # NOT stalled, cadence not due
# seed prior agent disagreement so the convergence gate can pass on turn 1
sess["history"] = [
    {"character": "user", "txt": "earlier question"},
    {"character": "ChatbotA", "txt": "I disagree with that framing entirely."},
]
r = user_turn(sess, fake, "So which one would you pick?")
rows = mod_rows(sess, mp)
check("P2 moderator ran on the request turn despite cadence",
      st["admin3_calls"] >= 1, f"admin3_calls={st['admin3_calls']}")
check("P2 phase reached Convergence on the request turn",
      r["phase"] in ("Convergence", aw.CONCLUDED_STATE), r["phase"])
check("P2 no suppressed row for the fast-tracked run",
      not any(x["character"] == "admin3_state_change_suppressed" for x in rows),
      str([x["character"] for x in rows]))

# ---- 3. the convergence gate still blocks a disagreement-free close -------
random.seed(13)
fake, st = make_fake("Convergence", AGREE, admin4_reply="request_recommendation")
sess, mp = make_session("Narrowing", turns_in_state=0)
sess["history"] = [{"character": "user", "txt": "earlier question"}]
r = user_turn(sess, fake, "So which one would you pick?")
rows = mod_rows(sess, mp)
check("P3 premature close gated to Structuring",
      sess["moderator_state"]["state"] == "Structuring", sess["moderator_state"]["state"])
check("P3 gate logged", any(x["character"] == "admin3_convergence_gated" for x in rows),
      str([x["character"] for x in rows]))
os.environ["AGORA_USER_MOVE_LAYER"] = "0"

# ---- 4. Concluded latch still reachable after the counter fix -------------
# Real run says Convergence (user spoke), then an agent-only re-check sees
# Convergence again with no user input in between -> Concluded.
random.seed(14)
fake, st = make_fake("Convergence", DISAGREE)
sess, mp = make_session("Convergence", turns_in_state=7)
r = user_turn(sess, fake, "first question")
r = user_turn(sess, fake, "second question")
rows = mod_rows(sess, mp)
check("P4 Concluded latch fires once the user goes quiet mid-burst",
      any(x["character"] == "admin3_concluded" for x in rows)
      or sess["moderator_state"]["state"] == aw.CONCLUDED_STATE,
      f"state={sess['moderator_state']['state']} rows={[x['character'] for x in rows]}")

_ck.finish("ALL MODERATOR-PROGRESS CHECKS PASSED")
