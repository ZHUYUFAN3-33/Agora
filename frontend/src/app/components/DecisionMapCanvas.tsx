import React, { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { motion } from "motion/react";
import { getUiFont, labelCaseClass, t, type UiLang } from "../i18n/ui";
import type {
  DecisionMapClaim,
  DecisionMapData,
  DecisionMapEdge,
  DecisionMapIssue,
  DecisionMapOption,
} from "./DecisionMapPanel";

export type CanvasNodeKind = "issue" | "claim" | "option";

export type CanvasNode = {
  id: string;
  kind: CanvasNodeKind;
  label: string;
  detail?: string;
  status?: string;
  x: number;
  y: number;
  w: number;
  h: number;
  messageIndexes: number[];
  issueId?: string | null;
  staggerIndex: number;
};

export type FrameLayout = {
  issue: DecisionMapIssue;
  x: number;
  y: number;
  w: number;
  h: number;
  minW: number;
  minH: number;
};

type Pt = { x: number; y: number };

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 1.8;
const CLAIM_W = 200;
const CLAIM_H = 72;
const OPTION_W = 148;
const OPTION_H = 52;
const OPTION_GAP = 12;
const OPTION_BAND_GAP = 28;
const GAP_X = 120;
const GAP_Y = 36;
const FRAME_PAD_X = 36;
const FRAME_PAD_Y = 28;
const FRAME_HEADER = 44;

function statusColor(status?: string): string {
  if (status === "settled" || status === "chosen") return "#059669";
  if (status === "leaning") return "#1560a8";
  if (status === "rejected") return "rgba(0,0,0,0.22)";
  return "rgba(0,0,0,0.35)";
}

function edgeStroke(type: string): { stroke: string; dash?: string; width: number } {
  if (type === "supports") return { stroke: "#059669", width: 1.75 };
  if (type === "opposes") return { stroke: "#dc2626", width: 1.75 };
  if (type === "chooses") return { stroke: "#b45309", width: 2.25 };
  return { stroke: "rgba(0,0,0,0.28)", width: 1.3, dash: "5 3" };
}

function bezierH(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.max(56, Math.abs(x2 - x1) * 0.45);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

function sidePort(n: CanvasNode, side: "left" | "right", slot = 0, slots = 1): Pt {
  const t = slots <= 1 ? 0.5 : (slot + 1) / (slots + 1);
  if (side === "right") return { x: n.x + n.w, y: n.y + n.h * t };
  return { x: n.x, y: n.y + n.h * t };
}

/** Layer claims left→right by argument edges (sources left, sinks right). */
function layerClaims(
  claims: DecisionMapClaim[],
  edges: DecisionMapEdge[],
): DecisionMapClaim[][] {
  const ids = new Set(claims.map((c) => c.id));
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  ids.forEach((id) => {
    incoming.set(id, 0);
    outgoing.set(id, []);
  });
  edges.forEach((e) => {
    if (e.type !== "supports" && e.type !== "opposes") return;
    if (!ids.has(e.from) || !ids.has(e.to)) return;
    incoming.set(e.to, (incoming.get(e.to) || 0) + 1);
    outgoing.get(e.from)!.push(e.to);
  });

  const layers: DecisionMapClaim[][] = [];
  const placed = new Set<string>();
  let frontier = claims.filter((c) => (incoming.get(c.id) || 0) === 0);
  if (frontier.length === 0) frontier = [...claims];

  while (placed.size < claims.length) {
    const layer = frontier.filter((c) => !placed.has(c.id));
    if (layer.length === 0) {
      const rest = claims.filter((c) => !placed.has(c.id));
      if (rest.length) layers.push(rest);
      break;
    }
    layers.push(layer);
    layer.forEach((c) => placed.add(c.id));
    const nextIds = new Set<string>();
    layer.forEach((c) => {
      (outgoing.get(c.id) || []).forEach((to) => {
        if (!placed.has(to)) nextIds.add(to);
      });
    });
    frontier = claims.filter((c) => nextIds.has(c.id));
    if (frontier.length === 0) {
      frontier = claims.filter((c) => !placed.has(c.id));
    }
  }
  return layers;
}

export function layoutIbisMap(
  data: DecisionMapData | null,
  frameSizeOverrides: Record<string, { w: number; h: number }> = {},
): { frames: FrameLayout[]; nodes: CanvasNode[] } {
  if (!data) return { frames: [], nodes: [] };
  const issues = data.issues || [];
  const claims = data.claims || [];
  const options = data.options || [];
  const allEdges = data.edges || [];
  const nodes: CanvasNode[] = [];
  const frames: FrameLayout[] = [];
  let stagger = 0;

  const roots = issues.filter((i) => !i.parent_id || !issues.some((p) => p.id === i.parent_id));
  const childrenOf = (id: string) => issues.filter((i) => i.parent_id === id);
  const ordered: DecisionMapIssue[] = [];
  const visit = (iss: DecisionMapIssue) => {
    ordered.push(iss);
    childrenOf(iss.id).forEach(visit);
  };
  roots.forEach(visit);
  issues.forEach((i) => {
    if (!ordered.some((o) => o.id === i.id)) ordered.push(i);
  });

  let cursorY = 56;
  const baseX = 64;

  ordered.forEach((issue, ii) => {
    const mineOpts = options.filter((o) => o.issue_id === issue.id);
    const mine = claims.filter((c) => c.issue_id === issue.id);
    const localEdges = allEdges.filter(
      (e) =>
        (e.type === "supports" || e.type === "opposes") &&
        mine.some((c) => c.id === e.from) &&
        mine.some((c) => c.id === e.to),
    );
    const layers = mine.length ? layerClaims(mine, localEdges) : [[]];

    // Options band (top row) — relative coords
    const optRel: { id: string; x: number; y: number; option: DecisionMapOption }[] = [];
    mineOpts.forEach((o, oi) => {
      optRel.push({
        id: o.id,
        x: oi * (OPTION_W + OPTION_GAP),
        y: 0,
        option: o,
      });
    });
    const optBandH = mineOpts.length ? OPTION_H + OPTION_BAND_GAP : 0;
    const optBandW = mineOpts.length
      ? mineOpts.length * OPTION_W + Math.max(0, mineOpts.length - 1) * OPTION_GAP
      : 0;

    // Claims layered below the options band
    const rel: { id: string; x: number; y: number; claim: DecisionMapClaim }[] = [];
    layers.forEach((layer, li) => {
      const colH = layer.length * CLAIM_H + Math.max(0, layer.length - 1) * GAP_Y;
      layer.forEach((c, ri) => {
        const x = li * (CLAIM_W + GAP_X);
        const y = optBandH + ri * (CLAIM_H + GAP_Y) - colH / 2 + CLAIM_H / 2;
        rel.push({ id: c.id, x, y, claim: c });
      });
    });

    let minRX = 0;
    let minRY = 0;
    let maxRX = Math.max(CLAIM_W, optBandW || CLAIM_W);
    let maxRY = Math.max(CLAIM_H, optBandH || CLAIM_H);
    const allBoxes = [
      ...optRel.map((r) => ({ x: r.x, y: r.y, w: OPTION_W, h: OPTION_H })),
      ...rel.map((r) => ({ x: r.x, y: r.y, w: CLAIM_W, h: CLAIM_H })),
    ];
    if (allBoxes.length) {
      minRX = Math.min(...allBoxes.map((r) => r.x));
      minRY = Math.min(...allBoxes.map((r) => r.y));
      maxRX = Math.max(...allBoxes.map((r) => r.x + r.w));
      maxRY = Math.max(...allBoxes.map((r) => r.y + r.h));
    }
    const contentW = Math.max(CLAIM_W, maxRX - minRX);
    const contentH = Math.max(CLAIM_H, maxRY - minRY);
    const minW = contentW + FRAME_PAD_X * 2;
    const minH = contentH + FRAME_HEADER + FRAME_PAD_Y * 2;
    const ov = frameSizeOverrides[issue.id];
    const frameW = Math.max(minW, ov?.w ?? minW);
    const frameH = Math.max(minH, ov?.h ?? minH);

    const isBranch = !!issue.parent_id;
    const frameX = baseX + (isBranch ? 48 : 0) + (ii % 2) * 16;
    const frameY = cursorY;

    const originX = frameX + FRAME_PAD_X + (frameW - FRAME_PAD_X * 2 - contentW) / 2 - minRX;
    const originY = frameY + FRAME_HEADER + FRAME_PAD_Y + (frameH - FRAME_HEADER - FRAME_PAD_Y * 2 - contentH) / 2 - minRY;

    frames.push({
      issue,
      x: frameX,
      y: frameY,
      w: frameW,
      h: frameH,
      minW,
      minH,
    });
    nodes.push({
      id: issue.id,
      kind: "issue",
      label: issue.label,
      detail: issue.summary || issue.status,
      status: issue.status,
      x: frameX,
      y: frameY,
      w: frameW,
      h: frameH,
      messageIndexes: [],
      issueId: issue.id,
      staggerIndex: stagger++,
    });

    optRel.forEach((r) => {
      nodes.push({
        id: r.option.id,
        kind: "option",
        label: r.option.label,
        detail: r.option.proposed_by || undefined,
        status: r.option.status || "open",
        x: originX + r.x,
        y: originY + r.y,
        w: OPTION_W,
        h: OPTION_H,
        messageIndexes: r.option.message_indexes || [],
        issueId: r.option.issue_id,
        staggerIndex: stagger++,
      });
    });

    rel.forEach((r) => {
      nodes.push({
        id: r.claim.id,
        kind: "claim",
        label: r.claim.speaker,
        detail: r.claim.text,
        status: r.claim.badge || undefined,
        x: originX + r.x,
        y: originY + r.y,
        w: CLAIM_W,
        h: CLAIM_H,
        messageIndexes: r.claim.message_indexes || [],
        issueId: r.claim.issue_id,
        staggerIndex: stagger++,
      });
    });

    cursorY += frameH + 72;
  });

  return { frames, nodes };
}

export function DecisionMapCanvas({
  data,
  lang = "en",
  selectedId,
  onSelect,
  onJumpIndexes: _onJumpIndexes,
  zoom,
  onZoomChange,
  pan,
  onPanChange,
  enterReady,
  insufficient,
}: {
  data: DecisionMapData | null;
  lang?: UiLang;
  selectedId?: string | null;
  onSelect: (id: string | null, kind: CanvasNodeKind | null) => void;
  onJumpIndexes: (indexes: number[]) => void;
  zoom: number;
  onZoomChange: (z: number) => void;
  pan: Pt;
  onPanChange: (p: Pt) => void;
  enterReady: boolean;
  insufficient?: boolean;
}) {
  const font = getUiFont(lang);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [frameSizeOverrides, setFrameSizeOverrides] = useState<Record<string, { w: number; h: number }>>({});
  const { frames: baseFrames, nodes: baseNodes } = useMemo(
    () => layoutIbisMap(data, frameSizeOverrides),
    [data, frameSizeOverrides],
  );
  const [overrides, setOverrides] = useState<Record<string, Pt>>({});
  const dragRef = useRef<{
    mode: "pan" | "node" | "resize";
    id?: string;
    startX: number;
    startY: number;
    origPan: Pt;
    origNode?: Pt;
    origSize?: { w: number; h: number; minW: number; minH: number };
  } | null>(null);

  const layoutKey = useMemo(
    () =>
      (data?.issues || []).map((i) => i.id).join("|") +
      "::" +
      (data?.claims || []).length +
      "::" +
      (data?.options || []).length +
      "::" +
      (data?.options || []).map((o) => o.status).join(","),
    [data],
  );
  useEffect(() => {
    setOverrides({});
    setFrameSizeOverrides({});
  }, [layoutKey]);

  const frames = baseFrames;
  const nodes = useMemo(() => {
    return baseNodes.map((n) => {
      if (n.kind === "issue") {
        const f = frames.find((fr) => fr.issue.id === n.id);
        return f ? { ...n, x: f.x, y: f.y, w: f.w, h: f.h } : n;
      }
      const o = overrides[n.id];
      return o ? { ...n, x: o.x, y: o.y } : n;
    });
  }, [baseNodes, overrides, frames]);

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const claimNodes = nodes.filter((n) => n.kind === "claim");
  const optionNodes = nodes.filter((n) => n.kind === "option");

  const edges = useMemo(() => {
    const list = (data?.edges || []).filter((e) =>
      e.type === "supports" || e.type === "opposes" || e.type === "emerged_from" || e.type === "chooses",
    ) as DecisionMapEdge[];
    return list.filter((e) => byId.has(e.from) && byId.has(e.to));
  }, [data, byId]);

  const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

  const fitView = useCallback(() => {
    const el = viewportRef.current;
    if (!el || nodes.length === 0) return;
    const pad = 80;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    nodes.forEach((n) => {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + n.w);
      maxY = Math.max(maxY, n.y + n.h);
    });
    const bw = Math.max(1, maxX - minX);
    const bh = Math.max(1, maxY - minY);
    const vw = el.clientWidth;
    const vh = el.clientHeight;
    const z = clampZoom(Math.min((vw - pad * 2) / bw, (vh - pad * 2) / bh, 1));
    onZoomChange(z);
    onPanChange({
      x: (vw - bw * z) / 2 - minX * z,
      y: (vh - bh * z) / 2 - minY * z,
    });
  }, [nodes, onPanChange, onZoomChange]);

  const fittedKey = useRef("");
  useEffect(() => {
    if (!enterReady || nodes.length === 0) return;
    if (fittedKey.current === layoutKey) return;
    fittedKey.current = layoutKey;
    const t = window.setTimeout(() => fitView(), 50);
    return () => window.clearTimeout(t);
  }, [enterReady, layoutKey, nodes.length, fitView]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        onPanChange({ x: pan.x - e.deltaX, y: pan.y - e.deltaY });
        return;
      }
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const next = clampZoom(zoom * (e.deltaY < 0 ? 1.08 : 1 / 1.08));
      const scale = next / zoom;
      onZoomChange(next);
      onPanChange({
        x: mx - (mx - pan.x) * scale,
        y: my - (my - pan.y) * scale,
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [pan, zoom, onPanChange, onZoomChange]);

  const onPointerDownBackground = (e: React.PointerEvent) => {
    if (e.button !== 0 && e.button !== 1) return;
    const target = e.target as HTMLElement;
    if (target.closest("[data-map-node]") || target.closest("[data-resize-handle]")) return;
    dragRef.current = {
      mode: "pan",
      startX: e.clientX,
      startY: e.clientY,
      origPan: { ...pan },
    };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    onSelect(null, null);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (d.mode === "pan") {
      onPanChange({ x: d.origPan.x + dx, y: d.origPan.y + dy });
      return;
    }
    if (d.mode === "node" && d.id && d.origNode) {
      setOverrides((prev) => ({
        ...prev,
        [d.id!]: {
          x: d.origNode!.x + dx / zoom,
          y: d.origNode!.y + dy / zoom,
        },
      }));
      return;
    }
    if (d.mode === "resize" && d.id && d.origSize) {
      const w = Math.max(d.origSize.minW, d.origSize.w + dx / zoom);
      const h = Math.max(d.origSize.minH, d.origSize.h + dy / zoom);
      setFrameSizeOverrides((prev) => ({ ...prev, [d.id!]: { w, h } }));
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    dragRef.current = null;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  const startNodeDrag = (e: React.PointerEvent, node: CanvasNode) => {
    if (node.kind !== "claim" && node.kind !== "option") return;
    e.stopPropagation();
    dragRef.current = {
      mode: "node",
      id: node.id,
      startX: e.clientX,
      startY: e.clientY,
      origPan: { ...pan },
      origNode: { x: node.x, y: node.y },
    };
    viewportRef.current?.setPointerCapture(e.pointerId);
  };

  const startFrameResize = (e: React.PointerEvent, f: FrameLayout) => {
    e.stopPropagation();
    e.preventDefault();
    dragRef.current = {
      mode: "resize",
      id: f.issue.id,
      startX: e.clientX,
      startY: e.clientY,
      origPan: { ...pan },
      origSize: { w: f.w, h: f.h, minW: f.minW, minH: f.minH },
    };
    viewportRef.current?.setPointerCapture(e.pointerId);
    onSelect(f.issue.id, "issue");
  };

  const outSlots = useMemo(() => {
    const m = new Map<string, DecisionMapEdge[]>();
    edges.forEach((e) => {
      if (e.type === "emerged_from") return;
      if (!m.has(e.from)) m.set(e.from, []);
      m.get(e.from)!.push(e);
    });
    return m;
  }, [edges]);

  const inSlots = useMemo(() => {
    const m = new Map<string, DecisionMapEdge[]>();
    edges.forEach((e) => {
      if (e.type === "emerged_from") return;
      if (!m.has(e.to)) m.set(e.to, []);
      m.get(e.to)!.push(e);
    });
    return m;
  }, [edges]);

  const worldW = 3200;
  const worldH = 2400;

  return (
    <div
      ref={viewportRef}
      className="relative flex-1 min-h-0 overflow-hidden cursor-grab active:cursor-grabbing"
      onPointerDown={onPointerDownBackground}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      style={{
        backgroundColor: "#f7f7f5",
        backgroundImage:
          "linear-gradient(rgba(0,0,0,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.04) 1px, transparent 1px)",
        backgroundSize: `${24 * zoom}px ${24 * zoom}px`,
        backgroundPosition: `${pan.x}px ${pan.y}px`,
      }}
    >
      <div
        className="absolute origin-top-left will-change-transform"
        style={{
          width: worldW,
          height: worldH,
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
        }}
      >
        {frames.map((f, fi) => (
          <motion.div
            key={`frame-${f.issue.id}`}
            data-map-node={f.issue.id}
            initial={enterReady ? { opacity: 0, y: -8 } : false}
            animate={enterReady ? { opacity: 1, y: 0 } : { opacity: 0 }}
            transition={{ duration: 0.28, delay: enterReady ? 0.06 + fi * 0.05 : 0, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(f.issue.id, "issue");
            }}
            className={`absolute rounded-[12px] border bg-white/75 ${
              selectedId === f.issue.id ? "border-black/30 ring-2 ring-black/8" : "border-black/10"
            }`}
            style={{
              left: f.x,
              top: f.y,
              width: f.w,
              height: f.h,
              boxShadow: "0 1px 0 rgba(0,0,0,0.03), 0 10px 28px rgba(0,0,0,0.05)",
            }}
          >
            <div className="h-[3px] rounded-t-[12px]" style={{ background: statusColor(f.issue.status) }} />
            <div className="px-3.5 pt-2.5 pb-1 flex items-start justify-between gap-2 pointer-events-none">
              <div className="min-w-0">
                <p className={`text-[9px] text-black/35 ${labelCaseClass(lang)}`}>{t(lang, "map.issues")}</p>
                <p className="text-[13px] text-black truncate" style={font as CSSProperties}>
                  {f.issue.label}
                </p>
              </div>
              <span className={`text-[9px] text-black/40 flex-shrink-0 mt-0.5 ${labelCaseClass(lang)}`}>
                {t(lang, `map.status.${f.issue.status}`) === `map.status.${f.issue.status}`
                  ? f.issue.status
                  : t(lang, `map.status.${f.issue.status}`)}
              </span>
            </div>
            {/* Resize handle — bottom-right */}
            <div
              data-resize-handle
              onPointerDown={(e) => startFrameResize(e, f)}
              className="absolute right-1 bottom-1 w-4 h-4 cursor-nwse-resize flex items-end justify-end p-0.5 opacity-50 hover:opacity-100"
              title={t(lang, "map.resizeFrame")}
            >
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
                <path d="M9 1L1 9M9 5L5 9M9 8L8 9" stroke="currentColor" strokeWidth="1.2" />
              </svg>
            </div>
          </motion.div>
        ))}

        <svg className="absolute inset-0 pointer-events-none" width={worldW} height={worldH} aria-hidden style={{ zIndex: 1 }}>
          {edges.map((e) => {
            const a = byId.get(e.from);
            const b = byId.get(e.to);
            if (!a || !b) return null;
            const style = edgeStroke(e.type);
            if (e.type === "emerged_from") {
              const p1 = { x: a.x + a.w / 2, y: a.y };
              const p2 = { x: b.x + b.w / 2, y: b.y + b.h };
              const midY = (p1.y + p2.y) / 2;
              const d = `M ${p1.x} ${p1.y} C ${p1.x} ${midY}, ${p2.x} ${midY}, ${p2.x} ${p2.y}`;
              return (
                <motion.path
                  key={e.id}
                  d={d}
                  fill="none"
                  stroke={style.stroke}
                  strokeWidth={style.width}
                  strokeDasharray={style.dash}
                  strokeLinecap="round"
                  initial={enterReady ? { opacity: 0 } : false}
                  animate={{ opacity: enterReady ? 1 : 0 }}
                  transition={{ duration: 0.25, delay: enterReady ? 0.12 : 0 }}
                />
              );
            }
            const og = outSlots.get(e.from) || [e];
            const ig = inSlots.get(e.to) || [e];
            const outSlot = Math.max(0, og.findIndex((x) => x.id === e.id));
            const inSlot = Math.max(0, ig.findIndex((x) => x.id === e.id));
            const fromRight = a.x + a.w / 2 <= b.x + b.w / 2;
            const p1 = sidePort(a, fromRight ? "right" : "left", outSlot, og.length);
            const p2 = sidePort(b, fromRight ? "left" : "right", inSlot, ig.length);
            return (
              <motion.path
                key={e.id}
                d={bezierH(p1.x, p1.y, p2.x, p2.y)}
                fill="none"
                stroke={style.stroke}
                strokeWidth={style.width}
                strokeLinecap="round"
                initial={enterReady ? { opacity: 0 } : false}
                animate={{ opacity: enterReady ? 1 : 0 }}
                transition={{ duration: 0.25, delay: enterReady ? 0.14 : 0 }}
              />
            );
          })}
        </svg>

        {optionNodes.map((node) => {
          const selected = selectedId === node.id;
          const chosen = node.status === "chosen";
          const rejected = node.status === "rejected";
          const delay = 0.08 + node.staggerIndex * 0.03;
          return (
            <motion.button
              key={node.id}
              type="button"
              data-map-node={node.id}
              initial={enterReady ? { opacity: 0, scale: 0.94, y: -4 } : false}
              animate={enterReady ? { opacity: rejected ? 0.55 : 1, scale: 1, y: 0 } : { opacity: 0 }}
              transition={{ duration: 0.24, delay: enterReady ? delay : 0, ease: [0.22, 1, 0.36, 1] }}
              onPointerDown={(e) => startNodeDrag(e, node)}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(node.id, "option");
              }}
              className={`absolute z-[3] text-left rounded-[8px] border bg-white overflow-hidden ${
                chosen
                  ? "border-black/55 shadow-[0_0_0_2px_rgba(0,0,0,0.08),0_6px_16px_rgba(0,0,0,0.08)]"
                  : selected
                    ? "border-black/35 ring-2 ring-black/10"
                    : "border-black/12 hover:border-black/25 shadow-[0_1px_0_rgba(0,0,0,0.04),0_4px_12px_rgba(0,0,0,0.05)]"
              }`}
              style={{
                left: node.x,
                top: node.y,
                width: node.w,
                height: node.h,
                fontFamily: (font as CSSProperties).fontFamily,
                cursor: "grab",
                borderWidth: chosen ? 2.5 : 1,
              }}
            >
              <div
                className="h-[3px]"
                style={{ background: statusColor(node.status) }}
              />
              <div className="px-2 py-1.5 h-[calc(100%-3px)] flex flex-col justify-center">
                <div className="flex items-center justify-between gap-1">
                  <p className={`text-[9px] text-black/35 ${labelCaseClass(lang)}`}>{t(lang, "map.options")}</p>
                  {chosen && (
                    <span className={`text-[8px] text-emerald-700 ${labelCaseClass(lang)}`}>
                      {t(lang, "map.status.chosen")}
                    </span>
                  )}
                  {rejected && (
                    <span className={`text-[8px] text-black/35 ${labelCaseClass(lang)}`}>
                      {t(lang, "map.status.rejected")}
                    </span>
                  )}
                </div>
                <p
                  className={`text-[12px] truncate leading-snug ${rejected ? "text-black/45" : "text-black"}`}
                  style={font as CSSProperties}
                >
                  {node.label}
                </p>
              </div>
            </motion.button>
          );
        })}

        {claimNodes.map((node) => {
          const selected = selectedId === node.id;
          const delay = 0.1 + node.staggerIndex * 0.04;
          return (
            <motion.button
              key={node.id}
              type="button"
              data-map-node={node.id}
              initial={enterReady ? { opacity: 0, scale: 0.94, y: -6 } : false}
              animate={enterReady ? { opacity: 1, scale: 1, y: 0 } : { opacity: 0 }}
              transition={{ duration: 0.26, delay: enterReady ? delay : 0, ease: [0.22, 1, 0.36, 1] }}
              onPointerDown={(e) => startNodeDrag(e, node)}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(node.id, "claim");
              }}
              className={`absolute z-[2] text-left rounded-[8px] border bg-white shadow-[0_1px_0_rgba(0,0,0,0.04),0_6px_16px_rgba(0,0,0,0.06)] overflow-hidden ${
                selected ? "border-black/35 ring-2 ring-black/10" : "border-black/12 hover:border-black/25"
              }`}
              style={{
                left: node.x,
                top: node.y,
                width: node.w,
                height: node.h,
                fontFamily: (font as CSSProperties).fontFamily,
                cursor: "grab",
              }}
            >
              <div className="px-2.5 py-2 h-full flex flex-col justify-center">
                <p className={`text-[9px] text-black/35 ${labelCaseClass(lang)}`}>{t(lang, "map.claims")}</p>
                <p className="text-[12px] text-black truncate" style={font as CSSProperties}>{node.label}</p>
                {node.detail && (
                  <p className="text-[10px] text-black/50 line-clamp-2 mt-0.5 leading-snug" style={font as CSSProperties}>{node.detail}</p>
                )}
              </div>
            </motion.button>
          );
        })}

        {insufficient && (
          <div className="absolute left-1/2 top-[38%] -translate-x-1/2 max-w-[320px] text-center px-4" style={font}>
            <p className="text-[13px] text-black/70 leading-relaxed">{t(lang, "map.insufficient")}</p>
          </div>
        )}

        {!insufficient && nodes.length === 0 && (
          <div className="absolute left-1/2 top-1/3 -translate-x-1/2 text-[12px] text-black/40" style={font}>
            {t(lang, "map.emptySmart")}
          </div>
        )}
      </div>

      <button type="button" className="hidden" data-map-fit onClick={fitView} aria-hidden />
    </div>
  );
}

export { MIN_ZOOM, MAX_ZOOM };
