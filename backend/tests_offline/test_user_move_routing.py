# -*- coding: utf-8 -*-
"""Offline verification for the user-move layer (Admin-4).

What is being protected:
  1. A user's bounded side question ("what should I check in the contract?")
     must be answered in its own terms — the per-burst contract replaces the
     phase task, the phase-keyed stance focus, the moderator goal, and the
     question budget, WITHOUT touching the phase itself.
  2. move="progress" must reproduce the pre-layer prompt exactly (regression).
  3. goal_switch resets the phase to Exploration deterministically and zeroes
     the moderator counters, logged as admin3_redirected.
  4. Every failure path (garbled label, classifier exception, layer disabled,
     low-content message) degrades to "progress" — i.e. to the old behavior.
  5. The Narrowing phase_focus rows added alongside this layer exist for all
     six stances in both languages (they were silently absent, which collapsed
     the three voices into one shape exactly in the elimination phase).

All LLM calls are stubbed — no API key, no network.
"""
import json
import os
import random
import sys

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_usermove_")

_ck = Checker()
check = _ck.check

# The harness defaults the layer OFF so older scripted tests keep their LLM
# call counts; this test is about the layer, so turn it on (read at call time).
os.environ["AGORA_USER_MOVE_LAYER"] = "1"

GOOD = ("[MOVE]\nclarify\n[/MOVE]\n[RATIONALE]\nwhy\n[/RATIONALE]\n"
        "[MESSAGE]\nunique answer alpha{n} bravo{n} charlie{n}\n[/MESSAGE]")


def make_fake(admin4_reply, admin2_pick="A", admin4_raises=False):
    """Stub keyed on system prompts; records agent system prompts + call counts."""
    state = {"agent_systems": [], "admin4_calls": 0, "n": 0}

    def fake_http(client, model, messages, temp, max_tok):
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        user_c = messages[-1]["content"]
        if sys_c.startswith("You are Admin-4"):
            state["admin4_calls"] += 1
            if admin4_raises:
                raise RuntimeError("admin4 down")
            return admin4_reply
        if sys_c.startswith("You are Admin-2"):
            return admin2_pick
        if sys_c.startswith("You are Admin-1"):
            return f"analysis. NEXT = {admin2_pick}"
        if "deliberation moderator" in sys_c:
            return ("[Moderator]\nmode: S\nstate: Narrowing\nstall: false\n"
                    "goal: g\n[/Moderator]")
        if "Distill" in user_c:
            return "stub stance."
        state["n"] += 1
        state["agent_systems"].append(sys_c)
        return GOOD.format(n=state["n"])

    return fake_http, state


def make_session(user_txt, phase="Narrowing", goal="compare the reversibility"):
    mod_path = os.path.abspath(f"mod_{random.randint(0, 10**9)}.jsonl")
    return {
        "room_id": "usermove1",
        "history": [{"character": "user", "txt": user_txt}],
        "moderator_state": {"mode": "S", "state": phase, "stall": False, "goal": goal},
        "has_spoken": {"A": False, "B": False, "C": False},
        "mention_queue": [],
        "agent_runtime_config": {
            k: {"decision": "Rational", "emotion": "Joy", "stance": s}
            for k, s in zip("ABC", ("growth_centered", "stability_centered", "life_centered"))
        },
        "think_fp": None,
        "moderator_fp": open(mod_path, "a", encoding="utf-8"),
        "chat_fp": None,
        "rationale_fp": None,
        "memory_fp": None,
        "memory_snippets": {"A": [], "B": [], "C": []},
        "turns_since_distill": {"A": 0, "B": 0, "C": 0},
        "latest_rationale": {"A": "", "B": "", "C": ""},
        "latest_snippet_id": {"A": None, "B": None, "C": None},
        "snippet_counters": {"A": 0, "B": 0, "C": 0},
    }, mod_path


def run_burst(user_txt, admin4_reply, *, phase="Narrowing", admin4_raises=False):
    fake, state = make_fake(admin4_reply, admin4_raises=admin4_raises)
    agents = {k: aw.ChatAgent(k, f"Chatbot{k}", f"role {k}") for k in "ABC"}
    agent_list = [agents[k] for k in "ABC"]
    for a in agent_list:
        a.spoke = 0
    random.seed(7)
    sess, mod_path = make_session(user_txt, phase=phase)
    r = aw.run_user_turn(
        session=sess,
        user_message=user_txt,
        agents=agents,
        agent_list=agent_list,
        all_agent_names=[a.name for a in agent_list],
        client_chat=object(),
        client_admin=object(),
        scene="s",
        scenario_type="employment",
        lang="en",
        prefer_agents=0.0,
        max_agent_turns_before_user=2,
        novelty_threshold=0.0,
        create_response_with_client=fake,
    )
    sess["moderator_fp"].close()
    mod_rows = [json.loads(l) for l in open(mod_path, encoding="utf-8") if l.strip()]
    return r, sess, state, mod_rows


QUESTION = "What should I check in the contract and probation period before I decide?"
NARROW_TASK = "stronger overall case"
NARROW_BUDGET = "Do NOT ask the other participants questions"
CONTRACT_MARK = "Answer THAT question first"

# ---- 1. local_question: contract replaces the Narrowing machinery ---------
r, sess, st, mod = run_burst(QUESTION, "local_question")
sys_prompts = st["agent_systems"]
check("U1 admin4 called exactly once for the user turn", st["admin4_calls"] == 1,
      f"calls={st['admin4_calls']}")
