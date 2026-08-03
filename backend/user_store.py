# -*- coding: utf-8 -*-
"""SQLite user accounts, sessions, and persistent profiles."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

from data_paths import DEFAULT_DB_PATH

USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
SESSION_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def validate_user_id(user_id: str) -> Optional[str]:
    uid = (user_id or "").strip()
    if not USER_ID_RE.fullmatch(uid):
        return None
    return uid


class UserStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );
                CREATE TABLE IF NOT EXISTS chat_rooms (
                    room_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    scenario_type TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    phase TEXT NOT NULL DEFAULT 'Exploration',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    concluded INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_chat_rooms_user
                    ON chat_rooms(user_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    character TEXT NOT NULL DEFAULT '',
                    txt TEXT NOT NULL DEFAULT '',
                    clarifying_question_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(room_id, seq)
                );
                CREATE INDEX IF NOT EXISTS idx_chat_messages_room
                    ON chat_messages(room_id, seq);
                CREATE TABLE IF NOT EXISTS session_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    scenario_type TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    date TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    open_threads_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, scenario_type, session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_session_memory_user
                    ON session_memory(user_id, scenario_type, created_at DESC);
                CREATE TABLE IF NOT EXISTS session_intake (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    scenario_type TEXT NOT NULL,
                    intake_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_session_intake_user
                    ON session_intake(user_id, scenario_type, created_at DESC);
                CREATE TABLE IF NOT EXISTS session_board_snapshot (
                    session_id TEXT PRIMARY KEY,
                    option_facts_json TEXT NOT NULL DEFAULT '{}',
                    constraints_json TEXT NOT NULL DEFAULT '[]',
                    eliminations_json TEXT NOT NULL DEFAULT '[]',
                    artifact_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                """
            )

    def ensure_admin_from_env(self) -> Optional[str]:
        """Create or promote admin from AGORA_ADMIN_USER_ID / AGORA_ADMIN_PASSWORD."""
        admin_id = validate_user_id(os.getenv("AGORA_ADMIN_USER_ID") or "")
        password = (os.getenv("AGORA_ADMIN_PASSWORD") or "").strip()
        if not admin_id or not password:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (admin_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET is_admin = 1, password_hash = ? WHERE user_id = ?",
                    (generate_password_hash(password, method="pbkdf2:sha256"), admin_id),
                )
            else:
                conn.execute(
                    "INSERT INTO users (user_id, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
                    (admin_id, generate_password_hash(password, method="pbkdf2:sha256"), _iso(_now())),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO profiles (user_id, profile_json, updated_at) VALUES (?, '{}', ?)",
                    (admin_id, _iso(_now())),
                )
            conn.commit()
        return admin_id

    def register(self, user_id: str, password: str) -> Tuple[Optional[dict], Optional[str]]:
        uid = validate_user_id(user_id)
        if not uid:
            return None, "User ID must be 3–32 chars: letters, numbers, _ or -"
        if not password or len(password) < 4:
            return None, "Password must be at least 4 characters"
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,)).fetchone()
            if exists:
                return None, "User ID already taken"
            conn.execute(
                "INSERT INTO users (user_id, password_hash, is_admin, created_at) VALUES (?, ?, 0, ?)",
                (uid, generate_password_hash(password, method="pbkdf2:sha256"), _iso(_now())),
            )
            conn.execute(
                "INSERT INTO profiles (user_id, profile_json, updated_at) VALUES (?, '{}', ?)",
                (uid, _iso(_now())),
            )
            conn.commit()
        token = self.create_session(uid)
        return {"token": token, "user_id": uid, "is_admin": False}, None

    def login(self, user_id: str, password: str) -> Tuple[Optional[dict], Optional[str]]:
        uid = validate_user_id(user_id)
        if not uid or not password:
            return None, "Invalid user ID or password"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, password_hash, is_admin FROM users WHERE user_id = ?",
                (uid,),
            ).fetchone()
        if not row or not check_password_hash(row["password_hash"], password):
            return None, "Invalid user ID or password"
        token = self.create_session(uid)
        return {
            "token": token,
            "user_id": uid,
            "is_admin": bool(row["is_admin"]),
        }, None

    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        expires = _now() + timedelta(days=SESSION_DAYS)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, _iso(expires)),
            )
            conn.commit()
        return token

    def resolve_token(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT s.token, s.expires_at, u.user_id, u.is_admin, u.created_at
                FROM sessions s
                JOIN users u ON u.user_id = s.user_id
                WHERE s.token = ?
                """,
                (token,),
            ).fetchone()
            if not row:
                return None
            try:
                exp = datetime.fromisoformat(row["expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
            if exp < _now():
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
                return None
            return {
                "user_id": row["user_id"],
                "is_admin": bool(row["is_admin"]),
                "created_at": row["created_at"],
            }

    def logout(self, token: Optional[str]) -> None:
        if not token:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()

    def get_profile(self, user_id: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json, updated_at FROM profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return {"profile": {}, "updated_at": None}
        try:
            profile = json.loads(row["profile_json"] or "{}")
        except json.JSONDecodeError:
            profile = {}
        if not isinstance(profile, dict):
            profile = {}
        return {"profile": profile, "updated_at": row["updated_at"]}

    def save_profile(self, user_id: str, profile: dict) -> dict:
        merged_src = self.get_profile(user_id)["profile"]
        merged = {**merged_src, **(profile or {})}
        now = _iso(_now())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles (user_id, profile_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(merged, ensure_ascii=False), now),
            )
            conn.commit()
        return {"profile": merged, "updated_at": now}

    def list_users(self) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT u.user_id, u.is_admin, u.created_at,
                       p.profile_json, p.updated_at AS profile_updated_at
                FROM users u
                LEFT JOIN profiles p ON p.user_id = u.user_id
                ORDER BY u.created_at DESC
                """
            ).fetchall()
        out = []
        for r in rows:
            try:
                profile = json.loads(r["profile_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                profile = {}
            if not isinstance(profile, dict):
                profile = {}
            out.append({
                "user_id": r["user_id"],
                "is_admin": bool(r["is_admin"]),
                "created_at": r["created_at"],
                "profile_updated_at": r["profile_updated_at"],
                "profile": profile,
                "profile_field_count": len([k for k, v in profile.items() if v not in (None, "", [])]),
            })
        return out

    def get_user_detail(self, user_id: str) -> Optional[dict]:
        uid = validate_user_id(user_id)
        if not uid:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.user_id, u.is_admin, u.created_at,
                       p.profile_json, p.updated_at AS profile_updated_at
                FROM users u
                LEFT JOIN profiles p ON p.user_id = u.user_id
                WHERE u.user_id = ?
                """,
                (uid,),
            ).fetchone()
        if not row:
            return None
        try:
            profile = json.loads(row["profile_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            profile = {}
        if not isinstance(profile, dict):
            profile = {}
        return {
            "user_id": row["user_id"],
            "is_admin": bool(row["is_admin"]),
            "created_at": row["created_at"],
            "profile_updated_at": row["profile_updated_at"],
            "profile": profile,
        }

    def admin_set_password(self, user_id: str, password: str) -> Tuple[bool, Optional[str]]:
        uid = validate_user_id(user_id)
        if not uid:
            return False, "Invalid user ID"
        if not password or len(password) < 4:
            return False, "Password must be at least 4 characters"
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,)).fetchone()
            if not row:
                return False, "User not found"
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE user_id = ?",
                (generate_password_hash(password, method="pbkdf2:sha256"), uid),
            )
            # Invalidate existing sessions after reset
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
            conn.commit()
        return True, None

    def admin_create_user(
        self, user_id: str, password: str, is_admin: bool = False
    ) -> Tuple[Optional[dict], Optional[str]]:
        """Create a user without logging them in (admin console)."""
        uid = validate_user_id(user_id)
        if not uid:
            return None, "User ID must be 3–32 chars: letters, numbers, _ or -"
        if not password or len(password) < 4:
            return None, "Password must be at least 4 characters"
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,)).fetchone()
            if exists:
                return None, "User ID already taken"
            conn.execute(
                "INSERT INTO users (user_id, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (uid, generate_password_hash(password, method="pbkdf2:sha256"), 1 if is_admin else 0, _iso(_now())),
            )
            conn.execute(
                "INSERT INTO profiles (user_id, profile_json, updated_at) VALUES (?, '{}', ?)",
                (uid, _iso(_now())),
            )
            conn.commit()
        return self.get_user_detail(uid), None

    def admin_set_admin(self, user_id: str, is_admin: bool, actor_id: str) -> Tuple[bool, Optional[str]]:
        """Promote/demote admin. Cannot demote yourself or remove the last admin."""
        uid = validate_user_id(user_id)
        if not uid:
            return False, "Invalid user ID"
        actor = (actor_id or "").strip()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, is_admin FROM users WHERE user_id = ?",
                (uid,),
            ).fetchone()
            if not row:
                return False, "User not found"
            currently_admin = bool(row["is_admin"])
            want_admin = bool(is_admin)
            if currently_admin == want_admin:
                return True, None
            if not want_admin:
                if uid == actor:
                    return False, "Cannot remove your own admin role"
                admin_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM users WHERE is_admin = 1"
                ).fetchone()["c"]
                if int(admin_count) <= 1:
                    return False, "Cannot demote the last admin"
            conn.execute(
                "UPDATE users SET is_admin = ? WHERE user_id = ?",
                (1 if want_admin else 0, uid),
            )
            conn.commit()
        return True, None

    def admin_delete_user(self, user_id: str, actor_id: str) -> Tuple[bool, Optional[str]]:
        uid = validate_user_id(user_id)
        if not uid:
            return False, "Invalid user ID"
        if uid == (actor_id or "").strip():
            return False, "Cannot delete your own account"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, is_admin FROM users WHERE user_id = ?",
                (uid,),
            ).fetchone()
            if not row:
                return False, "User not found"
            # Keep at least one admin
            if row["is_admin"]:
                admin_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM users WHERE is_admin = 1"
                ).fetchone()["c"]
                if int(admin_count) <= 1:
                    return False, "Cannot delete the last admin"
            # Cascade chat / memory rows for this user
            room_ids = [
                r["room_id"]
                for r in conn.execute(
                    "SELECT room_id FROM chat_rooms WHERE user_id = ?", (uid,)
                ).fetchall()
            ]
            for rid in room_ids:
                conn.execute("DELETE FROM chat_messages WHERE room_id = ?", (rid,))
                conn.execute("DELETE FROM session_board_snapshot WHERE session_id = ?", (rid,))
            conn.execute("DELETE FROM chat_rooms WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM session_memory WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM session_intake WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM profiles WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM users WHERE user_id = ?", (uid,))
            conn.commit()
        return True, None

    # ------------------------------------------------------------------
    # Chat rooms / messages / memory / intake / board snapshots
    # ------------------------------------------------------------------

    def create_chat_room(
        self,
        room_id: str,
        user_id: str,
        scenario_type: str = "",
        title: str = "",
        phase: str = "Exploration",
    ) -> dict:
        now = _iso(_now())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_rooms
                    (room_id, user_id, scenario_type, title, phase, created_at, updated_at, concluded)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(room_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    -- Never steal ownership: only fill user_id when previously empty
                    user_id = CASE
                        WHEN chat_rooms.user_id = '' AND excluded.user_id != '' THEN excluded.user_id
                        ELSE chat_rooms.user_id END,
                    scenario_type = CASE
                        WHEN excluded.scenario_type != '' THEN excluded.scenario_type
                        ELSE chat_rooms.scenario_type END,
                    title = CASE
                        WHEN excluded.title != '' THEN excluded.title
                        ELSE chat_rooms.title END
                """,
                (room_id, user_id or "", scenario_type or "", title or "", phase or "Exploration", now, now),
            )
            conn.commit()
        return {
            "room_id": room_id,
            "user_id": user_id,
            "scenario_type": scenario_type,
            "title": title,
            "phase": phase,
            "created_at": now,
            "updated_at": now,
            "concluded": False,
        }

    def update_chat_room(
        self,
        room_id: str,
        *,
        title: Optional[str] = None,
        phase: Optional[str] = None,
        concluded: Optional[bool] = None,
    ) -> None:
        now = _iso(_now())
        sets = ["updated_at = ?"]
        args: List[Any] = [now]
        if title is not None:
            sets.append("title = ?")
            args.append(title)
        if phase is not None:
            sets.append("phase = ?")
            args.append(phase)
        if concluded is not None:
            sets.append("concluded = ?")
            args.append(1 if concluded else 0)
        args.append(room_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE chat_rooms SET {', '.join(sets)} WHERE room_id = ?", args)
            conn.commit()

    def append_chat_message(
        self,
        room_id: str,
        character: str,
        txt: str,
        clarifying_question: Optional[dict] = None,
        created_at: Optional[str] = None,
    ) -> int:
        """Append one message; returns seq. Idempotent on (room_id, seq) via next seq."""
        ts = created_at or _iso(_now())
        cq_json = json.dumps(clarifying_question, ensure_ascii=False) if clarifying_question else None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM chat_messages WHERE room_id = ?",
                (room_id,),
            ).fetchone()
            seq = int(row["m"] or 0) + 1
            conn.execute(
                """
                INSERT INTO chat_messages
                    (room_id, seq, character, txt, clarifying_question_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (room_id, seq, character or "", txt or "", cq_json, ts),
            )
            conn.execute(
                "UPDATE chat_rooms SET updated_at = ? WHERE room_id = ?",
                (ts, room_id),
            )
            conn.commit()
        return seq

    def list_chat_rooms(self, user_id: str, limit: int = 50) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT room_id, user_id, scenario_type, title, phase,
                       created_at, updated_at, concluded
                FROM chat_rooms
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, max(1, int(limit))),
            ).fetchall()
        return [
            {
                "room_id": r["room_id"],
                "user_id": r["user_id"],
                "scenario_type": r["scenario_type"],
                "title": r["title"],
                "phase": r["phase"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "concluded": bool(r["concluded"]),
            }
            for r in rows
        ]

    def get_chat_room(self, room_id: str) -> Optional[dict]:
        with self._connect() as conn:
            r = conn.execute(
                """
                SELECT room_id, user_id, scenario_type, title, phase,
                       created_at, updated_at, concluded
                FROM chat_rooms WHERE room_id = ?
                """,
                (room_id,),
            ).fetchone()
        if not r:
            return None
        return {
            "room_id": r["room_id"],
            "user_id": r["user_id"],
            "scenario_type": r["scenario_type"],
            "title": r["title"],
            "phase": r["phase"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "concluded": bool(r["concluded"]),
        }

    def delete_chat_room(self, room_id: str) -> Tuple[bool, Optional[str], Optional[dict]]:
        """Delete one session (room + messages + intake/board/memory for that session_id).

        Does not touch users/profiles. Returns (ok, error, deleted_meta).
        """
        rid = (room_id or "").strip()
        if not rid:
            return False, "room_id required", None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT room_id, user_id, scenario_type, title FROM chat_rooms WHERE room_id = ?",
                (rid,),
            ).fetchone()
            if not row:
                return False, "Room not found", None
            meta = {
                "room_id": row["room_id"],
                "user_id": row["user_id"],
                "scenario_type": row["scenario_type"] or "",
                "title": row["title"] or "",
            }
            conn.execute("DELETE FROM chat_messages WHERE room_id = ?", (rid,))
            conn.execute("DELETE FROM session_board_snapshot WHERE session_id = ?", (rid,))
            conn.execute("DELETE FROM session_intake WHERE session_id = ?", (rid,))
            conn.execute(
                "DELETE FROM session_memory WHERE session_id = ?",
                (rid,),
            )
            conn.execute("DELETE FROM chat_rooms WHERE room_id = ?", (rid,))
            conn.commit()
        return True, None, meta

    def delete_session_memory(
        self, user_id: str, session_id: str, scenario_type: str = ""
    ) -> Tuple[bool, Optional[str]]:
        """Delete a memory row (and optionally scope by scenario_type)."""
        uid = (user_id or "").strip()
        sid = (session_id or "").strip()
        if not uid or not sid:
            return False, "user_id and session_id required"
        with self._connect() as conn:
            if scenario_type:
                cur = conn.execute(
                    """
                    DELETE FROM session_memory
                    WHERE user_id = ? AND session_id = ? AND scenario_type = ?
                    """,
                    (uid, sid, scenario_type),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM session_memory WHERE user_id = ? AND session_id = ?",
                    (uid, sid),
                )
            conn.commit()
            if cur.rowcount <= 0:
                return False, "Memory record not found"
        return True, None

    def list_chat_messages(self, room_id: str) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT seq, character, txt, clarifying_question_json, created_at
                FROM chat_messages
                WHERE room_id = ?
                ORDER BY seq ASC
                """,
                (room_id,),
            ).fetchall()
        out = []
        for r in rows:
            cq = None
            if r["clarifying_question_json"]:
                try:
                    cq = json.loads(r["clarifying_question_json"])
                except json.JSONDecodeError:
                    cq = None
            out.append({
                "seq": r["seq"],
                "character": r["character"],
                "txt": r["txt"],
                "clarifying_question": cq,
                "created_at": r["created_at"],
            })
        return out

    def upsert_session_memory(
        self,
        user_id: str,
        scenario_type: str,
        session_id: str,
        date: str,
        summary: str,
        open_threads: Optional[List[str]] = None,
    ) -> dict:
        now = _iso(_now())
        threads = [str(t).strip() for t in (open_threads or []) if str(t).strip()]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_memory
                    (user_id, scenario_type, session_id, date, summary, open_threads_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, scenario_type, session_id) DO UPDATE SET
                    date = excluded.date,
                    summary = excluded.summary,
                    open_threads_json = excluded.open_threads_json
                """,
                (
                    user_id,
                    scenario_type,
                    session_id,
                    date or "",
                    summary or "",
                    json.dumps(threads, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()
        return {
            "session_id": session_id,
            "date": date,
            "summary": summary,
            "open_threads": threads,
        }

    def load_session_memory(
        self, user_id: str, scenario_type: str, limit: int = 3
    ) -> List[dict]:
        with self._connect() as conn:
            if limit and limit > 0:
                rows = conn.execute(
                    """
                    SELECT session_id, date, summary, open_threads_json, created_at
                    FROM session_memory
                    WHERE user_id = ? AND scenario_type = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, scenario_type, limit),
                ).fetchall()
                rows = list(reversed(rows))
            else:
                rows = conn.execute(
                    """
                    SELECT session_id, date, summary, open_threads_json, created_at
                    FROM session_memory
                    WHERE user_id = ? AND scenario_type = ?
                    ORDER BY created_at ASC
                    """,
                    (user_id, scenario_type),
                ).fetchall()
        out = []
        for r in rows:
            try:
                threads = json.loads(r["open_threads_json"] or "[]")
            except json.JSONDecodeError:
                threads = []
            if not isinstance(threads, list):
                threads = []
            out.append({
                "session_id": r["session_id"],
                "date": r["date"],
                "summary": r["summary"],
                "open_threads": threads,
            })
        return out

    def upsert_session_intake(
        self,
        session_id: str,
        user_id: str,
        scenario_type: str,
        intake: dict,
    ) -> None:
        now = _iso(_now())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_intake
                    (session_id, user_id, scenario_type, intake_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    intake_json = excluded.intake_json,
                    scenario_type = excluded.scenario_type
                """,
                (session_id, user_id, scenario_type, json.dumps(intake or {}, ensure_ascii=False), now),
            )
            conn.commit()

    def get_session_intake(self, session_id: str) -> Optional[dict]:
        with self._connect() as conn:
            r = conn.execute(
                "SELECT session_id, user_id, scenario_type, intake_json, created_at FROM session_intake WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not r:
            return None
        try:
            intake = json.loads(r["intake_json"] or "{}")
        except json.JSONDecodeError:
            intake = {}
        return {
            "session_id": r["session_id"],
            "user_id": r["user_id"],
            "scenario_type": r["scenario_type"],
            "intake": intake if isinstance(intake, dict) else {},
            "created_at": r["created_at"],
        }

    def most_recent_session_intake(self, user_id: str, scenario_type: str) -> Optional[dict]:
        with self._connect() as conn:
            r = conn.execute(
                """
                SELECT intake_json FROM session_intake
                WHERE user_id = ? AND scenario_type = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, scenario_type),
            ).fetchone()
        if not r:
            return None
        try:
            intake = json.loads(r["intake_json"] or "{}")
        except json.JSONDecodeError:
            return None
        return intake if isinstance(intake, dict) else None

    def upsert_board_snapshot(
        self,
        session_id: str,
        *,
        option_facts: Optional[dict] = None,
        constraints: Optional[list] = None,
        eliminations: Optional[list] = None,
        artifact: Optional[dict] = None,
    ) -> None:
        now = _iso(_now())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_board_snapshot
                    (session_id, option_facts_json, constraints_json,
                     eliminations_json, artifact_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    option_facts_json = excluded.option_facts_json,
                    constraints_json = excluded.constraints_json,
                    eliminations_json = excluded.eliminations_json,
                    artifact_json = excluded.artifact_json,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    json.dumps(option_facts or {}, ensure_ascii=False),
                    json.dumps(constraints or [], ensure_ascii=False),
                    json.dumps(eliminations or [], ensure_ascii=False),
                    json.dumps(artifact or {}, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()

    def get_board_snapshot(self, session_id: str) -> Optional[dict]:
        with self._connect() as conn:
            r = conn.execute(
                """
                SELECT option_facts_json, constraints_json, eliminations_json,
                       artifact_json, updated_at
                FROM session_board_snapshot WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if not r:
            return None

        def _loads(s, default):
            try:
                return json.loads(s or json.dumps(default))
            except json.JSONDecodeError:
                return default

        return {
            "option_facts": _loads(r["option_facts_json"], {}),
            "constraints": _loads(r["constraints_json"], []),
            "eliminations": _loads(r["eliminations_json"], []),
            "artifact": _loads(r["artifact_json"], {}),
            "updated_at": r["updated_at"],
        }

    def export_user_bundle(
        self, user_id: str, scenario_type: Optional[str] = None
    ) -> dict:
        """Full export payload for admin/user download."""
        uid = (user_id or "").strip()
        profile = self.get_profile(uid)
        rooms = self.list_chat_rooms(uid, limit=500)
        if scenario_type:
            rooms = [r for r in rooms if r.get("scenario_type") == scenario_type]
        room_payloads = []
        for room in rooms:
            rid = room["room_id"]
            room_payloads.append({
                "room": room,
                "messages": self.list_chat_messages(rid),
                "intake": self.get_session_intake(rid),
                "board_snapshot": self.get_board_snapshot(rid),
            })
        memory: List[dict] = []
        scenarios = {r.get("scenario_type") for r in rooms if r.get("scenario_type")}
        if scenario_type:
            scenarios = {scenario_type}
        if not scenarios:
            # still export all memory rows for user
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT user_id, scenario_type, session_id, date, summary, open_threads_json
                    FROM session_memory WHERE user_id = ? ORDER BY created_at ASC
                    """,
                    (uid,),
                ).fetchall()
            for r in rows:
                try:
                    threads = json.loads(r["open_threads_json"] or "[]")
                except json.JSONDecodeError:
                    threads = []
                memory.append({
                    "session_id": r["session_id"],
                    "scenario_type": r["scenario_type"],
                    "date": r["date"],
                    "summary": r["summary"],
                    "open_threads": threads,
                })
        else:
            for sc in sorted(scenarios):
                for rec in self.load_session_memory(uid, sc, limit=0):
                    memory.append({**rec, "scenario_type": sc})
        return {
            "user_id": uid,
            "profile": profile.get("profile") or {},
            "rooms": room_payloads,
            "session_memory": memory,
            "exported_at": _iso(_now()),
        }


def profile_complete(profile: dict, fields: List[dict]) -> bool:
    if not fields:
        return False
    for f in fields:
        if f.get("optional"):
            continue
        v = (profile or {}).get(f.get("key"))
        if v is None or (isinstance(v, str) and not v.strip()) or v == []:
            return False
    return True


_store: Optional[UserStore] = None


def get_user_store() -> UserStore:
    global _store
    if _store is None:
        path = os.getenv("AGORA_DB_PATH") or DEFAULT_DB_PATH
        _store = UserStore(path)
        admin = _store.ensure_admin_from_env()
        if admin:
            print(f"✓ Admin account ready: {admin}")
    return _store
