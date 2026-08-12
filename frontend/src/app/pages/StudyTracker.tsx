import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { authFetch } from "../auth";
import { monoFont } from "./chatConstants";

/**
 * Study compliance view for the admin panel.
 *
 * The table is meant to be readable with no legend and no prior knowledge: the
 * protocol is spelled out in words directly above the header, every status is a
 * word rather than a colour alone, and each row carries the reason it is flagged.
 * Colour is always a second channel, never the only one.
 *
 * Nothing here gates a participant. The tracker observes and highlights; whether
 * to chase, excuse, or exclude someone stays the researcher's call.
 */

export type SurveyState = "not_due" | "due" | "overdue" | "done" | "waived";
export type Severity = "ok" | "watch" | "action" | "done" | "muted";

export type StudyReason = { code: string; severity: string; text: string };

export type StudySurveyRecord = {
  point: string;
  status: string;
  completed_on: string;
  completed_at: string;
  recorded_by: string;
  note: string;
};

export type SurveyDetail = {
  point: string;
  label: string;
  url: string;
  state: SurveyState;
  due_since: string | null;
  record: StudySurveyRecord | null;
  anchor: {
    kind: string;
    session_index: number | null;
    day: string | null;
    provisional: boolean;
  } | null;
  deviations: StudyReason[];
};

export type StudySession = {
  index: number;
  day: string;
  user_turns: number;
  message_count: number;
  first_at: string;
  last_at: string;
  room_ids: string[];
  scenario_types: string[];
  notes: { code: string; text: string }[];
};

export type StudyParticipant = {
  user_id: string;
  cohort: string;
  status: string;
  note: string;
  severity: Severity;
  start_on: string | null;
  first_day: string | null;
  last_day: string | null;
  deadline_day: string | null;
  session_count: number;
  sessions_needed: number;
  user_turns_total: number;
  span_days: number | null;
  elapsed_days: number | null;
  window_days: number;
  days_left: number | null;
  days_since_last: number | null;
  next_ok_on: string | null;
  earliest_finish: string | null;
  feasible: boolean;
  gaps: number[];
  gap_violations: { from: string; to: string; days: number }[];
  window_exceeded: boolean;
  surveys: Record<string, SurveyState>;
  survey_detail: Record<string, SurveyDetail>;
  reasons: StudyReason[];
};

export type StudyConfig = {
  min_sessions: number;
  min_gap_days: number;
  window_days: number;
  study_start_on: string;
  timezone: string;
  surveys: Record<string, { label: string; url: string }>;
  [key: string]: unknown;
};

export type StudyOverview = {
  generated_at: string;
  today: string;
  config: StudyConfig;
  counts: Record<string, number>;
  warnings: { code: string; count: number; text: string }[];
  participants: StudyParticipant[];
};

type Detail = StudyParticipant & {
  enrollment: { cohort: string; status: string; start_on: string; note: string };
  sessions: StudySession[];
  survey_records: Record<string, StudySurveyRecord>;
  today: string;
};

type Mutate = (path: string, init: RequestInit, okMsg: string) => Promise<boolean>;

const POINTS = ["pre", "post_first", "mid", "post_final"] as const;
const POINT_HEADS: Record<string, string> = {
  pre: "PRE", post_first: "POST1", mid: "MID", post_final: "FINAL",
};
// Only what a human has to assert. Finishing the study is derived from the
// session count and the survey records, so there is no button for it.
const DROP_ACTIONS = [
  { status: "withdrawn", label: "Withdrew", verb: "Mark withdrawn",
    hint: "the participant chose to stop" },
  { status: "excluded", label: "Excluded", verb: "Exclude",
    hint: "you are removing their data from the study" },
] as const;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const NUMERIC_SETTINGS: { key: string; label: string; hint: string }[] = [
  { key: "min_sessions", label: "Sessions required", hint: "at least this many, no upper limit" },
  { key: "min_gap_days", label: "Minimum days apart", hint: "consecutive sessions closer than this are flagged" },
  { key: "window_days", label: "Window (days)", hint: "from the first session to the last" },
];

