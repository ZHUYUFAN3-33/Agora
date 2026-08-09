import React, { useMemo } from "react";
import { getUiFont, labelCaseClass, phaseLabel, t, type UiLang } from "../i18n/ui";

export type DecisionNaviKind = "start" | "phase" | "topic" | "user_call";

export type DecisionNaviNode = {
  id: string;
  label: string;
  detail?: string;
  messageId: string;
  kind: DecisionNaviKind;
  phase?: string;
};

export type PhaseChangeMarker = {
  from: string;
  to: string;
  /** ISO timestamp from moderator log, when available */
  time?: string;
  /** Live-session anchor (preferred over time matching) */
  messageId?: string;
};

type MessageLike = {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  timestamp: number;
};

const MAX_NODES = 7;
const LABEL_MAX = 32;

const DECISION_CUE_RE =
  /(?:\bi\s+(?:decide|decided|chose|choose|prefer|will go with|lean(?:ing)? toward)|我(?:决定|选择|更倾向|打算|倾向)|決め(?:た|る)|〜に(?:する|しよう))/i;

function truncateLabel(text: string, max = LABEL_MAX): string {
  const oneLine = text.replace(/\s+/g, " ").trim();
  if (oneLine.length <= max) return oneLine;
  return `${oneLine.slice(0, max - 1).trimEnd()}…`;
}

