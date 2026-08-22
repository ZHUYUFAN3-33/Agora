# -*- coding: utf-8 -*-
"""Regression: a cap-truncated generation must never be silently discarded.

Measured across three study rooms (P34 953489, P41 675008/894275): 39 of 43
agent turns hit max_output_tokens mid-[MESSAGE], and the parser fallback —
_TRAILING_RATIONALE_RE over the whole raw text — matched the LEADING [MOVE]
tag at index 0 and deleted the entire generation. 90.7% of turns dropped;
P41 saw exactly one agent speak across two rooms and reported "一直是同一个
agent在说话". The phantom turns also consumed Force-U slots, moderator
cadence, and last_speaker_key, and locked Admin-1's fairness heuristic onto
the failing agent ("让未发言的 A 接话" while A had been scheduled 20 times).

Covered here:
  1. parse_agent_turn salvages an unclosed [MESSAGE] body (all tag spellings),
     trims the ragged tail to a sentence end, and never leaks private blocks.
  2. The legacy no-tags fallback still strips complete/unclosed private blocks
     without deleting untagged prose that FOLLOWS a closed leading block.
  3. agent_turn retries once at double the cap when the API reports
     max_output_tokens, and prefers the retry when it parses.
  4. A turn that still drops rolls its scheduling state back (no Force-U slot,
     no last_speaker, no moderator-cadence tick) but keeps sched_counts.
  5. The phantom-drop cap ends the burst instead of looping to the safety bound.
  6. Admin-1 is shown scheduled counts so a failing agent stops looking unspoken.
"""
import json
import os

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_salvage_")
_ck = Checker()
check = _ck.check

# ---------------------------------------------------------------- parser unit
TRUNC = (
    "[MOVE]\nextend @ChatbotC\n[/MOVE]\n"
    "[RATIONALE]\n先把岗位类型讲清楚才谈得上取舍。\n[/RATIONALE]\n"
    "[MESSAGE]\nHi, I'm ChatbotB。第一句完整。第二句也完整。第三句被截断在半"
)
p = aw.parse_agent_turn(TRUNC, truncated=True)
check("salvage: truncated MESSAGE body survives",
      p["message"].startswith("Hi, I'm ChatbotB。"), repr(p["message"]))
check("salvage: ragged tail trimmed to sentence end",
      p["message"].endswith("第二句也完整。"), repr(p["message"]))
check("salvage: rationale still captured", p["rationale"] == "先把岗位类型讲清楚才谈得上取舍。")
check("salvage: move still captured", p["move"] == "extend")
check("salvage: flagged as salvaged", p.get("salvaged") is True)
check("salvage: no tag token leaks", "[" not in p["message"], repr(p["message"]))

p = aw.parse_agent_turn("[动作]\nextend\n[/动作]\n[理由]\n理由。\n[/理由]\n[消息]\n中文第一句。被截断的第二句", truncated=True)
check("salvage: translated tags too", p["message"] == "中文第一句。" and p.get("salvaged") is True,
      repr(p["message"]))

p = aw.parse_agent_turn("[MOVE]\nextend\n[/MOVE]\n[RATIONALE]\nr\n[/RATIONALE]\n[MESSAGE]\n没有句读的短片段", truncated=True)
check("salvage: no terminator keeps the fragment", p["message"] == "没有句读的短片段")

# The tail trim must never mangle decimals, URLs, or latin abbreviations.
_P = "[MOVE]\nm\n[/MOVE]\n[RATIONALE]\nr\n[/RATIONALE]\n[MESSAGE]\n"
p = aw.parse_agent_turn(_P + "起薪大约是3.5万日元，另外还有奖金部分没说完", truncated=True)
check("trim: decimal point is not a sentence end", p["message"].endswith("没说完"), repr(p["message"]))
p = aw.parse_agent_turn(_P + "Some roles, e.g. alignment research, need philosophy and the rest is cut", truncated=True)
check("trim: single-letter abbreviation survives", p["message"].endswith("is cut"), repr(p["message"]))
p = aw.parse_agent_turn(_P + "可以看 linkedin.com 上的岗位列表，然后被截断", truncated=True)
check("trim: URL dot survives", p["message"].endswith("被截断"), repr(p["message"]))
p = aw.parse_agent_turn(_P + "This is a full sentence. And this one got cut hal", truncated=True)
check("trim: english sentence end still trims", p["message"] == "This is a full sentence.",
      repr(p["message"]))

# Truncation landing INSIDE a private block leaves no message — still a drop.
p = aw.parse_agent_turn("[MOVE]\nextend\n[/MOVE]\n[RATIONALE]\n截断发生在理由块内")
check("salvage: truncation inside RATIONALE still yields empty", p["message"] == "")

