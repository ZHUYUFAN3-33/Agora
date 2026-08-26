# -*- coding: utf-8 -*-
"""Offline verification for the lazy cross-session-memory backfill.

What it protects: memory used to be written ONLY by /api/summary, i.e. only
when the user pressed Generate — across 5 study users / 12 production rooms,
exactly 1 memory record existed. backfill_session_memory() runs at the next
/api/start for the same (user, scenario): summarize earlier rooms that have
dialogue but no record, right before the read.

Checks: eligibility (dialogue required, current room excluded, existing ids
skipped), oldest-first order, per-start cap, language detected from the room's
own messages (not the UI language), dual-store write, idempotence.

No LLM, no Flask, no SQLite — summarize_session is stubbed and the store
callables are fakes.
"""
import json
import os
import tempfile

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_backfill_")  # sys.path + temp cwd; aw itself unused

import agora2_http  # noqa: E402

_ck = Checker()
check = _ck.check

# Keep test records out of the real backend/memory/ dir (module-relative).
MEM_TMP = tempfile.mkdtemp(prefix="mem_backfill_")
agora2_http.MEMORY_DIR = MEM_TMP

calls = []


def spy_summarize(transcript_text, lang, create_response, model, **kw):
    calls.append({"lang": lang, "transcript": transcript_text, "model": model})
    return {"summary": f"recap[{lang}]", "open_threads": ["thread-1"]}


agora2_http.summarize_session = spy_summarize

ROOMS = [
    # oldest, Chinese dialogue, eligible
    {"room_id": "r_old", "scenario_type": "employment", "updated_at": "2026-08-20T10:00:00"},
    # newer, English dialogue, eligible
    {"room_id": "r_new", "scenario_type": "employment", "updated_at": "2026-08-22T10:00:00"},
    # already summarized elsewhere (DB)
    {"room_id": "r_done", "scenario_type": "employment", "updated_at": "2026-08-21T10:00:00"},
    # abandoned: intake only, no agent reply
    {"room_id": "r_empty", "scenario_type": "employment", "updated_at": "2026-08-23T10:00:00"},
    # other scenario must not be touched
    {"room_id": "r_pc", "scenario_type": "parent_child", "updated_at": "2026-08-23T11:00:00"},
    # the room being started right now
    {"room_id": "r_current", "scenario_type": "employment", "updated_at": "2026-08-24T10:00:00"},
]

MSGS = {
    "r_old": [
        {"character": "user", "txt": "我在两个 offer 之间犹豫，帮我比较一下成长和稳定。"},
        {"character": "ChatbotA", "txt": "好的，我们先看成长维度。"},
    ],
    "r_new": [
        {"character": "user", "txt": "Which contract terms should I verify before deciding?"},
        {"character": "ChatbotB", "txt": "Start with probation and funding."},
    ],
    "r_done": [
        {"character": "user", "txt": "hello"},
        {"character": "ChatbotA", "txt": "hi"},
    ],
    "r_empty": [
        {"character": "user", "txt": "只有我自己说了一句话，没有任何回复。"},
    ],
    "r_pc": [
        {"character": "user", "txt": "孩子不想上补习班怎么办"},
        {"character": "ChatbotA", "txt": "先听听孩子的说法。"},
    ],
    "r_current": [],
}

upserts = []


def fake_upsert(**kw):
    upserts.append(kw)


def run(existing=("r_done",), max_rooms=3):
    calls.clear()
    upserts.clear()
    return agora2_http.backfill_session_memory(
        "P99", "employment",
        create_response=lambda *a, **k: "",
        list_rooms=lambda: ROOMS,
        load_messages=lambda rid: MSGS.get(rid, []),
        existing_ids=set(existing),
        upsert_db=fake_upsert,
        exclude_room="r_current",
        max_rooms=max_rooms,
    )


# ---- 1. eligibility + order ----------------------------------------------
recs = run()
ids = [r["session_id"] for r in recs]
check("M1 exactly the two dialogue rooms backfilled", ids == ["r_old", "r_new"], str(ids))
check("M1 oldest room summarized first", calls and "犹豫" in calls[0]["transcript"])
check("M1 current / empty / done / other-scenario rooms untouched",
      not any(x in ids for x in ("r_current", "r_empty", "r_done", "r_pc")))
check("M1 record date is the room's own date, not today",
      recs[0]["date"] == "2026-08-20", recs[0]["date"])

# ---- 2. language detected from the room's messages ------------------------
check("M2 zh room summarized in zh", calls[0]["lang"] == "zh", calls[0]["lang"])
check("M2 en room summarized in en", calls[1]["lang"] == "en", calls[1]["lang"])

# ---- 3. dual-store write --------------------------------------------------
check("M3 DB upsert called for every record", len(upserts) == 2, str(len(upserts)))
path = agora2_http.memory_path("P99", "employment", MEM_TMP)
jsonl = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
check("M3 JSONL records written", [r["session_id"] for r in jsonl] == ["r_old", "r_new"],
      str([r.get("session_id") for r in jsonl]))

# ---- 4. idempotence: a second start backfills nothing ---------------------
recs2 = run()
check("M4 second run writes nothing (jsonl ids respected)", recs2 == [], str(recs2))

# ---- 5. per-start cap -----------------------------------------------------
os.remove(path)
recs3 = run(existing=(), max_rooms=1)
check("M5 cap bounds the work per start", [r["session_id"] for r in recs3] == ["r_old"],
      str([r["session_id"] for r in recs3]))

_ck.finish("ALL MEMORY-BACKFILL CHECKS PASSED")
