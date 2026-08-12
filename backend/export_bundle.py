"""Log export bundling: zip layout, manifest and the README that ships inside every zip.

Kept out of app.py because the README is long and because the per-room zip
(/api/export-logs/<room>), the per-room admin zip and the per-user admin zip all have to
produce the same subtree shape. They used to be three unrelated code paths writing three
different layouts, and only one of them shipped any jsonl at all.

Layout produced for one room:

    {room_id}/
        chat.jsonl              raw logs, one line per event
        thinking.jsonl
        moderator.jsonl
        rationale.jsonl
        memory.jsonl
        config.jsonl
        params.jsonl
        generation.jsonl
        novelty.jsonl
        ux.jsonl
        db.json                 SQLite side: room row, messages, intake, board snapshot
        transcript.txt          flat "speaker: text" render, convenience only
        derived/                rebuildable artifacts (decision map, option board, ...)
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple


# (suffix, extension, zip subdirectory, name inside the zip)
#
# Every per-room artifact is declared here once. The export zip, the admin room-delete and
# init_session all read from this list. They used to keep three separate hardcoded sets
# that had drifted apart: the delete loop knew about "_thinking"/"_params" but not
# _rationale/_memory, the export zip knew about _params but not _rationale/_memory/the
# decision-map artifacts, and neither handled the .json files at all. A deleted room left
# seven files on disk and the export shipped four of eleven.
ROOM_ARTIFACTS: Tuple[Tuple[str, str, str, str], ...] = (
    # Raw logs, written as the session runs.
    ("", ".jsonl", "", "chat.jsonl"),
    ("_thinkinglog", ".jsonl", "", "thinking.jsonl"),
    ("_thinking", ".jsonl", "", "thinking_cli.jsonl"),
    ("_moderator", ".jsonl", "", "moderator.jsonl"),
    ("_rationale", ".jsonl", "", "rationale.jsonl"),
    ("_memory", ".jsonl", "", "memory.jsonl"),
    ("_config", ".jsonl", "", "config.jsonl"),
    ("_params", ".jsonl", "", "params.jsonl"),
    ("_generation", ".jsonl", "", "generation.jsonl"),
    ("_novelty", ".jsonl", "", "novelty.jsonl"),
    ("_ux", ".jsonl", "", "ux.jsonl"),
    # Derived: rebuildable from the raw logs, but rebuilding needs an LLM call and is not
    # deterministic, so the artifact as produced at the time is what gets shipped.
    ("_decision_map", ".jsonl", "derived", "decision_map.jsonl"),
    ("_decision_map_annotations", ".json", "derived", "decision_map_annotations.json"),
    ("_option_board", ".json", "derived", "option_board.json"),
    ("_turn_summaries", ".jsonl", "derived", "turn_summaries.jsonl"),
    ("_choices", ".jsonl", "derived", "choices.jsonl"),
    ("_summary_meta", ".json", "derived", "summary_meta.json"),
)


def room_artifact_paths(log_dir: str, room_id: str) -> List[Tuple[str, str, int]]:
    """(arcname, abs_path, size) for every artifact of this room that exists on disk.

    Zero-byte files are reported with size 0 rather than skipped: init_session opens all
    per-room handles at /api/start, so an abandoned room leaves a full set of empty files
    (14 of the 21 rooms in the reference corpus are exactly this). Callers decide whether
    to keep them; the manifest has to know they were there, because "no chat.jsonl" and
    "empty chat.jsonl" mean different things.
    """
    found: List[Tuple[str, str, int]] = []
    for suffix, ext, subdir, arcname in ROOM_ARTIFACTS:
        path = os.path.join(log_dir, f"{room_id}{suffix}{ext}")
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        found.append((f"{subdir}/{arcname}" if subdir else arcname, path, size))
    return found


def _count_lines(path: str) -> Optional[int]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return None


def render_transcript(messages: List[dict]) -> str:
    """Flat 'speaker: text' render. Convenience only -- it drops timestamps, message ids,
    option chips and the injected knowledge card. chat.jsonl is the real transcript."""
    return "\n".join(f"{m.get('character')}: {m.get('txt')}" for m in (messages or []))


def write_room(
    zf,
    log_dir: str,
    room_id: str,
    prefix: str = "",
    db_payload: Optional[dict] = None,
) -> dict:
    """Write one room's subtree into an open zipfile. Returns that room's manifest entry."""
    base = f"{prefix}{room_id}/"
    files: Dict[str, dict] = {}

    for arcname, path, size in room_artifact_paths(log_dir, room_id):
        try:
            with open(path, "r", encoding="utf-8") as f:
                zf.writestr(base + arcname, f.read())
        except OSError:
            continue
        entry: Dict[str, object] = {"bytes": size}
        if arcname.endswith(".jsonl"):
            entry["lines"] = _count_lines(path)
        files[arcname] = entry

    db_messages: List[dict] = []
    if db_payload is not None:
        zf.writestr(base + "db.json", json.dumps(db_payload, ensure_ascii=False, indent=2))
        db_messages = db_payload.get("messages") or []
        files["db.json"] = {"messages": len(db_messages)}
        transcript = render_transcript(db_messages)
        zf.writestr(base + "transcript.txt", transcript)
        files["transcript.txt"] = {"bytes": len(transcript.encode("utf-8"))}

    chat_lines = (files.get("chat.jsonl") or {}).get("lines")
    entry = {
        "room_id": room_id,
        "files": files,
        "chat_lines": chat_lines,
        "db_messages": len(db_messages) if db_payload is not None else None,
        "empty": not any((f.get("bytes") or 0) > 0 for f in files.values()),
    }
    # A room's on-disk log and its SQLite copy are written by two different code paths
    # (only the HTTP path dual-writes; the CLI and legacy paths never touch SQLite). When
    # these disagree, that difference is itself the finding -- surface it, don't reconcile.
    if chat_lines is not None and db_payload is not None and chat_lines != len(db_messages):
        entry["divergence"] = (
            f"chat.jsonl has {chat_lines} lines but SQLite has {len(db_messages)} messages"
        )
    return entry


README = """AGORA LOG EXPORT
================================================================================
Everything in this archive for the rooms listed in manifest.json. One directory
per room. `derived/` holds artifacts rebuilt from the raw logs; everything else
is written live as the session runs.

