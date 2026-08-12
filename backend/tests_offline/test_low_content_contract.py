# -*- coding: utf-8 -*-
"""Low-content turn contract: greeting-shaped user turns get a short-reply
directive injected via the `extra` container; substantive turns do not.

Measured motivation: a bare "你好" drew ~950 words per agent on gpt-5.6 —
response effort did not track the information in the user's message.

NOTE Checker.check is (name, cond, detail) — name FIRST.
"""
from _harness import bootstrap, Checker

aw = bootstrap("low_content_")
_ck = Checker()
check = _ck.check

# ------------------------------------------------------------- classification
LOW = [
    "你好",            # CJK bigram -> 1 token
    "嗯嗯",            # 1 token
    "hi",              # <3-char latin word -> 0 tokens
    "ok thanks",       # still under the bar
    "Yea sure",        # smoke_chat's probe
    "",                # empty
]
NOT_LOW = [
    "选A还是B？",                                   # short but a real question (？ hatch)
    "which one?",                                   # ? hatch
    "@ChatbotC what would change your mind",        # @ hatch
    "我爸妈希望我考公务员，但我想去做产品设计，家里觉得不稳定。",
    "Location is the hard part - Tochigi means weekday separation from my partner.",
]
for t in LOW:
    check(f"low: {t!r}", aw.is_low_content_message(t))
for t in NOT_LOW:
    check(f"not low: {t!r}", not aw.is_low_content_message(t))

# ------------------------------------------------- injection into the prompt
SEED = "hello there"
MARKER = aw.LOW_CONTENT_TURN_DIRECTIVE


def _session():
    return {
        "room_id": "lc1",
        "history": [{"character": "user", "txt": SEED}],
        "moderator_state": {"mode": "S", "state": "Exploration", "stall": False, "goal": ""},
        "has_spoken": {k: False for k in "ABC"},
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


def run(**kwargs):
    """Capture every prompt the fake client sees, split by role of the call."""
    seen = {"agent_user_prompts": [], "admin_prompts": []}

    def fake(client, model, messages, temp, max_tok):
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        user_c = messages[-1]["content"]
        if "Distill the agent's CURRENT position" in user_c:
            return "d"
        if sys_c.startswith("You are Admin-2"):
            seen["admin_prompts"].append(user_c)
            return "A"
        if sys_c.startswith("You are Admin-1"):
            seen["admin_prompts"].append(user_c)
            return "analysis. NEXT = A"
        if "deliberation moderator" in sys_c:
            seen["admin_prompts"].append(user_c)
            return "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n[/Moderator]"
        seen["agent_user_prompts"].append(user_c)
        return ("[MOVE]\nnew_point\n[/MOVE]\n[RATIONALE]\nr\n[/RATIONALE]\n"
                "[MESSAGE]\nHi, I'm ChatbotA — what matters most to you?\n[/MESSAGE]")

    s = _session()
    aw.run_user_turn(
        session=s, user_message=SEED, agents=agents, agent_list=agent_list,
        all_agent_names=names, client_chat=object(), client_admin=object(), scene="s",
        prefer_agents=0.0, max_agent_turns_before_user=1,
        create_response_with_client=fake, **kwargs,
    )
    return seen


print("== directive lands in the agent prompt, and only there ==")
seen = run(turn_directive=MARKER)
check("agent prompt carries the directive",
      any(MARKER in p for p in seen["agent_user_prompts"]))
check("admin/moderator prompts do not",
      not any(MARKER in p for p in seen["admin_prompts"]))

print("== intro note and directive coexist on a first message ==")
first_prompt = next((p for p in seen["agent_user_prompts"] if MARKER in p), "")
check("force_intro line still present",
      "This is your FIRST message" in first_prompt)
check("directive sits after the board/intro notes (closest to generation)",
      first_prompt.rfind(MARKER) > first_prompt.rfind("This is your FIRST message"))

print("== production-shaped call without the kwarg is untouched ==")
seen_plain = run()
check("no directive anywhere when omitted",
      not any(MARKER in p for p in seen_plain["agent_user_prompts"]))

_ck.finish("ALL CHECKS PASSED")
