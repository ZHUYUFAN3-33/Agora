#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Closed-loop load generator for Agora.

Answers one question: with N participants online at once, how long does a single
message take to come back, and what breaks first?

Two scenarios:

  cheap  — hammers /api/health and /api/auth/login only. No OpenAI spend. Finds the
           Fly-proxy concurrency knee and SQLite write contention.
  chat   — the real thing: register -> /api/start -> loop of /api/message, each virtual
           user waiting for its own reply before thinking and sending again. That
           closed loop is what makes the queueing behaviour realistic; an open-loop
           firehose would just measure how fast we can pile up a backlog.

  --single-mode flips /api/message to the server's own single_mode branch (app.py:1115),
  which is 1 OpenAI call instead of ~18. Same HTTP, threading, SQLite and file-descriptor
  paths, ~1/50th the cost — so the plumbing can be saturated cheaply.

Request contract mirrors backend/scripts/smoke_chat.py, which already drives this flow.
Standard library only; runs from a laptop against the deployed app.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# Sent verbatim as user turns. Varied so the novelty check doesn't reject them as
# repeats, and long enough to be representative of real participant input.
PROMPTS = [
    "I'm weighing a job in Tochigi against staying in Tokyo, and I can't decide.",
    "The commute is the part I keep getting stuck on. Is that a reasonable thing to weigh so heavily?",
    "My partner works in Shinagawa, so weekday separation is the real cost here.",
    "What would I be giving up if I turned down the Honda offer?",
    "Money matters less to me than I expected. Does that change the picture?",
    "I keep going back and forth. Can you help me name what I'm actually afraid of?",
    "If I stayed in Tokyo, what would I need to be true in two years to feel good about it?",
    "Honestly I think I already know the answer and I'm looking for permission.",
]

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        sys.stdout.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        sys.stdout.flush()