# The no-tags fallback: a leading CLOSED private block must not trigger the
# trailing-block wipe (the exact regression that dropped 39 turns).
p = aw.parse_agent_turn("[MOVE]\nchallenge\n[/MOVE]\n直接就是正文，模型忘了 MESSAGE 标签。")
check("fallback: closed leading block + untagged prose publishes the prose",
      p["message"] == "直接就是正文，模型忘了 MESSAGE 标签。", repr(p["message"]))
check("fallback: move captured from the closed block", p["move"] == "challenge")

# Well-formed generations are untouched.
p = aw.parse_agent_turn("[MOVE]\nclarify\n[/MOVE]\n[RATIONALE]\nr。\n[/RATIONALE]\n[MESSAGE]\n完整正文。\n[/MESSAGE]")
check("well-formed: unchanged", p["message"] == "完整正文。" and p.get("salvaged") is False)

# --- private-content leaks (found by adversarial review) --------------------
# A literal [MESSAGE] token written INSIDE a private block must never anchor
# the salvage: the system prompt names the tags, so a model quoting them in its
# rationale is natural, and anchoring there published the agent's private
# strategy text to the room.
SECRET = "privately I think Option B is doomed and I plan to concede if pressed"
p = aw.parse_agent_turn(f"[MOVE]\nextend\n[/MOVE]\n[RATIONALE]\nKeep the [MESSAGE] upbeat; {SECRET}\n[/RATIONALE]")
check("leak: literal [MESSAGE] inside a CLOSED rationale does not anchor salvage",
      SECRET not in p["message"], repr(p["message"]))
p = aw.parse_agent_turn(f"[MOVE]\nextend\n[/MOVE]\n[RATIONALE]\nKeep the [MESSAGE] upbeat; {SECRET}")
check("leak: literal [MESSAGE] inside an UNCLOSED rationale does not anchor salvage",
      SECRET not in p["message"], repr(p["message"]))
p = aw.parse_agent_turn(f"[理由]\n把 [消息] 写得积极些；{SECRET}\n[/理由]")
check("leak: same via translated tag aliases", SECRET not in p["message"], repr(p["message"]))
p = aw.parse_agent_turn(
    '[MOVE]\nextend\n[/MOVE]\n[OPTIONS]\n[{"id":"o1","label":"[MESSAGE] style answer"},'
    '{"id":"o2","label":"brief"}]\n[/OPTIONS]')
check("leak: literal [MESSAGE] inside OPTIONS does not publish JSON junk",
      "o2" not in p["message"] and "label" not in p["message"], repr(p["message"]))

# A nested [RATIONALE] inside a CLOSED [MESSAGE] span used to publish verbatim.
p = aw.parse_agent_turn(f"[MESSAGE]\n可见正文。[RATIONALE]{SECRET}[/RATIONALE]\n[/MESSAGE]")
check("leak: nested RATIONALE inside a closed MESSAGE is stripped",
      SECRET not in p["message"] and "可见正文。" in p["message"], repr(p["message"]))

# Whitespace inside the brackets used to defeat every regex at once, so the
# whole raw text — private blocks included — was published.
p = aw.parse_agent_turn(f"[ RATIONALE ]\n{SECRET}\n[ /RATIONALE ]\n[ MESSAGE ]\n可见正文。\n[ /MESSAGE ]")
check("spaced tags: message parses", p["message"] == "可见正文。", repr(p["message"]))
check("spaced tags: private content does not leak", SECRET not in p["message"], repr(p["message"]))
check("spaced tags: rationale routed to its own field", p["rationale"] == SECRET, repr(p["rationale"]))

# --- trim only on real truncation ------------------------------------------
# A generation that merely forgot [/MESSAGE] is complete prose: its final,
# unpunctuated sentence (usually the question handing the floor back) must live.
NO_CLOSE = "[MOVE]\nclarify\n[/MOVE]\n[RATIONALE]\nok\n[/RATIONALE]\n[MESSAGE]\n我觉得A方案更稳妥。你们怎么看"
check("format slip (not truncated): final unpunctuated sentence survives",
      aw.parse_agent_turn(NO_CLOSE)["message"].endswith("你们怎么看"),
      repr(aw.parse_agent_turn(NO_CLOSE)["message"]))
check("same input WITH the truncation signal does trim",
      aw.parse_agent_turn(NO_CLOSE, truncated=True)["message"] == "我觉得A方案更稳妥。")