const TIMING_SETTINGS: { key: string; label: string }[] = [
  { key: "silent_start_grace_days", label: "Days of silence after the start date before flagging" },
  { key: "stall_grace_days", label: "Extra days past the minimum gap before calling it stalled" },
  { key: "post_first_grace_days", label: "Grace on the after-session-1 survey" },
  { key: "mid_grace_days", label: "Grace on the mid-study survey" },
  { key: "post_final_idle_days", label: "Idle days that mean a participant has finished" },
  { key: "post_final_grace_days", label: "Grace on the final survey after the deadline" },
];

/** "2026-08-11" -> "Aug 11", parsed by hand so no timezone can shift the day. */
function fmtDay(iso?: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}`;
}

function fmtTime(iso?: string | null): string {
  if (!iso) return "";
  return (iso.split("T")[1] || "").slice(0, 5);
}

function daysAgo(n: number | null): string {
  if (n === null || n === undefined) return "never";
  if (n === 0) return "today";
  if (n === 1) return "yesterday";
  return `${n} days ago`;
}

const SEVERITY_LABEL: Record<Severity, string> = {
  action: "ACTION", watch: "WATCH", ok: "OK", done: "DONE", muted: "CLOSED",
};

const SEVERITY_TEXT: Record<Severity, string> = {
  action: "text-red-600",
  watch: "text-black",
  ok: "text-[var(--app-muted-text)]",
  done: "text-black/50",
  muted: "text-black/40",
};

const SEVERITY_ROW: Record<Severity, string> = {
  action: "bg-red-50/60 border-l-2 border-red-400",
  watch: "border-l-2 border-black/20",
  ok: "border-l-2 border-transparent",
  done: "border-l-2 border-transparent",
  muted: "border-l-2 border-transparent opacity-40",
};

const SEVERITY_RANK: Record<Severity, number> = {
  action: 0, watch: 1, ok: 2, done: 3, muted: 4,
};

const SURVEY_LABEL: Record<SurveyState, string> = {
  overdue: "late", due: "due", done: "ok", waived: "n/a", not_due: "—",
};

const SURVEY_CLASS: Record<SurveyState, string> = {
  overdue: "text-red-600",
  due: "text-black",
  done: "text-black/45",
  waived: "text-black/45",
  not_due: "text-black/20",
};

export default function StudyTracker({
  overview, error, reload,
}: {
  overview: StudyOverview | null;
  error: string | null;
  reload: () => Promise<void>;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<"attention" | "id">("attention");
  const [showSettings, setShowSettings] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const loadDetail = useCallback(async (userId: string) => {
    setDetailError(null);
    try {
      const res = await authFetch(`/admin/study/participants/${encodeURIComponent(userId)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Failed to load participant");
      setDetail(data as Detail);
    } catch (e) {
      setDetail(null);
      setDetailError(e instanceof Error ? e.message : "Failed");
    }
  }, []);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    void loadDetail(selected);
  }, [selected, loadDetail]);

  // The detail panel sits under a 32-row table, so bring it into view when a new
  // participant is opened. Keyed on the id rather than the object, so refreshing
  // after a mutation does not yank the page while the admin is mid-form.
  const detailRef = useRef<HTMLDivElement | null>(null);
  const scrolledFor = useRef<string | null>(null);
  useEffect(() => {
    const uid = detail?.user_id;
    if (!uid) { scrolledFor.current = null; return; }
    if (scrolledFor.current === uid) return;
    scrolledFor.current = uid;
    // Instant, not smooth: smooth scrolling silently no-ops in throttled or
    // reduced-motion contexts, and a jump that sometimes does nothing is worse
    // than one that always lands.
    detailRef.current?.scrollIntoView({ block: "start" });
  }, [detail?.user_id]);

  const participants = useMemo(() => {
    const list = [...(overview?.participants || [])];
    list.sort((a, b) =>
      sortBy === "id"
        ? a.user_id.localeCompare(b.user_id)
        : (SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity])
          || a.user_id.localeCompare(b.user_id));
    return list;
  }, [overview, sortBy]);

  const cfg = overview?.config;
  const counts = overview?.counts || {};
  const today = overview?.today || "";

  /** Run a mutation, then refresh both the open row and the badge count. */
  const mutate = useCallback<Mutate>(async (path, init, okMsg) => {
    setBusy(true);
    setActionMsg(null);
    try {
      const res = await authFetch(path, init);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionMsg(data.error || "Failed");
        return false;
      }
      setActionMsg(okMsg);
      if (selected) await loadDetail(selected);
      await reload();
      return true;
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : "Failed");
      return false;
    } finally {
      setBusy(false);
    }
  }, [selected, loadDetail, reload]);

  return (
    <div className="max-w-[1400px] mx-auto p-4 flex flex-col gap-3">
      {/* The protocol, in words. Without this, "3 / 5" means nothing until you
          remember what 5 was — this line is what lets the table skip a legend. */}
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-3 flex-wrap">
          <p className="text-[13px] text-black" style={monoFont}>
            {cfg
              ? `${cfg.min_sessions} sessions · at least ${cfg.min_gap_days} days apart · within ${cfg.window_days} days`
              : "Loading the protocol…"}
          </p>
          {overview && (
            <p className="text-[11px] text-[var(--app-muted-text)]" style={monoFont}>
              {counts.enrolled} enrolled · {counts.action || 0} need action ·{" "}
              {counts.watch || 0} to watch · today is {fmtDay(today)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-stretch border border-black/10 rounded-[8px] overflow-hidden">
            {(["attention", "id"] as const).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setSortBy(k)}
                className={`h-[26px] px-2.5 text-[10px] ${
                  sortBy === k ? "bg-black text-white" : "text-black/60 hover:bg-black/[0.05]"
                }`}
                style={monoFont}
              >
                {k === "attention" ? "Sort: attention" : "Sort: ID"}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setShowSettings((v) => !v)}
            className="h-[26px] px-2.5 border border-black/15 rounded-[8px] text-[10px] text-black/70 hover:bg-black/[0.03]"
            style={monoFont}
          >
            {showSettings ? "Hide settings" : "Settings"}
          </button>
          <button
            type="button"
            onClick={() => void reload()}
            className="h-[26px] px-2.5 border border-black/15 rounded-[8px] text-[10px] text-black/70 hover:bg-black/[0.03]"
            style={monoFont}
          >
            Refresh
          </button>
        </div>
      </div>

      {error && <p className="text-[12px] text-red-600" style={monoFont}>{error}</p>}
      {(overview?.warnings || []).map((w) => (
        <p key={w.code} className="text-[11px] text-black/55" style={monoFont}>⚠ {w.text}</p>
      ))}
      {actionMsg && (
        <p className="text-[11px] text-black/70" style={monoFont}>{actionMsg}</p>
      )}

      {showSettings && cfg && <SettingsPanel config={cfg} busy={busy} onMutate={mutate} />}

      <section className="border border-black/10 rounded-[12px] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[11px]" style={monoFont}>
            <thead>
              <tr className="bg-black/[0.03] text-black/55 text-left">
                <th className="font-normal px-3 py-2">PARTICIPANT</th>
                <th className="font-normal px-2 py-2">STATUS</th>
                <th className="font-normal px-2 py-2">SESSIONS</th>
                <th className="font-normal px-2 py-2">ELAPSED</th>
                <th className="font-normal px-2 py-2">LAST SEEN</th>
                <th className="font-normal px-2 py-2">NEXT OK</th>
                <th className="font-normal px-2 py-2">GAPS</th>
                {POINTS.map((p) => (
                  <th key={p} className="font-normal px-2 py-2 text-center">{POINT_HEADS[p]}</th>
                ))}
                <th className="font-normal px-2 py-2">WHY</th>
              </tr>
            </thead>
            <tbody>
              {!overview && (
                <tr><td colSpan={12} className="px-3 py-4 text-[var(--app-muted-text)]">
                  Loading…
                </td></tr>
              )}
              {overview && participants.length === 0 && (
                <tr><td colSpan={12} className="px-3 py-4 text-[var(--app-muted-text)]">
                  No participants enrolled yet.
                </td></tr>
              )}
              {participants.map((p) => (
                <ParticipantRow
                  key={p.user_id}
                  p={p}
                  today={today}
                  minGap={cfg?.min_gap_days ?? 0}
                  selected={selected === p.user_id}
                  onSelect={() => setSelected(selected === p.user_id ? null : p.user_id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selected && detailError && (
        <p className="text-[12px] text-red-600" style={monoFont}>{detailError}</p>
      )}
      <div ref={detailRef}>
        {selected && detail && (
          <DetailPanel
            detail={detail}
            busy={busy}
            onClose={() => setSelected(null)}
            onMutate={mutate}
          />
        )}
      </div>
    </div>
  );
}

function ParticipantRow({
  p, today, minGap, selected, onSelect,
}: {
  p: StudyParticipant;
  today: string;
  minGap: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const target = p.session_count + p.sessions_needed;
  const why = p.reasons[0];
  const nextOk = p.next_ok_on
    ? (p.next_ok_on <= today ? "today" : fmtDay(p.next_ok_on))
    : "—";
  return (
    <tr
      onClick={onSelect}
      className={`border-t border-black/5 cursor-pointer hover:bg-black/[0.03] ${
        SEVERITY_ROW[p.severity]
      } ${selected ? "bg-black/[0.06]" : ""}`}
    >
      <td className="px-3 py-2 whitespace-nowrap">
        {p.user_id}
        {/* A real space, not just a margin — otherwise copied text reads "P03river". */}
        {p.cohort && <span className="text-black/40">{" "}{p.cohort}</span>}
      </td>
      <td className={`px-2 py-2 whitespace-nowrap ${SEVERITY_TEXT[p.severity]}`}>
        {p.severity === "muted" ? p.status.toUpperCase() : SEVERITY_LABEL[p.severity]}
      </td>
      <td className="px-2 py-2 whitespace-nowrap">{p.session_count} / {target}</td>
      <td className="px-2 py-2 whitespace-nowrap text-black/60">
        {p.elapsed_days === null ? "—" : `${p.elapsed_days} / ${p.window_days} d`}
      </td>
      <td className="px-2 py-2 whitespace-nowrap text-black/60">{daysAgo(p.days_since_last)}</td>
      <td className="px-2 py-2 whitespace-nowrap text-black/60">{nextOk}</td>
      <td className="px-2 py-2 whitespace-nowrap">
        {p.gaps.length === 0
          ? <span className="text-black/25">—</span>
          : p.gaps.map((g, i) => (
              <React.Fragment key={i}>
                {i > 0 && <span className="text-black/25">, </span>}
                <span className={g < minGap ? "text-red-600" : undefined}>
                  {g}{g < minGap ? "!" : ""}
                </span>
              </React.Fragment>
            ))}
      </td>
      {POINTS.map((pt) => {
        const s = (p.surveys[pt] || "not_due") as SurveyState;
        return (
          <td key={pt} className={`px-2 py-2 text-center ${SURVEY_CLASS[s]}`}>
            {SURVEY_LABEL[s]}
          </td>
        );
      })}
      <td className="px-2 py-2 text-black/70 max-w-[300px]">
        <span className="block truncate" title={p.reasons.map((r) => r.text).join(" · ")}>
          {why ? why.text : ""}
        </span>
      </td>
    </tr>
  );
}

function DetailPanel({
  detail, busy, onClose, onMutate,
}: { detail: Detail; busy: boolean; onClose: () => void; onMutate: Mutate }) {
  const base = `/admin/study/participants/${encodeURIComponent(detail.user_id)}`;
  return (
    <section className="border border-black/10 rounded-[12px] overflow-hidden">
      <div className="px-3 py-2 border-b border-black/8 flex items-center justify-between bg-black/[0.015]">
        <p className="text-[12px] text-black" style={monoFont}>
          {detail.user_id}{" "}
          <span className={SEVERITY_TEXT[detail.severity]}>
            {detail.severity === "muted"
              ? detail.status.toUpperCase()
              : SEVERITY_LABEL[detail.severity]}
          </span>
        </p>
        <button
          type="button"
          onClick={onClose}
          className="text-[11px] text-black/50 hover:text-black"
          style={monoFont}
        >
          Close
        </button>
      </div>

      <div className="p-3 flex flex-col gap-4">
        {detail.reasons.length > 0 && (
          <ul className="flex flex-col gap-1">
            {detail.reasons.map((r, i) => (
              <li
                key={i}
                className={`text-[11px] ${
                  r.severity === "action" ? "text-red-600" : "text-black/70"
                }`}
                style={monoFont}
              >
                • {r.text}
              </li>
            ))}
          </ul>
        )}

        <EnrollmentForm detail={detail} busy={busy} base={base} onMutate={onMutate} />

        <div>
          <p className="text-[10px] text-[var(--app-muted-text)] mb-1.5" style={monoFont}>
            Sessions ({detail.sessions.length})
            {detail.deadline_day && ` · window closes ${fmtDay(detail.deadline_day)}`}
            {detail.user_turns_total > 0 && ` · ${detail.user_turns_total} turns total`}
          </p>
          <SessionList sessions={detail.sessions} violations={detail.gap_violations} />
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>Surveys</p>
          {POINTS.map((pt) => (
            <SurveyBlock
              key={pt}
              info={detail.survey_detail[pt]}
              today={detail.today}
              busy={busy}
              base={base}
              onMutate={onMutate}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function EnrollmentForm({
  detail, busy, base, onMutate,
}: { detail: Detail; busy: boolean; base: string; onMutate: Mutate }) {
  const [startOn, setStartOn] = useState(detail.enrollment.start_on);
  const [cohort, setCohort] = useState(detail.enrollment.cohort);
  const [note, setNote] = useState(detail.enrollment.note);

  useEffect(() => {
    setStartOn(detail.enrollment.start_on);
    setCohort(detail.enrollment.cohort);
    setNote(detail.enrollment.note);
  }, [detail.user_id, detail.enrollment]);

  const dirty =
    startOn !== detail.enrollment.start_on ||
    cohort !== detail.enrollment.cohort ||
    note !== detail.enrollment.note;

  const save = () =>
    void onMutate(
      `${base}/enrollment`,
      { method: "POST", body: JSON.stringify({ start_on: startOn, cohort, note }) },
      `Saved ${detail.user_id}`,
    );

  const setStatus = (next: string, okMsg: string) =>
    void onMutate(
      `${base}/enrollment`,
      { method: "POST", body: JSON.stringify({ status: next }) },
      okMsg,
    );

  const dropped = detail.status === "withdrawn" || detail.status === "excluded";

  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col gap-1">
        <span className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>
          Start date
        </span>
        <input
          type="date"
          value={startOn}
          onChange={(e) => setStartOn(e.target.value)}
          className="h-[32px] px-2 border border-black/15 rounded-[8px] text-[11px] outline-none"
          style={monoFont}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>Cohort</span>
        <input
          type="text"
          value={cohort}
          onChange={(e) => setCohort(e.target.value)}
          placeholder="condition"
          className="h-[32px] w-[110px] px-2 border border-black/15 rounded-[8px] text-[11px] outline-none"
          style={monoFont}
        />
      </label>
      <label className="flex flex-col gap-1 flex-1 min-w-[180px]">
        <span className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>Note</span>
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className="h-[32px] px-2 border border-black/15 rounded-[8px] text-[11px] outline-none"
          style={monoFont}
        />
      </label>
      <button
        type="button"
        disabled={busy || !dirty}
        onClick={save}
        className="h-[32px] px-3 bg-black text-white rounded-[8px] text-[11px] hover:bg-neutral-800 disabled:opacity-40"
        style={monoFont}
      >
        Save
      </button>

      {/* The only thing here a human has to assert. Whether someone finished is
          read off their sessions and surveys; whether they dropped out is not
          visible in any data, so it stays a deliberate click. */}
      <div className="flex items-center gap-2 ml-auto">
        {dropped ? (
          <>
            <span className="text-[10px] text-black/50" style={monoFont}>
              {detail.status === "withdrawn" ? "Withdrew" : "Excluded"} — not counted
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => setStatus("active", `${detail.user_id} is back in the study`)}
              className="h-[32px] px-3 border border-black/15 rounded-[8px] text-[11px] text-black/70 hover:bg-black/[0.03] disabled:opacity-40"
              style={monoFont}
            >
              Put back in the study
            </button>
          </>
        ) : (
          DROP_ACTIONS.map((a) => (
            <button
              key={a.status}
              type="button"
              disabled={busy}
              title={a.hint}
              onClick={() => {
                if (!window.confirm(
                  `${a.verb}: ${detail.user_id} drops out of every count and off the `
                  + `attention badge. You can undo this.`)) return;
                setStatus(a.status, `${detail.user_id}: ${a.label.toLowerCase()}`);
              }}
              className="h-[32px] px-3 border border-red-200 text-red-600 rounded-[8px] text-[11px] hover:bg-red-50 disabled:opacity-40"
              style={monoFont}
            >
              {a.verb}
            </button>
          ))
        )}
      </div>
    </div>
  );
}

function SessionList({
  sessions, violations,
}: {
  sessions: StudySession[];
  violations: { from: string; to: string; days: number }[];
}) {
  if (sessions.length === 0) {
    return (
      <p className="text-[11px] text-[var(--app-muted-text)]" style={monoFont}>
        No sessions recorded yet.
      </p>
    );
  }
  const bad = new Set(violations.map((v) => `${v.from}->${v.to}`));
  return (
    <div className="border border-black/8 rounded-[8px] divide-y divide-black/5">
      {sessions.map((s, i) => {
        const prev = i > 0 ? sessions[i - 1] : null;
        const gapDays = prev
          ? Math.round(
              (Date.parse(`${s.day}T00:00:00Z`) - Date.parse(`${prev.day}T00:00:00Z`))
              / 86400000)
          : null;
        const violating = prev ? bad.has(`${prev.day}->${s.day}`) : false;
        return (
          <React.Fragment key={s.day}>
            {prev && (
              /* The gap is rendered between the rows it describes — that is what
                 makes the rhythm rule visible rather than something you compute. */
              <div
                className={`px-3 py-1 text-[10px] ${
                  violating ? "text-red-600 bg-red-50/50" : "text-black/40"
                }`}
                style={monoFont}
              >
                ↕ {gapDays} {gapDays === 1 ? "day" : "days"}
                {violating && " — closer than the protocol allows"}
              </div>
            )}
            <div className="px-3 py-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-[11px] text-black/40 w-[24px]" style={monoFont}>
                #{s.index}
              </span>
              <span className="text-[11px] text-black" style={monoFont}>{s.day}</span>
              <span className="text-[11px] text-black/55" style={monoFont}>
                {fmtTime(s.first_at)}–{fmtTime(s.last_at)}
              </span>
              <span className="text-[11px] text-black/70" style={monoFont}>
                {s.user_turns} turns / {s.message_count} msgs
              </span>
              <span className="text-[10px] text-black/40" style={monoFont}>
                {s.room_ids.length === 1 ? "room" : "rooms"} {s.room_ids.join(", ")}
              </span>
              {s.notes.map((n) => (
                <span key={n.code} className="text-[10px] text-black/45" style={monoFont}>
                  · {n.text}
                </span>
              ))}
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

function SurveyBlock({
  info, today, busy, base, onMutate,
}: {
  info?: SurveyDetail;
  today: string;
  busy: boolean;
  base: string;
  onMutate: Mutate;
}) {
  const [completedOn, setCompletedOn] = useState(today);
  const [note, setNote] = useState("");

  useEffect(() => { setCompletedOn(today); }, [today]);

  if (!info) return null;
  const done = info.state === "done" || info.state === "waived";
  const path = `${base}/surveys/${info.point}`;

  const record = () =>
    void onMutate(
      path,
      { method: "POST", body: JSON.stringify({ note, completed_on: completedOn }) },
      `Recorded ${info.label}`,
    ).then(() => { setNote(""); });

  const undo = () => {
    if (!window.confirm(`Remove the recorded ${info.label} survey?`)) return;
    void onMutate(path, { method: "DELETE" }, `Cleared ${info.label}`);
  };

  return (
    <div className="border border-black/8 rounded-[8px] p-2.5 flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[11px] text-black w-[110px]" style={monoFont}>{info.label}</span>
        <span className={`text-[11px] ${SURVEY_CLASS[info.state]}`} style={monoFont}>
          {info.state === "not_due" ? "not due yet"
            : info.state === "done" ? "recorded"
            : info.state === "waived" ? "waived"
            : info.state === "due" ? `due since ${fmtDay(info.due_since)}`
            : `overdue since ${fmtDay(info.due_since)}`}
        </span>
        {info.url && (
          <a
            href={info.url}
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-black/50 underline hover:text-black"
            style={monoFont}
          >
            open form
          </a>
        )}
        {info.anchor?.day && (
          <span className="text-[10px] text-black/40" style={monoFont}>
            {info.anchor.kind === "before_first_session" ? "belongs before" : "belongs after"}
            {" "}session #{info.anchor.session_index} ({fmtDay(info.anchor.day)})
            {/* Provisional because the last session — and so the midpoint — can
                still move while the participant is active. */}
            {info.anchor.provisional && " — provisional"}
          </span>
        )}
      </div>

      {info.deviations.map((d) => (
        <p key={d.code} className="text-[10px] text-red-600" style={monoFont}>⚠ {d.text}</p>
      ))}

      {done && info.record ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] text-black/55" style={monoFont}>
            {info.record.completed_on}
            {info.record.recorded_by && ` · recorded by ${info.record.recorded_by}`}
            {info.record.note && ` · ${info.record.note}`}
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={undo}
            className="h-[26px] px-2 border border-red-200 text-red-600 rounded-[6px] text-[10px] hover:bg-red-50 disabled:opacity-40"
            style={monoFont}
          >
            Undo
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-[10px] text-black/55" style={monoFont}>
            completed on
            <input
              type="date"
              value={completedOn}
              onChange={(e) => setCompletedOn(e.target.value)}
              className="h-[30px] px-1.5 border border-black/15 rounded-[6px] text-[11px] outline-none"
              style={monoFont}
            />
          </label>
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="note (optional) — e.g. Qualtrics response #482"
            className="h-[30px] flex-1 min-w-[220px] px-2 border border-black/15 rounded-[6px] text-[11px] outline-none"
            style={monoFont}
          />
          <button
            type="button"
            disabled={busy}
            onClick={record}
            className="h-[30px] px-3 bg-black text-white rounded-[6px] text-[11px] hover:bg-neutral-800 disabled:opacity-40"
            style={monoFont}
          >
            Mark done
          </button>
        </div>
      )}
    </div>
  );
}

function SettingsPanel({
  config, busy, onMutate,
}: { config: StudyConfig; busy: boolean; onMutate: Mutate }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [startOn, setStartOn] = useState("");
  const [surveys, setSurveys] = useState<Record<string, { label: string; url: string }>>({});
  const [showTiming, setShowTiming] = useState(false);

  useEffect(() => {
    const nums: Record<string, string> = {};
    for (const { key } of [...NUMERIC_SETTINGS, ...TIMING_SETTINGS]) {
      nums[key] = String(config[key] ?? "");
    }
    setDraft(nums);
    setStartOn(String(config.study_start_on ?? ""));
    const sv: Record<string, { label: string; url: string }> = {};
    for (const p of POINTS) {
      sv[p] = {
        label: config.surveys?.[p]?.label || "",
        url: config.surveys?.[p]?.url || "",
      };
    }
    setSurveys(sv);
  }, [config]);

  const save = () => {
    if (!window.confirm(
      "Changing these re-evaluates every participant against the new rules. Continue?")) return;
    const payload: Record<string, unknown> = { surveys, study_start_on: startOn };
    for (const [k, v] of Object.entries(draft)) {
      if (v.trim() !== "") payload[k] = Number(v);
    }
    void onMutate("/admin/study/config", {
      method: "POST", body: JSON.stringify(payload),
    }, "Settings saved");
  };

  return (
    <section className="border border-black/10 rounded-[12px] p-3 flex flex-col gap-3 bg-black/[0.015]">
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] text-black/70" style={monoFont}>Study start date</span>
          <input
            type="date"
            value={startOn}
            onChange={(e) => setStartOn(e.target.value)}
            className="h-[32px] px-2 border border-black/15 rounded-[8px] text-[11px] outline-none"
            style={monoFont}
          />
          <span className="text-[9px] text-black/40 max-w-[200px]" style={monoFont}>
            when the study opens for everyone; a late joiner overrides it on their own row
          </span>
        </label>
        {NUMERIC_SETTINGS.map(({ key, label, hint }) => (
          <label key={key} className="flex flex-col gap-1">
            <span className="text-[10px] text-black/70" style={monoFont}>{label}</span>
            <input
              type="number"
              min={0}
              value={draft[key] ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
              className="h-[32px] w-[90px] px-2 border border-black/15 rounded-[8px] text-[11px] outline-none"
              style={monoFont}
            />
            <span className="text-[9px] text-black/40 max-w-[200px]" style={monoFont}>{hint}</span>
          </label>
        ))}
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-[10px] text-[var(--app-muted-text)]" style={monoFont}>
          Surveys — the external form each point links to
        </p>
        {POINTS.map((p) => (
          <div key={p} className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] text-black/50 w-[52px]" style={monoFont}>
              {POINT_HEADS[p]}
            </span>
            <input
              type="text"
              value={surveys[p]?.label ?? ""}
              onChange={(e) => setSurveys((s) => ({ ...s, [p]: { ...s[p], label: e.target.value } }))}
              placeholder="label"
              className="h-[30px] w-[130px] px-2 border border-black/15 rounded-[6px] text-[11px] outline-none"
              style={monoFont}
            />
            <input
              type="text"
              value={surveys[p]?.url ?? ""}
              onChange={(e) => setSurveys((s) => ({ ...s, [p]: { ...s[p], url: e.target.value } }))}
              placeholder="https://…"
              className="h-[30px] flex-1 min-w-[200px] px-2 border border-black/15 rounded-[6px] text-[11px] outline-none"
              style={monoFont}
            />
          </div>
        ))}
      </div>

      <div>
        <button
          type="button"
          onClick={() => setShowTiming((v) => !v)}
          className="text-[10px] text-black/50 hover:text-black underline"
          style={monoFont}
        >
          {showTiming ? "Hide timing details" : "Timing details"}
        </button>
        {showTiming && (
          <div className="mt-2 flex flex-col gap-1.5">
            {TIMING_SETTINGS.map(({ key, label }) => (
              <label key={key} className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  value={draft[key] ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                  className="h-[28px] w-[64px] px-2 border border-black/15 rounded-[6px] text-[11px] outline-none"
                  style={monoFont}
                />
                <span className="text-[10px] text-black/60" style={monoFont}>{label}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div>
        <button
          type="button"
          disabled={busy}
          onClick={save}
          className="h-[32px] px-3 bg-black text-white rounded-[8px] text-[11px] hover:bg-neutral-800 disabled:opacity-40"
          style={monoFont}
        >
          Save settings
        </button>
      </div>
    </section>
  );
}
