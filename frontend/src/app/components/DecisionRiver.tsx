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
const LANE_GAP = 116; // corridor between lanes: edge runs + kind chips live here
// Vertical stagger between edges sharing a corridor. This has to clear a chip's
// full height with room to spare, not just its baseline: at 16 two parallel runs
// were closer together than the labels riding on them were tall, so a label sat
// in the gutter between two lines and belonged visibly to neither.
// LANE_GAP must stay >= 2 * (EDGE_LEVEL_STEP * maxLevels) + 28 or the clamp in
// buildEdges collapses the outer levels back onto each other.
const EDGE_LEVEL_STEP = 24;
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

/** A vertical run of an orthogonal edge, in world units. */
type VSeg = { x: number; y0: number; y1: number };
/** The horizontal run an edge's label rides, in world units. */
type HSeg = { y: number; x0: number; x1: number };

type EdgeGeom = {
  rel: RiverRelation;
  d: string;
  chipX: number;
  chipY: number;
  /** Range along this edge the chip may slide within to dodge its neighbours. */
  chipMin: number;
  chipMax: number;
  /**
   * This edge's OWN vertical runs. A chip always sits between its own two
   * verticals, so they are never an ambiguity — they have to be excluded from
   * the junction test or every short edge looks like a collision.
   */
  verts: VSeg[];
  /**
   * This edge's own horizontal run. Sliding along a line cannot escape a line
   * PARALLEL to it, so a neighbouring run grazing the pill has to be scored
   * against — and a parallel line touching a label reads as the label's own.
   */
  horiz: HSeg | null;
};

/**
 * Where along its own line a chip prefers to sit, as a fraction of the span.
 *
 * Starting every chip at its midpoint makes stacking the default and leaves
 * spreadChips to undo it one collision at a time — which only ever separates
 * labels that already overlap, never the ones that merely sit close enough to
 * be ambiguous. Keying the preferred spot to the corridor level instead means
 * edges running parallel are staggered before any collision test runs.
 */
const CHIP_BIAS = [0.5, 0.32, 0.68, 0.41, 0.59];

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
  /** Preferred chip spot for this edge's level, clamped to where it may sit. */
  const biased = (level: number, lo: number, hi: number) => {
    const f = CHIP_BIAS[(level - 1) % CHIP_BIAS.length];
    return lo + (hi - lo) * f;
  };
  const plans = planEdges(relations, byIndex);
  // Deepest level each corridor actually has to hold. Clamping the offset to a
  // ceiling — as `min((level-1)*STEP, room)` did — does not keep runs inside
  // the corridor, it stacks levels 3, 4 and 5 onto the SAME line: two distinct
  // relations drawn as one, each with its own label, and no placement rule can
  // recover which is which. Compressing the step instead keeps every level on
  // a line of its own, which is the property the labels depend on.
  const deepest = new Map<number, number>();
  for (const p of plans) {
    deepest.set(p.corridor, Math.max(deepest.get(p.corridor) || 1, p.level));
  }
  const ROOM = LANE_GAP / 2 - 14;

  for (const p of plans) {
    const rungs = Math.max(1, (deepest.get(p.corridor) || 1) - 1);
    const step = Math.min(EDGE_LEVEL_STEP, ROOM / rungs);
    const offset = (p.level - 1) * step;
    if (p.sameLane) {
      const yBase = laneTop(p.a.lane) - 5;
      // Corridor 0 is only PAD_TOP tall, not LANE_GAP, and the phase-band
      // label sits in its top ~22 units. Without this the deepest lane-0 arc
      // put its label at y = -1 (off canvas) before the apex fix and on top of
      // the phase label after it.
      const headroom = (p.a.lane === 0 ? PAD_TOP - 28 : LANE_GAP - 12) - 6;
      const maxLift = Math.max(24, headroom / 0.75);
      // Same compression as the corridor rungs above, for the same reason:
      // clamping to maxLift would land levels 2 and 3 on an identical arc in
      // the shallow corridor 0, drawing two relations as one curve.
      const arcStep = Math.min(EDGE_LEVEL_STEP, (maxLift - 18) / rungs);
      const lift = 18 + (p.level - 1) * arcStep;
      const d = `M ${p.sx} ${yBase} C ${p.sx} ${yBase - lift}, ${p.tx} ${yBase - lift}, ${p.tx} ${yBase}`;
      // Only the middle of the arc is flat enough to sit a chip on; the ends
      // dive toward the cards.
      const lo = Math.min(p.sx, p.tx);
      const hi = Math.max(p.sx, p.tx);
      // The chip has to sit ON the curve, and a cubic does not reach its
      // control points: with both controls at yBase-lift the arc peaks at
      // yBase - 0.75*lift. Placing the chip at yBase-lift+2 left it floating
      // 2.5 units above its own line at level 1 and 13.5 at level 3 — a label
      // attached to nothing, which is the very confusion being fixed here.
      // An x-inset of 0.39*span keeps it within ~1 unit of the curve at every
      // lift the corridor allows.
      const inset = (hi - lo) * 0.39;
      out.push({
        rel: p.rel,
        d,
        chipX: biased(p.level, lo + inset, hi - inset),
        chipY: yBase - lift * 0.75,
        chipMin: lo + inset,
        chipMax: hi - inset,
        // An arc has no straight `V` run, but it leaves and re-enters the lane
        // vertically, so its two ends occlude like verticals and have to be in
        // the obstacle set — otherwise a neighbouring chip parks on one.
        verts: [
          { x: p.sx, y0: yBase - lift * 0.55, y1: yBase },
          { x: p.tx, y0: yBase - lift * 0.55, y1: yBase },
        ],
        // The flat middle of the arc, where a label can ride it.
        horiz: { y: yBase - lift * 0.75, x0: lo + inset, x1: hi - inset },
      });
      continue;
    }
    const y1 = p.down ? p.a.y + p.a.h : p.a.y;
    const y2 = p.down ? p.b.y : p.b.y + p.b.h;
    const midY = corridorY(p.corridor) + (p.down ? -offset : offset);
    const lo = Math.min(p.sx, p.tx) + 14;
    const hi = Math.max(p.sx, p.tx) - 14;
    out.push({
      rel: p.rel,
      d: orthoPath(p.sx, y1, p.tx, y2, midY),
      chipX: biased(p.level, lo, hi),
      chipY: midY,
      chipMin: lo,
      chipMax: hi,
      // The two runs orthoPath drops out of the source and into the target.
      // Every one of these can cross some OTHER edge's corridor, which is
      // exactly how a label ends up sitting on a line that is not its own.
      verts: [
        { x: p.sx, y0: Math.min(y1, midY), y1: Math.max(y1, midY) },
        { x: p.tx, y0: Math.min(midY, y2), y1: Math.max(midY, y2) },
      ],
      horiz: { y: midY, x0: Math.min(p.sx, p.tx) + 11, x1: Math.max(p.sx, p.tx) - 11 },
    });
  }
  return out;
}

