# -*- coding: utf-8 -*-
"""Acceptance for the study compliance tracker (backend/study_tracker.py):

  1. sessions   -> messages fold into one session per calendar day, in the study
                   timezone, counting only days the participant actually spoke on.
  2. protocol   -> the 5-sessions / 2-day-gap / 14-day-window rules, and the
                   feasibility warning that fires before anything is overdue.
  3. surveys    -> the four points' live states, retrospective anchors, and the
                   pre-survey deviation that survives a late recording.
  4. config     -> defaults, persistence, validation, and corrupt-file fallback.
  5. roll-up    -> cohort counts and the badge number the admin panel shows.
  6. schema     -> the two new tables are additive and safe on an existing DB.

No API key or network: this only touches SQLite and pure functions.
"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
WORK = tempfile.mkdtemp(prefix="study_tracker_")
os.chdir(WORK)
# Redirect the config file before importing, so nothing writes into the repo.
os.environ["AGORA_STUDY_CONFIG_FILE"] = os.path.join(WORK, "study_config.json")
os.environ.pop("AGORA_STUDY_CONFIG", None)

from _harness import Checker  # noqa: E402

import study_tracker as st  # noqa: E402
import user_store  # noqa: E402

_ck = Checker(); check = _ck.check

TOKYO = timezone(timedelta(hours=9))
CFG = st.load_config()
D0 = date(2026, 8, 1)


def day(n):
    """Day n of the study, as an ISO date string."""
    return (D0 + timedelta(days=n)).isoformat()


def enrollment(user_id="P01", **kw):
    base = {"user_id": user_id, "cohort": "", "status": "active", "start_on": "",
            "note": "", "enrolled_at": "", "updated_at": ""}
    base.update(kw)
    return base


def sessions_on(offsets, turns=5):
    """Fabricate the session list evaluate_participant() expects."""
    return [{"index": i + 1, "day": day(n), "user_turns": turns, "message_count": turns * 4,
             "first_at": f"{day(n)}T09:00:00+09:00", "last_at": f"{day(n)}T09:30:00+09:00",
             "room_ids": [f"r{n}"], "scenario_types": ["employment"], "notes": []}
            for i, n in enumerate(offsets)]


def record(point="pre", completed_on=None, status="completed"):
    return {"user_id": "P01", "point": point, "status": status,
            "completed_on": completed_on or day(0),
            "completed_at": "", "recorded_by": "admin", "note": "", "updated_at": ""}


def clean(*points):
    """Surveys recorded on time, so they contribute no deviations of their own."""
    return {p: record(p, day(-1) if p == "pre" else day(0)) for p in points}


def ev(sessions, surveys=None, today_n=8, cfg=None, **enroll):
    return st.evaluate_participant(enrollment(**enroll), sessions, surveys or {},
                                   cfg or CFG, D0 + timedelta(days=today_n))


def codes(reasons):
    return {r["code"] for r in reasons}


# =========================================================== 1. sessions (6)
db_path = os.path.join(WORK, "sessions.db")
store = user_store.UserStore(db_path)
store.register("P01", "pw1234")
store.register("P02", "pw1234")

_seq = [0]


def msg(room, user, character, stamp):
    """Insert one chat message, creating its room on first use."""
    if not store.get_chat_room(room):
        store.create_chat_room(room, user, scenario_type="employment")
    _seq[0] += 1
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO chat_messages (room_id, seq, character, txt, created_at)"
            " VALUES (?, ?, ?, '', ?)",
            (room, _seq[0], character, stamp),
        )
        conn.commit()


# Two rooms, same Tokyo day -> one session (the backend-restart case).
msg("ra", "P01", "user", "2026-08-02T09:10:00+09:00")
msg("ra", "P01", "ChatbotA", "2026-08-02T09:11:00+09:00")
msg("rb", "P01", "user", "2026-08-02T21:40:00+09:00")
# A room with no user message is not a session.
msg("rc", "P01", "ChatbotB", "2026-08-03T10:00:00+09:00")
# The mixed-offset trap, built so that string handling fails in both ways:
#   a) "2026-08-04T16:00+00:00" is 01:00 on Aug *5* in Tokyo — reading the date
#      off the front of the string files it under Aug 4 and merges two sessions.
#   b) within Aug 5, "2026-08-05T00:30+09:00" (15:30 UTC) happens BEFORE
#      "2026-08-04T16:00+00:00" (16:00 UTC) yet sorts after it lexically.
msg("rd", "P01", "user", "2026-08-04T23:30:00+09:00")   # Aug 4, 23:30 Tokyo
msg("rd", "P01", "user", "2026-08-04T16:00:00+00:00")   # Aug 5, 01:00 Tokyo
msg("rd", "P01", "user", "2026-08-05T00:30:00+09:00")   # Aug 5, 00:30 Tokyo
# Unparseable timestamp.
msg("re", "P02", "user", "not-a-timestamp")
msg("re", "P02", "user", "2026-08-06T12:00:00+09:00")

got, diag = st.derive_sessions(store, ["P01", "P02"], CFG)
p1 = got["P01"]
check("same-day rooms collapse into one session",
      len(p1) == 3 and p1[0]["day"] == "2026-08-02", [s["day"] for s in p1])
check("multi-room session lists both rooms",
      p1[0]["room_ids"] == ["ra", "rb"] and
      any(n["code"] == "multi_room" for n in p1[0]["notes"]), p1[0])
check("agent-only day is not a session",
      "2026-08-03" not in [s["day"] for s in p1])
aug4 = [s for s in p1 if s["day"] == "2026-08-04"][0]
aug5 = [s for s in p1 if s["day"] == "2026-08-05"][0]
check("a +00:00 stamp is bucketed by its Tokyo day, not its string prefix",
      aug4["user_turns"] == 1 and aug5["user_turns"] == 2, [aug4, aug5])
check("first_at/last_at order by instant, not string",
      aug5["first_at"].startswith("2026-08-05T00:30") and
      aug5["last_at"].startswith("2026-08-05T01:00"), aug5)
check("counts are per-day, not per-room",
      p1[0]["user_turns"] == 2 and p1[0]["message_count"] == 3, p1[0])
check("unparseable timestamp is skipped and counted",
      diag["skipped_unparseable"] == 1 and len(got["P02"]) == 1, diag)

with store._connect() as conn:
    conn.execute("INSERT INTO chat_messages (room_id, seq, character, txt, created_at)"
                 " VALUES ('ghost', 1, 'user', '', '2026-08-01T10:00:00+09:00')")
    conn.commit()
check("orphan messages are excluded but reported", store.count_orphan_messages() == 1)


# ========================================================== 2. protocol (6)
DONE3 = clean("pre", "post_first", "mid")

perfect = ev(sessions_on([0, 2, 4, 6, 8]), DONE3)
check("perfect run is ok",
      perfect["severity"] == "ok" and perfect["session_count"] == 5
      and perfect["gap_violations"] == [] and perfect["span_days"] == 8,
      perfect["reasons"])
check("hitting the session target mid-study is not itself an alert",
      perfect["severity"] == "ok", perfect["reasons"])
ALL4 = clean("pre", "post_first", "mid", "post_final")
done_auto = ev(sessions_on([0, 2, 4, 6, 8]), ALL4, today_n=12)
check("DONE is derived, with nothing for the researcher to click",
      done_auto["severity"] == "done" and done_auto["status"] == "active",
      done_auto["reasons"])
check("a legacy hand-set 'completed' status reads as an ordinary participant",
      ev(sessions_on([0, 2]), DONE3, today_n=4, status="completed")["status"] == "active")

tooclose = ev(sessions_on([0, 1, 3, 5, 7]), DONE3)
check("gap under 2 days is a violation, naming the pair",
      len(tooclose["gap_violations"]) == 1
      and tooclose["gap_violations"][0] == {"from": day(0), "to": day(1), "days": 1},
      tooclose["gap_violations"])
check("gap violation is watch, not action",
      "gap_violation" in codes(tooclose["reasons"]) and tooclose["severity"] == "watch",
      tooclose["severity"])

overlong = ev(sessions_on([0, 4, 8, 12, 16]), DONE3, today_n=16)
check("span over the window is action",
      overlong["window_exceeded"] and overlong["span_days"] == 16
      and overlong["severity"] == "action", overlong["reasons"])

stuck = ev(sessions_on([0, 2]), today_n=11)
check("cannot finish in time -> infeasible",
      stuck["feasible"] is False and "infeasible" in codes(stuck["reasons"])
      and stuck["severity"] == "action", stuck["reasons"])
onpace = ev(sessions_on([0, 2]), today_n=4)
check("same shortfall earlier is still feasible",
      onpace["feasible"] is True and "infeasible" not in codes(onpace["reasons"]),
      onpace["reasons"])

silent = ev([], today_n=5, start_on=day(0))
check("enrolled but never started -> action",
      silent["severity"] == "action" and "never_started" in codes(silent["reasons"]),
      silent["reasons"])
nostart = ev([], today_n=5)
check("no sessions and no start date asks for one instead of guessing",
      nostart["severity"] == "watch" and "no_start_date" in codes(nostart["reasons"]),
      nostart["reasons"])

# One study-wide date beats typing 32 of them; a per-participant date still wins.
wide = st._merge(CFG, {"study_start_on": day(0)})
check("the study-wide start date anchors everyone",
      ev([], today_n=5, cfg=wide)["severity"] == "action"
      and "never_started" in codes(ev([], today_n=5, cfg=wide)["reasons"]))
check("a late joiner's own start date overrides the study-wide one",
      ev([], today_n=5, cfg=wide, start_on=day(4))["start_on"] == day(4)
      and ev([], today_n=5, cfg=wide, start_on=day(4))["severity"] == "watch")

gone = ev(sessions_on([0, 1, 3]), today_n=16, status="withdrawn")
check("withdrawn is muted despite violations", gone["severity"] == "muted")

stalled = ev(sessions_on([0, 2]), today_n=8)
check("stalled participant is action",
      "stalled" in codes(stalled["reasons"]), stalled["reasons"])


# =========================================================== 3. surveys (10)
started = ev(sessions_on([0]), today_n=0)
check("pre missing once a session exists -> overdue + action",
      started["surveys"]["pre"] == "overdue"
      and "pre_missing_after_session" in codes(started["reasons"])
      and started["severity"] == "action", started["reasons"])

nosess = ev([], today_n=0, start_on=day(0))
check("pre is due from enrollment, not not_due", nosess["surveys"]["pre"] == "due")

ontime = ev(sessions_on([0]), {"pre": record("pre", day(-1))}, today_n=0)
check("pre completed before the first session leaves no deviation",
      ontime["surveys"]["pre"] == "done"
      and not (codes(ontime["reasons"]) & {"pre_after_first_session",
                                           "pre_missing_after_session"}),
      ontime["reasons"])

late = ev(sessions_on([0, 2]), {"pre": record("pre", day(3))}, today_n=3)
check("recording pre late does NOT erase the deviation",
      late["surveys"]["pre"] == "done"
      and "pre_after_first_session" in codes(late["reasons"]), late["reasons"])

pf1 = ev(sessions_on([0]), {"pre": record("pre", day(-1))}, today_n=0)
check("post_first due after session 1", pf1["surveys"]["post_first"] == "due")
pf2 = ev(sessions_on([0, 2]), {"pre": record("pre", day(-1))}, today_n=2)
check("post_first overdue once session 2 happened",
      pf2["surveys"]["post_first"] == "overdue")
pf3 = ev(sessions_on([0]), {"pre": record("pre", day(-1))}, today_n=3)
check("post_first overdue past its grace even with one session",
      pf3["surveys"]["post_first"] == "overdue")
check("post_first not due before any session",
      ev([], today_n=0, start_on=day(0))["surveys"]["post_first"] == "not_due")

front = ev(sessions_on([0, 2, 4]), {"pre": record("pre", day(-1))}, today_n=4)
check("mid fires at session 3 for a front-loaded participant",
      front["surveys"]["mid"] == "due" and front["survey_detail"]["mid"]["due_since"] == day(4),
      front["survey_detail"]["mid"])
slow = ev(sessions_on([0, 5]), {"pre": record("pre", day(-1))}, today_n=7)
check("mid also fires on day 7 for a slow starter",
      slow["surveys"]["mid"] == "due" and slow["survey_detail"]["mid"]["due_since"] == day(7),
      slow["survey_detail"]["mid"])
check("mid not due before either trigger",
      ev(sessions_on([0, 2]), {"pre": record("pre", day(-1))},
         today_n=2)["surveys"]["mid"] == "not_due")

anchored = ev(sessions_on([0, 2, 4, 6, 8]), {"pre": record("pre", day(-1))}, today_n=8)
check("mid anchor is the session nearest the midpoint",
      anchored["survey_detail"]["mid"]["anchor"]["session_index"] == 3
      and anchored["survey_detail"]["mid"]["anchor"]["day"] == day(4),
      anchored["survey_detail"]["mid"]["anchor"])
check("mid anchor is provisional while the participant is active",
      anchored["survey_detail"]["mid"]["anchor"]["provisional"] is True)
tie = ev(sessions_on([0, 2, 6, 8]), {"pre": record("pre", day(-1))}, today_n=8)
check("mid anchor breaks ties toward the earlier session",
      tie["survey_detail"]["mid"]["anchor"]["session_index"] == 2,
      tie["survey_detail"]["mid"]["anchor"])

fin_idle = ev(sessions_on([0, 2, 4, 6, 8]), {"pre": record("pre", day(-1))}, today_n=11)
check("post_final fires after enough sessions and idle time",
      fin_idle["surveys"]["post_final"] == "due"
      and fin_idle["survey_detail"]["post_final"]["due_since"] == day(11),
      fin_idle["survey_detail"]["post_final"])
fin_dead = ev(sessions_on([0, 2]), {"pre": record("pre", day(-1))}, today_n=18)
check("post_final fires once the deadline passes even mid-protocol",
      fin_dead["surveys"]["post_final"] == "overdue")
check("post_final not due mid-protocol before the deadline",
      ev(sessions_on([0, 2, 4]), {"pre": record("pre", day(-1))},
         today_n=4)["surveys"]["post_final"] == "not_due")

waived = ev(sessions_on([0]), {"pre": record("pre", day(-1), status="waived")}, today_n=0)
check("a waived survey counts as satisfied", waived["surveys"]["pre"] == "waived")

# ---- recording is the admin's assertion; the store validates shape only
check("unknown survey point is rejected",
      store.upsert_survey_response("P01", "bogus")[1] is not None)
check("a malformed completion date is rejected",
      store.upsert_survey_response("P01", "pre", completed_on="08/01/2026")[1] is not None)
check("a rejected write leaves no row", store.list_survey_responses("P01") == [])


# ============================================================ 4. config (6)
check("defaults load with no file present",
      CFG["min_sessions"] == 5 and CFG["min_gap_days"] == 2 and CFG["window_days"] == 14)

saved, errs = st.save_config({"min_gap_days": 3,
                              "surveys": {"pre": {"url": "https://x.test/pre"}}},
                             actor="admin")
check("save persists and reloads", not errs and saved["min_gap_days"] == 3
      and st.load_config()["surveys"]["pre"]["url"] == "https://x.test/pre", errs)
check("saved file only stores the diff from defaults",
      set(json.load(open(st.config_path()))) <= {"min_gap_days", "surveys",
                                                 "updated_at", "updated_by"},
      json.load(open(st.config_path())))

for bad, why in (({"min_sessions": 0}, "min_sessions"),
                 ({"min_gap_days": -1}, "min_gap_days"),
                 ({"window_days": 0}, "window_days"),
                 ({"min_sessions": 5, "min_gap_days": 5, "window_days": 10}, "impossible"),
                 ({"nonsense": 1}, "unknown key")):
    _, errs = st.save_config(bad)
    check(f"rejects {why}", bool(errs), errs)
check("a rejected save does not corrupt the stored config",
      st.load_config()["min_gap_days"] == 3)

open(st.config_path(), "w").write("not json {")
check("corrupt config falls back to defaults",
      st.load_config()["min_gap_days"] == 2)
os.remove(st.config_path())

loose = st.load_config()
loose["min_gap_days"] = 1
relaxed = st.evaluate_participant(enrollment(), sessions_on([0, 1, 3, 5, 7]), {},
                                  loose, D0 + timedelta(days=8))
check("lowering min_gap_days actually reclassifies a participant",
      relaxed["gap_violations"] == [], relaxed["gap_violations"])


# =========================================================== 5. roll-up (4)
roll_db = os.path.join(WORK, "roll.db")
rs = user_store.UserStore(roll_db)
for uid in ("P01", "P02", "P03", "P04"):
    rs.register(uid, "pw1234")
    rs.upsert_enrollment(uid)
rs.upsert_enrollment("P01", start_on=day(0))          # never started -> action
rs.upsert_enrollment("P02", status="withdrawn")        # muted
rs.upsert_enrollment("P03", start_on="")               # no_start_date -> watch
rs.upsert_enrollment("P04", status="excluded")         # muted
ov = st.cohort_overview(rs, st.load_config(), D0 + timedelta(days=9))
c = ov["counts"]
check("cohort lists every enrolled participant", c["enrolled"] == 4)
check("severity counts cover all non-muted participants",
      c["action"] + c["watch"] + c["ok"] + c["done"] == 4 - c["muted"], c)
check("withdrawn and excluded are muted, not counted as attention",
      c["muted"] == 2 and c["action"] == 1 and c["watch"] == 1, c)
check("badge number is the action count",
      len([p for p in ov["participants"] if p["severity"] == "action"]) == c["action"])
check("not_started ignores muted participants", c["not_started"] == 2, c)
check("participant_detail returns sessions and records",
      set(st.participant_detail(rs, "P01", st.load_config(),
                                D0).keys()) >= {"sessions", "survey_records", "enrollment"})
check("participant_detail is None for a non-participant",
      st.participant_detail(rs, "nobody", st.load_config(), D0) is None)


# ============================================================ 6. schema (4)
check("_init_db is idempotent",
      user_store.UserStore(roll_db) is not None and len(rs.list_enrollments()) == 4)

with rs._connect() as conn:
    conn.execute("DROP TABLE study_survey_response")
    conn.execute("DROP TABLE study_enrollment")
    conn.commit()
rs2 = user_store.UserStore(roll_db)
check("dropped study tables are recreated without touching user data",
      rs2.list_enrollments() == [] and len(rs2.list_users()) == 4)

seed_path = user_store.DEFAULT_SEED_USERS_PATH
seed_db = user_store.UserStore(os.path.join(WORK, "seed.db"))
seed_db.ensure_admin_from_env()
seed_db.seed_users_from_file(seed_path)
n1 = seed_db.ensure_enrollment_from_seed(seed_path)
n2 = seed_db.ensure_enrollment_from_seed(seed_path)
seeded = json.load(open(seed_path, encoding="utf-8"))["users"]
check("enrolls exactly the seeded cohort, idempotently",
      n1 == len(seeded) and n2 == 0, f"{n1}/{n2} vs {len(seeded)}")
roster = {e["user_id"] for e in seed_db.list_enrollments()}
check("no admin lands in the roster",
      roster == {u["user_id"] for u in seeded}
      and not any(u["user_id"] in roster for u in seeded if u.get("is_admin")))

check("a status nobody can assert is rejected",
      seed_db.upsert_enrollment("P01", status="completed")[1] is not None)
seed_db.upsert_enrollment("P01", status="withdrawn", start_on=day(0))
seed_db.ensure_enrollment_from_seed(seed_path)
check("re-seeding never overwrites an admin's edits",
      seed_db.get_enrollment("P01")["status"] == "withdrawn")

seed_db.upsert_survey_response("P01", "pre", completed_on=day(0))
seed_db.ensure_admin_from_env()
with seed_db._connect() as conn:
    conn.execute("UPDATE users SET is_admin = 1 WHERE user_id = 'P32'")
    conn.commit()
seed_db.admin_delete_user("P01", "P32")
check("deleting a user leaves no ghost study rows",
      seed_db.get_enrollment("P01") is None
      and seed_db.list_survey_responses("P01") == [])

_ck.finish("ALL CHECKS PASSED — study tracker derives sessions and enforces the protocol")
