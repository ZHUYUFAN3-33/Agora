import React, { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { getUiFont, phaseLabel, t, type UiLang } from "../i18n/ui";

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
    // Allow phase to replace a weaker topic on same message
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

  // Topic waypoints: fill gaps so longer threads still have a usable outline
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

  // Ensure current phase appears even if moderator markers were missed
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

  // Keep chronological order by message position
  const order = new Map(messages.map((m, i) => [m.id, i]));
  nodes.sort((a, b) => (order.get(a.messageId) ?? 0) - (order.get(b.messageId) ?? 0));

  if (nodes.length <= MAX_NODES) return nodes;

  // Prefer start + phase + user_call; drop topics first
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

function kindDotClass(kind: DecisionNaviKind): string {
  if (kind === "start") return "bg-black";
  if (kind === "phase") return "bg-[#1560a8]";
  if (kind === "user_call") return "bg-[#9f3f26]";
  return "bg-black/35";
}

export function DecisionNavi({
  nodes,
  lang = "en",
  activeMessageId,
  onJump,
  className = "",
}: {
  nodes: DecisionNaviNode[];
  lang?: UiLang;
  activeMessageId?: string | null;
  onJump: (messageId: string) => void;
  className?: string;
}) {
  const font = getUiFont(lang);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    // Collapse by default on narrow viewports after first paint
    if (typeof window !== "undefined" && window.innerWidth < 640) {
      setExpanded(false);
    }
  }, []);

  const activeId = useMemo(() => {
    if (!nodes.length) return null;
    if (activeMessageId && nodes.some((n) => n.messageId === activeMessageId)) {
      return activeMessageId;
    }
    return nodes[nodes.length - 1]?.messageId ?? null;
  }, [nodes, activeMessageId]);

  if (nodes.length === 0) return null;

  return (
    <div className={`pointer-events-auto ${className}`}>
      <AnimatePresence initial={false} mode="wait">
        {!expanded ? (
          <motion.button
            key="collapsed"
            type="button"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            onClick={() => setExpanded(true)}
            className="flex items-center gap-2 px-3 py-2 rounded-[10px] border border-black/10 bg-white/95 shadow-[0_2px_12px_rgba(0,0,0,0.06)] hover:border-black/20 transition-colors"
            style={font}
            title={t(lang, "navi.title")}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-black" />
            <span className="text-[11px] text-black/80">{t(lang, "navi.title")}</span>
            <span className="text-[10px] text-[var(--app-muted-text)]">{nodes.length}</span>
          </motion.button>
        ) : (
          <motion.div
            key="expanded"
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            className="w-[220px] sm:w-[240px] rounded-[12px] border border-black/10 bg-white/95 shadow-[0_2px_16px_rgba(0,0,0,0.07)] overflow-hidden"
          >
            <div className="flex items-center justify-between gap-2 px-3 py-2.5 border-b border-black/6">
              <div className="min-w-0">
                <p className="text-[11px] text-black truncate" style={font}>
                  {t(lang, "navi.title")}
                </p>
                <p className="text-[10px] text-[var(--app-muted-text)] truncate" style={font}>
                  {t(lang, "navi.subtitle")}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="p-1 rounded-[6px] text-black/40 hover:text-black/70 hover:bg-black/5 transition-colors"
                aria-label={t(lang, "navi.collapse")}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <ol className="relative max-h-[min(52vh,420px)] overflow-y-auto py-2 px-2">
              <div className="absolute left-[18px] top-3 bottom-3 w-px bg-black/10" aria-hidden />
              {nodes.map((node, index) => {
                const isActive = node.messageId === activeId;
                return (
                  <li key={node.id}>
                    <button
                      type="button"
                      onClick={() => onJump(node.messageId)}
                      className={`relative w-full flex items-start gap-2.5 px-2 py-2 rounded-[8px] text-left transition-colors ${
                        isActive ? "bg-black/[0.04]" : "hover:bg-black/[0.03]"
                      }`}
                    >
                      <span
                        className={`relative z-10 mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ring-2 ring-white ${kindDotClass(node.kind)} ${
                          isActive ? "scale-125" : ""
                        }`}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5 min-w-0">
                          <span
                            className={`text-[11px] truncate ${isActive ? "text-black" : "text-black/75"}`}
                            style={font}
                          >
                            {node.label}
                          </span>
                          <span className="text-[9px] text-[var(--app-muted-text)] flex-shrink-0" style={font}>
                            {index + 1}/{nodes.length}
                          </span>
                        </span>
                        {node.detail && (
                          <span
                            className="block text-[10px] text-[var(--app-muted-text)] leading-snug mt-0.5 line-clamp-2"
                            style={font}
                          >
                            {node.detail}
                          </span>
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