# Single-letter option labels are core vocabulary — "an A." is a sentence end.
check("trim: period after a single-letter option label still ends a sentence",
      aw._trim_truncated_tail("Option B is risky. I would grade it an A. And moreov")
      == "Option B is risky. I would grade it an A.")
check("trim: period after a digit still ends a sentence",
      aw._trim_truncated_tail("I rate Option A a 7. And moreov") == "I rate Option A a 7.")

# --- retry must only replace a WORSE original ------------------------------
complete = aw.parse_agent_turn("[MESSAGE]\n完整的原始消息。\n[/MESSAGE]")
refusal = aw.parse_agent_turn("[MESSAGE]\nI'm sorry, I can't assist with that.\n[/MESSAGE]")
check("retry choice: a complete original is NOT replaced",
      aw._prefer_complete_turn(complete, refusal)["message"] == "完整的原始消息。")
salvaged_orig = aw.parse_agent_turn("[MESSAGE]\n被截断的原始。后半截", truncated=True)
check("retry choice: a salvaged original IS replaced by a complete retry",
      aw._prefer_complete_turn(salvaged_orig, complete)["message"] == "完整的原始消息。")
check("retry choice: a salvaged retry does not replace a salvaged original",
      aw._prefer_complete_turn(salvaged_orig, salvaged_orig)["message"] == salvaged_orig["message"])
empty = aw.parse_agent_turn("[MOVE]\nextend\n[/MOVE]")
check("retry choice: an empty original is replaced by anything usable",
      aw._prefer_complete_turn(empty, complete)["message"] == "完整的原始消息。")

# ------------------------------------------------------------- e2e scaffolding

def _session():
    return {
        "room_id": "salvage1",
        "history": [{"character": "user", "txt": "seed"}],
        "moderator_state": {"mode": "S", "state": "Exploration", "stall": False, "goal": ""},
        "has_spoken": {k: False for k in "ABC"},
        "mention_queue": [],
        "agent_runtime_config": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"},
        "think_fp": None,
        "moderator_fp": None,
        "chat_fp": None,
        "rationale_fp": open("rationale_salvage.jsonl", "a", encoding="utf-8"),
        "memory_fp": open("memory_salvage.jsonl", "a", encoding="utf-8"),
        "memory_snippets": {k: [] for k in "ABC"},
        "turns_since_distill": {k: 0 for k in "ABC"},
        "latest_rationale": {k: "" for k in "ABC"},
        "latest_snippet_id": {k: None for k in "ABC"},
        "snippet_counters": {k: 0 for k in "ABC"},
    }


agents = {k: aw.ChatAgent(k, f"Chatbot{k}", f"role {k}") for k in "ABC"}
agent_list = [agents[k] for k in "ABC"]
names = [a.name for a in agent_list]

COMPLETE_BODY = "重试后的完整消息。"
TRUNC_GEN = (
    "[MOVE]\nnew_point\n[/MOVE]\n[RATIONALE]\nwhy\n[/RATIONALE]\n"
    "[MESSAGE]\n被截断的首次尝试。后半句在这里断"
)
COMPLETE_GEN = (
    "[MOVE]\nnew_point\n[/MOVE]\n[RATIONALE]\nwhy\n[/RATIONALE]\n"
    f"[MESSAGE]\n{COMPLETE_BODY}\n[/MESSAGE]"
)


def run(agent_behavior, max_agent_turns=1):
    """agent_behavior(call_index, max_tok, meta) -> raw text for agent calls.

    The fake accepts meta (signature-probed by create()), so it can mark a
    generation as cap-truncated the way the real API metadata does.
    """
    state = {"agent_calls": [], "admin1_prompts": []}

    def fake(client, model, messages, temp, max_tok, meta=None):
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        user_c = messages[-1]["content"]
        if "Distill the agent's CURRENT position" in user_c:
            return "d"
        if sys_c.startswith("You are Admin-2"):
            return "A"
        if sys_c.startswith("You are Admin-1"):
            state["admin1_prompts"].append(user_c)
            return "analysis. NEXT = A"
        if "deliberation moderator" in sys_c:
            return "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n[/Moderator]"
        i = len(state["agent_calls"])
        state["agent_calls"].append(max_tok)
        return agent_behavior(i, max_tok, meta if meta is not None else {})

    s = _session()
    aw.run_user_turn(
        session=s, user_message="seed", agents=agents, agent_list=agent_list,
        all_agent_names=names, client_chat=object(), client_admin=object(), scene="s",
        prefer_agents=0.0, novelty_threshold=0.0,
        max_agent_turns_before_user=max_agent_turns,
        create_response_with_client=fake,
    )
    spoke = [m for m in s["history"] if m["character"] != "user"]
    return spoke, s, state


