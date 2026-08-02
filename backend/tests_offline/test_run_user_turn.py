# -*- coding: utf-8 -*-
"""HTTP-facing run_user_turn scheduling + in-session distill."""
import json

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_http_")
_ck = Checker()
check = _ck.check


def _session(user_txt: str, memory_path="memory_http.jsonl"):
    return {
        "room_id": "http1",
        "history": [{"character": "user", "txt": user_txt}],
        "moderator_state": {"mode": "S", "state": "Exploration", "stall": False, "goal": ""},
        "has_spoken": {"A": False, "B": False, "C": False},
        "mention_queue": [],
        "agent_runtime_config": {
            k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"
        },
        "think_fp": None,
        "moderator_fp": None,
        "chat_fp": None,
        "rationale_fp": open("rationale_http.jsonl", "a", encoding="utf-8"),
        "memory_fp": open(memory_path, "a", encoding="utf-8"),
        "memory_snippets": {"A": [], "B": [], "C": []},
        "turns_since_distill": {"A": 0, "B": 0, "C": 0},
        "latest_rationale": {"A": "", "B": "", "C": ""},
        "latest_snippet_id": {"A": None, "B": None, "C": None},
        "snippet_counters": {"A": 0, "B": 0, "C": 0},
    }


agents = {k: aw.ChatAgent(k, f"Chatbot{k}", f"role {k}") for k in "ABC"}
agent_list = [agents[k] for k in "ABC"]
names = [a.name for a in agent_list]


def fake_factory(admin2_pick="A", seen_sys=None):
    n = {"i": 0}

    def fake(client, model, messages, temp, max_tok):
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        user_c = messages[-1]["content"]
        if "Distill the agent's CURRENT position" in user_c:
            return "Distilled stance: prioritize growth with named trade-offs."
        if sys_c.startswith("You are Admin-2"):
            return admin2_pick
        if sys_c.startswith("You are Admin-1"):
            return f"analysis. NEXT = {admin2_pick}"
        if "deliberation moderator" in sys_c:
            return "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n[/Moderator]"
        if seen_sys is not None and sys_c.startswith("You are Chatbot"):
            seen_sys.append(sys_c)
        n["i"] += 1
        return (
            f"[MESSAGE]\nunique http point {n['i']} omega{n['i']} sigma{n['i']}\n[/MESSAGE]\n"
            f"[RATIONALE]\nwhy {n['i']}\n[/RATIONALE]"
        )

    return fake


# Mention hard-route: user @ChatbotB must speak first
sess = _session("@ChatbotB please")
r = aw.run_user_turn(
    session=sess,
    user_message="@ChatbotB please",
    agents=agents,
    agent_list=agent_list,
    all_agent_names=names,
    client_chat=object(),
    client_admin=object(),
    scene="s",
    prefer_agents=0.0,
    novelty_threshold=0.0,
    max_agent_turns_before_user=3,
    create_response_with_client=fake_factory("A"),
)
check("http: mention hard-routes B first", r["responses"][0]["agent"] == "ChatbotB", r["responses"])

# No consecutive same speaker even when Admin-2 always says A
sess2 = _session("go on")
for a in agent_list:
    a.spoke = 0
r2 = aw.run_user_turn(
    session=sess2,
    user_message="go on",
    agents=agents,
    agent_list=agent_list,
    all_agent_names=names,
    client_chat=object(),
    client_admin=object(),
    scene="s",
    prefer_agents=1.0,
    novelty_threshold=0.0,
    max_agent_turns_before_user=5,
    create_response_with_client=fake_factory("A"),
)
speakers = [x["agent"] for x in r2["responses"]]
dup = any(a == b for a, b in zip(speakers, speakers[1:]))
check("http: no consecutive same speaker under Admin-2=A + prefer=1", not dup, speakers)
check("http: returns phase key", "phase" in r and "concluded" in r)

