# -*- coding: utf-8 -*-
"""Compliance tracking for the two-week remote study.

The protocol each participant is held to (all three thresholds configurable):

  * at least ``min_sessions`` sessions (5), no upper limit
  * consecutive sessions **at least** ``min_gap_days`` (2) apart
  * at most ``window_days`` (14) elapsed from the first session to the last
  * four survey points: before the first session, right after it, after the
    session nearest the midpoint, and after the final one

Two definitions worth knowing before reading further:

**A session is a calendar day, not a room.** One study session = one day (in the
study timezone) on which the participant sent at least one message. Rooms on the
same day collapse into one session, which is also what absorbs the known trap
where a backend restart splits one sitting across two room ids.

**Gaps are calendar days, not 48-hour intervals.** Sessions at 23:00 Monday and
01:00 Wednesday are a compliant 2-day gap even though only 26 hours passed.
That is deliberate — participants think in days — so please don't "fix" it.

The evaluator is a pure function over plain dicts with ``today`` injected, so
every rule in here is testable without a database or a mocked clock.
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from data_paths import data_path
from user_store import SURVEY_POINTS

# Defaults live here and only here. A second copy in the JSON file would drift
# from this one the first time someone edited either.
DEFAULTS: Dict[str, Any] = {
    "timezone": "Asia/Tokyo",
    # --- the protocol itself ---
    "min_sessions": 5,
    "min_gap_days": 2,
    "window_days": 14,
    # --- how long to wait before something becomes someone's problem ---
    "silent_start_grace_days": 3,   # enrolled, still zero sessions -> action
    "stall_grace_days": 3,          # min_gap + this with no session -> action
    "post_first_grace_days": 1,
    "mid_grace_days": 2,
    "post_final_idle_days": 3,      # done enough sessions and gone quiet this long
    "post_final_grace_days": 3,
    "midnight_split_hours": 4,      # flag two "days" this close as one sitting
    "surveys": {
        "pre":        {"label": "Pre-study",       "url": ""},
        "post_first": {"label": "After session 1", "url": ""},
        "mid":        {"label": "Mid-study",       "url": ""},
        "post_final": {"label": "Final",           "url": ""},
    },
}

_INT_KEYS = (
    "min_sessions", "min_gap_days", "window_days", "silent_start_grace_days",
    "stall_grace_days", "post_first_grace_days", "mid_grace_days",
    "post_final_idle_days", "post_final_grace_days", "midnight_split_hours",
)

SEVERITY_ORDER = ("ok", "watch", "action")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def config_path() -> str:
    """Resolved at call time, not import time, so tests can redirect it."""
    override = (os.getenv("AGORA_STUDY_CONFIG_FILE") or "").strip()
    return override or data_path("study_config.json")


def _merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Top-level merge, one level deep for ``surveys``."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    out["surveys"] = {k: dict(v) for k, v in base.get("surveys", {}).items()}
    for key, val in (patch or {}).items():
        if key == "surveys" and isinstance(val, dict):
            for point, spec in val.items():
                if point in out["surveys"] and isinstance(spec, dict):
                    out["surveys"][point].update(
                        {k: v for k, v in spec.items() if k in ("label", "url")}
                    )
        else:
            out[key] = val
    return out


def _validate_config(cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Coerce and range-check. Returns (usable config, human-readable errors)."""
    errors: List[str] = []
    out = _merge(DEFAULTS, {})

    for key in _INT_KEYS:
        if key not in cfg:
            continue
        try:
            out[key] = int(cfg[key])
        except (TypeError, ValueError):
            errors.append(f"{key} must be a whole number")

    if "timezone" in cfg:
        tz = str(cfg.get("timezone") or "").strip()
        if not tz:
            errors.append("timezone cannot be empty")
        else:
            out["timezone"] = tz

    if out["min_sessions"] < 1:
        errors.append("min_sessions must be at least 1")
    if out["min_gap_days"] < 0:
        errors.append("min_gap_days cannot be negative")
    if out["window_days"] < 1:
        errors.append("window_days must be at least 1")
    for key in _INT_KEYS:
        if key not in ("min_sessions", "min_gap_days", "window_days") and out[key] < 0:
            errors.append(f"{key} cannot be negative")
    # A protocol nobody could satisfy: n sessions at a minimum gap already need
    # (n-1) * gap days, so a shorter window makes every participant fail by
    # construction. Catch it here rather than let the tracker flag all 32 people.
    span_needed = (out["min_sessions"] - 1) * out["min_gap_days"]
    if not errors and out["window_days"] < span_needed:
        errors.append(
            f"Impossible protocol: {out['min_sessions']} sessions at "
            f"{out['min_gap_days']}-day gaps need {span_needed} days, "
            f"but the window is {out['window_days']}"
        )

    surveys = cfg.get("surveys")
    if isinstance(surveys, dict):
        for point, spec in surveys.items():
            if point not in SURVEY_POINTS:
                errors.append(f"Unknown survey point '{point}'")
                continue
            if not isinstance(spec, dict):
                errors.append(f"Survey '{point}' must be an object")
                continue
            for field in ("label", "url"):
                if field in spec:
                    if not isinstance(spec[field], str):
                        errors.append(f"Survey '{point}' {field} must be text")
                    else:
                        out["surveys"][point][field] = spec[field].strip()

    unknown = set(cfg) - set(DEFAULTS)
    for key in sorted(unknown):
        errors.append(f"Unknown setting '{key}'")

    return out, errors


