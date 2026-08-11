import React, { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { AnimatePresence, motion } from "motion/react";
import { getUiFont, labelCaseClass, phaseLabel, t, userLabel, type UiLang } from "../i18n/ui";
import type { DecisionMapPhaseSpine } from "./DecisionMapPanel";

/**
 * DecisionRiver — the decision map's main view.
 *
 * A swimlane timeline: X is strictly turn order, Y is the speaker's lane, so
 * both axes carry meaning — which is also why cards are NOT draggable: a
 * dragged card would lie about when it happened and who said it. Structure is
 * deterministic (turn order, [MOVE] reply edges, option milestones, hand
 * choices); content is the per-turn summary layer (turn_summaries.py —
 * cached, incremental, degrades to raw text per card).
 *
 * Colors: four semantic hues are reserved — red challenge/oppose, green
 * support/chosen, amber milestone/concern, blue user — and the speaker
 * palette deliberately avoids all four so a lane stripe can never be mistaken
 * for a stance or a milestone.
 *
 * Edge routing never passes under a card. Turns occupy disjoint X intervals
 * (each turn gets its own slot on the time axis), so a vertical segment
 * anywhere inside a card's own X range is clear in every other lane;
 * horizontal runs stay inside the empty corridors between lanes. Cross-lane
 * edges are therefore routed orthogonally — down out of the source, along the
 * corridor next to the target, into the target's facing side — and same-lane
 * arcs nest by span like bracket guides.
 *
 * Ports follow the convention every layout engine uses (React Flow "handles",
 * ELK ports with portConstraints=FIXED_ORDER): a node has several attachment
 * points per side rather than one, so a turn answered by three others shows
 * three distinct landings. Port order along a side is the barycenter rule ELK
 * uses in its crossing-minimisation sweep — sort by the opposite endpoint's X
 * — which stops two edges from swapping over each other at the boundary.
 *
 * Arrowheads point at the TARGET: an edge means "this turn replies to that
 * one", so the head lands on what is being answered. Graphviz's ortho router
 * is known to invert head/tail because it derives direction from the overall
 * vector; taking the direction from the path's final segment (SVG marker
 * orient="auto") is what keeps it honest here.
 *
 * Crossings still occur (positions are data; no solver may move a node), but
 * occlusion and overlapping landings cannot.
 */

export type RiverStance = { option_id: string; sign: "support" | "concern" | string };

export type RiverTurn = {
  id: string;
  index: number;
  speaker: string;
  is_user: boolean;
  time?: string | null;
  summary?: string | null;
  has_summary: boolean;
  fallback_text: string;
  keywords: string[];
  stance?: RiverStance | null;
  stances?: RiverStance[];
  move_kind?: string | null;
  move_detail?: string | null;
  rationale?: string | null;
  softened_by?: string | null;
  badges: { options_shown?: string[]; choice?: { option_id: string; label: string } };
  key: boolean;
};

export type RiverRelation = {
  id: string;
  from_index: number;
  to_index: number;
  kind: string;
  sign: string;
  source?: string;
};

export type RiverOption = {
  id: string;
  axis_id?: string | null;
  label: string;
  status: string;
  proposed_by: string;
  endorsed_by: string[];
  first_index?: number | null;
};

export type RiverVerdict = {
  chosen_option_id?: string | null;
  chosen_label?: string | null;
  decided_index?: number | null;
  why_turn_ids: string[];
  counts: Record<string, { support: number; concern: number }>;
  undecided: boolean;
};

export type RiverLedgerPoint = {
  turn_id: string;
  index: number;
  speaker: string;
  is_user: boolean;
  text: string;
};

export type RiverLedgerEntry = {
  option_id: string;
  label: string;
  status: string;
  proposed_by: string;
  endorsed_by: string[];
  case_for: RiverLedgerPoint[];
  case_against: RiverLedgerPoint[];
  counts: { support: number; concern: number };
};

export type RiverGuidance = {
  why?: string[];
  against?: string[];
  would_change?: string[];
  your_call?: string[];
  strength_reason?: string;
  your_role?: string;
};

export type RiverData = {
  lang: string;
  turns: RiverTurn[];
  relations: RiverRelation[];
  phases: DecisionMapPhaseSpine[];
  options: RiverOption[];
  /** Per-option case for/against — the map's landing surface. */
  ledger?: RiverLedgerEntry[];
  guidance?: RiverGuidance;
  verdict: RiverVerdict;
};

type Pt = { x: number; y: number };

const MIN_ZOOM = 0.35;
const MAX_ZOOM = 1.8;
const CARD_W = 216;
const CARD_H = 96;
const DOT_W = 26;
const GAP_X = 18;
const LANE_GAP = 74; // corridor between lanes: edge runs + kind chips live here
const EDGE_LEVEL_STEP = 11; // vertical stagger between edges sharing a corridor
const PAD_TOP = 64;
const PAD_LEFT = 28; // small breathing room before the first turn
// Below this zoom the cards flip from summaries to keyword chips.
const KEYWORD_ZOOM = 0.62;
// Never auto-fit below this: at 0.35 an 11.5px summary renders at 4px, so the
// reader never reads one card and never discovers what the view encodes.
const LEGIBLE_ZOOM = 0.75;
// The lane rail: a frozen first column, barely wider than the type it holds.
// The name is set vertically (writing-mode), so the rail's width is a font
// height plus padding rather than a name length — the horizontal room a
// 200px-wide pill used to take now belongs to the cards.
const LANE_RAIL_W = 26;
const LANE_RAIL_GAP = 14; // clearance between the rail and the first turn
const LANE_RAIL_OPEN_W = 248; // the hover panel that floats out to its right

// Semantic colors (reserved): red challenge/oppose, green support/chosen,
// amber milestone/concern, blue user. The speaker palette avoids all four.
const USER_COLOR = "#1560a8";
const SPEAKER_PALETTE = ["#0f766e", "#7c3aed", "#be185d", "#0e7490", "#4f46e5", "#57534e"];

type EdgeStyle = { stroke: string; chip: string; marker: string; dash?: string; width: number };

/** Arrowhead defs — one per edge color, since SVG markers cannot inherit stroke. */
const ARROW_MARKERS: { id: string; color: string }[] = [
  { id: "river-arrow-oppose", color: "#dc2626" },
  { id: "river-arrow-support", color: "#059669" },
  { id: "river-arrow-neutral", color: "rgba(0,0,0,0.42)" },
  { id: "river-arrow-answers", color: "rgba(0,0,0,0.30)" },
];

function edgeStyle(rel: RiverRelation): EdgeStyle {
  if (rel.sign === "opposes") {
    return { stroke: "#dc2626", chip: "#dc2626", marker: "river-arrow-oppose", width: 1.8 };
  }
  if (rel.sign === "supports") {
    return { stroke: "#059669", chip: "#059669", marker: "river-arrow-support", width: 1.8 };
  }
  // "answers" is the conversation backbone (agent replying to the user), not an
  // argument move — drawn lighter so it never competes with challenge/extend.
  if (rel.kind === "answers") {
    return {
      stroke: "rgba(0,0,0,0.20)",
      chip: "rgba(0,0,0,0.42)",
      marker: "river-arrow-answers",
      width: 1.1,
      dash: "3 4",
    };
  }
  return {
    stroke: "rgba(0,0,0,0.30)",
    chip: "rgba(0,0,0,0.52)",
    marker: "river-arrow-neutral",
    width: 1.25,
    dash: "5 4",
  };
}

/** Edge kinds in the reader's own words. The raw kinds ("challenge",
 * "extend", "mention", "answers") are the [MOVE] vocabulary — internal terms
 * that a first-time reader has no way to interpret, and untranslated English
 * on top of that for a zh/ja reader. */
function edgeWord(lang: UiLang, kind: string): string {
  const key = `map.edge.${kind}`;
  const word = t(lang, key);
  return word === key ? kind : word;
}

/** Alpha over a #rrggbb from the speaker palette. */
function withAlpha(hex: string, a: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function shortLabel(label: string, n = 16): string {
  const one = (label || "").trim();
  return one.length > n ? one.slice(0, n - 1).trimEnd() + "…" : one;
}

type NodePos = {
  turn: RiverTurn;
  x: number;
  w: number;
  y: number;
  h: number;
  lane: number;
};

type LaneFocus = { kind: "supports" | "worries"; option: string } | null;
type Lane = { key: string; label: string; focus: LaneFocus; isUser: boolean; color: string };

/**
 * Which option this speaker argued FOR most often.
 *
 * This used to tally raw keywords, which carry no sign — and since every
 * summary names both options, the keyword that scored highest for a speaker was
 * reliably the one they were arguing AGAINST. Observed: ChatbotA, the NovaAI
 * advocate, was labelled "mostly talks about stability" (BigTech's case) three
 * turns running. Stances carry a sign, so they can answer this question; nothing
 * derived from keyword frequency ever can.
 */
function laneFocus(
  turns: RiverTurn[],
  speaker: string,
  options: RiverOption[],
): { kind: "supports" | "worries"; option: string } | null {
  const supports = new Map<string, number>();
  const concerns = new Map<string, number>();
  for (const turn of turns) {
    if (turn.is_user || turn.speaker !== speaker) continue;
    for (const s of turn.stances || []) {
      const bucket = s.sign === "support" ? supports : concerns;
      bucket.set(s.option_id, (bucket.get(s.option_id) || 0) + 1);
    }
  }
  const top = (m: Map<string, number>) => {
    let id = "";
    let n = 0;
    for (const [k, v] of m) if (v > n) [id, n] = [k, v];
    return id;
  };
  // Full label, not a truncation: this line is only ever shown inside the
  // hover panel, which wraps. A "…" there hides exactly the words that would
  // tell the reader which option is meant.
  const label = (id: string) => (options.find((o) => o.id === id)?.label || "").trim();
  // A single supporting turn IS a position. Requiring two used to leave one
  // lane described and the others blank with no rule a reader could infer.
  const sup = top(supports);
  if (sup && label(sup)) return { kind: "supports", option: label(sup) };
  // Someone who only ever raised problems still has a stance worth naming.
  const con = top(concerns);
  if (con && label(con)) return { kind: "worries", option: label(con) };
  return null;
}

function buildLanes(turns: RiverTurn[], options: RiverOption[]): Lane[] {
  const lanes: Lane[] = [];
  let paletteIdx = 0;
  for (const turn of turns) {
    if (turn.is_user) continue;
    if (!lanes.some((l) => l.key === turn.speaker)) {
      lanes.push({
        key: turn.speaker,
        label: turn.speaker,
        focus: laneFocus(turns, turn.speaker, options),
        isUser: false,
        color: SPEAKER_PALETTE[paletteIdx % SPEAKER_PALETTE.length],
      });
      paletteIdx += 1;
    }
  }
  if (turns.some((t) => t.is_user)) {
    lanes.push({ key: "__user__", label: "", focus: null, isUser: true, color: USER_COLOR });
  }
  // All or nothing. One lane described and the rest blank gives the reader no
  // rule to infer, so an unreadable speaker suppresses the line everywhere.
  const agentLanes = lanes.filter((l) => !l.isUser);
  if (agentLanes.length && agentLanes.some((l) => !l.focus)) {
    agentLanes.forEach((l) => {
      l.focus = null;
    });
  }
  return lanes;
}

function laneTop(lane: number): number {
  return PAD_TOP + lane * (CARD_H + LANE_GAP);
}

function layoutRiver(turns: RiverTurn[], options: RiverOption[]): { nodes: NodePos[]; lanes: Lane[]; width: number; height: number } {
  const lanes = buildLanes(turns, options);
  const laneOf = (t: RiverTurn) =>
    Math.max(0, lanes.findIndex((l) => (t.is_user ? l.isUser : l.key === t.speaker)));
  let x = PAD_LEFT;
  const nodes: NodePos[] = [];
  for (const turn of turns) {
    const w = turn.key ? CARD_W : DOT_W;
    const lane = laneOf(turn);
    const h = turn.key ? CARD_H : DOT_W;
    const y = turn.key ? laneTop(lane) : laneTop(lane) + CARD_H / 2 - DOT_W / 2;
    nodes.push({ turn, x, w, y, h, lane });
    x += w + GAP_X;
  }
  const height = PAD_TOP + lanes.length * (CARD_H + LANE_GAP) + 60;
  return { nodes, lanes, width: x + 240, height };
}

/** Center Y of the empty corridor directly above lane `i`. */
function corridorY(i: number): number {
  return laneTop(i) - LANE_GAP / 2;
}

/**
 * Rounded orthogonal path: down/up the source X, along `midY`, into the
 * target. Both vertical runs sit at a card's center X — unoccupied in every
 * other lane — and the horizontal run stays in a corridor, so the path can
 * never disappear behind a card.
 */
function orthoPath(x1: number, y1: number, x2: number, y2: number, midY: number): string {
  const dx = x2 - x1;
  if (Math.abs(dx) < 2) return `M ${x1} ${y1} L ${x2} ${y2}`;
  const dirX = dx > 0 ? 1 : -1;
  const dirY1 = midY > y1 ? 1 : -1;
  const dirY2 = y2 > midY ? 1 : -1;
  const r = Math.max(
    2,
    Math.min(11, Math.abs(dx) / 2, Math.abs(midY - y1), Math.abs(y2 - midY)),
  );
  return [
    `M ${x1} ${y1}`,
    `V ${midY - dirY1 * r}`,
    `Q ${x1} ${midY} ${x1 + dirX * r} ${midY}`,
    `H ${x2 - dirX * r}`,
    `Q ${x2} ${midY} ${x2} ${midY + dirY2 * r}`,
    `V ${y2}`,
  ].join(" ");
}

type Side = "top" | "bottom";

type EdgePlan = {
  rel: RiverRelation;
  a: NodePos;
  b: NodePos;
  sameLane: boolean;
  down: boolean;
  sourceSide: Side;
  targetSide: Side;
  corridor: number;
  sx: number;
  tx: number;
  x0: number;
  x1: number;
  level: number;
};

type EdgeGeom = { rel: RiverRelation; d: string; chipX: number; chipY: number };

/** Evenly spread `count` ports across a node's width, inset from the corners. */
function portOffset(node: NodePos, slot: number, count: number): number {
  if (count <= 1) return node.x + node.w / 2;
  const inset = Math.min(20, node.w / 3);
  const span = node.w - inset * 2;
  return node.x + inset + (span * slot) / (count - 1);
}

/**
 * Assign every edge its ports, corridor and stagger level.
 *
 * Ports: grouped per (node, side) and ordered by the opposite endpoint's X —
 * the barycenter rule — so edges landing on one card fan out in the same order
 * as the cards they come from, and never swap over each other at the boundary.
 *
 * Levels: edges sharing a corridor and overlapping in X get separate levels
 * (shortest span innermost), which keeps parallel runs — several agents
 * answering the same user turn — from collapsing onto one line.
 */
function planEdges(relations: RiverRelation[], byIndex: Map<number, NodePos>): EdgePlan[] {
  type Draft = Omit<EdgePlan, "sx" | "tx" | "x0" | "x1" | "level">;
  const drafts: Draft[] = [];
  for (const rel of relations) {
    const a = byIndex.get(rel.from_index);
    const b = byIndex.get(rel.to_index);
    if (!a || !b) continue;
    const sameLane = a.lane === b.lane;
    const down = b.lane > a.lane;
    drafts.push({
      rel,
      a,
      b,
      sameLane,
      down,
      sourceSide: sameLane ? "top" : down ? "bottom" : "top",
      targetSide: sameLane ? "top" : down ? "top" : "bottom",
      // Same lane: the corridor above it. Cross-lane: the corridor adjacent to
      // the TARGET, so the long horizontal run lands next to what it answers.
      corridor: sameLane ? a.lane : down ? b.lane : b.lane + 1,
    });
  }

  type Attachment = { node: NodePos; otherX: number; draft: number; isSource: boolean };
  const groups = new Map<string, Attachment[]>();
  const push = (key: string, att: Attachment) => {
    const list = groups.get(key);
    if (list) list.push(att);
    else groups.set(key, [att]);
  };
  drafts.forEach((d, i) => {
    push(`${d.a.turn.id}:${d.sourceSide}`, {
      node: d.a,
      otherX: d.b.x + d.b.w / 2,
      draft: i,
      isSource: true,
    });
    push(`${d.b.turn.id}:${d.targetSide}`, {
      node: d.b,
      otherX: d.a.x + d.a.w / 2,
      draft: i,
      isSource: false,
    });
  });
  const portX = new Map<string, number>();
  for (const group of groups.values()) {
    group.sort((m, n) => m.otherX - n.otherX);
    group.forEach((att, slot) => {
      portX.set(
        `${att.draft}:${att.isSource ? "s" : "t"}`,
        portOffset(att.node, slot, group.length),
      );
    });
  }

  const plans: EdgePlan[] = drafts.map((d, i) => {
    const sx = portX.get(`${i}:s`) ?? d.a.x + d.a.w / 2;
    const tx = portX.get(`${i}:t`) ?? d.b.x + d.b.w / 2;
    return {
      ...d,
      sx,
      tx,
      x0: Math.min(sx, tx),
      x1: Math.max(sx, tx),
      level: 1,
    };
  });

  const bySpan = [...plans].sort((p1, p2) => p1.x1 - p1.x0 - (p2.x1 - p2.x0));
  const placed: EdgePlan[] = [];
  for (const p of bySpan) {
    let level = 1;
    for (const q of placed) {
      if (q.corridor === p.corridor && p.x0 < q.x1 && q.x0 < p.x1) {
        level = Math.max(level, q.level + 1);
      }
    }
    p.level = level;
    placed.push(p);
  }
  return plans;
}

function buildEdges(relations: RiverRelation[], byIndex: Map<number, NodePos>): EdgeGeom[] {
  const out: EdgeGeom[] = [];
  for (const p of planEdges(relations, byIndex)) {
    // Stagger inward from the corridor's far side, clamped so runs stay inside
    // the corridor no matter how many edges pile up.
    const offset = Math.min((p.level - 1) * EDGE_LEVEL_STEP, LANE_GAP / 2 - 14);
    if (p.sameLane) {
      const yBase = laneTop(p.a.lane) - 5;
      const lift = Math.min(18 + offset, LANE_GAP - 12);
      const d = `M ${p.sx} ${yBase} C ${p.sx} ${yBase - lift}, ${p.tx} ${yBase - lift}, ${p.tx} ${yBase}`;
      out.push({ rel: p.rel, d, chipX: (p.sx + p.tx) / 2, chipY: yBase - lift + 2 });
      continue;
    }
    const y1 = p.down ? p.a.y + p.a.h : p.a.y;
    const y2 = p.down ? p.b.y : p.b.y + p.b.h;
    const midY = corridorY(p.corridor) + (p.down ? -offset : offset);
    out.push({
      rel: p.rel,
      d: orthoPath(p.sx, y1, p.tx, y2, midY),
      chipX: (p.sx + p.tx) / 2,
      chipY: midY,
    });
  }
  return out;
}

export function DecisionRiver({
  river,
  lang = "en",
  userName,
  selectedId,
  onSelect,
  zoom,
  onZoomChange,
  pan,
  onPanChange,
  enterReady,
}: {
  river: RiverData;
  lang?: UiLang;
  userName?: string;
  selectedId?: string | null;
  onSelect: (id: string | null, kind: "turn" | null) => void;
  zoom: number;
  onZoomChange: (z: number) => void;
  pan: Pt;
  onPanChange: (p: Pt) => void;
  enterReady: boolean;
}) {
  const font = getUiFont(lang);
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startX: number; startY: number; origPan: Pt } | null>(null);
  const [hoverRel, setHoverRel] = useState<string | null>(null);
  const [hoverLane, setHoverLane] = useState<string | null>(null);
  // Which rail names are too long for their row. The fade that marks a cut has
  // to be conditional: applied unconditionally it dims the tail of every name,
  // including the ones that fit, which reads as a rendering fault.
  const railTextRefs = useRef<Record<string, HTMLSpanElement | null>>({});
  const [railClipped, setRailClipped] = useState<Record<string, boolean>>({});

  const turns = river.turns || [];
  const { nodes, lanes, width: worldW, height: worldH } = useMemo(
    () => layoutRiver(turns, river.options || []),
    [turns, river.options],
  );
  const byIndex = useMemo(() => {
    const m = new Map<number, NodePos>();
    nodes.forEach((n) => m.set(n.turn.index, n));
    return m;
  }, [nodes]);

  const relations = river.relations || [];
  const edges = useMemo(() => buildEdges(relations, byIndex), [relations, byIndex]);

  const optById = useMemo(() => {
    const m = new Map<string, RiverOption>();
    (river.options || []).forEach((o) => m.set(o.id, o));
    return m;
  }, [river.options]);

  // Phase bands cut at each transition turn, spanning all lanes.
  const bands = useMemo(() => {
    const cuts = (river.phases || [])
      .filter((p) => typeof p.message_index === "number")
      .map((p) => ({ index: p.message_index as number, to: p.to || "" }))
      .sort((a, b) => a.index - b.index);
    if (!nodes.length) return [] as { x0: number; x1: number; label: string }[];
    const out: { x0: number; x1: number; label: string }[] = [];
    let prevX = 0;
    let prevLabel = cuts.length ? "Exploration" : "";
    for (const c of cuts) {
      const node = byIndex.get(c.index);
      if (!node) continue;
      out.push({ x0: prevX, x1: node.x - GAP_X / 2, label: prevLabel });
      prevX = node.x - GAP_X / 2;
      prevLabel = c.to;
    }
    out.push({ x0: prevX, x1: worldW, label: prevLabel });
    return out.filter((b) => b.x1 - b.x0 > 4 && b.label);
  }, [river.phases, nodes, byIndex, worldW]);

  useEffect(() => {
    const next: Record<string, boolean> = {};
    for (const [key, el] of Object.entries(railTextRefs.current)) {
      if (el) next[key] = el.scrollHeight > el.clientHeight + 1;
    }
    setRailClipped((prev) => {
      const keys = Object.keys(next);
      const same =
        keys.length === Object.keys(prev).length && keys.every((k) => prev[k] === next[k]);
      return same ? prev : next;
    });
  }, [lanes, zoom, lang, userName]);

  const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

  const fitView = useCallback(() => {
    const el = viewportRef.current;
    if (!el || nodes.length === 0) return;
    const pad = 48;
    const bw = Math.max(1, worldW);
    const bh = Math.max(1, worldH);
    const vw = el.clientWidth;
    const vh = el.clientHeight;
    const z = clampZoom(Math.max(LEGIBLE_ZOOM, Math.min((vw - pad * 2) / bw, (vh - pad * 2) / bh, 1)));
    onZoomChange(z);
    // The rail is pinned to the left edge; start the timeline clear of it.
    onPanChange({ x: LANE_RAIL_W + LANE_RAIL_GAP, y: Math.max(8, (vh - bh * z) / 2) });
  }, [nodes.length, worldW, worldH, onPanChange, onZoomChange]);

  const layoutKey = `${turns.length}:${relations.length}:${lanes.length}`;
  const fittedKey = useRef("");
  useEffect(() => {
    if (!enterReady || nodes.length === 0) return;
    if (fittedKey.current === layoutKey) return;
    fittedKey.current = layoutKey;
    const timer = window.setTimeout(() => fitView(), 50);
    return () => window.clearTimeout(timer);
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
      onPanChange({ x: mx - (mx - pan.x) * scale, y: my - (my - pan.y) * scale });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [pan, zoom, onPanChange, onZoomChange]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0 && e.button !== 1) return;
    const target = e.target as HTMLElement;
    if (target.closest("[data-river-node]")) return;
    // A panel left open while the canvas slides under it points at the wrong row.
    setHoverLane(null);
    dragRef.current = { startX: e.clientX, startY: e.clientY, origPan: { ...pan } };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    onSelect(null, null);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    onPanChange({ x: d.origPan.x + (e.clientX - d.startX), y: d.origPan.y + (e.clientY - d.startY) });
  };
  const onPointerUp = (e: React.PointerEvent) => {
    dragRef.current = null;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  // Zoomed out, a card shows one line instead of three. Not a mode the reader
  // has to learn — the text just gets shorter as the cards get smaller.
  const summaryLines = zoom < KEYWORD_ZOOM ? 1 : 3;
  const hoveredEdge = edges.find((e) => e.rel.id === hoverRel) || null;
  const hoveredFrom = hoveredEdge ? byIndex.get(hoveredEdge.rel.from_index) : null;
  const hoveredTo = hoveredEdge ? byIndex.get(hoveredEdge.rel.to_index) : null;

  return (
    <div
      ref={viewportRef}
      className="relative flex-1 min-h-0 overflow-hidden cursor-grab active:cursor-grabbing"
      onPointerDown={onPointerDown}
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
        {/* Phase bands span all lanes */}
        {bands.map((b, i) => (
          <div
            key={`band-${i}`}
            className="absolute top-0 bottom-0"
            style={{
              left: b.x0,
              width: b.x1 - b.x0,
              background: i % 2 === 1 ? "rgba(21,96,168,0.035)" : "transparent",
              borderLeft: i > 0 ? "1px dashed rgba(0,0,0,0.10)" : "none",
            }}
          >
            <span
              className={`absolute top-2 left-2 text-[10px] text-black/35 ${labelCaseClass(lang)}`}
              style={font as CSSProperties}
            >
              {phaseLabel(lang, b.label) || b.label}
            </span>
          </div>
        ))}

        {/* Lane guides */}
        {lanes.map((lane, i) => (
          <div
            key={`lane-${lane.key}`}
            className="absolute"
            style={{
              left: 0,
              right: 0,
              top: laneTop(i) + CARD_H / 2,
              height: 1,
              background: "rgba(0,0,0,0.05)",
            }}
          />
        ))}

        {/* Reply edges */}
        <svg className="absolute inset-0 pointer-events-none" width={worldW} height={worldH} aria-hidden>
          <defs>
            {ARROW_MARKERS.map((m) => (
              <marker
                key={m.id}
                id={m.id}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                markerUnits="userSpaceOnUse"
                orient="auto"
              >
                <path d="M 0 1 L 10 5 L 0 9 z" fill={m.color} />
              </marker>
            ))}
          </defs>
          {edges.map(({ rel, d }) => {
            const st = edgeStyle(rel);
            const active = hoverRel === rel.id;
            return (
              <motion.path
                key={rel.id}
                d={d}
                fill="none"
                stroke={st.stroke}
                strokeWidth={active ? st.width + 1 : st.width}
                strokeDasharray={st.dash}
                strokeLinecap="round"
                markerEnd={`url(#${st.marker})`}
                initial={enterReady ? { opacity: 0 } : false}
                animate={{ opacity: enterReady ? (hoverRel && !active ? 0.22 : 0.9) : 0 }}
                transition={{ duration: 0.25, delay: enterReady ? 0.15 : 0 }}
              />
            );
          })}
        </svg>

        {/* Kind chips at each edge midpoint (hover target) */}
        {edges.map(({ rel, chipX, chipY }) => {
          const st = edgeStyle(rel);
          return (
            <button
              key={`chip-${rel.id}`}
              type="button"
              data-river-node
              onMouseEnter={() => setHoverRel(rel.id)}
              onMouseLeave={() => setHoverRel(null)}
              onClick={(e) => {
                e.stopPropagation();
                const from = turns.find((x) => x.index === rel.from_index);
                if (from) onSelect(from.id, "turn");
              }}
              className="absolute px-1.5 py-0.5 rounded-full border text-[9px] leading-none bg-white whitespace-nowrap"
              style={{
                left: chipX - 24,
                top: chipY - 9,
                borderColor: st.chip,
                color: st.chip,
                fontFamily: (font as CSSProperties).fontFamily,
              }}
            >
              {edgeWord(lang, rel.kind)}
            </button>
          );
        })}

        {/* Rationale tooltip for the hovered edge */}
        {hoveredEdge && hoveredFrom && hoveredTo && (
          <div
            className="absolute z-30 w-[240px] rounded-[6px] border border-black/15 bg-white shadow-[0_10px_28px_rgba(0,0,0,0.14)] px-2.5 py-2 pointer-events-none"
            style={{
              left: hoveredEdge.chipX - 60,
              top: hoveredEdge.chipY - 84,
              fontFamily: (font as CSSProperties).fontFamily,
            }}
          >
            <p className="text-[10px] text-black/55">
              <span className="text-black">
                {hoveredFrom.turn.is_user ? userLabel(lang, userName) : hoveredFrom.turn.speaker}
              </span>
              <span className="mx-1" style={{ color: edgeStyle(hoveredEdge.rel).chip }}>
                {edgeWord(lang, hoveredEdge.rel.kind)}
              </span>
              <span className="text-black">
                {hoveredTo.turn.is_user ? userLabel(lang, userName) : hoveredTo.turn.speaker}
              </span>
            </p>
            {/* A turn only carries a rationale when the model emitted one; when
                it did not, show what was replied TO rather than leaving the
                hover as a bare "A replied B", which reads as a broken tooltip. */}
            {hoveredFrom.turn.rationale ? (
              <p className="text-[10px] text-black/70 mt-1 leading-snug">
                “{hoveredFrom.turn.rationale}”
              </p>
            ) : (
              <p className="text-[10px] text-black/60 mt-1 leading-snug">
                <span className="text-black/40">{t(lang, "map.tooltip.repliedTo")} </span>
                {hoveredTo.turn.summary || hoveredTo.turn.fallback_text}
              </p>
            )}
          </div>
        )}

        {/* Turn nodes */}
        {nodes.map(({ turn, x, w, y, lane }, ni) => {
          const selected = selectedId === turn.id;
          const color = lanes[lane]?.color || "rgba(0,0,0,0.5)";
          const delay = Math.min(0.5, 0.05 + ni * 0.018);
          if (!turn.key) {
            return (
              <motion.button
                key={turn.id}
                type="button"
                data-river-node
                title={`#${turn.index} ${turn.speaker}: ${turn.fallback_text}`}
                initial={enterReady ? { opacity: 0, scale: 0.8 } : false}
                animate={enterReady ? { opacity: 1, scale: 1 } : { opacity: 0 }}
                transition={{ duration: 0.2, delay: enterReady ? delay : 0 }}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(turn.id, "turn");
                }}
                className={`absolute rounded-full border bg-white ${selected ? "ring-2 ring-black/20" : ""}`}
                style={{
                  left: x,
                  top: y,
                  width: DOT_W,
                  height: DOT_W,
                  borderColor: "rgba(0,0,0,0.14)",
                }}
              >
                <span
                  className="absolute inset-[6px] rounded-full"
                  style={{ background: color, opacity: 0.45 }}
                />
              </motion.button>
            );
          }
          const summaryText = turn.summary || turn.fallback_text;
          const stanceOpt = turn.stance ? optById.get(turn.stance.option_id) : null;
          const choiceBadge = turn.badges?.choice;
          return (
            <motion.button
              key={turn.id}
              type="button"
              data-river-node
              initial={enterReady ? { opacity: 0, y: 10 } : false}
              animate={enterReady ? { opacity: 1, y: 0 } : { opacity: 0 }}
              transition={{ duration: 0.24, delay: enterReady ? delay : 0, ease: [0.22, 1, 0.36, 1] }}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(turn.id, "turn");
              }}
              className={`absolute text-left rounded-[10px] border overflow-hidden ${
                turn.is_user ? "bg-[#10151b]" : "bg-white"
              } ${selected ? "border-black/45 ring-2 ring-black/12" : "border-black/12 hover:border-black/30"}`}
              style={{
                left: x,
                top: y,
                width: w,
                height: CARD_H,
                boxShadow: "0 1px 0 rgba(0,0,0,0.04), 0 8px 20px rgba(0,0,0,0.06)",
                fontFamily: (font as CSSProperties).fontFamily,
              }}
            >
              {/* Stance rides the card's left border as pure color — a chip
                  spelling out "▲ Join NovaAI" costs a line of reading for
                  something the verdict banner already says. */}
              {stanceOpt && (
                <span
                  className="absolute left-0 top-0 bottom-0 w-[3px]"
                  style={{ background: turn.stance!.sign === "support" ? "#059669" : "#b45309" }}
                />
              )}
              <div className="h-[3px]" style={{ background: color }} />
              <div className="px-2.5 py-2 h-[calc(100%-3px)] flex flex-col">
                <p
                  className={`text-[11.5px] leading-snug ${
                    turn.is_user ? "text-white/90" : "text-black/85"
                  } ${turn.has_summary ? "" : "italic opacity-75"}`}
                  style={{
                    display: "-webkit-box",
                    WebkitLineClamp: summaryLines,
                    WebkitBoxOrient: "vertical",
                    overflow: "hidden",
                  }}
                >
                  {summaryText}
                </p>
                {/* The one badge worth permanent space: the decision itself. */}
                {choiceBadge && (
                  <span
                    className="mt-auto self-start px-1.5 py-[2px] rounded-[4px] text-[9px] text-white"
                    style={{ background: "#059669" }}
                  >
                    ✓ {shortLabel(choiceBadge.label, 16)}
                  </span>
                )}
              </div>
            </motion.button>
          );
        })}

        {nodes.length === 0 && (
          <div
            className="absolute left-1/2 top-1/3 -translate-x-1/2 text-[12px] text-black/40"
            style={font}
          >
            {t(lang, "map.emptySmart")}
          </div>
        )}
      </div>

      {/* The lane rail: one opaque strip per row, pinned to the viewport's left
          edge and tracking pan/zoom so it stays aligned to the cards in its
          row. Opaque on purpose — panning is unbounded, so a translucent rail
          would show cards sliding underneath the names.

          The name is set with writing-mode: vertical-rl, which turns Latin 90°
          clockwise and stacks CJK upright — the correct vertical setting for
          each script, and something transform: rotate(90deg) cannot do (it
          would lay 中文 on its side, and rotation does not affect layout, so
          the strip could not size itself to the type).

          A name too long for its row is clipped under a fade, never an "…":
          the ellipsis costs a character's width to say "there is more" while
          the fade says it for free, and the full text is one hover away. */}
      {lanes.map((lane, i) => {
        const top = pan.y + laneTop(i) * zoom;
        const height = Math.max(48, CARD_H * zoom);
        const name = lane.isUser ? userLabel(lang, userName) : lane.label;
        const open = hoverLane === lane.key;
        return (
          <div
            key={`lanerail-${lane.key}`}
            className="absolute left-0"
            style={{ top, height, fontFamily: (font as CSSProperties).fontFamily }}
            onMouseEnter={() => setHoverLane(lane.key)}
            onMouseLeave={() => setHoverLane(null)}
          >
            <motion.div
              initial={false}
              animate={{
                backgroundColor: open ? "#ffffff" : "#fbfbfa",
                borderColor: open ? withAlpha(lane.color, 0.45) : "rgba(0,0,0,0.10)",
              }}
              transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
              className="h-full flex flex-col items-center rounded-r-[8px] border border-l-0 overflow-hidden"
              style={{ width: LANE_RAIL_W }}
            >
              <motion.span
                className="rounded-full flex-shrink-0 mt-1.5 mb-1"
                initial={false}
                animate={{ width: open ? 8 : 6, height: open ? 8 : 6 }}
                transition={{ duration: 0.16 }}
                style={{ background: lane.color }}
              />
              <span
                ref={(el) => {
                  railTextRefs.current[lane.key] = el;
                }}
                // In vertical writing mode the line box's *thickness* is
                // horizontal, so line-height governs the column's width. At
                // leading-none the column is 11px while the glyphs need ~14,
                // and every letter gets shaved on both sides.
                className="flex-1 min-h-0 overflow-hidden text-[11px] leading-[1.6] tracking-wide text-black/75"
                style={{
                  writingMode: "vertical-rl",
                  textOrientation: "mixed",
                  whiteSpace: "nowrap",
                  // Fade the cut instead of stamping an ellipsis on it, and only
                  // when there is a cut — the rest of the text is at full weight.
                  ...(railClipped[lane.key]
                    ? {
                        maskImage: "linear-gradient(to bottom, #000 calc(100% - 16px), transparent)",
                        WebkitMaskImage:
                          "linear-gradient(to bottom, #000 calc(100% - 16px), transparent)",
                      }
                    : null),
                }}
              >
                {name}
              </span>
            </motion.div>

            <AnimatePresence>
              {open && (
                <motion.div
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -6 }}
                  transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
                  className="absolute top-0 z-20 rounded-[9px] bg-white border border-black/12 shadow-[0_6px_20px_rgba(0,0,0,0.10)] px-3 py-2 pointer-events-none"
                  style={{ left: LANE_RAIL_W + 6, width: LANE_RAIL_OPEN_W }}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ background: lane.color }}
                    />
                    <span className="text-[12px] text-black leading-snug">{name}</span>
                  </span>
                  {lane.focus && (
                    <span className="block text-[11px] text-black/60 leading-snug mt-1">
                      {t(lang, lane.focus.kind === "supports" ? "map.lane.focus" : "map.lane.worry")}{" "}
                      <span className="text-black/80">{lane.focus.option}</span>
                    </span>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}

      <button type="button" className="hidden" data-map-fit onClick={fitView} aria-hidden />
    </div>
  );
}

/** Verdict strip above the canvas: the 10-second takeaway. */
/**
 * The key — the whole grammar of the picture in one line, no clicking.
 *
 * It lives in the footer, not on the canvas. On the canvas it was a sibling of
 * the world layer with no z-index, so it painted over the cards; since panning
 * is unbounded, any card could be dragged into the strip and collide with it.
 * Moving it out of the canvas removes the collision by construction rather than
 * by fighting it with z-index or pan clamps.
 *
 * It stays in this file so the swatch colors sit next to the edge colors they
 * describe (see edgeStyle / ARROW_MARKERS above).
 */
export function RiverKeyStrip({ lang = "en" }: { lang?: UiLang }) {
  const font = getUiFont(lang);
  return (
    <div
      className="flex items-center gap-x-3 gap-y-0.5 flex-wrap text-[10px] text-black/60 leading-relaxed"
      style={font as CSSProperties}
    >
      <span>{t(lang, "map.key.rows")}</span>
      <span className="text-black/25" aria-hidden>·</span>
      <span>{t(lang, "map.key.time")}</span>
      <span className="text-black/25" aria-hidden>·</span>
      <span className="inline-flex items-center gap-1">
        <svg width="16" height="6" aria-hidden className="flex-shrink-0">
          <path d="M0 5 Q 8 -1 16 5" fill="none" stroke="rgba(0,0,0,0.55)" strokeWidth="1.3" />
        </svg>
        {t(lang, "map.key.line")}
      </span>
      <span className="text-black/25" aria-hidden>·</span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block w-3 h-[2px] rounded flex-shrink-0"
          style={{ background: "#dc2626" }}
        />
        {t(lang, "map.key.red")}
      </span>
    </div>
  );
}

export function RiverVerdictBanner({
  river,
  lang = "en",
  onPickTurn,
}: {
  river: RiverData;
  lang?: UiLang;
  onPickTurn: (turnId: string) => void;
}) {
  const font = getUiFont(lang);
  const v = river.verdict;
  const turnsById = useMemo(() => {
    const m = new Map<string, RiverTurn>();
    river.turns.forEach((turn) => m.set(turn.id, turn));
    return m;
  }, [river.turns]);
  const whyTurns = (v.why_turn_ids || [])
    .map((id) => turnsById.get(id))
    .filter(Boolean) as RiverTurn[];
  const optById = useMemo(() => {
    const m = new Map<string, RiverOption>();
    river.options.forEach((o) => m.set(o.id, o));
    return m;
  }, [river.options]);

  if (v.undecided) {
    const entries = Object.entries(v.counts || {});
    if (!entries.length && !river.options.length) return null;
    return (
      <div className="flex-shrink-0 border-b border-black/8 bg-white/95 px-4 py-2" style={font}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[9px] tracking-widest text-[var(--app-muted-text)] ${labelCaseClass(lang)}`}>
            {t(lang, "map.verdict.leaning")}
          </span>
          <span className="text-[11px] text-black/60">{t(lang, "map.verdict.undecided")}</span>
          {entries.map(([oid, c]) => {
            const label = optById.get(oid)?.label || oid;
            return (
              <span
                key={oid}
                className="px-2 py-0.5 rounded-[5px] bg-black/[0.04] text-[10px] text-black/70"
                title={label}
              >
                {shortLabel(label, 22)}
                <span className="text-[#059669] ml-1">▲{c.support}</span>
                {c.concern > 0 && <span className="text-[#b45309] ml-1">⚠{c.concern}</span>}
              </span>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-shrink-0 border-b border-black/8 bg-white/95 px-4 py-2" style={font}>
      <div className="flex items-start gap-3 flex-wrap">
        <div className="min-w-0">
          <p className={`text-[9px] tracking-widest text-[var(--app-muted-text)] ${labelCaseClass(lang)}`}>
            {t(lang, "map.verdict.chosen")}
          </p>
          <p className="text-[12px] text-black mt-0.5">
            <span className="inline-block w-2 h-2 rounded-full bg-[#059669] mr-1.5 align-middle" />
            {v.chosen_label}
          </p>
        </div>
        {whyTurns.length > 0 && (
          <div className="min-w-0 flex-1">
            <p className={`text-[9px] tracking-widest text-[var(--app-muted-text)] ${labelCaseClass(lang)}`}>
              {t(lang, "map.verdict.why")}
            </p>
            <div className="flex gap-1.5 flex-wrap mt-0.5">
              {whyTurns.map((turn) => (
                <button
                  key={turn.id}
                  type="button"
                  onClick={() => onPickTurn(turn.id)}
                  className="max-w-[300px] truncate px-2 py-0.5 rounded-[5px] bg-black/[0.04] hover:bg-black/[0.08] text-[10px] text-black/75 text-left"
                  title={turn.summary || turn.fallback_text}
                >
                  {turn.speaker}: {turn.summary || turn.fallback_text}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
