# -*- coding: utf-8 -*-
"""Offline checks for the Option Board (no LLM).

The replay cases use the REAL labels from room 732594 — the room where three
chip groups appeared in eleven messages, two of them semantically identical
back-to-back during the greeting round.
"""
import os
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

failures = []


def check(cond, name, detail=""):
    if cond:
        print(f"  OK  {name}")
    else:
        print(f"FAIL  {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


from option_board import (
    SIM_THRESHOLD,
    active_axis,
    board_has_content,
    board_prompt_block,
    decide_display,
    empty_board,
    load_board,
    mark_chosen,
    reconcile,
    save_board,
    seed_intake,
    similarity,
    user_asked_to_choose,
)
from decision_map import assemble_smart_map, build_option_layer_from_board


# ---------------------------------------------------------------------------
print("== similarity ==")
MERGE = [
    ("Choose Sony for stability", "Sony for balance"),
    ("Explore Honda for growth despite risks", "Honda for growth"),
    ("选择索尼求稳", "索尼稳定路线"),
    ("Stay at current job", "Stay at your current job"),
]
SPLIT = [
    ("Choose a startup", "Choose a big company"),
    ("Choose a startup", "Choose Sony for stability"),
    ("华为手机", "苹果手机"),          # generic suffix must not merge
    ("Sony for balance", "Honda for growth"),
    ("换到新工作", "留在现在的公司"),
]
for a, b in MERGE:
    check(similarity(a, b) >= SIM_THRESHOLD, f"merges: {a!r} ~ {b!r}",
          f"sim={similarity(a, b):.2f}")
for a, b in SPLIT:
    check(similarity(a, b) < SIM_THRESHOLD, f"splits: {a!r} vs {b!r}",
          f"sim={similarity(a, b):.2f}")

# ---------------------------------------------------------------------------
print("== reconcile: room 732594 replay ==")
b = empty_board("732594")
r2 = reconcile(b, [
    {"id": "o1", "label": "Choose Sony for stability"},
    {"id": "o2", "label": "Explore Honda for growth despite risks"},
], speaker="ChatbotB", msg_index=2)
r3 = reconcile(b, [
    {"id": "o1", "label": "Sony for balance"},
    {"id": "o2", "label": "Honda for growth"},
], speaker="ChatbotC", msg_index=3)
r5 = reconcile(b, [
    {"id": "o1", "label": "Choose a startup"},
    {"id": "o2", "label": "Choose a big company"},
], speaker="ChatbotA", msg_index=5)

check(len(b["axes"]) == 2, "two axes (Sony/Honda + startup/bigco)")
ax1 = b["axes"][0]
check(len(ax1["options"]) == 2, "repeat group merged, not appended")
check(not r3["added"] and len(r3["endorsed"]) == 2,
      "C's repeat recorded as endorsement of both options")
check(all(any(e["by"] == "ChatbotC" for e in o["endorsed_by"]) for o in ax1["options"]),
      "endorsed_by carries ChatbotC")
check(any("Sony for balance" in (o.get("aliases") or []) for o in ax1["options"]),
      "new wording kept as alias")
check(r5["axis"]["id"] != ax1["id"], "different question opens a new axis")
check(r3["mapping"]["o1"] == ax1["options"][0]["id"],
      "proposal ids map to canonical board ids")

# same speaker re-proposing own option is not an endorsement
rb = reconcile(b, [
    {"id": "o1", "label": "Sony for stability"},
    {"id": "o2", "label": "Honda for growth"},
], speaker="ChatbotB", msg_index=7)
check(not rb["endorsed"], "proposer repeating own options adds no endorsement")

# ---------------------------------------------------------------------------
print("== display policy ==")
check(decide_display(b, r2["axis"], force_intro=True, msg_index=2) is None,
      "greeting turn never renders chips")
check(decide_display(b, r3["axis"], phase="Exploration", user_message="thanks",
                     msg_index=3) is None,
      "early exploration, no ask: suppressed (board still accumulated)")
check(user_asked_to_choose("Should I choose a startup or a big company?"),
      "choose-intent detected (en)")
check(user_asked_to_choose("我该选哪个？"), "choose-intent detected (zh)")
chips = decide_display(b, r5["axis"], phase="Exploration",
                       user_message="Should I choose a startup or a big company?",
                       msg_index=5)
check(chips is not None and len(chips) == 2, "user ask renders the axis")
check(decide_display(b, b["axes"][0], phase="Exploration", user_message="",
                     msg_index=6) is None,
      "global cooldown right after a render")
stable = decide_display(b, b["axes"][0], phase="Exploration", user_message="",
                        msg_index=99)
check(stable is not None, "stable axis eventually renders once")
check(decide_display(b, b["axes"][0], phase="Narrowing", user_message="",
                     msg_index=120) is None,
      "no re-render when nothing changed since last display")

# ---------------------------------------------------------------------------
print("== choice ==")
target = b["axes"][1]["options"][1]["id"]
axis = mark_chosen(b, target)
check(axis is not None and axis["chosen_option_id"] == target, "mark_chosen finds axis")
check([o["status"] for o in axis["options"]] == ["rejected", "chosen"],
      "open siblings become rejected")
check(mark_chosen(b, "msg-3:o1") is None, "legacy id misses the board (no-op)")
check(decide_display(b, axis, phase="Narrowing", user_message="选哪个",
                     msg_index=30) is None,
      "decided axis never re-renders")

# ---------------------------------------------------------------------------
print("== user-ask without proposal (intake-seeded axis) ==")
ib = empty_board("intake-room")
seed_intake(ib, [
    "Stay at BigTech Co (stable, high salary, slower growth)",
    "Join NovaAI startup (Series B, equity, faster growth, higher risk)",
])
iax = active_axis(ib)
check(iax is not None, "active_axis finds the intake axis")
check(ib["axes"][0]["options"][0]["label"].endswith("growth)"),
      "intake labels survive uncut")
ichips = decide_display(ib, iax, phase="Exploration",
                        user_message="which one should I choose?",
                        msg_index=10, user_msg_index=9)
check(ichips is not None and len(ichips) == 2,
      "user ask renders an axis nobody re-proposed")
check(decide_display(ib, iax, phase="Exploration",
                     user_message="which one should I choose?",
                     msg_index=11, user_msg_index=9) is None,
      "same ask renders once per round, not per agent")

# ---------------------------------------------------------------------------
print("== prompt block ==")
blk = board_prompt_block(b)
check("Choose Sony for stability" in blk and "endorsed by ChatbotC" in blk,
      "prompt block lists canonical labels + endorsers")
check("[chosen]" in blk and "[rejected]" in blk, "prompt block shows statuses")
check(board_prompt_block(empty_board("x")) == "", "empty board yields no block")

# ---------------------------------------------------------------------------
print("== persistence + intake ==")
with tempfile.TemporaryDirectory() as td:
    save_board(td, "999999", b)
    b2 = load_board(td, "999999")
    check(b2["axes"][1]["chosen_option_id"] == target, "board round-trips")
    nb = empty_board("888888")
    seed_intake(nb, ["Plan A", {"label": "Plan B"}, ""])
    check(board_has_content(nb) and len(nb["axes"][0]["options"]) == 2,
          "intake seeds an axis silently")
    check(nb["axes"][0]["options"][0]["proposed_by"] == "intake", "intake attribution")

# ---------------------------------------------------------------------------
print("== board -> map layer ==")
choices = [{
    "id": "ch-1",
    "choice_group_id": "whatever-msg-id",
    "option_id": target,
    "label": "Choose a big company",
    "selection_message_index": 11,
}]
layer = build_option_layer_from_board(b, choices, lang="en")
check(len(layer["options"]) == 4, "all board options surface")
by_id = {o["id"]: o for o in layer["options"]}
check(by_id[target]["status"] == "chosen", "chosen status flows through")
check(any(o["endorsed_by"] == ["ChatbotC"] for o in layer["options"]),
      "endorsed_by reaches the map payload")
check(any(e["type"] == "chooses" and e["to"] == target for e in layer["edges"]),
      "chooses edge points at the board id")
check(layer["issues"][0]["winning_option_id"] == target, "winning option set")
sel = [c for c in layer["claims"] if c["badge"] == "selection"]
check(len(sel) == 1 and sel[0]["message_indexes"] == [11], "selection claim with index")

msgs = [{"character": "user", "txt": f"m{i}"} for i in range(12)]
payload = assemble_smart_map(
    room_id="732594", msgs=msgs, lang="en", choices=choices, board=b,
)
pby = {o["id"]: o for o in payload.get("options") or []}
check(target in pby and pby[target]["status"] == "chosen",
      "assemble_smart_map board fast path keeps board ids + chosen")
check(any(o.get("endorsed_by") for o in payload.get("options") or []),
      "endorsed_by survives normalize/merge in the full payload")

legacy_payload = assemble_smart_map(
    room_id="000000",
    msgs=[
        {"id": "m1", "character": "A", "txt": "hi",
         "options": [{"id": "o1", "label": "X"}, {"id": "o2", "label": "Y"}]},
    ] * 3,
    lang="en",
    choices=[],
    board=None,
)
check(any(str(o["id"]).startswith("m1:") for o in legacy_payload.get("options") or []),
      "legacy rooms still use the read-time layer")

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL OK")
