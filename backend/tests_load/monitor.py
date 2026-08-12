#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Samples the server while loadtest.py drives it.

Two independent probes, on separate clocks because they cost very different amounts:

  every --health-interval   GET /api/health -> round-trip latency and the live
                            `sessions` count (app.py:2216). Health latency is the
                            useful signal: it is a trivial handler, so when it slows
                            down the request is queueing behind gunicorn's 4 threads,
                            not doing work.

  every --vm-interval       `fly ssh console` -> gunicorn worker RSS, its open file
                            descriptor count, and machine MemAvailable. FDs matter
                            because each live session holds 8 append-mode log handles
                            (app.py:552) and nothing evicts sessions.

Baseline on an idle production machine: worker RSS ~65 MB, 11 FDs, ~747 MB available.

Writes every sample to JSON so the report can be redrawn without re-running the test.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# One shell snippet, parsed here rather than on the box: no awk/ps dependency, and the
# raw text stays in the log if parsing ever needs revisiting.
REMOTE_SNIPPET = (
    'grep -E "MemTotal|MemAvailable" /proc/meminfo; '
    'for d in /proc/[0-9]*; do '
    'r=$(grep VmRSS $d/status 2>/dev/null | tr -s " " | cut -d" " -f2); '
    'if [ -n "$r" ] && [ "$r" -gt 2000 ]; then '
    'echo "$d rss_kb=$r fds=$(ls $d/fd 2>/dev/null | wc -l) '
    'cmd=$(tr "\\0" " " < $d/cmdline | cut -c1-60)"; fi; done'
)

_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        sys.stdout.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        sys.stdout.flush()


def probe_health(base: str, timeout: int = 30) -> Dict[str, Any]:
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            return {
                "ok": True,
                "latency": round(time.monotonic() - t0, 3),
                "sessions": payload.get("sessions"),
                "status": resp.status,
            }
    except urllib.error.HTTPError as e:
        return {"ok": False, "latency": round(time.monotonic() - t0, 3), "status": e.code}
    except Exception as e:
        return {"ok": False, "latency": round(time.monotonic() - t0, 3),
                "status": 0, "error": f"{type(e).__name__}: {e}"}


def probe_vm(app: str, timeout: int = 60) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            ["fly", "ssh", "console", "-a", app, "-C", f"/bin/sh -c '{REMOTE_SNIPPET}'"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "fly ssh timeout"}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or "").strip()[:200]}

    out: Dict[str, Any] = {"ok": True, "procs": []}
    for line in proc.stdout.splitlines():
        m = re.match(r"(MemTotal|MemAvailable):\s+(\d+)", line)
        if m:
            out[m.group(1).lower() + "_kb"] = int(m.group(2))
            continue
        m = re.search(r"rss_kb=(\d+) fds=(\d+) cmd=(.*)$", line)
        if m:
            entry = {"rss_kb": int(m.group(1)), "fds": int(m.group(2)), "cmd": m.group(3).strip()}
            out["procs"].append(entry)
            # The worker is the gunicorn process with the larger RSS; the master forks it
            # and stays small. Tracking the max is enough and survives a worker restart.
            if "gunicorn" in entry["cmd"]:
                if entry["rss_kb"] >= out.get("worker_rss_kb", 0):
                    out["worker_rss_kb"] = entry["rss_kb"]
                    out["worker_fds"] = entry["fds"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Sample Agora while it is under load")
    ap.add_argument("--app", default="agora-loadtest", help="fly app name (for ssh probes)")
    ap.add_argument("--base", default="", help="defaults to https://<app>.fly.dev")
    ap.add_argument("--duration", type=int, default=900)
    ap.add_argument("--health-interval", type=float, default=5.0)
    ap.add_argument("--vm-interval", type=float, default=15.0)
    ap.add_argument("--no-vm", action="store_true", help="skip fly ssh probes")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    base = (args.base or f"https://{args.app}.fly.dev").rstrip("/")
    samples: List[dict] = []
    t0 = time.time()
    stop_at = t0 + args.duration
    peak = {"health_latency": 0.0, "sessions": 0, "worker_rss_kb": 0, "worker_fds": 0}

    def health_loop() -> None:
        while time.time() < stop_at:
            s = probe_health(base)
            s.update(kind="health", t=round(time.time() - t0, 2))
            with _lock:
                samples.append(s)
            peak["health_latency"] = max(peak["health_latency"], s.get("latency") or 0)
            if s.get("sessions") is not None:
                peak["sessions"] = max(peak["sessions"], s["sessions"])
            if not s["ok"] or (s.get("latency") or 0) > 2.0:
                log(f"health {s.get('status')} {s.get('latency')}s  <-- degraded")
            time.sleep(args.health_interval)

    def vm_loop() -> None:
        while time.time() < stop_at:
            s = probe_vm(args.app)
            s.update(kind="vm", t=round(time.time() - t0, 2))
            with _lock:
                samples.append(s)
            if s.get("ok"):
                peak["worker_rss_kb"] = max(peak["worker_rss_kb"], s.get("worker_rss_kb", 0))
                peak["worker_fds"] = max(peak["worker_fds"], s.get("worker_fds", 0))
                log(f"vm  rss={s.get('worker_rss_kb', 0) // 1024}MB  "
                    f"fds={s.get('worker_fds')}  "
                    f"avail={s.get('memavailable_kb', 0) // 1024}MB")
            else:
                log(f"vm probe failed: {s.get('error')}")
            time.sleep(args.vm_interval)

    log(f"monitoring {base} for {args.duration}s")
    threads = [threading.Thread(target=health_loop, daemon=True)]
    if not args.no_vm:
        threads.append(threading.Thread(target=vm_loop, daemon=True))
    for t in threads:
        t.start()
    try:
        for t in threads:
            t.join(timeout=args.duration + 120)
    except KeyboardInterrupt:
        log("interrupted")

    health = [s for s in samples if s["kind"] == "health"]
    ok = [s for s in health if s["ok"]]
    print("\n" + "=" * 72)
    print(f"  monitor summary — {len(samples)} samples over {int(time.time() - t0)}s")
    print("=" * 72)
    if health:
        lats = sorted(s["latency"] for s in ok)
        print(f"  health checks    {len(ok)}/{len(health)} ok")
        if lats:
            print(f"  health latency   p50 {lats[len(lats) // 2]:.3f}s   "
                  f"max {max(lats):.3f}s")
    print(f"  peak sessions    {peak['sessions']}")
    if peak["worker_rss_kb"]:
        print(f"  peak worker RSS  {peak['worker_rss_kb'] // 1024} MB")
        print(f"  peak worker FDs  {peak['worker_fds']}")
    print()

    out = args.out or f"monitor_{args.app}_{int(time.time())}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"args": vars(args), "peak": peak, "samples": samples}, f,
                  ensure_ascii=False, indent=2)
    log(f"raw samples -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
