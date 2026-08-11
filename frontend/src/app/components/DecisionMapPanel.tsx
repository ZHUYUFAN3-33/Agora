import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { getUiFont, labelCaseClass, phaseLabel, t, userLabel, type UiLang } from "../i18n/ui";
import {
  DecisionMapCanvas,
  MAX_ZOOM,
  MIN_ZOOM,
} from "./DecisionMapCanvas";
import { ReplyGraph, type FactLayer } from "./ReplyGraph";
import {
  DecisionRiver,
  RiverKeyStrip,
  RiverVerdictBanner,
  type RiverData,
  type RiverTurn,
} from "./DecisionRiver";
import { OptionLedger } from "./OptionLedger";

export type DecisionMapIssue = {
  id: string;
  label: string;
  parent_id?: string | null;
  status: "open" | "leaning" | "settled" | string;
  winning_claim_id?: string | null;
  winning_option_id?: string | null;
  phase?: string | null;
  summary?: string | null;
};

export type DecisionMapClaim = {
  id: string;
  issue_id: string;
  speaker: string;
  text: string;
  badge?: string | null;
  message_indexes: number[];
};

export type DecisionMapOption = {
  id: string;
  issue_id: string;
  label: string;
  summary?: string | null;
  proposed_by?: string | null;
  status?: "open" | "leaning" | "chosen" | "rejected" | string;
  message_indexes?: number[];
  choice_group_id?: string | null;
};

export type DecisionMapEdge = {
  id: string;
  type: "emerged_from" | "supports" | "opposes" | "chooses" | string;
  from: string;
  to: string;
};

export type DecisionMapAnnotation = {
  id: string;
  text: string;
  kind: "system" | "user" | "layer" | string;
  target_id?: string | null;
  message_indexes?: number[];
};

export type DecisionMapPhaseSpine = {
  from?: string;
  to?: string;
  time?: string;
  message_index?: number | null;
};

export type DecisionMapData = {
  room_id: string;
  lang: string;
  issues: DecisionMapIssue[];
  claims: DecisionMapClaim[];
  options?: DecisionMapOption[];
  edges: DecisionMapEdge[];
  annotations: DecisionMapAnnotation[];
  phase_spine: DecisionMapPhaseSpine[];
  room_leaning?: { direction?: string; strength?: string } | null;
  agents?: { key?: string; name?: string; stance?: string | null }[];
  extracted?: boolean;
  insufficient?: boolean;
  counts?: { user?: number; agent?: number; total?: number };
  /**
   * Deterministic reply graph from map_facts.py — turns and the [MOVE]-derived
   * edges between them. Separate from `edges` above, which is the LLM's IBIS
   * claim graph. Absent on older responses.
   */
  facts?: FactLayer | null;
  /**
   * The river payload (map_river.py): time-ordered turns with per-turn
   * summaries, reply edges, option milestones and the verdict. When present,
   * the panel renders DecisionRiver as the main view; the legacy IBIS canvas
   * + ReplyGraph strip remain only as the fallback for old responses.
   */
  river?: RiverData | null;
  /** @deprecated legacy */
  topics?: unknown[];
  stances?: unknown[];
  conclusions?: unknown[];
};

/**
 * The two footer rows — the key and the hint — share one class so they cannot
 * drift apart. Both are chrome, so both are set at the same 10px; equal padding
 * plus a min-height makes them the same height by construction rather than by
 * two paddings that happen to agree today.
 */
const FOOTER_ROW = "px-4 sm:px-5 py-2 min-h-[34px] flex items-center";