Read manifest.json first: it records the line count of every file, flags empty
rooms, and flags rooms where the on-disk log and the SQLite copy disagree.

NOT YET WRITTEN: generation.jsonl, novelty.jsonl and ux.jsonl are documented
below and are collected by the export, but the code that writes them has not
landed yet. Rooms recorded before it does will have these files empty or absent.
Check manifest.json rather than assuming a file has content.


WHAT EACH FILE RECORDS
================================================================================

chat.jsonl
  The visible transcript: one line per message that appeared on screen, user and
  agent alike, in display order.
  Fields: chat_room_id, time (ISO-8601 +09:00, second precision), character, txt.
  Optional: id, options, knowledge, choice.
    character  Either the literal "user" or an agent DISPLAY NAME -- never the
               slot key A/B/C. The name comes straight from the /api/start
               request body, so "ChatbotA" is a default, not a guarantee. To
               join against files that use slot keys, map through config.jsonl.
    txt        Post-sanitize prose only. The [MOVE]/[RATIONALE]/[OPTIONS] blocks
               of the raw generation were stripped out and routed to
               rationale.jsonl.
    id         "m-<12 hex>". Only on agent lines, and only for rooms created
               after 2026-08-06. Older rooms have no message ids at all, so
               anything keyed on id silently drops them.
    options    Option chips shown under this message: [{id, label}].
               Labels are truncated to 48 chars ONLY when the model proposed
               them; chips coming from the option board carry the full label.
               Ids come in two shapes: "o1"/"o2" (model-proposed) and
               "ax1-o1" (board-canonical). Do not assume one format.
    knowledge  {id, tag, source} -- the stance-knowledge card actually injected
               into this agent's prompt for this response.
    choice     Only on a "user" line: {choice_group_id, option_id, label}.
               choice_group_id points at the `id` of the agent message that
               offered the chips.
  Note: a turn dropped by the novelty or refusal guard writes NOTHING here. It
  appears only as a turn_dropped row in rationale.jsonl.

thinking.jsonl
  The scheduler. This is where the decision of who speaks next is made.
  Fields: chat_room_id, time, character, txt.
    admin1     Free-text reasoning about who should speak next.
    admin2     The resulting pick -- a single letter (A/B/C) or U for the user.
               Called with a 16-token cap, so an "incomplete" generation status
               is normal here, not an error.
    admin_rule / admin_bias / admin_no_repeat / admin_fallback
               A hard rule overrode the model's pick. txt says which.
    novelty_retry
               Repetition guard fired. Scores are embedded in the text; the
               structured version of the same event is in novelty.jsonl.
  The CLI writes this file as thinking_cli.jsonl instead (different filename,
  same shape). If both are present the room was run through both paths.

moderator.jsonl
  Phase/state classification for the conversation as a whole.
  Fields: chat_room_id, time, character, txt.
    admin3_moderator            the classifier's raw output
    admin3_state_change         a phase actually changed, with a timestamp
    admin3_state_change_suppressed
                                a change was proposed and rejected
  Shares its field names with chat.jsonl but the `character` column means
  something completely different. Do not union the two without a source column.