/**
 * Chips within this many world units of each other vertically can collide.
 * Kept just above EDGE_LEVEL_STEP so chips one level apart still push each
 * other sideways: vertically separated is not the same as unambiguous, and two
 * labels stacked at the same X read as a pair whichever line they sit on.
 */
const CHIP_BAND = EDGE_LEVEL_STEP + 4;
/**
 * Chip width, measured rather than guessed. In Share Tech Mono at 9px a Latin
 * glyph advances 4.86 world units and a CJK glyph 9.0, and the pill adds
 * exactly 14 for its padding and border. The old single 5.6 constant
 * over-reserved Latin by 15% (harmless) but UNDER-reserved Chinese by 20%,
 * which meant every clearance guarantee below was quietly false in zh.
 */
const CHIP_CHAR_W_LATIN = 4.86;
const CHIP_CHAR_W_CJK = 9.0;
const CHIP_CHROME_W = 14;
const CJK_RE = /[⺀-鿿　-ヿ가-힯＀-￯]/;
/** Half the chip's own height in world units (9px text + padding + border). */
const CHIP_HALF_H = 8;
/**
 * Clear space demanded around a chip. A gap has to read as a gap: auto-fit
 * never goes below LEGIBLE_ZOOM, so 8 world units is the 6 screen pixels
 * that stays visible at the smallest size the reader is ever shown.
 */
const CHIP_PAD = 8;
/** Granularity of the slide search along a line. */
const CHIP_STEP = 4;

/** Rendered width of a chip in world units, before layout. */
function chipWidth(word: string): number {
  let w = CHIP_CHROME_W;
  for (const ch of word) w += CJK_RE.test(ch) ? CHIP_CHAR_W_CJK : CHIP_CHAR_W_LATIN;
  return w;
}

