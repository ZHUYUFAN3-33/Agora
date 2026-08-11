# -*- coding: utf-8 -*-
"""River payload + per-turn summaries (no real LLM)."""
import json
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


from decision_map import _is_leaning_placeholder, normalize_ibis
from map_river import build_river, extract_guidance, flat_board_options
from turn_summaries import ensure_turn_summaries, is_meta_summary, load_summaries

# ---------------------------------------------------------------------------
print("== placeholder guard ==")
check(_is_leaning_placeholder("room leaning or empty"), "en placeholder caught")
check(_is_leaning_placeholder("全场倾向一句（中文）或空"), "zh placeholder caught")
check(not _is_leaning_placeholder("Leaning toward NovaAI for growth"), "real leaning kept")
n = normalize_ibis({"room_leaning": {"direction": "room leaning or empty", "strength": "clear"}})
check(n["room_leaning"] is None, "normalize drops echoed template")

# ---------------------------------------------------------------------------
print("== turn summaries: cache + fake LLM ==")
TURNS = [
    {"id": "m1", "index": 0, "speaker": "user", "is_user": True, "txt": "Which offer should I take?"},
    {"id": "m2", "index": 1, "speaker": "ChatbotA", "is_user": False, "txt": "NovaAI grows your skills faster."},
    {"id": "m3", "index": 2, "speaker": "ChatbotB", "is_user": False, "txt": "BigTech pays reliably; layoffs are the risk."},
]
OPTIONS = [
    {"id": "ax1-o1", "label": "Stay at BigTech Co"},
    {"id": "ax1-o2", "label": "Join NovaAI startup"},
]
calls = {"n": 0}


def fake_llm(model, messages, temp, max_tok):
    calls["n"] += 1
    return json.dumps([
        {"index": 0, "summary": "Asks which offer to take", "keywords": ["choice"], "stances": []},
        {"index": 1, "summary": "NovaAI grows skills faster", "keywords": ["growth"],
         "stances": [{"option_id": "ax1-o2", "sign": "support", "quote": "skills compound faster"}]},
        # The comparative turn: under the old singular contract this produced
        # nothing at all. It must now yield one entry per option.
        {"index": 2, "summary": "BigTech pays reliably; NovaAI equity is the gamble",
         "keywords": ["salary", "layoffs", "equity"],
         "stances": [
             {"option_id": "ax1-o1", "sign": "support", "quote": "pay is predictable"},
             {"option_id": "ax1-o2", "sign": "concern", "quote": "equity may never vest"},
             {"option_id": "ax1-o1", "sign": "concern", "quote": "duplicate option, must be dropped"},
             {"option_id": "nope", "sign": "support", "quote": "unknown option id"},
         ]},
        {"index": 99, "summary": "hallucinated extra row", "keywords": []},
    ])


with tempfile.TemporaryDirectory() as td:
    s1 = ensure_turn_summaries(td, "r1", TURNS, lang="en", options=OPTIONS, create_response=fake_llm)
    check(len(s1) == 3 and calls["n"] == 1, "one batched call summarizes all turns")
    check(s1["m2"]["stances"] == [{"option_id": "ax1-o2", "sign": "support", "quote": "skills compound faster"}],
          "single-option turn keeps one stance")
    two = s1["m3"]["stances"]
    check(len(two) == 2 and {t["option_id"] for t in two} == {"ax1-o1", "ax1-o2"},
          "comparative turn emits one entry per option",
          f"got {two}")
    check(all(t["option_id"] != "nope" for t in two), "unknown option ids rejected")
    check(s1["m3"]["stances"][0]["quote"] == "pay is predictable", "per-option quote kept")
    check("hallucinated" not in json.dumps(s1), "unrequested indexes dropped")
    check(s1["m1"]["schema"] >= 2, "rows carry the schema version")
    s2 = ensure_turn_summaries(td, "r1", TURNS, lang="en", options=OPTIONS, create_response=fake_llm)
    check(calls["n"] == 1, "second call is pure cache (no LLM)")
    edited = [dict(TURNS[0], txt="Changed text"), TURNS[1], TURNS[2]]
    ensure_turn_summaries(td, "r1", edited, lang="en", options=OPTIONS, create_response=fake_llm)
    check(calls["n"] == 2, "text change re-summarizes just that turn")

    # A row written under the old contract must be re-annotated, not reused.
    import os as _os
    with open(_os.path.join(td, "old_turn_summaries.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "turn_id": "m1", "index": 0, "text_hash": "x", "lang": "en",
            "summary": "stale", "keywords": [], "stance": None,
        }) + "\n")
    before = calls["n"]
    ensure_turn_summaries(td, "old", TURNS, lang="en", options=OPTIONS, create_response=fake_llm)
    check(calls["n"] > before, "schema-1 rows are re-annotated, not trusted")

    def broken_llm(model, messages, temp, max_tok):
        raise RuntimeError("api down")

    s4 = ensure_turn_summaries(td, "r2", TURNS, lang="en", options=OPTIONS, create_response=broken_llm)
    check(s4 == {}, "LLM failure returns cache only, never raises")
    check(load_summaries(td, "r1", lang="zh") == {}, "lang-scoped load keeps rooms language-pure")