check("U1 label logged to moderator log",
      any(m["character"] == "admin4_usermove" and m["txt"] == "local_question" for m in mod),
      str([m["character"] for m in mod]))
check("U1 run_user_turn returns user_move", r.get("user_move") == "local_question", str(r.get("user_move")))
check("U2 agents actually spoke under the contract", len(sys_prompts) >= 1, str(len(sys_prompts)))
check("U2 contract text present in every agent system prompt",
      all(CONTRACT_MARK in p for p in sys_prompts))
check("U2 Narrowing task suppressed", all(NARROW_TASK not in p for p in sys_prompts))
check("U2 Narrowing question budget suppressed", all(NARROW_BUDGET not in p for p in sys_prompts))
check("U2 moderator goal suppressed", all("Current goal:" not in p for p in sys_prompts))
check("U2 phase-keyed stance focus suppressed",
      all("What only YOU should be putting" not in p for p in sys_prompts))
check("U2 phase itself untouched and visible",
      all("Phase: Narrowing" in p for p in sys_prompts)
      and sess["moderator_state"]["state"] == "Narrowing")

# ---- 2. progress: pre-layer prompt reproduced (regression) ----------------
r, sess, st, mod = run_burst(QUESTION, "progress")
sys_prompts = st["agent_systems"]
check("U3 progress keeps the Narrowing task", all(NARROW_TASK in p for p in sys_prompts),
      (sys_prompts or ["<no agent turn>"])[0][:400])
check("U3 progress keeps the question budget", all(NARROW_BUDGET in p for p in sys_prompts))
check("U3 progress keeps the moderator goal", all("Current goal:" in p for p in sys_prompts))
check("U3 progress keeps the stance focus line",
      all("What only YOU should be putting" in p for p in sys_prompts))
check("U3 no contract text", all(CONTRACT_MARK not in p for p in sys_prompts))

# ---- 3. goal_switch: deterministic redirect -------------------------------
r, sess, st, mod = run_burst("Forget the offers — how do I fix my visa paperwork?", "goal_switch")
check("U4 phase reset to Exploration", sess["moderator_state"]["state"] == "Exploration",
      sess["moderator_state"]["state"])
check("U4 admin3_redirected logged",
      any(m["character"] == "admin3_redirected" for m in mod), str([m["character"] for m in mod]))
check("U4 moderator counters zeroed at redirect",
      # the agent turns of the burst re-increment turns_since_moderator afterwards,
      # so assert the user-turn counter, which only user turns touch
      int(sess.get("user_turns_since_moderator") or 0) == 0,
      str(sess.get("user_turns_since_moderator")))
check("U4 goal cleared", sess["moderator_state"]["goal"] == "", sess["moderator_state"]["goal"])
check("U4 goal_switch contract active",
      all("moved to a different question" in p for p in st["agent_systems"]))

# ---- 4. degradation paths -------------------------------------------------
r, sess, st, mod = run_burst(QUESTION, "banana banana banana")
check("U5 garbled label degrades to progress", r.get("user_move") == "progress", str(r.get("user_move")))
check("U5 garbled label keeps phase machinery", all(NARROW_TASK in p for p in st["agent_systems"]))

r, sess, st, mod = run_burst(QUESTION, "", admin4_raises=True)
check("U6 classifier exception degrades to progress and burst completes",
      r.get("user_move") == "progress" and len(r.get("responses") or []) >= 1,
      f"move={r.get('user_move')} responses={len(r.get('responses') or [])}")

r, sess, st, mod = run_burst("ok thanks", "local_question")
check("U7 low-content message skips the classifier", st["admin4_calls"] == 0,
      f"calls={st['admin4_calls']}")

os.environ["AGORA_USER_MOVE_LAYER"] = "0"
r, sess, st, mod = run_burst(QUESTION, "local_question")
check("U8 kill switch: no admin4 call, phase machinery intact",
      st["admin4_calls"] == 0 and all(NARROW_TASK in p for p in st["agent_systems"]),
      f"calls={st['admin4_calls']}")
os.environ["AGORA_USER_MOVE_LAYER"] = "1"

# ---- 5. request_recommendation has no contract ----------------------------
r, sess, st, mod = run_burst("So which one should I pick?", "request_recommendation")
check("U9 request_recommendation keeps the phase task",
      all(NARROW_TASK in p for p in st["agent_systems"])
      and all(CONTRACT_MARK not in p for p in st["agent_systems"]))

# ---- 6. parse_user_move unit checks ---------------------------------------
check("U10 parse: exact label", aw.parse_user_move("local_question") == "local_question")
check("U10 parse: label inside prose", aw.parse_user_move("Label: goal_switch.") == "goal_switch")
check("U10 parse: empty -> progress", aw.parse_user_move("") == "progress")
check("U10 parse: junk -> progress", aw.parse_user_move("the user is asking about visas") == "progress")

# ---- 7. Narrowing stance focus rows exist (both scenarios, both langs) ----
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stance  # noqa: E402

pairs = [("employment", s) for s in ("growth_centered", "stability_centered", "life_centered")] + \
        [("parent_child", s) for s in ("child_centered", "parent_centered", "relationship_centered")]
ok = all(stance.get_stance_phase_focus(sc, st_, "Narrowing", lg)
         for sc, st_ in pairs for lg in ("zh", "en"))
check("U11 Narrowing phase_focus present for all 6 stances x zh/en", ok)

_ck.finish("ALL USER-MOVE CHECKS PASSED")
