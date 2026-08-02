#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live API smoke — Agora-2 prose loop (no chips/board). Needs Flask :5001 + OpenAI."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PROFILES = BACKEND / "profiles"

SCRIPT: List[Dict[str, Any]] = [
    {"user": "Hi", "max_agents": 5, "note": "opening"},
    {"user": "Yea sure", "max_agents": 5, "note": "low-content"},
    {
        "user": (
            "Location is the hard part — Honda in Tochigi would mean weekday separation "
            "from my partner in Shinagawa. Tokyo options feel safer for that."
        ),
        "max_agents": 5,
        "min_agents": 1,
        "note": "constraint",
    },
]


def _http_json(method: str, url: str, body: dict | None = None, headers: dict | None = None, timeout: int = 180) -> Tuple[int, dict]:
    data = None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"error": raw[:400]}
        return e.code, payload


def _load_persona(user_id: str) -> Tuple[dict, dict]:
    path = PROFILES / f"{user_id}.json"
    if not path.exists():
        return {}, {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    profile = raw.get("profile") or {}
    intake = {}
    for row in reversed(raw.get("session_history") or []):
        if (row.get("scenario_type") or "") == "employment" and isinstance(row.get("intake"), dict):
            intake = row["intake"]
            break
    return profile, intake


def _agent_texts(payload: dict) -> List[str]:
    out = []
    for r in payload.get("responses") or []:
        if str(r.get("agent_key") or r.get("agent") or "").lower() == "system":
            continue
        t = (r.get("message") or "").strip()
        if t:
            out.append(t)
    return out


def run(base: str, user: str, password: str, lang: str) -> int:
    base = base.rstrip("/")
    code, login = _http_json("POST", f"{base}/api/auth/login", {"user_id": user, "password": password}, timeout=30)
    if code != 200:
        print(f"LOGIN FAIL {code}: {login}", file=sys.stderr)
        return 1
    token = login.get("token") or ""
    auth = {"Authorization": f"Bearer {token}"}
    profile, intake = _load_persona(user)
    code, start = _http_json(
        "POST",
        f"{base}/api/start",
        {
            "scene_id": "employment",
            "scenario_type": "employment",
            "lang": lang,
            "mode": "full",
            "profile": profile,
            "intake": intake,
            "use_demo_intake": not bool(intake),
        },
        headers=auth,
        timeout=60,
    )
    if code != 200:
        print(f"START FAIL {code}: {start}", file=sys.stderr)
        return 1
    room_id = start.get("room_id")
    print(f"room_id={room_id} pipeline={start.get('pipeline')}")

    all_ok = True
    for i, step in enumerate(SCRIPT, 1):
        print(f"\n--- turn {i}: {step.get('note', '')}")
        print(f"U: {step['user']}")
        code, payload = _http_json(
            "POST",
            f"{base}/api/message",
            {"room_id": room_id, "message": step["user"]},
            headers=auth,
            timeout=180,
        )
        if code != 200:
            print(f"MESSAGE FAIL {code}: {payload}", file=sys.stderr)
            all_ok = False
            continue
        if "board" in payload or any((r or {}).get("clarifying_question") for r in (payload.get("responses") or [])):
            print("   FAIL: board/chips still present")
            all_ok = False
        texts = _agent_texts(payload)
        for t in texts:
            print(f"A: {t[:280]}{'…' if len(t) > 280 else ''}")
        if not texts:
            print("A: (no agent messages)")
        n = len(texts)
        print(f"   phase={payload.get('phase')} agents={n}")
        if "max_agents" in step and n > int(step["max_agents"]):
            print(f"   FAIL: agent_count={n}")
            all_ok = False
        elif "min_agents" in step and n < int(step["min_agents"]):
            print(f"   FAIL: agent_count={n}")
            all_ok = False
        else:
            print("   OK")

    print("\n" + ("PASS" if all_ok else "FAIL"))
    return 0 if all_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.getenv("AGORA_API", "http://127.0.0.1:5001"))
    ap.add_argument("--user", default="maya_chen")
    ap.add_argument("--password", default="test1234")
    ap.add_argument("--lang", default="en")
    args = ap.parse_args()
    return run(args.base, args.user, args.password, args.lang)


if __name__ == "__main__":
    sys.exit(main())
