#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Replay room transcripts through the novelty metric, old and new, and report
where the current thresholds sit on each cohort's distribution.

Why this exists: the 0.40 trigger / 0.25 drop bar were calibrated on gpt-4o
rooms. gpt-5.6 both words things differently and @-targets far more often, and
quote exclusion (novelty_ratio's exclude_tokens) changed what group_ratio means.
This script replays PUBLISHED messages — content good enough to ship — from
existing room logs and reports, per cohort × metric × scope, how much of that
known-good content each candidate threshold would have flagged. It prints a
report and writes JSON; it deliberately changes no runtime default. Which value
goes into AGORA_NOVELTY_THRESHOLD / AGORA_NOVELTY_DROP_THRESHOLD is a study
decision, not this script's.

Replay caveats, so the numbers are read correctly:
- Only published messages replay. First attempts that were retried exist solely
  in the live _novelty.jsonl rows (the text was never persisted), so live rows
  are used for fidelity checks but distributions come from the transcript.
- move_detail is joined from {room}_rationale.jsonl move events by
  (agent key, second-resolution timestamp) — same convention map_facts uses —
  with body @mentions as fallback, mirroring resolve_reply_target.
- Fidelity: for _novelty.jsonl rows with reason == "pass", the replayed OLD
  group score should match group_ratio_raw (or group_ratio in pre-exclusion
  rooms). Kept-retry rows can NOT match — the published text is the retry but
  the logged first_group_ratio belongs to the discarded draft.

Usage:
  python3 backend/scripts/recalibrate_novelty.py \
      [--logs-dir backend/logs] [--json-out /tmp/recal.json] \
      [--rooms-new 038136 006555 469587 540206 297132] \
      [--rooms-old 198163 811066]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-recalibration")

import agentwake_new as aw  # noqa: E402


def _jl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _agents_of(logs_dir: str, room: str) -> Dict[str, str]:
    """key -> display name, from the room's config log."""
    for row in _jl(os.path.join(logs_dir, f"{room}_config.jsonl")):
        agents = row.get("agents") or []
        if agents:
            return {a["key"]: a.get("name") or a["key"] for a in agents if a.get("key")}
    return {}


def _moves_of(logs_dir: str, room: str) -> Dict[tuple, str]:
    """(agent key, iso-second timestamp) -> move detail string."""
    out: Dict[tuple, str] = {}
    for row in _jl(os.path.join(logs_dir, f"{room}_rationale.jsonl")):
        if row.get("event") == "move" and isinstance(row.get("detail"), str):
            out[(row.get("agent"), row.get("time"))] = row["detail"]
    return out


def replay_room(logs_dir: str, room: str,
                group_window: int, self_window: int) -> List[dict]:
    """One record per published agent message: old + new scores, both scopes."""
    name_map = _agents_of(logs_dir, room)
    if not name_map:
        return []
    key_of_name = {v: k for k, v in name_map.items()}
    mention_patterns = aw.build_mention_patterns(list(name_map), name_map)
    moves = _moves_of(logs_dir, room)

    records: List[dict] = []
    transcript_lines: List[str] = []
    for row in _jl(os.path.join(logs_dir, f"{room}.jsonl")):
        who = row.get("character") or ""
        txt = (row.get("txt") or "").strip()
        if not txt:
            continue
        if who != "user" and who in key_of_name and transcript_lines:
            if not aw._content_tokens(txt):
                # Bare-"…" and other content-free bubbles score 0.0 by
                # construction. They are the failure mode, not known-good
                # content; letting them into the distribution drags every
                # percentile toward zero (measured: the 4o cohort's p10 was
                # 0.0 purely from its 10 ellipsis replies).
                transcript_lines.append(f"{who}: {txt}")
                continue
            self_key = key_of_name[who]
            own_prefix = f"{who}: "
            window = transcript_lines[-group_window:]
            own_lines = [ln[len(own_prefix):] for ln in transcript_lines
                         if ln.startswith(own_prefix)][-self_window:]
            group_old = aw.novelty_ratio(txt, window)
            self_old = aw.novelty_ratio(txt, own_lines) if own_lines else 1.0
            move_detail = moves.get((self_key, row.get("time")), "")
            target = aw.resolve_reply_target(move_detail, txt, mention_patterns, self_key)
            exclude: set = set()
            if target:
                t_text = aw.last_message_of(name_map.get(target, target), transcript_lines)
                if t_text:
                    exclude = aw._content_tokens(t_text)
            if exclude:
                group_new = aw.novelty_ratio(txt, window, exclude_tokens=exclude)
                self_new = (aw.novelty_ratio(txt, own_lines, exclude_tokens=exclude)
                            if own_lines else 1.0)
            else:
                group_new, self_new = group_old, self_old
            records.append({
                "room": room, "agent": self_key, "time": row.get("time"),
                "group_old": group_old, "self_old": self_old,
                "group_new": group_new, "self_new": self_new,
                "target": target, "excluded": len(exclude),
            })
        transcript_lines.append(f"{who}: {txt}")
    return records


def fidelity(logs_dir: str, room: str, records: List[dict]) -> dict:
    """Match replayed OLD group scores against live pass rows (see caveats)."""
    live = [r for r in _jl(os.path.join(logs_dir, f"{room}_novelty.jsonl"))
            if r.get("reason") == "pass"]
    by_key = defaultdict(list)
    for rec in records:
        by_key[rec["agent"]].append(rec)
    matched = missed = 0
    for row in live:
        want = row.get("group_ratio_raw", row.get("group_ratio"))
        cands = by_key.get(row.get("agent")) or []
        if any(abs(rec["group_old"] - want) < 0.005 for rec in cands):
            matched += 1
        else:
            missed += 1
    return {"pass_rows": len(live), "matched": matched, "missed": missed}


def _pct(values: List[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


def summarize(records: List[dict], key: str, thresholds: List[float]) -> dict:
    vals = [r[key] for r in records]
    out = {
        "n": len(vals),
        "min": round(min(vals), 3) if vals else None,
        "p10": round(_pct(vals, 0.10), 3) if vals else None,
        "p25": round(_pct(vals, 0.25), 3) if vals else None,
        "p50": round(_pct(vals, 0.50), 3) if vals else None,
    }
    for th in thresholds:
        out[f"below_{th}"] = (round(sum(1 for v in vals if v < th) / len(vals), 3)
                              if vals else None)
    return out


def suggest(records: List[dict], key: str, miskill_budget: float = 0.05) -> float:
    """Largest threshold keeping the false-flag rate on published messages
    within budget, on a 0.05 grid."""
    vals = sorted(r[key] for r in records)
    if not vals:
        return 0.0
    best = 0.0
    for th_i in range(1, 20):
        th = th_i * 0.05
        if sum(1 for v in vals if v < th) / len(vals) <= miskill_budget:
            best = th
    return round(best, 2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--logs-dir", default=os.path.join(_BACKEND, "logs"))
    ap.add_argument("--rooms-new", nargs="*",
                    default=["038136", "006555", "469587", "540206", "297132"],
                    help="gpt-5.6 rooms")
    ap.add_argument("--rooms-old", nargs="*", default=["198163", "811066"],
                    help="gpt-4o comparison rooms")
    ap.add_argument("--group-window", type=int, default=10)
    ap.add_argument("--self-window", type=int, default=6)
    ap.add_argument("--thresholds", nargs="*", type=float, default=[0.40, 0.35, 0.30, 0.25])
    ap.add_argument("--miskill-budget", type=float, default=0.05)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    cohorts = {"gpt-5.6": args.rooms_new, "gpt-4o": args.rooms_old}
    report: dict = {"windows": [args.group_window, args.self_window], "cohorts": {}}

    for cohort, rooms in cohorts.items():
        records: List[dict] = []
        fid = []
        for room in rooms:
            recs = replay_room(args.logs_dir, room, args.group_window, args.self_window)
            if not recs:
                print(f"!! {room}: no replayable rows (missing logs?)", file=sys.stderr)
                continue
            records.extend(recs)
            fid.append({"room": room, **fidelity(args.logs_dir, room, recs),
                        "messages": len(recs)})
        with_target = sum(1 for r in records if r["target"])
        cohort_out = {
            "rooms": fid,
            "messages": len(records),
            "with_reply_target": with_target,
            "target_rate": round(with_target / len(records), 3) if records else None,
            "scores": {},
            "suggested_trigger": {},
        }
        for metric in ("old", "new"):
            for scope in ("group", "self"):
                key = f"{scope}_{metric}"
                cohort_out["scores"][key] = summarize(records, key, args.thresholds)
            cohort_out["suggested_trigger"][metric] = suggest(
                records, f"group_{metric}", args.miskill_budget)
        report["cohorts"][cohort] = cohort_out

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nwrote {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
