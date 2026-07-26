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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "agora.db")

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