# ---- in-session distill: periodic after DISTILL_TRIGGER_INTERVAL utterances of A
mem_path = "memory_distill.jsonl"
open(mem_path, "w", encoding="utf-8").close()
sess_d = _session("@ChatbotA only", memory_path=mem_path)
seen = []
fake = fake_factory("U", seen_sys=seen)

for i in range(1, 5):
    # Keep one persistent session across HTTP turns
    if i > 1:
        sess_d["history"].append({"character": "user", "txt": f"@ChatbotA again {i}"})
    for a in agent_list:
        a.spoke = 0
    aw.run_user_turn(
        session=sess_d,
        user_message=f"@ChatbotA again {i}" if i > 1 else "@ChatbotA only",
        agents=agents,
        agent_list=agent_list,
        all_agent_names=names,
        client_chat=object(),
        client_admin=object(),
        scene="s",
        prefer_agents=0.0,
        novelty_threshold=0.0,
        max_agent_turns_before_user=1,
        create_response_with_client=fake,
    )

mem_recs = [json.loads(l) for l in open(mem_path, encoding="utf-8") if l.strip()]
check("http distill: periodic produced at least one memory record", len(mem_recs) >= 1, mem_recs)
check(
    "http distill: trigger is periodic (or phase_change)",
    mem_recs[0].get("trigger") in {"periodic", "phase_change", "stall"},
    mem_recs[0],
)
check("http distill: snippet has content", bool(mem_recs[0].get("content")), mem_recs[0])
check(
    "http distill: session memory_snippets populated for A",
    len(sess_d.get("memory_snippets", {}).get("A") or []) >= 1,
    sess_d.get("memory_snippets"),
)

# Next turn: ChatbotA system prompt must include YOUR MEMORY
seen.clear()
sess_d["history"].append({"character": "user", "txt": "@ChatbotA remember"})
aw.run_user_turn(
    session=sess_d,
    user_message="@ChatbotA remember",
    agents=agents,
    agent_list=agent_list,
    all_agent_names=names,
    client_chat=object(),
    client_admin=object(),
    scene="s",
    prefer_agents=0.0,
    novelty_threshold=0.0,
    max_agent_turns_before_user=1,
    create_response_with_client=fake_factory("U", seen_sys=seen),
)
a_prompts = [p for p in seen if p.startswith("You are ChatbotA")]
check("http distill: ChatbotA spoke again with captured system prompt", len(a_prompts) >= 1, len(a_prompts))
check(
    "http distill: YOUR MEMORY injected into ChatbotA system prompt",
    any("YOUR MEMORY" in p for p in a_prompts),
    a_prompts[0][-400:] if a_prompts else "",
)

# parent_id chain if we got 2+ snippets for A
a_snips = sess_d.get("memory_snippets", {}).get("A") or []
if len(a_snips) >= 2:
    check(
        "http distill: parent_id links to previous snippet",
        a_snips[1].get("parent_id") == a_snips[0].get("id"),
        a_snips,
    )
else:
    # Force a second periodic by 4 more A-only turns
    for i in range(4):
        sess_d["history"].append({"character": "user", "txt": f"@ChatbotA more {i}"})
        aw.run_user_turn(
            session=sess_d,
            user_message=f"@ChatbotA more {i}",
            agents=agents,
            agent_list=agent_list,
            all_agent_names=names,
            client_chat=object(),
            client_admin=object(),
            scene="s",
            prefer_agents=0.0,
            novelty_threshold=0.0,
            max_agent_turns_before_user=1,
            create_response_with_client=fake_factory("U"),
        )
    a_snips = sess_d.get("memory_snippets", {}).get("A") or []
    check("http distill: second snippet exists after more turns", len(a_snips) >= 2, a_snips)
    if len(a_snips) >= 2:
        check(
            "http distill: parent_id links to previous snippet",
            a_snips[1].get("parent_id") == a_snips[0].get("id"),
            a_snips,
        )

_ck.finish("RUN_USER_TURN CHECKS PASSED")