export function DecisionMapPanel({
  open,
  onClose,
  data,
  loading,
  error,
  lang = "en",
  selectedTopicId,
  onSelectTopic,
  onJumpIndexes,
  onRefresh,
  onExtract,
  extracting = false,
  userName,
  docked = false,
  onUndock,
}: {
  open: boolean;
  onClose: () => void;
  data: DecisionMapData | null;
  loading?: boolean;
  error?: string | null;
  lang?: UiLang;
  selectedTopicId?: string | null;
  onSelectTopic: (topicId: string | null) => void;
  onJumpIndexes: (indexes: number[]) => void;
  onRefresh: () => void;
  onExtract?: () => void;
  extracting?: boolean;
  /** The reader's account id, shown instead of a generic "you". */
  userName?: string;
  /** Docked: the map collapses to a floating "back to map" pill while the
   * user reads evidence in the chat. The panel stays mounted so selection,
   * zoom and pan survive the round trip. */
  docked?: boolean;
  onUndock?: () => void;
}) {
  const font = getUiFont(lang);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 40, y: 40 });
  const [enterReady, setEnterReady] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [fitNonce, setFitNonce] = useState(0);
  const canvasHostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      setEnterReady(false);
      setSelectedNodeId(null);
      setViewPref(null);
      return;
    }
    const t = window.setTimeout(() => setEnterReady(true), 40);
    return () => window.clearTimeout(t);
  }, [open]);

  useEffect(() => {
    if (selectedTopicId) {
      setSelectedNodeId((prev) => prev || selectedTopicId);
    }
  }, [selectedTopicId]);

  const river = useMemo(
    () => (data?.river && (data.river.turns?.length || 0) > 0 ? data.river : null),
    [data?.river],
  );
  // The ledger answers "what were my options and what was said about each" with
  // no diagram literacy at all, so it is what the map opens on. The river is
  // the drill-down for when the reader doubts a line.
  const hasLedger = (river?.ledger?.length || 0) > 0;
  // Derived, not sticky: the ledger arrives with the payload, so a stored
  // default set before the fetch resolves would strand the reader on the river.
  const [viewPref, setViewPref] = useState<"ledger" | "river" | null>(null);
  const view: "ledger" | "river" = hasLedger ? viewPref ?? "ledger" : "river";
  const setView = setViewPref;
  const selectedTurn = useMemo<RiverTurn | null>(
    () => river?.turns.find((x) => x.id === selectedNodeId) || null,
    [river, selectedNodeId],
  );
  const selectedIssue = useMemo(
    () => data?.issues?.find((x) => x.id === selectedNodeId) || null,
    [data, selectedNodeId],
  );
  const selectedClaim = useMemo(
    () => data?.claims?.find((x) => x.id === selectedNodeId) || null,
    [data, selectedNodeId],
  );
  const selectedOption = useMemo(
    () => data?.options?.find((x) => x.id === selectedNodeId) || null,
    [data, selectedNodeId],
  );

  const claimById = useMemo(() => {
    const m = new Map<string, DecisionMapClaim>();
    (data?.claims || []).forEach((c) => m.set(c.id, c));
    return m;
  }, [data?.claims]);

  const issueClaims = useMemo(() => {
    if (!selectedIssue) return [];
    return (data?.claims || []).filter((c) => c.issue_id === selectedIssue.id);
  }, [data?.claims, selectedIssue]);

  const claimLinks = useMemo(() => {
    if (!selectedClaim) {
      return { supports: [] as DecisionMapClaim[], opposes: [] as DecisionMapClaim[], supportedBy: [] as DecisionMapClaim[], opposedBy: [] as DecisionMapClaim[] };
    }
    const edges = data?.edges || [];
    const pick = (ids: string[]) =>
      ids.map((id) => claimById.get(id)).filter(Boolean) as DecisionMapClaim[];
    return {
      supports: pick(edges.filter((e) => e.type === "supports" && e.from === selectedClaim.id).map((e) => e.to)),
      opposes: pick(edges.filter((e) => e.type === "opposes" && e.from === selectedClaim.id).map((e) => e.to)),
      supportedBy: pick(edges.filter((e) => e.type === "supports" && e.to === selectedClaim.id).map((e) => e.from)),
      opposedBy: pick(edges.filter((e) => e.type === "opposes" && e.to === selectedClaim.id).map((e) => e.from)),
    };
  }, [data?.edges, selectedClaim, claimById]);

  const parentIssue = useMemo(() => {
    const child = selectedClaim || selectedOption;
    if (!child) return null;
    return data?.issues?.find((i) => i.id === child.issue_id) || null;
  }, [data?.issues, selectedClaim, selectedOption]);

  const winningClaim = useMemo(() => {
    if (!selectedIssue?.winning_claim_id) return null;
    return claimById.get(selectedIssue.winning_claim_id) || null;
  }, [selectedIssue, claimById]);

  const zoomPct = Math.round(zoom * 100);
  const insufficient = !!data?.insufficient;
  const busy = !!(loading || extracting);

  const bumpZoom = (dir: 1 | -1) => {
    if (view !== "river") return;
    const host = canvasHostRef.current;
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * (dir > 0 ? 1.12 : 1 / 1.12)));
    if (!host) {
      setZoom(next);
      return;
    }
    const rect = host.getBoundingClientRect();
    const mx = rect.width / 2;
    const my = rect.height / 2;
    const scale = next / zoom;
    setZoom(next);
    setPan({
      x: mx - (mx - pan.x) * scale,
      y: my - (my - pan.y) * scale,
    });
  };

  const leaning = data?.room_leaning;
  // Last line of defence against the model echoing its own prompt schema. The
  // backend guard catches these too, but this is the string that renders under
  // the word CONCLUSION — the most authoritative line in the panel — so it does
  // not get to fail open.
  const leaningDirection = useMemo(() => {
    const d = (leaning?.direction || "").trim();
    if (!d) return "";
    const bare = d.replace(/["'`。.\s]/g, "").toLowerCase();
    const junk = new Set([
      "empty", "none", "null", "na", "tbd", "unknown",
      "clear", "leaning", "undecided", "direction", "roomleaning",
      "无", "空", "未知", "なし", "不明",
    ]);
    return junk.has(bare) ? "" : d;
  }, [leaning?.direction]);
  // Strength arrives as a bare enum token; translate it or drop it.
  const leaningStrength = useMemo(() => {
    const s = (leaning?.strength || "").trim();
    if (!s) return "";
    const key = `map.strength.${s.toLowerCase()}`;
    const localized = t(lang, key);
    return localized === key ? (/^[a-z]+$/i.test(s) ? "" : s) : localized;
  }, [leaning?.strength, lang]);

  return (
    <>
    <AnimatePresence>
      {open && !docked && (
        <div className="fixed inset-0 z-[200]" style={font}>
          <motion.button
            type="button"
            aria-label={t(lang, "map.close")}
            className="absolute inset-0 bg-black/20"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={t(lang, "map.title")}
            className="absolute inset-0 flex flex-col bg-[#f7f7f5] shadow-[0_12px_40px_rgba(0,0,0,0.12)]"
            initial={{ y: "-8%", opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: "-6%", opacity: 0 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-center justify-between gap-3 px-4 sm:px-5 h-14 border-b border-black/8 bg-white/90 backdrop-blur-sm flex-shrink-0">
              <div className="min-w-0 flex items-center gap-3">
                <div className="min-w-0">
                  <p className={`text-[12px] text-black ${labelCaseClass(lang)}`}>{t(lang, "map.title")}</p>
                  <p className="text-[10px] text-[var(--app-muted-text)] truncate hidden sm:block">
                    {busy
                      ? t(lang, "map.extracting")
                      : t(lang, view === "ledger" ? "map.subtitleLedger" : "map.subtitleSmart")}
                  </p>
                </div>

                {/* The two views sit in the title bar rather than on a rule of
                    their own: a third full-width horizontal divider directly
                    under two others read as a stripe, not as structure. */}
                {hasLedger && !insufficient && (
                  <div className="flex items-center gap-0.5 ml-1 p-0.5 rounded-[7px] bg-black/[0.05] flex-shrink-0">
                    {(["ledger", "river"] as const).map((v) => (
                      <button
                        key={v}
                        type="button"
                        onClick={() => setView(v)}
                        className={`px-2.5 py-1 rounded-[5px] text-[11px] transition-colors ${
                          view === v
                            ? "bg-white text-black shadow-[0_1px_2px_rgba(0,0,0,0.10)]"
                            : "text-black/55 hover:text-black/80"
                        }`}
                      >
                        {t(lang, v === "ledger" ? "map.view.ledger" : "map.view.river")}
                      </button>
                    ))}
                  </div>
                )}

                {/* Clicking a phase chip jumps into the chat, which collapses
                    the whole map — surprising on the ledger, where it reads as
                    a status badge rather than a control. Hidden below lg now
                    that the view switch shares this row. */}
                {view === "river" && (data?.phase_spine?.length || 0) > 0 && (
                  <div className="hidden lg:flex items-center gap-1 ml-2 pl-2 border-l border-black/8">
                    {data!.phase_spine.slice(0, 5).map((p, i) => (
                      <button
                        key={`phase-${p.to}-${i}`}
                        type="button"
                        onClick={() => p.message_index != null && onJumpIndexes([p.message_index])}
                        className="px-1.5 py-0.5 rounded-[4px] bg-black/[0.04] text-[10px] text-black/65 hover:bg-black/[0.07]"
                      >
                        {phaseLabel(lang, p.to || "") || p.to}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  type="button"
                  onClick={onRefresh}
                  disabled={busy}
                  className="px-2 py-1 rounded-[6px] text-[10px] text-black/60 hover:bg-black/5 disabled:opacity-40"
                >
                  {busy ? t(lang, "map.loading") : t(lang, "map.refresh")}
                </button>
                {onExtract && !insufficient && (
                  <button
                    type="button"
                    onClick={onExtract}
                    disabled={busy}
                    className="px-2 py-1 rounded-[6px] text-[10px] text-black/60 hover:bg-black/5 disabled:opacity-40"
                    title={t(lang, "map.extractHint")}
                  >
                    {extracting ? t(lang, "map.extracting") : t(lang, "map.extract")}
                  </button>
                )}

                {/* Zoom belongs to the canvas only. On the ledger — a plain
                    scrolling list — these used to move the percentage readout
                    while nothing on screen changed, which reads as a broken app
                    within the first ten seconds. */}
                <div className={`items-center gap-0.5 ml-1 pl-1 border-l border-black/8 ${
                  view === "river" && !insufficient ? "flex" : "hidden"
                }`}>
                  <button
                    type="button"
                    onClick={() => bumpZoom(-1)}
                    className="w-7 h-7 rounded-[6px] text-[14px] text-black/55 hover:bg-black/5"
                    title={t(lang, "map.zoomOut")}
                    aria-label={t(lang, "map.zoomOut")}
                  >
                    −
                  </button>
                  <span className="min-w-[40px] text-center text-[10px] text-black/50 tabular-nums">
                    {zoomPct}%
                  </span>
                  <button
                    type="button"
                    onClick={() => bumpZoom(1)}
                    className="w-7 h-7 rounded-[6px] text-[14px] text-black/55 hover:bg-black/5"
                    title={t(lang, "map.zoomIn")}
                    aria-label={t(lang, "map.zoomIn")}
                  >
                    +
                  </button>
                  <button
                    type="button"
                    onClick={() => setFitNonce((n) => n + 1)}
                    className="px-2 h-7 rounded-[6px] text-[10px] text-black/55 hover:bg-black/5"
                    title={t(lang, "map.fit")}
                  >
                    {t(lang, "map.fit")}
                  </button>
                </div>

                <button
                  type="button"
                  onClick={onClose}
                  className="ml-1 p-1.5 rounded-[6px] hover:bg-black/5 text-black/50"
                  aria-label={t(lang, "map.close")}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </header>

            {error && (
              <p className="px-4 py-2 text-[11px] text-red-600/90 bg-white border-b border-black/6">{error}</p>
            )}

            {river && !insufficient && view === "river" && (
              <RiverVerdictBanner
                river={river}
                lang={lang}
                onPickTurn={(id) => setSelectedNodeId(id)}
              />
            )}

            <div ref={canvasHostRef} className="relative flex-1 min-h-0 flex flex-col">
              {hasLedger && view === "ledger" && !insufficient && river ? (
                <OptionLedger
                  river={river}
                  lang={lang}
                  userName={userName}
                  onPick={(_id, index) => onJumpIndexes([index])}
                />
              ) : (
              <CanvasFitBridge fitNonce={fitNonce}>
                {river && !insufficient ? (
                  <DecisionRiver
                    river={river}
                    lang={lang}
                    userName={userName}
                    selectedId={selectedNodeId}
                    onSelect={(id) => setSelectedNodeId(id)}
                    zoom={zoom}
                    onZoomChange={setZoom}
                    pan={pan}
                    onPanChange={setPan}
                    enterReady={enterReady}
                  />
                ) : (
                  <DecisionMapCanvas
                    data={data}
                    lang={lang}
                    selectedId={selectedNodeId}
                    insufficient={insufficient}
                    onSelect={(id, kind) => {
                      setSelectedNodeId(id);
                      if (kind === "issue" && id) onSelectTopic(id);
                    }}
                    onJumpIndexes={onJumpIndexes}
                    zoom={zoom}
                    onZoomChange={setZoom}
                    pan={pan}
                    onPanChange={setPan}
                    enterReady={enterReady}
                  />
                )}
              </CanvasFitBridge>
              )}

              {/* TD-style parameter panel (top-right) */}
              <AnimatePresence>
                {view === "river" && (selectedIssue || selectedClaim || selectedOption || selectedTurn) && !insufficient && (
                  <motion.aside
                    key={selectedNodeId || "params"}
                    initial={{ opacity: 0, x: 16 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 12 }}
                    transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
                    className="absolute top-3 right-3 z-20 w-[min(300px,calc(100%-1.5rem))] max-h-[min(70vh,520px)] overflow-y-auto rounded-[6px] border border-black/15 bg-[#efefed]/[0.97] shadow-[0_8px_28px_rgba(0,0,0,0.12)] backdrop-blur-sm"
                    style={font}
                  >
                    <div className="sticky top-0 flex items-center justify-between gap-2 px-2.5 py-1.5 border-b border-black/10 bg-[#e6e6e4]/95">
                      <p className={`text-[10px] text-black/55 ${labelCaseClass(lang)}`}>{t(lang, "map.params")}</p>
                      <button
                        type="button"
                        className="w-5 h-5 flex items-center justify-center text-black/40 hover:text-black/70 text-[12px]"
                        aria-label={t(lang, "map.closeParams")}
                        onClick={() => setSelectedNodeId(null)}
                      >
                        ×
                      </button>
                    </div>

                    <div className="divide-y divide-black/8 text-[11px]">
                      <ParamRow
                        lang={lang}
                        label={t(lang, "map.param.type")}
                        value={
                          selectedTurn
                            ? t(lang, "map.param.turn")
                            : selectedIssue
                              ? t(lang, "map.issues")
                              : selectedOption
                                ? t(lang, "map.options")
                                : t(lang, "map.claims")
                        }
                      />

                      {selectedTurn && (
                        <>
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.speaker")}
                            value={
                              selectedTurn.is_user
                                ? userLabel(lang, userName)
                                : selectedTurn.speaker
                            }
                          />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.move")}
                            value={selectedTurn.move_detail || selectedTurn.move_kind || t(lang, "map.param.none")}
                          />
                          {selectedTurn.rationale && (
                            <ParamRow
                              lang={lang}
                              label={t(lang, "map.param.rationale")}
                              value={selectedTurn.rationale}
                              multiline
                            />
                          )}
                          {selectedTurn.stance && (
                            <ParamRow
                              lang={lang}
                              label={t(lang, "map.param.stance")}
                              value={`${selectedTurn.stance.sign === "support" ? "▲" : "⚠"} ${
                                river?.options.find((o) => o.id === selectedTurn.stance?.option_id)?.label ||
                                selectedTurn.stance.option_id
                              }`}
                              multiline
                            />
                          )}
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.summary")}
                            value={selectedTurn.summary || selectedTurn.fallback_text}
                            multiline
                          />
                          {selectedTurn.badges?.choice && (
                            <ParamRow
                              lang={lang}
                              label={t(lang, "map.milestone.choice")}
                              value={selectedTurn.badges.choice.label}
                              multiline
                            />
                          )}
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.evidence")}
                            value={`#${selectedTurn.index}`}
                          />
                        </>
                      )}

                      {selectedIssue && (
                        <>
                          <ParamRow lang={lang} label={t(lang, "map.param.label")} value={selectedIssue.label} />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.status")}
                            value={
                              t(lang, `map.status.${selectedIssue.status}`) === `map.status.${selectedIssue.status}`
                                ? selectedIssue.status
                                : t(lang, `map.status.${selectedIssue.status}`)
                            }
                          />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.phase")}
                            value={phaseLabel(lang, selectedIssue.phase) || selectedIssue.phase || t(lang, "map.param.none")}
                          />
                          <ParamRow lang={lang} label={t(lang, "map.param.claims")} value={String(issueClaims.length)} />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.winning")}
                            value={winningClaim ? `${winningClaim.speaker}: ${winningClaim.text}` : t(lang, "map.param.none")}
                            multiline
                          />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.summary")}
                            value={selectedIssue.summary || t(lang, "map.param.none")}
                            multiline
                          />
                          {issueClaims.length > 0 && (
                            <div className="px-2.5 py-2 space-y-1">
                              <p className={`text-[9px] text-black/40 ${labelCaseClass(lang)}`}>{t(lang, "map.claims")}</p>
                              {issueClaims.map((c) => (
                                <button
                                  key={c.id}
                                  type="button"
                                  className="w-full text-left px-1.5 py-1 rounded-[3px] hover:bg-black/[0.05] text-[10px] text-black/75"
                                  onClick={() => setSelectedNodeId(c.id)}
                                >
                                  <span className="text-black/40 mr-1">→</span>
                                  {c.speaker}
                                </button>
                              ))}
                            </div>
                          )}
                        </>
                      )}

                      {selectedClaim && (
                        <>
                          <ParamRow lang={lang} label={t(lang, "map.param.speaker")} value={selectedClaim.speaker} />
                          <ParamRow lang={lang} label={t(lang, "map.param.badge")} value={selectedClaim.badge || t(lang, "map.param.none")} />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.issue")}
                            value={parentIssue?.label || selectedClaim.issue_id}
                            onJump={
                              parentIssue
                                ? () => {
                                    setSelectedNodeId(parentIssue.id);
                                    onSelectTopic(parentIssue.id);
                                  }
                                : undefined
                            }
                          />
                          <ParamRow lang={lang} label={t(lang, "map.param.text")} value={selectedClaim.text} multiline />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.evidence")}
                            value={
                              selectedClaim.message_indexes?.length
                                ? selectedClaim.message_indexes.join(", ")
                                : t(lang, "map.param.none")
                            }
                          />
                          <ClaimLinkBlock lang={lang} titleKey="map.param.supports" claims={claimLinks.supports} onPick={setSelectedNodeId} />
                          <ClaimLinkBlock lang={lang} titleKey="map.param.opposes" claims={claimLinks.opposes} onPick={setSelectedNodeId} />
                          <ClaimLinkBlock lang={lang} titleKey="map.param.supportedBy" claims={claimLinks.supportedBy} onPick={setSelectedNodeId} />
                          <ClaimLinkBlock lang={lang} titleKey="map.param.opposedBy" claims={claimLinks.opposedBy} onPick={setSelectedNodeId} />
                        </>
                      )}

                      {selectedOption && (
                        <>
                          <ParamRow lang={lang} label={t(lang, "map.param.label")} value={selectedOption.label} />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.proposedBy")}
                            value={selectedOption.proposed_by || t(lang, "map.param.none")}
                          />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.optionStatus")}
                            value={
                              t(lang, `map.status.${selectedOption.status || "open"}`) ===
                              `map.status.${selectedOption.status || "open"}`
                                ? selectedOption.status || "open"
                                : t(lang, `map.status.${selectedOption.status || "open"}`)
                            }
                          />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.issue")}
                            value={parentIssue?.label || selectedOption.issue_id}
                            onJump={
                              parentIssue
                                ? () => {
                                    setSelectedNodeId(parentIssue.id);
                                    onSelectTopic(parentIssue.id);
                                  }
                                : undefined
                            }
                          />
                          <ParamRow
                            lang={lang}
                            label={t(lang, "map.param.evidence")}
                            value={
                              selectedOption.message_indexes?.length
                                ? selectedOption.message_indexes.join(", ")
                                : t(lang, "map.param.none")
                            }
                          />
                        </>
                      )}
                    </div>

                    <div className="sticky bottom-0 px-2.5 py-2 border-t border-black/10 bg-[#e6e6e4]/95 flex flex-wrap gap-1.5">
                      {selectedTurn && (
                        <button
                          type="button"
                          className="px-2 py-1 rounded-[3px] bg-black text-white text-[10px] hover:bg-black/85"
                          onClick={() => onJumpIndexes([selectedTurn.index])}
                        >
                          {t(lang, "map.jumpEvidence")}
                        </button>
                      )}
                      {selectedClaim && (selectedClaim.message_indexes?.length || 0) > 0 && (
                        <button
                          type="button"
                          className="px-2 py-1 rounded-[3px] bg-black text-white text-[10px] hover:bg-black/85"
                          onClick={() => onJumpIndexes(selectedClaim.message_indexes)}
                        >
                          {t(lang, "map.jumpEvidence")}
                        </button>
                      )}
                      {selectedOption && (selectedOption.message_indexes?.length || 0) > 0 && (
                        <button
                          type="button"
                          className="px-2 py-1 rounded-[3px] bg-black text-white text-[10px] hover:bg-black/85"
                          onClick={() => onJumpIndexes(selectedOption.message_indexes || [])}
                        >
                          {t(lang, "map.jumpEvidence")}
                        </button>
                      )}
                      {(selectedClaim || selectedOption) && parentIssue && (
                        <button
                          type="button"
                          className="px-2 py-1 rounded-[3px] border border-black/15 bg-white text-[10px] text-black/70 hover:bg-black/[0.04]"
                          onClick={() => {
                            setSelectedNodeId(parentIssue.id);
                            onSelectTopic(parentIssue.id);
                          }}
                        >
                          {t(lang, "map.param.issue")}
                        </button>
                      )}
                      {selectedIssue && winningClaim && (
                        <button
                          type="button"
                          className="px-2 py-1 rounded-[3px] border border-black/15 bg-white text-[10px] text-black/70 hover:bg-black/[0.04]"
                          onClick={() => setSelectedNodeId(winningClaim.id)}
                        >
                          {t(lang, "map.jumpClaim")}
                        </button>
                      )}
                    </div>
                  </motion.aside>
                )}
              </AnimatePresence>
            </div>

            {/* Legacy fact strip: only for old responses without the river —
                the river IS the reply graph now, with content on the nodes. */}
            {!insufficient && !river && (
              <div className="flex-shrink-0">
                <ReplyGraph facts={data?.facts} lang={lang} userName={userName} onJumpIndexes={onJumpIndexes} />
              </div>
            )}

            <footer className="flex-shrink-0 border-t border-black/10 bg-white">
              {/* The key sits above the hint and off the canvas: on the canvas
                  it painted over the world layer, so panning a card into the
                  bottom strip made the two collide. */}
              {river && !insufficient && view === "river" && (
                <div className={`${FOOTER_ROW} border-b border-black/[0.06] bg-black/[0.015]`}>
                  <div className="max-w-[1100px] mx-auto w-full">
                    <RiverKeyStrip lang={lang} />
                  </div>
                </div>
              )}

              <div className={FOOTER_ROW}>
                <div className="max-w-[1100px] mx-auto min-w-0 w-full">
                  {insufficient ? (
                    <p className="text-[10px] text-black/75 leading-relaxed">{t(lang, "map.insufficient")}</p>
                  ) : leaningDirection ? (
                    <>
                      <p className={`text-[10px] text-[var(--app-muted-text)] ${labelCaseClass(lang)}`}>
                        {t(lang, "map.conclusion")}
                      </p>
                      <p className="text-[13px] text-black mt-1 leading-snug">{leaningDirection}</p>
                      {leaningStrength && (
                        <p className="text-[11px] text-black/60 mt-0.5">{leaningStrength}</p>
                      )}
                    </>
                  ) : (
                    <p className="text-[10px] text-black/60 leading-relaxed">
                      {t(lang, view === "ledger" ? "map.ledgerHint" : "map.selectHint")}
                    </p>
                  )}
                </div>
              </div>
            </footer>
          </motion.div>
        </div>
      )}
    </AnimatePresence>

    {/* Docked pill: the way back after "jump to evidence". Kept outside the
        fullscreen tree so the chat is fully interactive while it shows. */}
    <AnimatePresence>
      {open && docked && (
        <motion.div
          initial={{ opacity: 0, y: 14, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 14, scale: 0.96 }}
          transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          className="fixed bottom-24 right-4 z-[190] flex items-center gap-1.5"
          style={font}
        >
          <button
            type="button"
            onClick={onUndock}
            className="h-9 pl-3 pr-3.5 rounded-full bg-black text-white text-[11px] shadow-[0_10px_28px_rgba(0,0,0,0.28)] hover:bg-black/85 flex items-center gap-1.5"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M9 20l-6-2V6l6 2m0 12l6-2m-6 2V8m6 10l6 2V8l-6-2m0 12V6M9 8l6-2" />
            </svg>
            {t(lang, "map.backToMap")}
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label={t(lang, "map.close")}
            className="w-9 h-9 rounded-full bg-white border border-black/12 text-black/55 shadow-[0_10px_28px_rgba(0,0,0,0.16)] hover:bg-black/[0.04] flex items-center justify-center"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </motion.div>
      )}
    </AnimatePresence>
    </>
  );
}

function ParamRow({
  label,
  value,
  multiline,
  onJump,
  lang = "en",
}: {
  label: string;
  value: string;
  multiline?: boolean;
  onJump?: () => void;
  lang?: UiLang;
}) {
  return (
    <div className="grid grid-cols-[88px_1fr] gap-2 px-2.5 py-1.5 items-start">
      <span className={`text-[9px] text-black/40 pt-0.5 ${labelCaseClass(lang)}`}>{label}</span>
      {onJump ? (
        <button
          type="button"
          onClick={onJump}
          className={`text-left text-black/80 hover:text-[#1560a8] ${multiline ? "whitespace-pre-wrap leading-snug" : "truncate"}`}
        >
          {value}
        </button>
      ) : (
        <span className={`text-black/80 ${multiline ? "whitespace-pre-wrap leading-snug" : "truncate"}`}>{value}</span>
      )}
    </div>
  );
}

function ClaimLinkBlock({
  lang,
  titleKey,
  claims,
  onPick,
}: {
  lang: UiLang;
  titleKey: string;
  claims: DecisionMapClaim[];
  onPick: (id: string) => void;
}) {
  if (!claims.length) return null;
  return (
    <div className="px-2.5 py-2 space-y-1">
      <p className={`text-[9px] text-black/40 ${labelCaseClass(lang)}`}>{t(lang, titleKey)}</p>
      {claims.map((c) => (
        <button
          key={`${titleKey}-${c.id}`}
          type="button"
          className="w-full text-left px-1.5 py-1 rounded-[3px] hover:bg-black/[0.05] text-[10px] text-black/75"
          onClick={() => onPick(c.id)}
        >
          <span className="text-black/40 mr-1">→</span>
          {c.speaker}
          <span className="block text-black/45 truncate pl-3">{c.text}</span>
        </button>
      ))}
    </div>
  );
}

function CanvasFitBridge({
  fitNonce,
  children,
}: {
  fitNonce: number;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!fitNonce) return;
    const btn = ref.current?.querySelector("[data-map-fit]") as HTMLButtonElement | null;
    btn?.click();
  }, [fitNonce]);
  return (
    <div ref={ref} className="relative flex-1 min-h-0 flex flex-col">
      {children}
    </div>
  );
}