def load_config() -> Dict[str, Any]:
    """Defaults, overlaid with the saved file, overlaid with AGORA_STUDY_CONFIG.

    A corrupt or unreadable file falls back to defaults with a warning — the
    admin panel staying up matters more than honouring a half-written file.
    """
    cfg = _merge(DEFAULTS, {})
    saved: Dict[str, Any] = {}
    path = config_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                saved = loaded
            else:
                print(f"⚠ Study config: {path} is not an object, using defaults")
        except Exception as exc:
            print(f"⚠ Study config: cannot read {path}: {exc} — using defaults")

    env_raw = (os.getenv("AGORA_STUDY_CONFIG") or "").strip()
    if env_raw:
        try:
            env_cfg = json.loads(env_raw)
            if isinstance(env_cfg, dict):
                saved = _merge_plain(saved, env_cfg)
        except Exception as exc:
            print(f"⚠ Study config: AGORA_STUDY_CONFIG is not valid JSON: {exc}")

    saved.pop("updated_at", None)
    saved.pop("updated_by", None)
    cfg, errors = _validate_config(saved)
    if errors:
        print(f"⚠ Study config: ignoring invalid values ({'; '.join(errors)})")
    cfg["updated_at"] = _file_mtime_iso(path)
    return cfg


def _merge_plain(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two *saved* patches (not defaults) without materialising defaults."""
    out = dict(base)
    for key, val in patch.items():
        if key == "surveys" and isinstance(val, dict) and isinstance(out.get("surveys"), dict):
            merged = {k: dict(v) for k, v in out["surveys"].items() if isinstance(v, dict)}
            for point, spec in val.items():
                if isinstance(spec, dict):
                    merged.setdefault(point, {}).update(spec)
            out["surveys"] = merged
        else:
            out[key] = val
    return out


def _file_mtime_iso(path: str) -> Optional[str]:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat()
    except OSError:
        return None


def save_config(patch: Dict[str, Any], *, actor: str = "") -> Tuple[Dict[str, Any], List[str]]:
    """Validate a partial patch, persist it, and return the effective config.

    Only the fields that differ from the defaults are written, so bumping a
    default later actually reaches deployments that never touched that field.
    On any validation error nothing is written.
    """
    if not isinstance(patch, dict):
        return load_config(), ["Config must be an object"]

    current: Dict[str, Any] = {}
    path = config_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                current = loaded
        except Exception:
            current = {}
    current.pop("updated_at", None)
    current.pop("updated_by", None)

    merged = _merge_plain(current, {k: v for k, v in patch.items()
                                    if k not in ("updated_at", "updated_by")})
    effective, errors = _validate_config(merged)
    if errors:
        return load_config(), errors

    to_save: Dict[str, Any] = {}
    for key in _INT_KEYS + ("timezone",):
        if effective[key] != DEFAULTS[key]:
            to_save[key] = effective[key]
    surveys: Dict[str, Any] = {}
    for point, spec in effective["surveys"].items():
        diff = {k: v for k, v in spec.items() if v != DEFAULTS["surveys"][point].get(k)}
        if diff:
            surveys[point] = diff
    if surveys:
        to_save["surveys"] = surveys
    to_save["updated_at"] = datetime.now().astimezone().isoformat()
    if actor:
        to_save["updated_by"] = actor

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(to_save, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return load_config(), []


def _tz(cfg: Dict[str, Any]):
    from zoneinfo import ZoneInfo  # local import: keeps the module importable
    try:
        return ZoneInfo(cfg.get("timezone") or "Asia/Tokyo")
    except Exception:
        return None


def today_in_study_tz(cfg: Optional[Dict[str, Any]] = None) -> date:
    cfg = cfg or load_config()
    tz = _tz(cfg)
    return (datetime.now(tz) if tz else datetime.now()).date()


# ---------------------------------------------------------------------------
# Session derivation
# ---------------------------------------------------------------------------

def derive_sessions(
    store,
    user_ids: List[str],
    cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, List[dict]], dict]:
    """Group each participant's messages into one study session per calendar day.

    Folded in Python rather than grouped in SQL on purpose: ``date()``/``strftime``
    return NULL for an unparseable timestamp, which would silently sweep those
    rows into a phantom day bucket instead of reporting them. Fifteen thousand
    rows at study end is nothing to fold here, and doing it in Python also gets
    the ordering right across the two timestamp formats in the database.

    Returns ``({user_id: [session, ...]}, diagnostics)``, sessions sorted by day.
    """
    cfg = cfg or load_config()
    tz = _tz(cfg)
    rows = store.list_study_messages(user_ids)

    skipped = 0
    # user_id -> day -> accumulator
    buckets: Dict[str, Dict[date, dict]] = {}
    for row in rows:
        raw = row.get("created_at") or ""
        try:
            stamp = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            skipped += 1
            continue
        # A naive timestamp is what now_local_iso() emits when tzdata is missing;
        # leaving it naive makes astimezone() read it as system-local, which is
        # how it was written on both a UTC server and a JST laptop.
        local = stamp.astimezone(tz) if (tz and stamp.tzinfo) else stamp
        day = local.date()
        by_day = buckets.setdefault(row.get("user_id") or "", {})
        acc = by_day.get(day)
        if acc is None:
            acc = by_day[day] = {
                "day": day, "user_turns": 0, "message_count": 0,
                "first": local, "last": local, "rooms": set(), "scenarios": set(),
            }
        acc["message_count"] += 1
        if (row.get("character") or "") == "user":
            acc["user_turns"] += 1
        if local < acc["first"]:
            acc["first"] = local
        if local > acc["last"]:
            acc["last"] = local
        if row.get("room_id"):
            acc["rooms"].add(row["room_id"])
        if row.get("scenario_type"):
            acc["scenarios"].add(row["scenario_type"])

    split_hours = int(cfg.get("midnight_split_hours") or 0)
    sessions: Dict[str, List[dict]] = {}
    for uid, by_day in buckets.items():
        # A day with no user message is the participant re-reading an old room,
        # not a session.
        days = sorted(d for d, acc in by_day.items() if acc["user_turns"] > 0)
        out: List[dict] = []
        for i, day in enumerate(days):
            acc = by_day[day]
            notes = []
            if len(acc["rooms"]) > 1:
                notes.append({
                    "code": "multi_room",
                    "text": f"{len(acc['rooms'])} rooms (a backend restart splits one sitting)",
                })
            if i > 0 and split_hours > 0:
                prev = by_day[days[i - 1]]
                apart = (acc["first"] - prev["last"]).total_seconds() / 3600.0
                if 0 <= apart <= split_hours:
                    notes.append({
                        "code": "midnight_split",
                        "text": (f"only {apart:.1f}h after the previous session "
                                 f"(crossed midnight); may be one sitting"),
                    })
            out.append({
                "index": i + 1,
                "day": day.isoformat(),
                "user_turns": acc["user_turns"],
                "message_count": acc["message_count"],
                "first_at": acc["first"].isoformat(),
                "last_at": acc["last"].isoformat(),
                "room_ids": sorted(acc["rooms"]),
                "scenario_types": sorted(acc["scenarios"]),
                "notes": notes,
            })
        sessions[uid] = out

    for uid in user_ids:
        sessions.setdefault(uid, [])

    return sessions, {"skipped_unparseable": skipped}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _parse_day(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _fmt(day: Optional[date]) -> Optional[str]:
    return day.isoformat() if day else None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def evaluate_participant(
    enrollment: dict,
    sessions: List[dict],
    surveys: Dict[str, dict],
    cfg: Dict[str, Any],
    today: date,
) -> dict:
    """Judge one participant against the protocol. Pure: no DB, no clock.

    ``surveys`` maps a point name to its stored record (or omits it entirely).
    Returns the summary shape the admin panel renders, including ``reasons`` —
    English sentences formatted here rather than in JSX so they stay testable.
    """
    min_sessions = int(cfg["min_sessions"])
    min_gap = int(cfg["min_gap_days"])
    window = int(cfg["window_days"])
    status = (enrollment.get("status") or "active").strip() or "active"

    days = [d for d in (_parse_day(s.get("day")) for s in sessions) if d]
    days.sort()
    count = len(days)
    first_day = days[0] if days else None
    last_day = days[-1] if days else None
    start_on = _parse_day(enrollment.get("start_on"))
    anchor_day = start_on or first_day

    gaps = [(days[i + 1] - days[i]).days for i in range(len(days) - 1)]
    gap_violations = [
        {"from": days[i].isoformat(), "to": days[i + 1].isoformat(), "days": g}
        for i, g in enumerate(gaps) if g < min_gap
    ]

    span_days = (last_day - first_day).days if (first_day and last_day) else None
    window_exceeded = bool(span_days is not None and span_days > window)
    deadline_day = anchor_day + timedelta(days=window) if anchor_day else None
    elapsed_days = max(0, (today - anchor_day).days) if anchor_day else None
    days_left = (deadline_day - today).days if deadline_day else None
    days_since_last = (today - last_day).days if last_day else None
    next_ok_on = last_day + timedelta(days=min_gap) if last_day else None

    needed = max(0, min_sessions - count)
    earliest_finish = None
    if needed:
        start = max(today, next_ok_on) if next_ok_on else today
        earliest_finish = start + timedelta(days=(needed - 1) * min_gap)
    feasible = (needed == 0) or bool(
        deadline_day and earliest_finish and earliest_finish <= deadline_day
    )

    survey_states = _evaluate_surveys(
        enrollment, days, surveys, cfg, today, anchor_day, deadline_day, status
    )

    reasons: List[dict] = []

    def add(code: str, severity: str, text: str) -> None:
        reasons.append({"code": code, "severity": severity, "text": text})

    for point in SURVEY_POINTS:
        info = survey_states[point]
        for dev in info["deviations"]:
            add(dev["code"], dev["severity"], dev["text"])
        if info["state"] == "overdue":
            since = info.get("due_since")
            add("survey_overdue", "action",
                f"{info['label']} survey overdue"
                + (f" since {since}" if since else ""))
        elif info["state"] == "due":
            add("survey_due", "watch", f"{info['label']} survey due now")

    if count == 0:
        if start_on and (today - start_on).days > int(cfg["silent_start_grace_days"]):
            add("never_started", "action",
                f"No sessions yet, {_plural((today - start_on).days, 'day')} after {start_on}")
        elif not start_on:
            add("no_start_date", "watch",
                "No sessions and no start date — set one to track this participant")
    else:
        if window_exceeded:
            add("window_exceeded", "action",
                f"Span is {_plural(span_days, 'day')}, over the {window}-day window")
        if gap_violations:
            worst = min(v["days"] for v in gap_violations)
            add("gap_violation", "watch",
                f"{_plural(len(gap_violations), 'gap')} shorter than {min_gap} days "
                f"(shortest {_plural(worst, 'day')})")
        if needed and not feasible:
            add("infeasible", "action",
                f"Cannot reach {min_sessions} sessions by "
                f"{_fmt(deadline_day) or 'the deadline'}: {needed} more at "
                f"{min_gap}-day gaps lands on {_fmt(earliest_finish)}")
        elif needed and days_since_last is not None and \
                days_since_last > min_gap + int(cfg["stall_grace_days"]):
            add("stalled", "action",
                f"No session for {_plural(days_since_last, 'day')}, "
                f"{needed} still needed")
        # Only once the exit survey is in play. The protocol has no upper limit on
        # sessions, so flagging everyone the moment they hit five would leave
        # participants who are still happily working pinned at "needs attention".
        if (needed == 0 and status == "active"
                and survey_states["post_final"]["state"] != "not_due"):
            add("ready_to_complete", "watch",
                f"{count} sessions done and the study looks finished — "
                f"mark the participant completed")

    if status in ("withdrawn", "excluded"):
        severity = "muted"
    elif (status == "completed" and needed == 0
          and all(survey_states[p]["state"] in ("done", "waived") for p in SURVEY_POINTS)):
        severity = "done"
    else:
        severity = "ok"
        for r in reasons:
            if SEVERITY_ORDER.index(r["severity"]) > SEVERITY_ORDER.index(severity):
                severity = r["severity"]

    reasons.sort(key=lambda r: -SEVERITY_ORDER.index(r["severity"]))

    return {
        "user_id": enrollment.get("user_id") or "",
        "cohort": enrollment.get("cohort") or "",
        "status": status,
        "note": enrollment.get("note") or "",
        "severity": severity,
        "start_on": _fmt(start_on),
        "first_day": _fmt(first_day),
        "last_day": _fmt(last_day),
        "anchor_day": _fmt(anchor_day),
        "deadline_day": _fmt(deadline_day),
        "session_count": count,
        "sessions_needed": needed,
        "user_turns_total": sum(int(s.get("user_turns") or 0) for s in sessions),
        "span_days": span_days,
        "elapsed_days": elapsed_days,
        "window_days": window,
        "days_left": days_left,
        "days_since_last": days_since_last,
        "next_ok_on": _fmt(next_ok_on),
        "earliest_finish": _fmt(earliest_finish),
        "feasible": feasible,
        "gaps": gaps,
        "gap_violations": gap_violations,
        "window_exceeded": window_exceeded,
        "surveys": {p: survey_states[p]["state"] for p in SURVEY_POINTS},
        "survey_detail": survey_states,
        "reasons": reasons,
    }


def _evaluate_surveys(
    enrollment: dict,
    days: List[date],
    surveys: Dict[str, dict],
    cfg: Dict[str, Any],
    today: date,
    anchor_day: Optional[date],
    deadline_day: Optional[date],
    status: str,
) -> Dict[str, dict]:
    """Live state plus a retrospective anchor for each of the four points.

    ``state`` is what an admin chases today. ``anchor`` is the methodological
    ground truth — which session the point should attach to — carried separately
    and flagged ``provisional`` while it can still move. The live rule is never
    presented as the definition.
    """
    min_sessions = int(cfg["min_sessions"])
    window = int(cfg["window_days"])
    count = len(days)
    first_day = days[0] if days else None
    last_day = days[-1] if days else None
    specs = cfg.get("surveys") or {}
    out: Dict[str, dict] = {}

    for point in SURVEY_POINTS:
        spec = specs.get(point) or {}
        record = surveys.get(point)
        info = {
            "point": point,
            "label": spec.get("label") or DEFAULTS["surveys"][point]["label"],
            "url": spec.get("url") or "",
            "state": "not_due",
            "due_since": None,
            "record": record,
            "anchor": None,
            "deviations": [],
        }
        out[point] = info
        if record:
            info["state"] = "waived" if record.get("status") == "waived" else "done"

    # --- pre -------------------------------------------------------------
    pre = out["pre"]
    pre["anchor"] = {"kind": "before_first_session", "day": _fmt(first_day),
                     "session_index": 1 if first_day else None, "provisional": False}
    if pre["state"] not in ("done", "waived"):
        if count >= 1:
            pre["state"] = "overdue"
            pre["due_since"] = _fmt(first_day)
        else:
            pre["state"] = "due"
            pre["due_since"] = enrollment.get("start_on") or None
    if count >= 1 and pre["state"] not in ("done", "waived"):
        pre["deviations"].append({
            "code": "pre_missing_after_session", "severity": "action",
            "text": ("Pre-study survey was never recorded but sessions have already "
                     "started — the baseline cannot be collected retroactively"),
        })
    else:
        done_on = _parse_day((pre["record"] or {}).get("completed_on"))
        # Recording it late does not undo the deviation; back-dating completed_on
        # does, which is exactly what that field is for.
        if done_on and first_day and done_on > first_day:
            pre["deviations"].append({
                "code": "pre_after_first_session", "severity": "action",
                "text": (f"Pre-study survey completed {done_on}, after the first "
                         f"session on {first_day}"),
            })

    # --- post_first ------------------------------------------------------
    pf = out["post_first"]
    if first_day:
        pf["anchor"] = {"kind": "after_session", "session_index": 1,
                        "day": _fmt(first_day), "provisional": False}
    if pf["state"] not in ("done", "waived"):
        if count == 0:
            pf["state"] = "not_due"
        else:
            pf["due_since"] = _fmt(first_day)
            grace = int(cfg["post_first_grace_days"])
            if count >= 2 or (first_day and today > first_day + timedelta(days=grace)):
                pf["state"] = "overdue"
            else:
                pf["state"] = "due"

    # --- mid -------------------------------------------------------------
    mid = out["mid"]
    if days:
        # Retrospective: the session nearest the midpoint of the observed span,
        # ties resolved to the earlier one.
        span = (last_day - first_day).days
        midpoint = first_day + timedelta(days=span / 2)
        best = min(range(len(days)), key=lambda i: (abs((days[i] - midpoint).days), i))
        mid["anchor"] = {"kind": "after_session", "session_index": best + 1,
                         "day": _fmt(days[best]), "provisional": status == "active"}
    if mid["state"] not in ("done", "waived"):
        triggers: List[date] = []
        # Session trigger — catches the front-loaded participant who has already
        # done 4 of 5 sessions by study day 7.
        session_trigger_n = math.ceil(min_sessions / 2)
        if count >= session_trigger_n:
            triggers.append(days[session_trigger_n - 1])
        # Date trigger — catches the slow starter with no session near day 7.
        if anchor_day:
            halfway = anchor_day + timedelta(days=window // 2)
            if today >= halfway and count >= 1:
                triggers.append(halfway)
        if triggers:
            since = min(triggers)
            mid["due_since"] = _fmt(since)
            mid["state"] = ("overdue"
                            if today > since + timedelta(days=int(cfg["mid_grace_days"]))
                            else "due")

    # --- post_final ------------------------------------------------------
    pfin = out["post_final"]
    if last_day:
        pfin["anchor"] = {"kind": "after_session", "session_index": count,
                          "day": _fmt(last_day), "provisional": status == "active"}
    if pfin["state"] not in ("done", "waived"):
        triggers = []
        if status == "completed":
            marked = _parse_day((enrollment.get("updated_at") or "")[:10])
            triggers.append(marked or today)
        if deadline_day and today > deadline_day:
            triggers.append(deadline_day + timedelta(days=1))
        idle = int(cfg["post_final_idle_days"])
        if count >= min_sessions and last_day and (today - last_day).days >= idle:
            triggers.append(last_day + timedelta(days=idle))
        if triggers:
            since = min(triggers)
            pfin["due_since"] = _fmt(since)
            overdue_after = (deadline_day + timedelta(days=int(cfg["post_final_grace_days"]))
                             if deadline_day else None)
            pfin["state"] = "overdue" if (overdue_after and today > overdue_after) else "due"

    return out


# ---------------------------------------------------------------------------
# Cohort roll-up
# ---------------------------------------------------------------------------

def cohort_overview(
    store,
    cfg: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> dict:
    """Everything the Study tab needs in one call."""
    cfg = cfg or load_config()
    today = today or today_in_study_tz(cfg)

    enrollments = store.list_enrollments()
    user_ids = [e["user_id"] for e in enrollments]
    sessions_by_user, diagnostics = derive_sessions(store, user_ids, cfg)

    surveys_by_user: Dict[str, Dict[str, dict]] = {}
    for rec in store.list_survey_responses():
        surveys_by_user.setdefault(rec["user_id"], {})[rec["point"]] = rec

    participants = [
        evaluate_participant(
            e, sessions_by_user.get(e["user_id"], []),
            surveys_by_user.get(e["user_id"], {}), cfg, today,
        )
        for e in enrollments
    ]

    counts = {
        "enrolled": len(participants),
        "active": 0, "completed": 0, "withdrawn": 0, "excluded": 0,
        "action": 0, "watch": 0, "ok": 0, "done": 0, "muted": 0,
        "not_started": 0,
    }
    for p in participants:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
        counts[p["severity"]] = counts.get(p["severity"], 0) + 1
        if p["severity"] != "muted" and p["session_count"] == 0:
            counts["not_started"] += 1

    warnings = []
    orphans = store.count_orphan_messages()
    if orphans:
        warnings.append({
            "code": "orphan_messages", "count": orphans,
            "text": (f"{orphans} messages belong to rooms with no owner record "
                     f"(legacy or CLI runs) and are not counted"),
        })
    if diagnostics.get("skipped_unparseable"):
        n = diagnostics["skipped_unparseable"]
        warnings.append({
            "code": "unparseable_timestamps", "count": n,
            "text": f"{n} messages have an unreadable timestamp and are not counted",
        })

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "today": today.isoformat(),
        "config": cfg,
        "counts": counts,
        "warnings": warnings,
        "diagnostics": diagnostics,
        "participants": participants,
    }


def participant_detail(
    store,
    user_id: str,
    cfg: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> Optional[dict]:
    """One participant, with the session list and full survey records."""
    cfg = cfg or load_config()
    today = today or today_in_study_tz(cfg)

    enrollment = store.get_enrollment(user_id)
    if not enrollment:
        return None
    sessions_by_user, diagnostics = derive_sessions(store, [enrollment["user_id"]], cfg)
    sessions = sessions_by_user.get(enrollment["user_id"], [])
    records = {r["point"]: r for r in store.list_survey_responses(enrollment["user_id"])}
    summary = evaluate_participant(enrollment, sessions, records, cfg, today)
    return {
        **summary,
        "enrollment": enrollment,
        "sessions": sessions,
        "survey_records": records,
        "diagnostics": diagnostics,
        "today": today.isoformat(),
        "config": cfg,
    }


