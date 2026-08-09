# -*- coding: utf-8 -*-
"""Writable runtime paths (SQLite, profiles, logs, memory).

Local default: directories under this backend package (unchanged layout).
Production (Fly): set AGORA_DATA_DIR=/data so a volume keeps experiment data.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Load .env before reading path overrides (app.py also loads; safe to repeat)
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(os.path.dirname(BASE_DIR), ".env"))

DATA_DIR = (os.getenv("AGORA_DATA_DIR") or "").strip() or BASE_DIR


def data_path(*parts: str) -> str:
    return os.path.join(DATA_DIR, *parts)


LOG_DIR = data_path("logs")
PROFILES_DIR = data_path("profiles")
MEMORY_DIR = data_path("memory")

# Prefer explicit AGORA_DB_PATH; else keep local backend/data/agora.db,
# or /data/agora.db when AGORA_DATA_DIR points at a volume root.
if (os.getenv("AGORA_DB_PATH") or "").strip():
    DEFAULT_DB_PATH = os.getenv("AGORA_DB_PATH", "").strip()
elif (os.getenv("AGORA_DATA_DIR") or "").strip():
    DEFAULT_DB_PATH = data_path("agora.db")
else:
    DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "agora.db")
