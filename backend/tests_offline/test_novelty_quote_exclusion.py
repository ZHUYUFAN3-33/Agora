# -*- coding: utf-8 -*-
"""Quote exclusion: replying to a claim must not be scored as repeating it.

Measured before this change: 11 of 28 novelty retries scored LOWER than the
first attempt, because engaging a specific point re-quotes it and the metric
counted the quotation as repetition. Now the reply-target's last message (from
the [MOVE] @target, falling back to body @mentions) is excluded from scoring:
excluded tokens count neither as new nor toward the denominator, so the score
measures only the non-quoted part. A message that is nothing but quotation
scores 0.0 — same semantics as an empty message.
"""
from _harness import bootstrap, Checker

aw = bootstrap("novelty_qx_")
_ck = Checker()
check = _ck.check

# ---------------------------------------------------------------- pure metric
B_CLAIM = "the relocation cost and the probation clause make company b fragile"
WINDOW = [f"ChatbotB: {B_CLAIM}"]
# Replies to B by quoting the claim, then adds a genuinely new angle.
# Short tail on purpose: 0.40 plain (comfortably under the 0.5 trigger without
# sitting on it) vs 1.0 once the quotation is excluded.
REPLY = B_CLAIM + " however visa sponsorship flips that"
EXCL = aw._content_tokens(B_CLAIM)

plain = aw.novelty_ratio(REPLY, WINDOW)
excluded = aw.novelty_ratio(REPLY, WINDOW, exclude_tokens=EXCL)
check(f"without exclusion the reply reads as mostly repetition ({plain:.2f})",
      plain < 0.5)
check(f"with the quote excluded, the new part is fully novel ({excluded:.2f})",
      excluded == 1.0)
check("pure quotation scores 0.0 — no contribution",
      aw.novelty_ratio(B_CLAIM, WINDOW, exclude_tokens=EXCL) == 0.0)
check("exclude_tokens=None is byte-identical to the old behaviour",
      aw.novelty_ratio(REPLY, WINDOW, exclude_tokens=None) == plain)

# CJK bigrams travel through the same path.
zh_claim = "搬家成本和试用期风险让乙公司变得脆弱"
zh_reply = zh_claim + "不过签证支持完全改变判断"
zh_plain = aw.novelty_ratio(zh_reply, [f"ChatbotB: {zh_claim}"])
zh_excl = aw.novelty_ratio(zh_reply, [f"ChatbotB: {zh_claim}"],
                           exclude_tokens=aw._content_tokens(zh_claim))
check(f"CJK: exclusion raises the score ({zh_plain:.2f} -> {zh_excl:.2f})",
      zh_excl > zh_plain)

# ------------------------------------------------------- target resolution
mp = aw.build_mention_patterns(["A", "B", "C"], {"A": "ChatbotA", "B": "ChatbotB", "C": "ChatbotC"})
check("move_detail @name resolves",
      aw.resolve_reply_target("challenge @ChatbotB", "", mp, "A") == "B")
check("self-mention in move_detail is skipped, body fallback used",
      aw.resolve_reply_target("challenge @A", "some text @ChatbotC", mp, "A") == "C")
check("no target -> None (old behaviour)",
      aw.resolve_reply_target("new_point", "no mentions here", mp, "A") is None)
check("@U is not an agent and resolves to nothing",
      aw.resolve_reply_target("clarify @U", "", mp, "A") is None)
check("last_message_of returns the newest unprefixed utterance",
      aw.last_message_of("ChatbotB", ["ChatbotB: first", "ChatbotA: x", "ChatbotB: second"]) == "second")
check("never-spoke target yields empty string",
      aw.last_message_of("ChatbotC", ["ChatbotB: first"]) == "")

# ---------------------------------------------------- end-to-end (HTTP path)
SEED = "I am weighing stability against growth in this job decision right now"
B_LINE = "the probation clause and relocation budget both count against company b"
# 0.417 against the seeded window without a target (trips the 0.5 trigger,
# clears the 0.25 drop bar), 1.0 with B's line excluded.
NEW_TAIL = " yet the mentorship pipeline argues otherwise"


def _session():
    return {
        "room_id": "qx1",
        "history": [{"character": "user", "txt": SEED},
                    {"character": "ChatbotB", "txt": B_LINE}],
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


def run(move_line, body):
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
        return (
            f"[MOVE]\n{move_line}\n[/MOVE]\n[RATIONALE]\nwhy\n[/RATIONALE]\n"
            f"[MESSAGE]\n{body}\n[/MESSAGE]"
        )

    s = _session()
    aw.run_user_turn(
        session=s, user_message=SEED, agents=agents, agent_list=agent_list,
        all_agent_names=names, client_chat=object(), client_admin=object(), scene="s",
        prefer_agents=0.0, max_agent_turns_before_user=1, create_response_with_client=fake,
    )
    published = [m for m in s["history"] if m["character"] not in ("user",)]
    # history seeded with one ChatbotB row; drop it from the "published this turn" view
    published = [m for m in published if (m.get("txt") or "") != B_LINE]
    return published, state["agent_calls"]

print("== engaging B's claim with an @ does not trip the guard ==")
spoke, calls = run("challenge @ChatbotB", B_LINE + NEW_TAIL)
check(f"no retry: the quoted part was excluded (calls={calls})",
      calls == 1)
check("the reply is published first time",
      len(spoke) == 1)

print("== the same text without a target still trips it ==")
spoke2, calls2 = run("new_point", B_LINE + NEW_TAIL)
check(f"without a target the old semantics hold and the guard retries (calls={calls2})",
      calls2 == 2)

print("== pure quotation with a target is still caught ==")
spoke3, calls3 = run("challenge @ChatbotB", B_LINE)
check(f"all-quote message scores 0.0 and triggers the retry (calls={calls3})",
      calls3 == 2)

_ck.finish("ALL CHECKS PASSED")