/**
 * Place every edge label so it sits on its own line and on nothing else.
 *
 * Two separate ambiguities are being solved here, and they need different
 * remedies:
 *
 * 1. Two labels stacked on top of each other read as one blob. Fixed by the
 *    per-level CHIP_BIAS at build time plus the chip-vs-chip test below.
 *
 * 2. A label sitting where two lines cross cannot say which line it belongs
 *    to. This is the harder one and it is structural: an edge reaching a
 *    non-adjacent lane must cross every corridor in between, so its vertical
 *    run passes straight through the horizontal run of any edge living in that
 *    corridor. Measured on two real rooms, 4 of 17 labels sat on a foreign
 *    line this way. No amount of chip-vs-chip spreading can see it, because
 *    the obstacle is not a chip.
 *
 * So the search treats three things as obstacles: other chips, other edges'
 * vertical runs, and the phase-band dividers (full-height dashed rules that
 * look near-identical to a neutral reply line). A chip's OWN verticals are
 * excluded — a label always sits between its own two elbows, and that is never
 * confusing.
 *
 * A chip may still only move along the line it labels, so the fix can never
 * make a label point at the wrong edge. Lines are placed shortest-first: a
 * short run has almost no freedom, so it should claim one of its few legal
 * spots before a long run takes it.
 *
 * When no position on the whole line is clean, the chip does not give up and
 * sit wherever it started — that is the reported bug reproduced verbatim in
 * the cases sliding cannot win. It goes to the LEAST misreadable position
 * instead, and the ranking is deliberately asymmetric: a line passing through
 * the middle of the pill reads as passing behind it, while the same line
 * grazing the pill's border reads as attached to it. A near miss is the
 * confident lie, so if a chip must be crossed, it is crossed squarely.
 */
