# -*- coding: utf-8 -*-
"""Unit checks for IBIS decision_map (no LLM)."""
import os
import sys

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


from decision_map import (
    enough_messages,
    count_messages,
    assemble_smart_map,
    normalize_ibis,
    merge_ibis_maps,
    strength_to_status,
    promote_layer_annotations,
    save_summary_overall,
    load_summary_overall,
)

few = [
    {"character": "user", "txt": "hi", "time": "2026-01-01T10:00:00"},
    {"character": "ChatbotA", "txt": "hello", "time": "2026-01-01T10:01:00"},
]
check(not enough_messages(few), "too few messages → insufficient")

msgs = [
    {"character": "user", "txt": "Should I switch jobs?", "time": "2026-01-01T10:00:00"},
    {"character": "ChatbotA", "txt": "Growth matters more now", "time": "2026-01-01T10:01:00"},
    {"character": "ChatbotB", "txt": "Stability first", "time": "2026-01-01T10:02:00"},
    {"character": "ChatbotC", "txt": "Balance life too", "time": "2026-01-01T10:03:00"},
    {"character": "user", "txt": "I lean toward growth", "time": "2026-01-01T10:04:00"},
]
u, a, t = count_messages(msgs)
check(u >= 2 and a >= 3, "enough message counts", f"u={u} a={a} t={t}")
check(enough_messages(msgs), "enough_messages true")

insuff = assemble_smart_map(room_id="r", msgs=few, lang="en")
check(insuff["insufficient"] is True, "assemble marks insufficient")
check(insuff["issues"] == [] and insuff["claims"] == [], "no fake graph when insufficient")

ibis = {
    "issues": [{"id": "issue_1", "label": "Job switch", "status": "leaning", "parent_id": None}],
    "claims": [
        {"id": "claim_a", "issue_id": "issue_1", "speaker": "ChatbotA", "text": "Grow now", "message_indexes": [1]},
        {"id": "claim_b", "issue_id": "issue_1", "speaker": "ChatbotB", "text": "Stay stable", "message_indexes": [2]},
    ],
    "edges": [{"id": "e1", "type": "opposes", "from": "claim_b", "to": "claim_a"}],
    "room_leaning": {"direction": "toward growth", "strength": "leaning"},
}
norm = normalize_ibis(ibis, msg_count=len(msgs))
check(len(norm["issues"]) == 1 and len(norm["claims"]) == 2, "normalize keeps issues/claims")
check(norm["edges"][0]["type"] == "opposes", "challenges→opposes / opposes kept")

# Drop claim without evidence when msg_count known
bad = normalize_ibis({
    "issues": [{"id": "i", "label": "x", "status": "open"}],
    "claims": [{"id": "c", "issue_id": "i", "speaker": "A", "text": "no idx", "message_indexes": []}],
    "edges": [],
}, msg_count=5)
check(bad["claims"] == [], "claims without indexes dropped")

merged = merge_ibis_maps({"issues": [], "claims": [], "edges": []}, ibis, msg_count=len(msgs))
check(len(merged["claims"]) == 2, "merge_ibis overlay")

full = assemble_smart_map(
    room_id="r2",
    msgs=msgs,
    phase_changes=[{"from": "Exploration", "to": "Structuring", "time": "2026-01-01T10:02:30"}],
    lang="en",
    overall={"direction": "growth", "strength": "倾向"},
    fresh=ibis,
)
check(full["insufficient"] is False, "enough → not insufficient")
check(len(full["issues"]) >= 1 and len(full["claims"]) >= 2, "fresh IBIS in assemble")
check(len(full["phase_spine"]) == 1, "phase spine present")
check(full.get("room_leaning") and "growth" in (full["room_leaning"].get("direction") or ""), "overall leaning applied")

check(strength_to_status("明确") == "settled", "strength settled")
check(strength_to_status("leaning") == "leaning", "strength leaning")

promoted = promote_layer_annotations([
    {"id": "L1", "layer": "decision", "excerpt": "key call", "message_index": 4},
    {"id": "L2", "layer": "expression", "excerpt": "emo", "message_index": 1},
])
check(len(promoted) == 1 and promoted[0]["kind"] == "layer", "layer promote decision only")

import tempfile
tmpdir = tempfile.mkdtemp(prefix="dmap_")
save_summary_overall(tmpdir, "r1", {"direction": "x", "strength": "clear"}, "en")
loaded = load_summary_overall(tmpdir, "r1")
check(loaded and loaded.get("direction") == "x", "summary overall cache")

# legacy challenges alias
n2 = normalize_ibis({
    "issues": [{"id": "i", "label": "t", "status": "open"}],
    "claims": [
        {"id": "c1", "issue_id": "i", "speaker": "A", "text": "a", "message_indexes": [0]},
        {"id": "c2", "issue_id": "i", "speaker": "B", "text": "b", "message_indexes": [1]},
    ],
    "edges": [{"id": "e", "type": "challenges", "from": "c2", "to": "c1"}],
}, msg_count=5)
check(n2["edges"][0]["type"] == "opposes", "challenges normalized to opposes")

if failures:
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1)
print("\nAll IBIS decision_map checks passed.")
