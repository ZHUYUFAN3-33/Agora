# -*- coding: utf-8 -*-
"""Import logs/*.jsonl into SQLite — only when ownership is known.

Never bulk-assign orphan logs to a user (that polluted other users' sidebars).
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Set

from profile_store import load_profile
from user_store import get_user_store

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE, "logs")


def _infer_scenario(texts: List[str]) -> str:
    blob = "\n".join(texts).lower()
    if any(w in blob for w in ("parent", "child", "juku", "school", "parenting")):
        return "parent_child"
    if any(w in blob for w in ("salary", "offer", "sony", "honda", "toyota", "employment", "commute")):
        return "employment"
    return ""


def _title(scenario: str, room_id: str) -> str:
    if scenario == "employment":
        return "Employment Decision"
    if scenario == "parent_child":
        return "Parent-Child Decision"
    if scenario:
        return scenario.replace("_", " ").title()
    return f"Chat {room_id}"


def _owned_room_ids(user_id: str) -> Set[str]:
    """Rooms we can prove belong to this user (intake / profile history)."""
    store = get_user_store()
    owned: Set[str] = set()
    try:
        with store._connect() as conn:
            for r in conn.execute(
                "SELECT session_id FROM session_intake WHERE user_id = ?",
                (user_id,),
            ):
                if r["session_id"]:
                    owned.add(str(r["session_id"]))
    except Exception:
        pass
    disk = load_profile(user_id, "profiles")
    for h in disk.get("session_history") or []:
        sid = str(h.get("session_id") or "").strip()
        if sid:
            owned.add(sid)
    return owned


def backfill(
    user_id: str,
    *,
    room_ids: Optional[Iterable[str]] = None,
    only_owned: bool = True,
) -> dict:
    store = get_user_store()
    imported = []
    skipped = []

    if room_ids:
        candidates = [str(r).strip() for r in room_ids if str(r).strip()]
    elif only_owned:
        candidates = sorted(_owned_room_ids(user_id))
    else:
        raise ValueError("Refusing orphan bulk import. Pass --rooms or use owned intake/history only.")

    owned = _owned_room_ids(user_id)

    for room_id in candidates:
        if only_owned and room_id not in owned and not room_ids:
            skipped.append((room_id, "not_owned"))
            continue
        # Explicit --rooms still allowed, but warn via skip tag if not in owned
        path = os.path.join(LOG_DIR, f"{room_id}.jsonl")
        if not os.path.isfile(path):
            skipped.append((room_id, "missing_log"))
            continue

        existing = store.get_chat_room(room_id)
        if existing and existing.get("user_id") and existing["user_id"] != user_id:
            skipped.append((room_id, f"owned_by:{existing['user_id']}"))
            continue
        if existing and existing.get("user_id") == user_id and store.list_chat_messages(room_id):
            skipped.append((room_id, "already"))
            continue

        msgs = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and str(obj.get("txt") or "").strip():
                    msgs.append(obj)
        if not msgs:
            skipped.append((room_id, "empty"))
            continue

        texts = [str(m.get("txt") or "") for m in msgs]
        scenario = _infer_scenario(texts)
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
        store.create_chat_room(
            room_id,
            user_id,
            scenario_type=scenario,
            title=_title(scenario, room_id),
            phase="Exploration",
        )
        if not store.list_chat_messages(room_id):
            for m in msgs:
                store.append_chat_message(
                    room_id,
                    character=str(m.get("character") or ""),
                    txt=str(m.get("txt") or ""),
                    clarifying_question=m.get("clarifying_question"),
                    created_at=str(m.get("time") or "") or mtime,
                )
        imported.append(room_id)

    return {"imported": imported, "skipped": skipped, "user_id": user_id}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill chat rooms for ONE user with proven ownership")
    ap.add_argument("--user", required=True)
    ap.add_argument("--rooms", nargs="*", default=None, help="Explicit room ids (still won't steal other users')")
    ap.add_argument(
        "--allow-unlinked",
        action="store_true",
        help="With --rooms, import even if not in intake/history (still won't steal)",
    )
    args = ap.parse_args()
    result = backfill(
        args.user,
        room_ids=args.rooms,
        only_owned=not args.allow_unlinked,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
