# -*- coding: utf-8 -*-
"""Regression: the private RATIONALE must never reach the chat message.

Observed live in a zh parent_child session: the system prompt orders "write every
message in Chinese, do not switch language mid-message", and the model applied
that to the TAGS as well, emitting [消息]/[理由] instead of [MESSAGE]/[RATIONALE].
The parser matched only the English spelling, fell through to its no-tags branch,
and that branch stripped only English tags — so the whole generation, private
rationale and both tag pairs included, was published as the chat message while
the rationale log got nothing.

Covered here: translated tags, mixed pairs, an unclosed rationale block, the
original English form, and plain untagged text.
"""
import os
import sys

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_tags_")
_ck = Checker(); check = _ck.check

MSG = "@ChatbotC，我们可以：A) 短期试验，或 B) 暂时不报名。"
RAT = "我提出了两个简化选项，强调可逆性。"

CASES = [
    ("translated tags (the live failure)",
     f"[消息]\n{MSG}\n[/消息]\n[理由]\n{RAT}\n[/理由]", MSG, RAT),
    ("english tags (unchanged behaviour)",
     "[MESSAGE]\nhello there\n[/MESSAGE]\n[RATIONALE]\nbecause reasons\n[/RATIONALE]",
     "hello there", "because reasons"),
    ("mixed english/chinese pairs",
     f"[MESSAGE]\n{MSG}\n[/消息]\n[理由]\n{RAT}\n[/RATIONALE]", MSG, RAT),
]

for name, raw, want_msg, want_rat in CASES:
    p = aw.parse_agent_turn(raw)
    check(f"{name}: message is the message", p["message"] == want_msg, repr(p["message"]))
    check(f"{name}: rationale is captured", p["rationale"] == want_rat, repr(p["rationale"]))

# An unclosed rationale block used to leave the rationale sitting in the message.
p = aw.parse_agent_turn(f"[消息]\n{MSG}\n[/消息]\n[理由]\n{RAT}")
check("unclosed rationale: message stays clean", p["message"] == MSG, repr(p["message"]))
check("unclosed rationale: nothing of it leaks",
      RAT not in p["message"], repr(p["message"]))

# Untagged output still falls back to "the whole thing is the message".
p = aw.parse_agent_turn("就是一段普通文字，没有任何标签")
check("untagged text is used as-is", p["message"] == "就是一段普通文字，没有任何标签")

# No tag token of any spelling may survive into a published message.
for raw in [c[1] for c in CASES] + [f"[消息]\n{MSG}\n[/消息]\n[理由]\n{RAT}"]:
    m = aw.parse_agent_turn(raw)["message"]
    check("no tag token survives into the chat message",
          not any(t in m for t in ("[MESSAGE]", "[/MESSAGE]", "[RATIONALE]", "[/RATIONALE]",
                                   "[消息]", "[/消息]", "[理由]", "[/理由]")), repr(m))

# The prompt itself must tell the model not to translate the tags.
_sp = aw.ChatAgent("A", "ChatbotA", "(role)").system_prompt(
    scene="(s)", name_map={"A": "ChatbotA"}, lang="zh")
check("prompt instructs that the tags stay in English",
      "Do NOT translate them" in _sp and "[消息]" in _sp, _sp[-400:])

# OPTIONS: English tags + zh / ja aliases; labels keep chat language.
OPTS_EN = '[{"id":"o1","label":"Stay"},{"id":"o2","label":"Switch"}]'
OPTS_ZH = '[{"id":"o1","label":"留下"},{"id":"o2","label":"跳槽"}]'
OPTS_JA = '[{"id":"o1","label":"残る"},{"id":"o2","label":"転職する"}]'

p = aw.parse_agent_turn(
    f"[MESSAGE]\nPick one.\n[/MESSAGE]\n[OPTIONS]\n{OPTS_EN}\n[/OPTIONS]\n[RATIONALE]\nr\n[/RATIONALE]"
)
check("OPTIONS english tags parse", len(p["options"]) == 2 and p["options"][0]["label"] == "Stay",
      repr(p["options"]))
check("OPTIONS stripped from message", "OPTIONS" not in p["message"] and "Stay" not in p["message"],
      repr(p["message"]))

p = aw.parse_agent_turn(
    f"[消息]\n选一个。\n[/消息]\n[选项]\n{OPTS_ZH}\n[/选项]\n[理由]\nr\n[/理由]"
)
check("OPTIONS chinese alias tags parse",
      len(p["options"]) == 2 and p["options"][1]["label"] == "跳槽", repr(p["options"]))

p = aw.parse_agent_turn(
    f"[メッセージ]\nどれにする？\n[/メッセージ]\n[選択肢]\n{OPTS_JA}\n[/選択肢]\n[根拠]\nr\n[/根拠]"
)
check("OPTIONS japanese alias tags parse",
      len(p["options"]) == 2 and p["options"][0]["label"] == "残る", repr(p["options"]))
check("japanese MESSAGE captured", p["message"] == "どれにする？", repr(p["message"]))

_sp_ja = aw.ChatAgent("A", "ChatbotA", "(role)").system_prompt(
    scene="(s)", name_map={"A": "ChatbotA"}, lang="ja")
check("ja session asks for Japanese messages", "日本語" in _sp_ja, _sp_ja[:500])

_ck.finish("TAG PARSING CHECKS PASSED")
