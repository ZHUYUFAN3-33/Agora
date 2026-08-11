import React, { useMemo, useState } from "react";
import { t, userLabel, type UiLang } from "../i18n/ui";

/**
 * ReplyGraph — the deterministic "who answered whom" strip.
 *
 * Deliberately NOT drawn inside DecisionMapCanvas. That canvas is the IBIS
 * layer: issue frames holding claims, laid out by argument structure, all of it
 * LLM-inferred. This is the fact layer: one node per chat TURN in file order,
 * edges taken from each agent's own [MOVE] self-report, no model involved.
 * Two different structures and two different levels of confidence — overlaying
 * them would make it impossible to tell which half is a guess.
 *
 * Layout is a swimlane timeline: one row per speaker, turns as dots along X in
 * transcript order, relations as arcs. Reading an arc backwards along X is the
 * point — it shows a turn reaching back to the turn it answers.
 */

export type FactTurn = {
  id: string;
  index: number;
  speaker: string;
  is_user: boolean;
  txt: string;
  move_kind?: string | null;
  softened_by?: string | null;
};

export type FactRelation = {
  id: string;
  from_index: number;
  to_index: number;
  kind: string;
  sign: string;
  source?: string;
};

export type FactLayer = {
  turns?: FactTurn[];
  relations?: FactRelation[];
  roster?: Record<string, string>;
  stats?: Record<string, number>;
};

const ROW_H = 34;
const DOT_R = 6;
const X_GAP = 52;
const PAD_X = 96;
const PAD_Y = 16;

/** Same palette as the IBIS canvas so the two layers read as one system. */
function signStroke(sign: string): { stroke: string; width: number; dash?: string } {
  if (sign === "opposes") return { stroke: "#dc2626", width: 1.6 };
  if (sign === "supports") return { stroke: "#059669", width: 1.6 };
  return { stroke: "rgba(0,0,0,0.26)", width: 1.2, dash: "4 3" };
}

/** Arc that leaves the source, bows above the lanes, and lands on the target. */
function arcPath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.abs(x2 - x1);
  const lift = Math.min(46, 14 + dx * 0.22);
  const my = Math.min(y1, y2) - lift;
  return `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`;
}

export function ReplyGraph({
  facts,
  lang = "en",
  userName,
  onJumpIndexes,
}: {
  facts?: FactLayer | null;
  lang?: UiLang;
  userName?: string;
  onJumpIndexes?: (indexes: number[]) => void;
}) {
  const [open, setOpen] = useState(true);
  const [hover, setHover] = useState<string | null>(null);

  const turns = useMemo(() => facts?.turns ?? [], [facts]);
  const relations = useMemo(() => facts?.relations ?? [], [facts]);

  // Speaker lanes in order of first appearance; the user always sits last so
  // agent-to-agent traffic stays visually contiguous.
  const lanes = useMemo(() => {
    const seen: string[] = [];
    for (const turn of turns) {
      if (!turn.is_user && !seen.includes(turn.speaker)) seen.push(turn.speaker);
    }
    if (turns.some((turn) => turn.is_user)) seen.push("__user__");
    return seen;
  }, [turns]);

  const laneOf = (turn: FactTurn) =>
    Math.max(0, lanes.indexOf(turn.is_user ? "__user__" : turn.speaker));

  const posOf = (index: number) => {
    const turn = turns.find((candidate) => candidate.index === index);
    if (!turn) return null;
    return { x: PAD_X + turns.indexOf(turn) * X_GAP, y: PAD_Y + laneOf(turn) * ROW_H + ROW_H / 2 };
  };

  if (!turns.length) return null;

  const width = PAD_X + turns.length * X_GAP + 24;
  const height = PAD_Y * 2 + lanes.length * ROW_H + 52;
  const opposes = relations.filter((relation) => relation.sign === "opposes").length;

  return (
    <div className="border-t border-black/8 bg-[#f4f4f2]">
      <button
        onClick={() => setOpen((value) => !value)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-[10px] text-black/55 hover:bg-black/[0.03] transition-colors"
      >
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .15s" }}
        >
          <path d="M9 18l6-6-6-6" />
        </svg>
        <span>{t(lang, "map.replyGraph")}</span>
        <span className="text-black/35">
          {t(lang, "map.replyGraphCount")
            .replace("{turns}", String(turns.length))
            .replace("{relations}", String(relations.length))}
        </span>
        {opposes > 0 && (
          <span className="ml-auto flex items-center gap-1 text-[#dc2626]/80">
            <span className="inline-block w-3 h-[1.5px] bg-[#dc2626]" />
            {t(lang, "map.replyGraphOpposes").replace("{n}", String(opposes))}
          </span>
        )}
      </button>

      {open && (
        <div className="overflow-x-auto overflow-y-hidden max-h-[220px]">
          <svg width={width} height={height} className="block">
            {/* lane guides + speaker labels */}
            {lanes.map((lane, i) => {
              const y = PAD_Y + i * ROW_H + ROW_H / 2;
              const label = lane === "__user__" ? userLabel(lang, userName) : lane;
              return (
                <g key={lane}>
                  <line x1={PAD_X - 12} y1={y} x2={width - 16} y2={y} stroke="rgba(0,0,0,0.06)" strokeWidth={1} />
                  <text x={PAD_X - 20} y={y + 3} textAnchor="end" fontSize={9} fill="rgba(0,0,0,0.45)">
                    {label.length > 12 ? `${label.slice(0, 12)}…` : label}
                  </text>
                </g>
              );
            })}

            {/* relations under the dots so nodes stay clickable */}
            {relations.map((relation) => {
              const a = posOf(relation.from_index);
              const b = posOf(relation.to_index);
              if (!a || !b) return null;
              const style = signStroke(relation.sign);
              const active = hover === relation.id;
              return (
                <path
                  key={relation.id}
                  d={arcPath(a.x, a.y, b.x, b.y)}
                  fill="none"
                  stroke={style.stroke}
                  strokeWidth={active ? style.width + 0.9 : style.width}
                  strokeDasharray={style.dash}
                  opacity={hover && !active ? 0.25 : 0.85}
                  onMouseEnter={() => setHover(relation.id)}
                  onMouseLeave={() => setHover(null)}
                  style={{ cursor: "pointer" }}
                >
                  <title>{`${relation.kind} → ${relation.sign}`}</title>
                </path>
              );
            })}

            {/* turns */}
            {turns.map((turn, i) => {
              const x = PAD_X + i * X_GAP;
              const y = PAD_Y + laneOf(turn) * ROW_H + ROW_H / 2;
              const challenged = turn.move_kind === "challenge";
              return (
                <g
                  key={turn.id}
                  onClick={() => onJumpIndexes?.([turn.index])}
                  style={{ cursor: onJumpIndexes ? "pointer" : "default" }}
                >
                  <circle
                    cx={x}
                    cy={y}
                    r={DOT_R}
                    fill={turn.is_user ? "#1560a8" : challenged ? "#dc2626" : "rgba(0,0,0,0.34)"}
                    opacity={turn.is_user ? 0.85 : challenged ? 0.9 : 0.55}
                  />
                  {turn.softened_by && (
                    // The speaker later conceded this point: a ring, not an edge —
                    // concede records carry no target in practice.
                    <circle cx={x} cy={y} r={DOT_R + 3} fill="none" stroke="#b45309" strokeWidth={1.2} opacity={0.7} />
                  )}
                  <title>{`#${turn.index} ${turn.speaker}${turn.move_kind ? ` · ${turn.move_kind}` : ""}\n${turn.txt.slice(0, 140)}`}</title>
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </div>
  );
}