def http_json(
    method: str,
    url: str,
    body: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 300,
) -> Tuple[int, Any, float]:
    """Returns (status, parsed_body, elapsed_seconds). Never raises for HTTP errors."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(raw) if raw else {}), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"error": raw[:500]}
        return e.code, payload, time.monotonic() - t0
    except Exception as e:  # socket timeout, connection reset, DNS, ...
        return 0, {"error": f"{type(e).__name__}: {e}"}, time.monotonic() - t0


class Recorder:
    def __init__(self) -> None:
        self.rows: List[dict] = []
        self.lock = threading.Lock()
        self.t0 = time.time()

    def add(self, **kw: Any) -> None:
        kw["t"] = round(time.time() - self.t0, 3)
        with self.lock:
            self.rows.append(kw)


def classify(status: int, payload: Any) -> str:
    """Bucket a failure so the report can say *what* broke, not just that it did."""
    if status == 200:
        return "ok"
    text = json.dumps(payload, ensure_ascii=False).lower() if payload else ""
    if status == 0:
        return "timeout/conn" if "timeout" in text else "conn_error"
    if status == 429:
        return "rate_limited_429"
    if "database is locked" in text:
        return "sqlite_locked"
    if status == 502:
        return "upstream_502"
    if status in (503, 504):
        return f"proxy_{status}"
    if status == 400 and "invalid room_id" in text:
        return "room_lost_400"
    return f"http_{status}"


# --------------------------------------------------------------------------- chat

def chat_user(
    idx: int,
    base: str,
    rec: Recorder,
    stop_at: float,
    args: argparse.Namespace,
) -> None:
    uid = f"{args.prefix}{idx:02d}"
    password = args.password

    # Stagger arrivals so 32 users don't all register in the same instant.
    time.sleep(random.uniform(0, args.ramp))

    # Register; fall back to login if the account already exists from a prior run.
    status, payload, dt = http_json(
        "POST", f"{base}/api/auth/register", {"user_id": uid, "password": password}, timeout=60
    )
    if status != 200:
        status, payload, dt = http_json(
            "POST", f"{base}/api/auth/login", {"user_id": uid, "password": password}, timeout=60
        )
    rec.add(user=uid, op="auth", status=status, latency=round(dt, 3), kind=classify(status, payload))
    token = (payload or {}).get("token")
    if not token:
        log(f"{uid}: AUTH FAILED {status} {payload}")
        return
    auth = {"Authorization": f"Bearer {token}"}

    status, payload, dt = http_json(
        "POST",
        f"{base}/api/start",
        {
            "scene_id": "employment",
            "scenario_type": "employment",
            "lang": args.lang,
            "mode": "full",
            "use_demo_intake": True,
        },
        headers=auth,
        timeout=120,
    )
    rec.add(user=uid, op="start", status=status, latency=round(dt, 3), kind=classify(status, payload))
    room_id = (payload or {}).get("room_id")
    if not room_id:
        log(f"{uid}: START FAILED {status} {str(payload)[:200]}")
        return
    log(f"{uid}: room {room_id} ready ({dt:.1f}s)")

    seq = 0
    while time.time() < stop_at and (args.messages <= 0 or seq < args.messages):
        body: Dict[str, Any] = {
            "room_id": room_id,
            "message": PROMPTS[seq % len(PROMPTS)],
        }
        if args.single_mode:
            body["single_mode"] = True
        if args.max_agent_turns:
            body["max_agent_turns_before_user"] = args.max_agent_turns

        status, payload, dt = http_json(
            "POST", f"{base}/api/message", body, headers=auth, timeout=args.timeout
        )
        kind = classify(status, payload)
        n_agents = len((payload or {}).get("responses") or []) if status == 200 else 0
        row = dict(
            user=uid, op="message", seq=seq, status=status,
            latency=round(dt, 3), kind=kind, n_agents=n_agents,
        )
        if status != 200:
            # Keep the server's own words. "which 503" matters: a Fly-proxy 503 and an
            # app-level 503 from a missing key look identical from the status code alone.
            row["err"] = json.dumps(payload, ensure_ascii=False)[:300]
        rec.add(**row)
        log(f"{uid}: msg#{seq} {kind} {dt:.1f}s agents={n_agents}")
        seq += 1

        if time.time() >= stop_at:
            break
        # Think time: read the replies, type the next turn. Jittered so users drift apart.
        think = args.think * random.uniform(0.6, 1.4)
        time.sleep(min(think, max(0.0, stop_at - time.time())))


# -------------------------------------------------------------------------- cheap

def cheap_user(idx: int, base: str, rec: Recorder, stop_at: float, args: argparse.Namespace) -> None:
    uid = f"{args.prefix}{idx:02d}"
    time.sleep(random.uniform(0, args.ramp))
    if args.login_every > 0:
        # Ensure the account exists so /api/auth/login does a real hash check + session insert.
        http_json("POST", f"{base}/api/auth/register",
                  {"user_id": uid, "password": args.password}, timeout=60)

    n = 0
    while time.time() < stop_at:
        # --login-every 0 makes this health-only, which separates the two causes of
        # collapse: /api/health is a dict lookup, so any latency there is pure queueing,
        # whereas /api/auth/login burns ~600k pbkdf2 iterations of real CPU.
        if args.login_every > 0 and n % args.login_every == args.login_every - 1:
            status, payload, dt = http_json(
                "POST", f"{base}/api/auth/login",
                {"user_id": uid, "password": args.password}, timeout=60,
            )
            op = "login"
        else:
            status, payload, dt = http_json("GET", f"{base}/api/health", timeout=60)
            op = "health"
        rec.add(user=uid, op=op, status=status, latency=round(dt, 3), kind=classify(status, payload))
        n += 1
        time.sleep(args.think)


# ------------------------------------------------------------------------ summary

def pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return s[k]


def summarize(rows: List[dict], args: argparse.Namespace) -> dict:
    out: Dict[str, Any] = {"scenario": args.scenario, "users": args.users, "total_requests": len(rows)}
    print("\n" + "=" * 72)
    print(f"  {args.scenario} scenario — {args.users} users, {args.duration}s")
    print("=" * 72)

    for op in ("auth", "start", "message", "health", "login"):
        subset = [r for r in rows if r["op"] == op]
        if not subset:
            continue
        lats = [r["latency"] for r in subset if r["kind"] == "ok"]
        kinds: Dict[str, int] = {}
        for r in subset:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        ok = kinds.get("ok", 0)
        stats = {
            "count": len(subset),
            "ok": ok,
            "error_rate": round(1 - ok / len(subset), 4) if subset else 0,
            "kinds": kinds,
        }
        if lats:
            stats.update({
                "p50": round(statistics.median(lats), 2),
                "p90": round(pct(lats, 0.90), 2),
                "p95": round(pct(lats, 0.95), 2),
                "max": round(max(lats), 2),
                "mean": round(statistics.fmean(lats), 2),
            })
        out[op] = stats

        print(f"\n  {op}  ({len(subset)} requests, {ok} ok)")
        if lats:
            print(f"    latency  p50 {stats['p50']}s   p90 {stats['p90']}s   "
                  f"p95 {stats['p95']}s   max {stats['max']}s")
        if len(kinds) > 1 or "ok" not in kinds:
            for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]):
                print(f"    {k:24s} {v}")

    msgs = [r for r in rows if r["op"] == "message" and r["kind"] == "ok"]
    if msgs:
        span = max(r["t"] for r in msgs) - min(r["t"] for r in msgs)
        if span > 0:
            tput = len(msgs) / span
            out["throughput_msg_per_min"] = round(tput * 60, 2)
            print(f"\n  throughput  {tput * 60:.1f} messages/min sustained")
        agents = [r["n_agents"] for r in msgs]
        out["mean_agent_replies"] = round(statistics.fmean(agents), 2)
        print(f"  agent replies per message  mean {statistics.fmean(agents):.1f}")
    print()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Agora load generator")
    ap.add_argument("--base", default=os.getenv("AGORA_API", "https://agora-loadtest.fly.dev"))
    ap.add_argument("--scenario", choices=["chat", "cheap"], default="chat")
    ap.add_argument("--users", type=int, default=32)
    ap.add_argument("--duration", type=int, default=900, help="seconds")
    ap.add_argument("--think", type=float, default=90.0, help="seconds between a reply and the next send")
    ap.add_argument("--ramp", type=float, default=20.0, help="spread user arrivals over this many seconds")
    ap.add_argument("--messages", type=int, default=0, help="max messages per user (0 = unlimited)")
    ap.add_argument("--single-mode", action="store_true", help="1 OpenAI call per message instead of ~18")
    ap.add_argument("--max-agent-turns", type=int, default=0, help="override max_agent_turns_before_user")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--login-every", type=int, default=3,
                    help="cheap scenario: login on every Nth request (0 = health only)")
    ap.add_argument("--prefix", default="LT", help="virtual user id prefix")
    ap.add_argument("--password", default="loadtest1234")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    status, payload, dt = http_json("GET", f"{base}/api/health", timeout=30)
    if status != 200:
        log(f"target {base} is not healthy: {status} {payload}")
        return 1
    log(f"target {base} healthy ({dt * 1000:.0f}ms), sessions={payload.get('sessions')}")

    rec = Recorder()
    stop_at = time.time() + args.duration
    worker = chat_user if args.scenario == "chat" else cheap_user

    log(f"starting {args.users} virtual users, {args.duration}s, "
        f"think={args.think}s, single_mode={args.single_mode}")
    threads = [
        threading.Thread(target=worker, args=(i + 1, base, rec, stop_at, args), daemon=True)
        for i in range(args.users)
    ]
    for t in threads:
        t.start()
    try:
        for t in threads:
            # Generous join: an in-flight request may outlive stop_at by up to --timeout.
            t.join(timeout=args.duration + args.timeout + 60)
    except KeyboardInterrupt:
        log("interrupted — summarizing what we have")

    summary = summarize(rec.rows, args)
    out = args.out or f"loadtest_{args.scenario}_{args.users}u_{int(time.time())}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"args": vars(args), "summary": summary, "rows": rec.rows}, f,
                  ensure_ascii=False, indent=2)
    log(f"raw samples -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
