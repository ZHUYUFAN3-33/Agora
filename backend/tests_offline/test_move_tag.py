# -*- coding: utf-8 -*-
"""Unit tests for the [MOVE] self-report block.

Agents label what their own turn DOES (challenge / extend / new_point /
concede / clarify). The consensus guard and the convergence gate read this
signal OR the marker scan — self-report catches politely-worded pushback the
marker list deliberately ignores, markers catch turns whose MOVE block is
missing or garbled. Parsing must degrade to "" (fall back to markers) on any
malformed block, and stray MOVE tags must never leak into the chat message.
"""
from _harness import bootstrap, Checker

aw = bootstrap("agentwake_move_")
_ck = Checker(); check = _ck.check

FULL = ("[MESSAGE]\n我觉得这里有个问题。\n[/MESSAGE]\n"
        "[MOVE]\nchallenge @ChatbotB\n[/MOVE]\n"
        "[RATIONALE]\npushing back on B's cost claim\n[/RATIONALE]")

# ---------------------------------------------------------------- happy path
p = aw.parse_agent_turn(FULL)
check("move parsed", p["move"] == "challenge", repr(p["move"]))
check("move_detail keeps the target", "@ChatbotB" in p["move_detail"], p["move_detail"])
check("message untouched by the move block", p["message"] == "我觉得这里有个问题。", p["message"])
check("rationale untouched", p["rationale"].startswith("pushing back"), p["rationale"])

# ------------------------------------------------------- tolerant normalizing
for body, want in (
    ("challenge", "challenge"),
    ("CHALLENGE.", "challenge"),
    ("new point", "new_point"),
    ("new-point @U", "new_point"),
    ("concede — accepting the schedule cost", "concede"),
    ("something the model made up", ""),
    ("", ""),
):
    check(f"normalize_move({body!r}) -> {want!r}",
          aw.normalize_move(body) == want, repr(aw.normalize_move(body)))

# --------------------------------------------------- absence degrades cleanly
p = aw.parse_agent_turn("[MESSAGE]\nhi\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]")
check("missing MOVE block -> empty move", p["move"] == "" and p["message"] == "hi")

# ------------------------------------------- no leak into the no-tags branch
p = aw.parse_agent_turn("plain text reply [MOVE]challenge @ChatbotA")
check("unclosed MOVE tail stripped from the message",
      p["message"] == "plain text reply", repr(p["message"]))
p = aw.parse_agent_turn("回复内容[动作]challenge[/动作]")
check("translated MOVE tags stripped from the message",
      "[" not in p["message"] and p["message"].startswith("回复内容"), repr(p["message"]))

# --------------------------------------------------- combined challenge signal
check("self-reported challenge counts without marker wording",
      aw.turn_is_challenge("challenge", "也许我们可以再看看另一个角度。"))
check("marker wording counts without a move block",
      aw.turn_is_challenge("", "我不同意这个方向，代价是长期成长。"))
check("agreeable extend is not a challenge",
      not aw.turn_is_challenge("extend", "补充一点：项目周期也值得考虑。"))

_ck.finish("MOVE TAG CHECKS PASSED")