print("== truncation triggers one retry at double the cap ==")

def truncate_then_complete(i, max_tok, meta):
    if i == 0:
        meta["incomplete_reason"] = "max_output_tokens"
        meta["status"] = "incomplete"
        return TRUNC_GEN
    return COMPLETE_GEN

spoke, s, st = run(truncate_then_complete)
check("retry: exactly two generation calls", len(st["agent_calls"]) == 2, st["agent_calls"])
check("retry: second call doubles the cap",
      len(st["agent_calls"]) == 2 and st["agent_calls"][1] == st["agent_calls"][0] * 2,
      st["agent_calls"])
check("retry: the complete retry is what publishes",
      len(spoke) == 1 and COMPLETE_BODY in spoke[0]["txt"], spoke)
check("retry: no phantom slot burned", int(s.get("bots_since_user") or 0) == 1)

print("== retry also truncated: the salvage publishes ==")

def truncate_twice(i, max_tok, meta):
    meta["incomplete_reason"] = "max_output_tokens"
    meta["status"] = "incomplete"
    return TRUNC_GEN

spoke2, s2, st2 = run(truncate_twice)
check("salvage e2e: turn publishes despite double truncation",
      len(spoke2) == 1 and "被截断的首次尝试。" in spoke2[0]["txt"], spoke2)
check("salvage e2e: ragged tail not published",
      len(spoke2) == 1 and "后半句在这里断" not in spoke2[0]["txt"], spoke2)

print("== a genuinely empty turn rolls back and the cap ends the burst ==")

def always_empty(i, max_tok, meta):
    return "[MOVE]\nnew_point\n[/MOVE]\n[RATIONALE]\nr\n[/RATIONALE]"

spoke3, s3, st3 = run(always_empty, max_agent_turns=5)
check("rollback: nothing published", len(spoke3) == 0)
check("rollback: no Force-U slot consumed", int(s3.get("bots_since_user") or 0) == 0,
      s3.get("bots_since_user"))
check("rollback: last_speaker_key untouched", s3.get("last_speaker_key") is None,
      s3.get("last_speaker_key"))
check("rollback: moderator cadence not ticked by phantoms",
      int(s3.get("turns_since_moderator") or 0) <= 1, s3.get("turns_since_moderator"))
check("phantom cap: burst stops after MAX_PHANTOM_DROPS_PER_USER_TURN attempts",
      len(st3["agent_calls"]) == aw.MAX_PHANTOM_DROPS_PER_USER_TURN, st3["agent_calls"])
check("sched_counts: attempts recorded despite rollback",
      sum((s3.get("sched_counts") or {}).values()) == aw.MAX_PHANTOM_DROPS_PER_USER_TURN,
      s3.get("sched_counts"))

print("== the phantom cap does not leak mentions into the next user turn ==")

def run_mentions(user_txt, agent_behavior, max_agent_turns=5):
    state = {"agent_calls": []}

    def fake(client, model, messages, temp, max_tok, meta=None):
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
        i = len(state["agent_calls"])
        state["agent_calls"].append(max_tok)
        return agent_behavior(i, max_tok, meta if meta is not None else {})

    s = _session()
    s["history"] = [{"character": "user", "txt": user_txt}]
    aw.run_user_turn(
        session=s, user_message=user_txt, agents=agents, agent_list=agent_list,
        all_agent_names=names, client_chat=object(), client_admin=object(), scene="s",
        prefer_agents=0.0, novelty_threshold=0.0,
        max_agent_turns_before_user=max_agent_turns,
        create_response_with_client=fake,
    )
    return s, state

s_m, st_m = run_mentions("@ChatbotA @ChatbotB @ChatbotC hello", always_empty)
check("mention leak: queue is emptied when the phantom cap aborts the burst",
      (s_m.get("mention_queue") or []) == [], s_m.get("mention_queue"))

print("== Admin-1 sees scheduled counts ==")
check("admin1 prompt carries scheduled counts",
      st3["admin1_prompts"] and all("Scheduled counts" in p for p in st3["admin1_prompts"]),
      (st3["admin1_prompts"] or [""])[0][-300:])
check("admin1 system prompt tells it to balance on scheduled counts",
      "SCHEDULED counts" in aw.build_admin_prompts(list("ABC"), 5)[0])

# The default cap must clear the measured full-length turn (~750 tokens).
import inspect
check("default cap raised past the measured turn length",
      inspect.signature(aw.run_user_turn).parameters["max_output_tokens"].default >= 900)

_ck.finish("ALL CHECKS PASSED")