print("== meta-verb detection ==")
check(is_meta_summary("ChatbotB analyzes financial security of both options"), "meta summary flagged")
check(not is_meta_summary("BigTech pays reliably; NovaAI equity is the gamble"), "substantive summary passes")

# ---------------------------------------------------------------------------
print("== river assembly ==")
BOARD = {
    "room_id": "r1", "version": 1,
    "axes": [{
        "id": "ax1", "created_index": None, "last_new_index": -1,
        "displayed_index": 1, "chosen_option_id": "ax1-o2",
        "options": [
            {"id": "ax1-o1", "label": "Stay at BigTech Co", "aliases": [], "first_index": None,
             "proposed_by": "intake", "endorsed_by": [], "status": "rejected"},
            {"id": "ax1-o2", "label": "Join NovaAI startup", "aliases": [], "first_index": None,
             "proposed_by": "intake", "endorsed_by": [{"by": "ChatbotC", "index": 2, "label": "NovaAI"}],
             "status": "chosen"},
        ],
    }],
}
FACTS = {
    "turns": [
        {"id": "m1", "index": 0, "speaker": "user", "is_user": True, "time": "t0",
         "txt": "Which offer should I take?", "rationale": None, "move_kind": None,
         "move_detail": None, "softened_by": None},
        {"id": "m2", "index": 1, "speaker": "ChatbotA", "is_user": False, "time": "t1",
         "txt": "NovaAI grows your skills faster.", "rationale": "push growth", "move_kind": "challenge",
         "move_detail": "challenge @ChatbotB", "softened_by": None},
        {"id": "m3", "index": 2, "speaker": "ChatbotB", "is_user": False, "time": "t2",
         "txt": "BigTech pays reliably; layoffs are the risk.", "rationale": None, "move_kind": None,
         "move_detail": None, "softened_by": None},
        {"id": "m4", "index": 3, "speaker": "user", "is_user": True, "time": "t3",
         "txt": "Chose: Join NovaAI startup", "rationale": None, "move_kind": None,
         "move_detail": None, "softened_by": None},
    ],
    "relations": [
        {"id": "r-m2-m3", "from_id": "m2", "from_index": 1, "to_id": "m3", "to_index": 2,
         "kind": "challenge", "sign": "opposes", "source": "move"},
    ],
    "roster": {}, "stats": {},
}
SUMS = {
    "m1": {"turn_id": "m1", "summary": "Asks which offer to take", "keywords": ["choice"], "stances": []},
    "m2": {"turn_id": "m2", "summary": "NovaAI accelerates growth", "keywords": ["growth"],
           "stances": [{"option_id": "ax1-o2", "sign": "support", "quote": "skills compound faster"}]},
    # Comparative turn: fills BOTH columns at once — the whole point of plural stances.
    "m3": {"turn_id": "m3", "summary": "BigTech pays reliably but layoffs loom", "keywords": ["salary", "layoffs"],
           "stances": [
               {"option_id": "ax1-o1", "sign": "support", "quote": "pay is predictable"},
               {"option_id": "ax1-o1", "sign": "concern", "quote": "layoffs last quarter"},
               {"option_id": "ax1-o2", "sign": "concern", "quote": "equity is hard to value"},
           ]},
}
CHOICES = [{"id": "ch1", "option_id": "ax1-o2", "label": "Join NovaAI startup",
            "selection_message_index": 3, "choice_group_id": "x"}]