rationale.jsonl
  Per-turn structured events extracted from each agent's raw generation.
  Fields: chat_room_id, time, agent (slot key), event, detail, plus per-event
  keys.
    move            the agent's self-reported conversational move
    agent_mention   one agent named another (a soft cue -- it does NOT route the
                    next turn; the scheduler still decides)
    rationale       the agent's stated reason for its turn
    turn_dropped    a generated turn was discarded and never shown
    option_board    option-board bookkeeping
  turn_dropped does not currently say whether the cause was the refusal guard or
  the novelty guard -- cross-reference novelty.jsonl by timestamp.

memory.jsonl
  Memory snippet chains: what each agent distilled and carried forward.
  Separate from the cross-session memory in the user directory.

config.jsonl
  Append-only record of the effective agent configuration. THIS is the file that
  tells you which experimental condition produced a room.
  Every line carries the FULL effective config, not a delta, because deltas
  cannot be replayed: when a user switches an agent's emotion off the frontend
  omits the field entirely and the server keeps the previous value, so a delta
  log and the real state diverge.
  Events: session_start, roster_change, runtime_override, scene_change.
  Written for every room regardless of mode.

params.jsonl
  What the user changed in the customizer, and when. A DIFF log: only fields
  whose value actually changed appear, so it cannot reconstruct state on its own
  -- use config.jsonl for that. This file answers "what did the user touch".
  Change types: agent_name, accent_color, emotion, decision, stance.
  The `agent` field holds the display name, not the slot key.
  Note: accent_color is recorded here but never reaches the server's runtime
  config, so those rows describe a UI-only change.

generation.jsonl
  One line per LLM call, including calls that produced nothing visible.
  Fields: model, call_kind, agent, retry_index, input_tokens, output_tokens,
  status, incomplete_reason, refusal, latency_ms.
  call_kind separates agent turns from admin1/admin2/admin3, memory distillation,
  refusal retries, novelty retries and stall bursts. Expect roughly 5x more rows
  here than there are messages in chat.jsonl.
  Rows are emitted before a message id exists, so they cannot be joined to
  chat.jsonl by id -- join on message_index, and expect dropped turns to have no
  counterpart at all.

novelty.jsonl
  The repetition guard, structured. One row per scored generation.
  Fields: agent, seq, group_ratio, self_ratio, the RESOLVED thresholds that were
  actually in force, group_failed, self_failed, retried, kept, dropped, reason.
  Thresholds are recorded per row rather than assumed, because the HTTP and CLI
  defaults disagree and the documented value does not match the code.
  Stall-burst turns publish without novelty scoring, so they have no row here.

ux.jsonl
  Client-side behavior: what the user did, as opposed to what they typed.
  Option chips shown/clicked with dwell time, decision-map opens and dwell,
  composer timing (pause before typing, time spent composing, keystroke and
  backspace counts, abandoned drafts), scroll-back, panel opens.
  Counts and durations only -- never draft text and never per-key timing.

db.json
  The SQLite side of the same room: the chat_rooms row, its messages, the intake
  answers and the option-board snapshot.
  chat_messages.clarifying_question_json is misnamed: it is a generic payload
  blob holding {"options": [...], "knowledge": {...}}, not a question.
  Only the HTTP path writes to SQLite. CLI and legacy runs have logs but no DB
  rows, which is why manifest.json compares the two counts per room.

transcript.txt
  Flat "speaker: text" convenience render. Drops timestamps, ids, chips and
  knowledge cards. Never analyze from this file.

derived/
  decision_map.jsonl              extracted issue/position/argument structure
  decision_map_annotations.json   user-authored annotations (machine-generated
                                  everything else in this directory)
  option_board.json               option lifecycle state
  turn_summaries.jsonl            per-turn summaries
  choices.jsonl                   which option the user picked, with the group
                                  it belonged to
  summary_meta.json               summary generation metadata


TRAPS
================================================================================
* An empty room is not a missing room. Log handles are opened when a session
  starts, so an abandoned room leaves a complete set of zero-byte files.
  manifest.json marks these with "empty": true.
* Room ids are random 6-digit numbers with no collision check and all writers
  append, so a recycled id can in principle interleave two sessions in one file.
  config.jsonl carries a creation timestamp per session_start for this reason.
* Timestamps are second-precision local time (Asia/Tokyo). They are not a
  reliable ordering key within a single second; use file order.
* A user session can span two room ids: after a backend restart the frontend
  silently starts a new room and keeps the same visible conversation.
"""


def build_manifest(rooms: List[dict], scope: str, generated_at: str) -> dict:
    non_empty = [r for r in rooms if not r.get("empty")]
    return {
        "scope": scope,
        "generated_at": generated_at,
        "room_count": len(rooms),
        "non_empty_room_count": len(non_empty),
        "divergences": [
            {"room_id": r["room_id"], "detail": r["divergence"]}
            for r in rooms
            if r.get("divergence")
        ],
        "rooms": rooms,
    }