function parseTimeMs(value?: string): number | null {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

function findMessageNearTime(messages: MessageLike[], timeIso?: string): MessageLike | null {
  const target = parseTimeMs(timeIso);
  if (target == null || messages.length === 0) return null;
  let best: MessageLike | null = null;
  let bestDist = Number.POSITIVE_INFINITY;
  for (const m of messages) {
    const dist = Math.abs(m.timestamp - target);
    if (dist < bestDist) {
      best = m;
      bestDist = dist;
    }
  }
  return best;
}

function findMessageById(messages: MessageLike[], id?: string): MessageLike | null {
  if (!id) return null;
  return messages.find((m) => m.id === id) || null;
}

/** Build a short decision-trajectory outline from messages + phase markers. */
export function buildDecisionNaviNodes(
  messages: MessageLike[],
  phaseMarkers: PhaseChangeMarker[],
  currentPhase: string | null | undefined,
  lang: UiLang,
): DecisionNaviNode[] {
  const userMessages = messages.filter((m) => m.role === "user" && (m.content || "").trim());
  if (userMessages.length === 0) return [];

  const nodes: DecisionNaviNode[] = [];
  const usedMessageIds = new Set<string>();

  const pushNode = (node: DecisionNaviNode) => {
    if (usedMessageIds.has(node.messageId) && node.kind !== "phase") return;
    if (usedMessageIds.has(node.messageId)) {
      const idx = nodes.findIndex((n) => n.messageId === node.messageId);
      if (idx >= 0 && nodes[idx].kind === "topic") {
        nodes[idx] = node;
      }
      return;
    }
    usedMessageIds.add(node.messageId);
    nodes.push(node);
  };

  const first = userMessages[0];
  pushNode({
    id: `start-${first.id}`,
    label: t(lang, "navi.start"),
    detail: truncateLabel(first.content),
    messageId: first.id,
    kind: "start",
    phase: "Exploration",
  });

  for (const marker of phaseMarkers) {
    const anchored =
      findMessageById(messages, marker.messageId) ||
      findMessageNearTime(messages, marker.time) ||
      first;
    pushNode({
      id: `phase-${marker.to}-${anchored.id}`,
      label: phaseLabel(lang, marker.to) || marker.to,
      detail: marker.from
        ? t(lang, "navi.phaseFrom", { from: phaseLabel(lang, marker.from) || marker.from })
        : undefined,
      messageId: anchored.id,
      kind: "phase",
      phase: marker.to,
    });
  }

  for (const m of userMessages.slice(1)) {
    if (!DECISION_CUE_RE.test(m.content)) continue;
    pushNode({
      id: `call-${m.id}`,
      label: t(lang, "navi.userCall"),
      detail: truncateLabel(m.content),
      messageId: m.id,
      kind: "user_call",
    });
  }

  if (nodes.length < 3 && userMessages.length >= 2) {
    const midIndexes = new Set<number>();
    if (userMessages.length === 2) {
      midIndexes.add(1);
    } else {
      const step = Math.max(1, Math.floor((userMessages.length - 1) / 3));
      for (let i = step; i < userMessages.length - 1; i += step) {
        midIndexes.add(i);
      }
      midIndexes.add(Math.floor(userMessages.length / 2));
      midIndexes.add(userMessages.length - 1);
    }
    for (const i of [...midIndexes].sort((a, b) => a - b)) {
      const m = userMessages[i];
      if (!m || usedMessageIds.has(m.id)) continue;
      pushNode({
        id: `topic-${m.id}`,
        label: t(lang, "navi.topic"),
        detail: truncateLabel(m.content),
        messageId: m.id,
        kind: "topic",
      });
      if (nodes.length >= MAX_NODES) break;
    }
  }

  if (currentPhase && !nodes.some((n) => n.phase === currentPhase && n.kind === "phase")) {
    const lastUser = userMessages[userMessages.length - 1];
    if (lastUser && currentPhase !== "Exploration") {
      pushNode({
        id: `phase-current-${currentPhase}-${lastUser.id}`,
        label: phaseLabel(lang, currentPhase) || currentPhase,
        detail: t(lang, "navi.currentPhase"),
        messageId: lastUser.id,
        kind: "phase",
        phase: currentPhase,
      });
    }
  }

  const order = new Map(messages.map((m, i) => [m.id, i]));
  nodes.sort((a, b) => (order.get(a.messageId) ?? 0) - (order.get(b.messageId) ?? 0));

  if (nodes.length <= MAX_NODES) return nodes;

  const essential = nodes.filter((n) => n.kind !== "topic");
  if (essential.length >= MAX_NODES) {
    return [essential[0], ...essential.slice(-(MAX_NODES - 1))];
  }
  const topics = nodes.filter((n) => n.kind === "topic");
  const need = MAX_NODES - essential.length;
  return [...essential, ...topics.slice(0, need)].sort(
    (a, b) => (order.get(a.messageId) ?? 0) - (order.get(b.messageId) ?? 0),
  );
}

/** Header trigger: opens the Decision Map side panel. */
export function DecisionNavi({
  nodes,
  count,
  lang = "en",
  open = false,
  onOpen,
  className = "",
}: {
  nodes?: DecisionNaviNode[];
  /** Prefer map topic count when available; falls back to nodes.length */
  count?: number;
  lang?: UiLang;
  open?: boolean;
  onOpen: () => void;
  className?: string;
}) {
  const font = getUiFont(lang);
  const n = useMemo(() => {
    if (typeof count === "number") return count;
    return nodes?.length ?? 0;
  }, [count, nodes]);

  if (n <= 0 && (!nodes || nodes.length === 0)) return null;

  return (
    <div className={`relative flex items-center ${className}`}>
      <button
        type="button"
        onClick={onOpen}
        className="flex items-center gap-1.5 h-4 hover:opacity-80 transition-opacity"
        aria-expanded={open}
        title={t(lang, "map.title")}
      >
        <span className="w-[7px] h-[7px] rounded-full bg-black flex-shrink-0" />
        <span
          className={`text-[10px] tracking-widest text-black ${labelCaseClass(lang)}`}
          style={font}
        >
          {t(lang, "map.title")}
        </span>
        <span className="text-[10px] text-[var(--app-muted-text)]" style={font}>
          {n || nodes?.length || 0}
        </span>
        <svg
          width="8"
          height="8"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden
          className={`opacity-40 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M2 4L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  );
}
