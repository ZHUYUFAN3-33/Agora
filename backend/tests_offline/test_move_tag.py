# -*- coding: utf-8 -*-
"""Unit tests for the [MOVE] self-report block.

Agents label what their own turn DOES (challenge / extend / new_point /
concede / clarify). Ported from feature/dialogue-naturalness WITHOUT that
branch's consumers: there the signal also steered the consensus warning and the
convergence gate, which would change speaker scheduling and break this fork's
fidelity to agora2/backend-dev. Here the move is parsed and logged only — it
reaches {room}_rationale.jsonl as a "move" event for map_facts.py, and nothing
in the deliberation loop reads it. That is why this file does not test
turn_is_challenge: the function was deliberately left behind.

Parsing must degrade to "" on any malformed block (never a guessed move), and
stray MOVE tags must never leak into the chat message.
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

# ------------------------------------------------- the prompt asks for it
_sp = aw.ChatAgent("A", "ChatbotA", "(role)").system_prompt(
    scene="(s)", name_map={"A": "ChatbotA", "B": "ChatbotB"}, lang="zh")
check("OUTPUT FORMAT declares the MOVE block", "[MOVE]" in _sp and "[/MOVE]" in _sp)
check("prompt lists every accepted move",
      all(m in _sp for m in aw.AGENT_MOVES), aw.AGENT_MOVES)
# Used to assert the prompt called MOVE/RATIONALE "private". That wording was
# false — both render in the decision map — and it was why rationales came back
# written as internal notes about "the user". The contract the model actually
# needs is: not spoken in the room, but read by the person being advised.
check("prompt says MOVE/RATIONALE are not spoken aloud", "not spoken aloud" in _sp)
check("prompt says the advised person reads them in the map",
      "decision map" in _sp and "written to be read by that person" not in _sp.split("decision map")[0])

# --------------------------------------- the fact layer's parsing caveat holds
# map_facts.py takes the kind off the FIRST token rather than calling
# normalize_move, because normalize_move scans AGENT_MOVES in tuple order.
# Pin that difference so a future reorder does not silently change either side.
check("normalize_move is tuple-ordered, not text-ordered (map_facts relies on this)",
      aw.normalize_move("extend @ChatbotB, not a challenge") == "challenge",
      aw.normalize_move("extend @ChatbotB, not a challenge"))
check("first-token rule would disagree, which is why map_facts uses it",
      "extend @ChatbotB, not a challenge".split()[0] == "extend")

_ck.finish("MOVE TAG CHECKS PASSED")
