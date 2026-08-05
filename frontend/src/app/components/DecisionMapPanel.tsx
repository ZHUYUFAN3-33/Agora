import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { getUiFont, labelCaseClass, phaseLabel, t, type UiLang } from "../i18n/ui";
import {
  DecisionMapCanvas,
  MAX_ZOOM,
  MIN_ZOOM,
} from "./DecisionMapCanvas";

export type DecisionMapIssue = {
  id: string;
  label: string;
  parent_id?: string | null;
  status: "open" | "leaning" | "settled" | string;
  winning_claim_id?: string | null;
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

export type DecisionMapEdge = {
  id: string;
  type: "emerged_from" | "supports" | "opposes" | string;
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
  edges: DecisionMapEdge[];
  annotations: DecisionMapAnnotation[];
  phase_spine: DecisionMapPhaseSpine[];
  room_leaning?: { direction?: string; strength?: string } | null;
  agents?: { key?: string; name?: string; stance?: string | null }[];
  extracted?: boolean;
  insufficient?: boolean;
  counts?: { user?: number; agent?: number; total?: number };
  /** @deprecated legacy */
  topics?: unknown[];
  stances?: unknown[];
  conclusions?: unknown[];
};

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
  annotationDraft,
  onAnnotationDraftChange,
  onAddAnnotation,
  onDeleteAnnotation,
  onPromoteLayers,
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
  annotationDraft: string;
  onAnnotationDraftChange: (v: string) => void;
  onAddAnnotation: () => void;
  onDeleteAnnotation?: (id: string) => void;
  onPromoteLayers?: () => void;
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

  const selectedIssue = useMemo(
    () => data?.issues?.find((x) => x.id === selectedNodeId) || null,
    [data, selectedNodeId],
  );
  const selectedClaim = useMemo(
    () => data?.claims?.find((x) => x.id === selectedNodeId) || null,
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
    if (!selectedClaim) return null;
    return data?.issues?.find((i) => i.id === selectedClaim.issue_id) || null;
  }, [data?.issues, selectedClaim]);

  const winningClaim = useMemo(() => {
    if (!selectedIssue?.winning_claim_id) return null;
    return claimById.get(selectedIssue.winning_claim_id) || null;
  }, [selectedIssue, claimById]);

  const annotations = useMemo(() => {
    const all = data?.annotations || [];
    if (!selectedNodeId) return all.slice(0, 4);
    const focused = all.filter((a) => !a.target_id || a.target_id === selectedNodeId);
    return (focused.length ? focused : all).slice(0, 5);
  }, [data?.annotations, selectedNodeId]);

  const zoomPct = Math.round(zoom * 100);
  const insufficient = !!data?.insufficient;
  const busy = !!(loading || extracting);

  const bumpZoom = (dir: 1 | -1) => {
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

  return (
    <AnimatePresence>
      {open && (
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
            <header className="flex items-center justify-between gap-3 px-4 sm:px-5 h-12 border-b border-black/8 bg-white/90 backdrop-blur-sm flex-shrink-0">
              <div className="min-w-0 flex items-center gap-3">
                <div className="min-w-0">
                  <p className={`text-[12px] text-black ${labelCaseClass(lang)}`}>{t(lang, "map.title")}</p>
                  <p className="text-[10px] text-[var(--app-muted-text)] truncate hidden sm:block">
                    {busy ? t(lang, "map.extracting") : t(lang, "map.subtitleSmart")}
                  </p>
                </div>
                {(data?.phase_spine?.length || 0) > 0 && (
                  <div className="hidden md:flex items-center gap-1 ml-2 pl-2 border-l border-black/8">
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

                <div className="flex items-center gap-0.5 ml-1 pl-1 border-l border-black/8">
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

            <div ref={canvasHostRef} className="relative flex-1 min-h-0 flex flex-col">
              <CanvasFitBridge fitNonce={fitNonce}>
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
              </CanvasFitBridge>

              {/* TD-style parameter panel (top-right) */}
              <AnimatePresence>
                {(selectedIssue || selectedClaim) && !insufficient && (
                  <motion.aside
                    key={selectedNodeId || "params"}
                    initial={{ opacity: 0, x: 16 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 12 }}
                    transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
                    className="absolute top-3 right-3 z-20 w-[min(300px,calc(100%-1.5rem))] max-h-[min(70vh,520px)] overflow-y-auto rounded-[6px] border border-black/15 bg-[#efefed]/[0.97] shadow-[0_8px_28px_rgba(0,0,0,0.12)] backdrop-blur-sm"
                    style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}
                  >
                    <div className="sticky top-0 flex items-center justify-between gap-2 px-2.5 py-1.5 border-b border-black/10 bg-[#e6e6e4]/95">
                      <p className="text-[10px] uppercase tracking-[0.12em] text-black/55">{t(lang, "map.params")}</p>
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
                      <ParamRow label={t(lang, "map.param.type")} value={selectedIssue ? t(lang, "map.issues") : t(lang, "map.claims")} />

                      {selectedIssue && (
                        <>
                          <ParamRow label={t(lang, "map.param.label")} value={selectedIssue.label} />
                          <ParamRow
                            label={t(lang, "map.param.status")}
                            value={
                              t(lang, `map.status.${selectedIssue.status}`) === `map.status.${selectedIssue.status}`
                                ? selectedIssue.status
                                : t(lang, `map.status.${selectedIssue.status}`)
                            }
                          />
                          <ParamRow
                            label={t(lang, "map.param.phase")}
                            value={phaseLabel(lang, selectedIssue.phase) || selectedIssue.phase || t(lang, "map.param.none")}
                          />
                          <ParamRow label={t(lang, "map.param.claims")} value={String(issueClaims.length)} />
                          <ParamRow
                            label={t(lang, "map.param.winning")}
                            value={winningClaim ? `${winningClaim.speaker}: ${winningClaim.text}` : t(lang, "map.param.none")}
                            multiline
                          />
                          <ParamRow
                            label={t(lang, "map.param.summary")}
                            value={selectedIssue.summary || t(lang, "map.param.none")}
                            multiline
                          />
                          {issueClaims.length > 0 && (
                            <div className="px-2.5 py-2 space-y-1">
                              <p className="text-[9px] uppercase tracking-wider text-black/40">{t(lang, "map.claims")}</p>
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
                          <ParamRow label={t(lang, "map.param.speaker")} value={selectedClaim.speaker} />
                          <ParamRow label={t(lang, "map.param.badge")} value={selectedClaim.badge || t(lang, "map.param.none")} />
                          <ParamRow
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
                          <ParamRow label={t(lang, "map.param.text")} value={selectedClaim.text} multiline />
                          <ParamRow
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
                    </div>

                    <div className="sticky bottom-0 px-2.5 py-2 border-t border-black/10 bg-[#e6e6e4]/95 flex flex-wrap gap-1.5">
                      {selectedClaim && (selectedClaim.message_indexes?.length || 0) > 0 && (
                        <button
                          type="button"
                          className="px-2 py-1 rounded-[3px] bg-black text-white text-[10px] hover:bg-black/85"
                          onClick={() => onJumpIndexes(selectedClaim.message_indexes)}
                        >
                          {t(lang, "map.jumpEvidence")}
                        </button>
                      )}
                      {selectedClaim && parentIssue && (
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

            <footer className="flex-shrink-0 border-t border-black/8 bg-white/95 backdrop-blur-sm px-4 py-3">
              <div className="max-w-[1100px] mx-auto flex flex-col sm:flex-row gap-3 sm:items-start">
                <div className="flex-1 min-w-0">
                  {insufficient ? (
                    <p className="text-[12px] text-black/65 leading-relaxed pt-0.5">{t(lang, "map.insufficient")}</p>
                  ) : leaning?.direction ? (
                    <>
                      <p className={`text-[9px] tracking-widest text-[var(--app-muted-text)] ${labelCaseClass(lang)}`}>
                        {t(lang, "map.conclusion")}
                      </p>
                      <p className="text-[12px] text-black mt-0.5">{leaning.direction}</p>
                      {leaning.strength && (
                        <p className="text-[10px] text-black/45 mt-0.5">{leaning.strength}</p>
                      )}
                    </>
                  ) : (
                    <p className="text-[11px] text-[var(--app-muted-text)] pt-1">{t(lang, "map.selectHint")}</p>
                  )}

                  {!insufficient && annotations.length > 0 && (
                    <ul className="mt-2 space-y-1 max-h-[72px] overflow-y-auto">
                      {annotations.map((a) => (
                        <li key={a.id} className="flex items-start gap-1.5 text-[10px] text-black/60">
                          <button
                            type="button"
                            className="flex-1 text-left hover:text-black"
                            onClick={() => a.message_indexes?.length && onJumpIndexes(a.message_indexes)}
                          >
                            <span className="text-black/30 mr-1">[{a.kind}]</span>
                            {a.text}
                          </button>
                          {a.kind === "user" && onDeleteAnnotation && (
                            <button
                              type="button"
                              className="text-black/30 hover:text-red-500"
                              onClick={() => onDeleteAnnotation(a.id)}
                              aria-label={t(lang, "map.deleteAnnotation")}
                            >
                              ×
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {!insufficient && (
                  <div className="sm:w-[320px] flex-shrink-0 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <p className={`text-[9px] tracking-widest text-[var(--app-muted-text)] ${labelCaseClass(lang)}`}>
                        {t(lang, "map.annotations")}
                      </p>
                      {onPromoteLayers && (
                        <button
                          type="button"
                          onClick={onPromoteLayers}
                          className="text-[10px] text-black/50 hover:text-black/80"
                        >
                          {t(lang, "map.promoteLayers")}
                        </button>
                      )}
                    </div>
                    <div className="flex gap-1.5">
                      <input
                        type="text"
                        value={annotationDraft}
                        onChange={(e) => onAnnotationDraftChange(e.target.value)}
                        placeholder={t(lang, "map.annotationPh")}
                        className="flex-1 min-w-0 h-8 px-2 rounded-[6px] border border-black/10 text-[11px] outline-none focus:border-black/25 bg-white"
                        style={font}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            onAddAnnotation();
                          }
                        }}
                      />
                      <button
                        type="button"
                        onClick={onAddAnnotation}
                        disabled={!annotationDraft.trim()}
                        className="h-8 px-2.5 rounded-[6px] bg-black text-white text-[10px] disabled:opacity-30"
                      >
                        {t(lang, "map.addAnnotation")}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </footer>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

function ParamRow({
  label,
  value,
  multiline,
  onJump,
}: {
  label: string;
  value: string;
  multiline?: boolean;
  onJump?: () => void;
}) {
  return (
    <div className="grid grid-cols-[88px_1fr] gap-2 px-2.5 py-1.5 items-start">
      <span className="text-[9px] uppercase tracking-wider text-black/40 pt-0.5">{label}</span>
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
      <p className="text-[9px] uppercase tracking-wider text-black/40">{t(lang, titleKey)}</p>
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