river = build_river(facts=FACTS, board=BOARD, choices=CHOICES, summaries=SUMS,
                    phase_spine=[{"from": "Exploration", "to": "Narrowing", "message_index": 2}],
                    lang="en")
check(len(river["turns"]) == 4, "every turn present")
t2 = river["turns"][1]
check(t2["summary"] == "NovaAI accelerates growth" and t2["has_summary"], "summary attached")
m4 = river["turns"][3]
check(not m4["has_summary"] and m4["fallback_text"].startswith("Chose:"), "missing summary falls back to raw text")
check(m4["badges"].get("choice", {}).get("option_id") == "ax1-o2", "choice badge lands on the confirm turn")
check(t2["badges"].get("options_shown") == ["ax1"], "chips-shown badge on display turn")
check(all(t["key"] for t in river["turns"][:2]) and river["turns"][2]["key"], "user/edge/stance turns are key")
v = river["verdict"]
check(v["chosen_option_id"] == "ax1-o2" and v["chosen_label"] == "Join NovaAI startup", "verdict chosen from choices+board")
check(v["why_turn_ids"] == ["m2"], "why cites the supporting turn")
check(v["counts"] == {"ax1-o2": {"support": 1, "concern": 1}, "ax1-o1": {"support": 1, "concern": 1}},
      "stance tallies count every entry, not one per turn", str(v["counts"]))

print("== the ledger ==")
led = {l["option_id"]: l for l in river["ledger"]}
check(len(river["ledger"]) == 2, "one card per option")
check(river["ledger"][0]["option_id"] == "ax1-o2", "chosen option leads the ledger")
check([p["text"] for p in led["ax1-o1"]["case_for"]] == ["pay is predictable"],
      "case_for uses the per-option quote, not the whole summary")
check([p["text"] for p in led["ax1-o1"]["case_against"]] == ["layoffs last quarter"],
      "same turn also fills the other column")
check(led["ax1-o2"]["case_for"] and led["ax1-o2"]["case_against"],
      "chosen option shows BOTH cases — the honest version")
check(led["ax1-o2"]["endorsed_by"] == ["ChatbotC"], "who backed it surfaces in the ledger")
check(led["ax1-o1"]["status"] == "rejected" and led["ax1-o2"]["status"] == "chosen", "status per card")
check(all("turn_id" in p and "speaker" in p for p in led["ax1-o1"]["case_for"]),
      "every ledger line is attributable and clickable")

print("== guidance passthrough ==")
g = extract_guidance({
    "direction": "Lean NovaAI", "strength": "leaning",
    "why": ["A said growth compounds", "  "],
    "against": ["nobody priced the equity"],
    "would_change": [], "your_call": ["whether you can absorb the risk"],
    "your_role": "you never confirmed the salary floor",
})
check(g["why"] == ["A said growth compounds"], "blank guidance entries dropped")
check(g["against"] == ["nobody priced the equity"], "unanswered counter-reasons kept")
check("would_change" not in g, "empty lists omitted")
check(g["your_role"].startswith("you never"), "string guidance fields kept")
check(extract_guidance(None) == {}, "no summary yet -> no guidance")
check(len(river["options"]) == 2 and river["options"][1]["endorsed_by"] == ["ChatbotC"],
      "flattened board carries endorsements")

# Undecided room: no choices, no chosen status
b2 = json.loads(json.dumps(BOARD))
b2["axes"][0]["chosen_option_id"] = None
for o in b2["axes"][0]["options"]:
    o["status"] = "open"
r2 = build_river(facts=FACTS, board=b2, choices=[], summaries=SUMS, phase_spine=[], lang="en")
check(r2["verdict"]["undecided"] and r2["verdict"]["chosen_option_id"] is None, "undecided verdict")
check(r2["verdict"]["counts"], "leaning counts still present when undecided")

# Empty everything: renders empty river, no crash
r3 = build_river(facts={"turns": [], "relations": []}, board=None, choices=[], summaries={}, phase_spine=[], lang="en")
check(r3["turns"] == [] and r3["verdict"]["undecided"], "empty room degrades cleanly")

check(flat_board_options(None) == [], "no board -> no options")

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("ALL OK")