function spreadChips(edges: EdgeGeom[], lang: UiLang, dividerXs: number[] = []): EdgeGeom[] {
  const width = (e: EdgeGeom) => chipWidth(edgeWord(lang, e.rel.kind));
  const verts = edges.flatMap((e, i) => e.verts.map((v) => ({ ...v, owner: i })));
  const horizs = edges
    .map((e, i) => (e.horiz ? { ...e.horiz, owner: i } : null))
    .filter((h): h is HSeg & { owner: number } => !!h);
  // Least freedom first, then top-to-bottom for a stable order.
  const order = edges
    .map((e, i) => ({ e, i }))
    .sort(
      (m, n) =>
        m.e.chipMax - m.e.chipMin - (n.e.chipMax - n.e.chipMin) ||
        m.e.chipY - n.e.chipY ||
        m.e.chipX - n.e.chipX,
    );
  const out = edges.slice();
  const placed: { x: number; y: number; half: number }[] = [];

  for (const { e, i } of order) {
    const half = width(e) / 2;
    // A run shorter than the two 14-unit insets inverts the range (min > max).
    // Collapse it to the midpoint rather than letting the clamp below snap the
    // chip past the end of the line it labels.
    const raw0 = Math.min(e.chipMin, e.chipMax);
    const raw1 = Math.max(e.chipMin, e.chipMax);
    const mid = (e.chipMin + e.chipMax) / 2;
    const degenerate = e.chipMax < e.chipMin;
    const lo = degenerate ? mid : raw0;
    const hi = degenerate ? mid : raw1;
    const y = e.chipY;

    /**
     * How badly a position misreads. 0 means nothing else touches the pill.
     * A crossing dead through the middle scores 1; anything else scores 3,
     * because a line stopping at the pill's edge looks like it belongs to it.
     */
    const penalty = (x: number) => {
      const bx0 = x - half - CHIP_PAD;
      const bx1 = x + half + CHIP_PAD;
      const by0 = y - CHIP_HALF_H - CHIP_PAD;
      const by1 = y + CHIP_HALF_H + CHIP_PAD;
      let score = 0;
      const crossing = (lineX: number) => {
        const d = Math.abs(lineX - x);
        if (d >= half + CHIP_PAD) return 0; // outside the pill entirely
        return d <= 4 ? 1 : 3; // through the middle vs grazing the border
      };
      for (const v of verts) {
        if (v.owner === i) continue;
        if (v.x >= bx0 && v.x <= bx1 && v.y0 <= by1 && v.y1 >= by0) score += crossing(v.x);
      }
      for (const dx of dividerXs) {
        if (dx >= bx0 && dx <= bx1) score += crossing(dx);
      }
      // A parallel line can never be escaped by sliding, and one grazing the
      // pill reads as the pill's own line — always the bad reading, never a
      // "passing behind".
      for (const h of horizs) {
        if (h.owner === i) continue;
        if (Math.abs(h.y - y) <= CHIP_HALF_H + CHIP_PAD && h.x0 <= bx1 && h.x1 >= bx0) score += 3;
      }
      for (const p of placed) {
        if (Math.abs(p.y - y) < CHIP_BAND && Math.abs(p.x - x) < p.half + half + 6) score += 3;
      }
      return score;
    };

    // Scan outward from the preferred spot and take the nearest clean one.
    // Scanning beats the old push-past-the-hit walk: pushing could only ever
    // move right then left by whole obstacle widths, so it stepped over narrow
    // gaps a label would have fitted in and gave up while room remained.
    let x = e.chipX;
    if (penalty(x) > 0) {
      const reach = hi - lo;
      // Seeded with the preferred spot at distance 0, so an equally-bad
      // candidate can never displace it — the chip only moves when moving
      // actually reads better.
      let best = e.chipX;
      let bestScore = penalty(e.chipX);
      let bestDist = 0;
      for (let d = CHIP_STEP; d <= reach + CHIP_STEP && bestScore > 0; d += CHIP_STEP) {
        for (const cand of [Math.min(hi, e.chipX + d), Math.max(lo, e.chipX - d)]) {
          if (cand < lo || cand > hi) continue;
          const s = penalty(cand);
          const dist = Math.abs(cand - e.chipX);
          if (s < bestScore || (s === bestScore && dist < bestDist)) {
            best = cand;
            bestScore = s;
            bestDist = dist;
          }
          if (bestScore === 0) break;
        }
      }
      x = best;
    }
    x = Math.max(lo, Math.min(hi, x));
    placed.push({ x, y, half });
    out[i] = { ...e, chipX: x };
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

  const optById = useMemo(() => {
    const m = new Map<string, RiverOption>();
    (river.options || []).forEach((o) => m.set(o.id, o));
    return m;
  }, [river.options]);

  // Phase bands cut at each transition turn, spanning all lanes.
  // Computed BEFORE the edges: every band after the first draws a full-height
  // dashed rule, which is one more line a label can land on, so chip placement
  // needs their Xs. There is no cycle — bands depend only on nodes/phases.
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

  // The Xs actually drawn as dividers: the left edge of every band but the
  // first, taken AFTER the filter above. Re-deriving them from river.phases
  // would list rules that were filtered out and never painted.
  const dividerXs = useMemo(() => bands.slice(1).map((b) => b.x0), [bands]);

  const relations = river.relations || [];
  const edges = useMemo(
    () => spreadChips(buildEdges(relations, byIndex), lang, dividerXs),
    [relations, byIndex, lang, dividerXs],
  );

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
    // Panning is a drag over text, so the browser starts selecting instead and
    // the canvas ends up striped with selection highlight. Turning selection
    // off imperatively (not via state) matters: a re-render is not guaranteed
    // to land before the first pointermove, and by then the selection has
    // already begun. Restored on pointerup, so card text stays selectable.
    e.preventDefault();
    const host = e.currentTarget as HTMLElement;
    host.style.userSelect = "none";
    window.getSelection()?.removeAllRanges();
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
    (e.currentTarget as HTMLElement).style.userSelect = "";
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
              className="absolute px-1.5 py-0.5 rounded-full border text-[9px] leading-none bg-white whitespace-nowrap -translate-x-1/2 -translate-y-1/2"
              style={{
                left: chipX,
                top: chipY,
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
            {/* Both ends, not the rationale. The header above gives two NAMES; an
                arc is about the PAIR, so the thing the reader cannot get from it
                is what each end actually said — and at low zoom the endpoint cards
                are collapsed or off-screen. The agent's private motive answers a
                second-order question and lives on click (DecisionMapPanel), where
                there is room for it under the summary. */}
            <p className="text-[10px] text-black/70 mt-1 leading-snug">
              {hoveredFrom.turn.summary || hoveredFrom.turn.fallback_text}
            </p>
            <p className="text-[10px] text-black/60 mt-1 leading-snug">
              <span className="text-black/40">{t(lang, "map.tooltip.repliedTo")} </span>
              {hoveredTo.turn.summary || hoveredTo.turn.fallback_text}
            </p>
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
/**
 * A key swatch that actually looks like the thing it explains: a straight line
 * ending in an arrowhead, dashed or solid, in the edge's own color.
 *
 * The previous reply swatch was a drawn arc, which no edge on the canvas is —
 * cross-lane edges are orthogonal and only same-lane ones curve — and it
 * carried no arrowhead even though direction is the whole point of the line.
 */
function KeyArrow({ color, dash }: { color: string; dash?: string }) {
  return (
    <svg width="22" height="8" aria-hidden className="flex-shrink-0">
      <line x1="0" y1="4" x2="15" y2="4" stroke={color} strokeWidth="1.4" strokeDasharray={dash} />
      <path d="M14.5 1 L20.5 4 L14.5 7 Z" fill={color} />
    </svg>
  );
}

export function RiverKeyStrip({ lang = "en" }: { lang?: UiLang }) {
  const font = getUiFont(lang);
  // Every entry reads "<what you see> = <what it means>", so the two drawn
  // swatches parse the same way as the two written ones. They used to be three
  // different grammars in one line ("one row per voice", "a line means…",
  // "red = …"), which made the strip look like four unrelated notes.
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
        <KeyArrow color="rgba(0,0,0,0.45)" dash="4 3" />
        {t(lang, "map.key.line")}
      </span>
      <span className="text-black/25" aria-hidden>·</span>
      <span className="inline-flex items-center gap-1">
        <KeyArrow color="#dc2626" />
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
