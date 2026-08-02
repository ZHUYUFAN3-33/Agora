import React, { useState, useRef, useEffect, useCallback, useLayoutEffect, useMemo, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { motion, AnimatePresence } from "motion/react";
import { createPortal } from "react-dom";
import { AgoraLogo, AgoraLogoFull } from "../components/AgoraLogo";
import { CustomDropdown } from "../components/ui/CustomDropdown";
import { AppearanceModal } from "../components/AppearanceModal";
import {
  IntakeModal,
  ProfileModal,
  MemoryHistoryPanel,
  type Agora2IntakePayload,
  type UiLang,
} from "../components/IntakeModal";
import { authFetch, getAuth, logoutRequest } from "../auth";
import { useAppearanceContext } from "../context/AppearanceContext";
import {
  type AgentKey,
  type AgentPoolKey,
  type AgentCustomSetting,
  type ExperimentMode,
  type Scene,
  AGENT_KEYS,
  LIMITED_AGENT_POOL,
  LIMITED_DEFAULT_SELECTED,
  DEFAULT_AGENT_NAMES,
  DEFAULT_AGENT_ROLES,
  DEFAULT_AGENT_COLORS,
  API_BASE,
  BACKEND_NAME_TO_KEY,
  DECISION_BLOCKS,
  DECISION_BLOCK_DESCRIPTIONS,
  DECISION_BLOCK_EXAMPLES,
  EMOTION_EMOJI,
  EMOTION_COLORS,
  EMOTION_EXAMPLES,
  EMOTION_IMAGES,
  defaultSetting,
  getEmotionDecisionSummary,
  getEmotionDecisionRole,
  isAgora2SceneId,
} from "../data/agents";
import {
  monoFont,
  condensedFont,
  FULL_AGENT_NAMES,
  type GuideGradientPalette,
  DEFAULT_GUIDE_GRADIENT,
  GUIDE_FRAME_FILL,
  LIMITED_POOL_ACCENT_MAP,
  EMOTION_EMOJI_VARIANTS,
  EMOJI_REGEX,
  WELCOME_TUTORIAL_STEPS,
} from "./chatConstants";

function hashSeed(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) % 10007;
  }
  return hash;
}

function EmotionIcon({ emotion, size = 20 }: { emotion: string; size?: number }) {
  const key = (emotion || "").toLowerCase();
  const imgSrc = EMOTION_IMAGES[key];
  const emoji = EMOTION_EMOJI[key] || "😐";
  const [imgError, setImgError] = useState(false);
  if (imgSrc && !imgError) {
    return (
      <img
        src={imgSrc}
        alt={emotion}
        style={{ width: size, height: size, objectFit: "contain" }}
        className="flex-shrink-0"
        onError={() => setImgError(true)}
      />
    );
  }
  return <span className="leading-none" style={{ fontSize: size }}>{emoji}</span>;
}

function hexToRgba(hex: string, alpha: number) {
  const normalized = hex.replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) return `rgba(0,0,0,${alpha})`;
  const r = parseInt(normalized.slice(0, 2), 16);
  const g = parseInt(normalized.slice(2, 4), 16);
  const b = parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function clampGuideCycle(value: number) {
  return Math.min(10, Math.max(2.5, value));
}

function AnimatedGuideFrame({
  active,
  palette,
  rounded = "rounded-[14px]",
  inset = "inset-0",
  fillColor = "rgba(255,255,255,0)",
  pulse = false,
}: {
  active: boolean;
  palette: GuideGradientPalette;
  rounded?: string;
  inset?: string;
  fillColor?: string;
  pulse?: boolean;
}) {
  if (!active) return null;
  const frameStyle = {
    border: "2px solid rgba(0,0,0,0.08)",
    background: fillColor,
  } as const;

  if (!pulse) {
    return (
      <div
        aria-hidden="true"
        className={`pointer-events-none absolute ${inset} ${rounded} z-0 overflow-hidden`}
        style={frameStyle}
      />
    );
  }

  return (
    <motion.div
      aria-hidden="true"
      className={`pointer-events-none absolute ${inset} ${rounded} z-0 overflow-hidden`}
      initial={{ borderColor: "rgba(0,0,0,0.06)" }}
      animate={{
        borderColor: ["rgba(0,0,0,0.06)", "rgba(0,0,0,0.28)", "rgba(0,0,0,0.06)"],
      }}
      transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
      style={{ background: fillColor, border: "2px solid" }}
    />
  );
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface Message {
  id: string;
  role: "user" | "agent" | "system";
  agentKey?: AgentKey;
  content: string;
  timestamp: number;
  emotionTagSnapshot?: string | null;
}

interface ConvSettings {
  agentNames: Record<AgentKey, string>;
  agentBackendNames: Record<AgentKey, string>;
  agentSettings: Record<AgentKey, AgentCustomSetting>;
  limitedSelectedAgents: AgentPoolKey[];
  selectedScene: Scene | null;
  maxAgentTurns: number;
  maxUserGap: number;
  mode: ExperimentMode;
}

interface Conversation {
  id: string;
  roomId: string;
  title: string;
  preview: string;
  timestamp: string;
  messages: Message[];
  settings?: ConvSettings;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

// Replace backend names (ChatbotA/B/C) with user-defined display names; replace generic user label with nickname.
function applyDisplayNames(
  content: string,
  names: Record<AgentKey, string>,
  nickname?: string,
  mode: ExperimentMode = "full",
  backendNames?: Record<AgentKey, string>,
): string {
  let out = content
    .replace(/\bChatbotA\b/g, names.A)
    .replace(/\bChatbotB\b/g, names.B)
    .replace(/\bChatbotC\b/g, names.C);
  if (mode === "limited" && backendNames) {
    (["A", "B", "C"] as AgentKey[]).forEach((k) => {
      const internalName = (backendNames[k] || "").trim();
      if (!internalName) return;
      const escaped = internalName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      out = out.replace(new RegExp(`\\b${escaped}\\b`, "g"), names[k]);
    });
  }
  if (nickname && nickname.trim()) {
    out = out.replace(/\buser\b/gi, nickname.trim());
  }
  return out;
}

function stripRepeatedFirstTurnIntro(content: string, agentName: string): string {
  const escapedName = agentName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  let out = content.trim();
  out = out.replace(/^(?:[\p{Emoji_Presentation}\p{Extended_Pictographic}]\s*)+/u, "");
  out = out.replace(
    new RegExp(`^(?:hi|hello|hey)\\s*,?\\s*i['’]?m\\s+${escapedName}[.!]?\\s*`, "i"),
    "",
  );
  return out.trim() || content.trim();
}

function diversifyEmotionEmoji(
  content: string,
  emotionTag: string | null | undefined,
  repeatIndex: number,
  agentKey?: AgentKey,
  messageId?: string,
): string {
  const tag = (emotionTag || "").toLowerCase();
  const palette = EMOTION_EMOJI_VARIANTS[tag];
  if (!palette || repeatIndex < 1) return content;
  const replaceable = new Set(palette.replaceable);
  const accentSet = new Set(palette.accent);
  const primaryPool = palette.primary;
  const accentPool = palette.accent.length > 0 ? palette.accent : palette.primary;
  const agentOffset = agentKey ? AGENT_KEYS.indexOf(agentKey) + 1 : 0;
  const messageOffset = hashSeed(messageId || content) % 11;
  let replacementIndex = 0;
  let replaced = false;
  const nextContent = content.replace(EMOJI_REGEX, (emoji) => {
    if (!replaceable.has(emoji)) return emoji;
    const pool = accentSet.has(emoji) ? accentPool : primaryPool;
    const nextEmoji = pool[(repeatIndex + agentOffset + messageOffset + replacementIndex) % pool.length];
    replacementIndex += 1;
    replaced = replaced || nextEmoji !== emoji;
    return nextEmoji;
  });
  return replaced ? nextContent : content;
}

function normalizeLimitedSelection(keys: AgentPoolKey[]): AgentPoolKey[] {
  const valid = keys.filter((k): k is AgentPoolKey => LIMITED_AGENT_POOL.some((p) => p.key === k));
  const unique = Array.from(new Set(valid));
  if (unique.length >= 3) return unique.slice(0, 3);
  const padding = LIMITED_AGENT_POOL.map((p) => p.key).filter((k) => !unique.includes(k));
  return [...unique, ...padding].slice(0, 3);
}

function sameEmotionSnapshot(a: AgentCustomSetting, b: AgentCustomSetting): boolean {
  return (
    a.emotionOn === b.emotionOn &&
    a.emotionTag === b.emotionTag &&
    a.valence === b.valence &&
    a.arousal === b.arousal &&
    a.control === b.control
  );
}

// ─── In-chat layer annotation (paper) ─────────────────────────────────────────

type ChatLayerKind = "decision" | "expression" | "scene";
type ChatLayerAnnotation = { id: string; start: number; end: number; layer: ChatLayerKind };

function chatAnnotationOverlap(aStart: number, aEnd: number, bStart: number, bEnd: number): boolean {
  return aStart < bEnd && bStart < aEnd;
}

function getChatSelectionInElement(container: HTMLElement): { start: number; end: number; rect: DOMRect } | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!container.contains(range.commonAncestorContainer)) return null;
  const pre = range.cloneRange();
  pre.selectNodeContents(container);
  pre.setEnd(range.startContainer, range.startOffset);
  const start = pre.toString().length;
  pre.setEnd(range.endContainer, range.endOffset);
  const end = pre.toString().length;
  if (end <= start) return null;
  if (!range.toString().trim()) return null;
  const rect = range.getBoundingClientRect();
  return { start, end, rect };
}

function layerSpanClass(layer: ChatLayerKind, variant: "agent" | "user"): string {
  if (layer === "decision") {
    return variant === "user"
      ? "bg-[#7c3aed]/45 border-b-2 border-[#c4b5fd] text-white"
      : "bg-[#7c3aed]/25 border-b-2 border-[#7c3aed]/80 text-black/80";
  }
  if (layer === "expression") {
    return variant === "user"
      ? "bg-[#e07a5f]/45 border-b-2 border-[#fdba74] text-white"
      : "bg-[#e07a5f]/25 border-b-2 border-[#e07a5f]/80 text-black/80";
  }
  // scene — #7BC3FF
  return variant === "user"
    ? "bg-[#7BC3FF]/50 border-b-2 border-[#b8ddff] text-white"
    : "bg-[#7BC3FF]/35 border-b-2 border-[#7BC3FF] text-black/85";
}

function layerTitle(layer: ChatLayerKind): string {
  if (layer === "decision") return "Decision Layer";
  if (layer === "expression") return "Emotion Layer";
  return "Scene Layer";
}

function renderChatAnnotatedText(
  text: string,
  annotations: ChatLayerAnnotation[],
  variant: "agent" | "user",
): ReactNode {
  if (!annotations.length) return text;
  const sorted = [...annotations].sort((a, b) => a.start - b.start);
  let cursor = 0;
  const out: React.ReactNode[] = [];
  sorted.forEach((a) => {
    if (cursor < a.start) out.push(<span key={`p-${a.id}-${cursor}`}>{text.slice(cursor, a.start)}</span>);
    out.push(
      <span
        key={a.id}
        className={layerSpanClass(a.layer, variant)}
        title={layerTitle(a.layer)}
      >
        {text.slice(a.start, a.end)}
      </span>,
    );
    cursor = a.end;
  });
  if (cursor < text.length) out.push(<span key={`tail-${cursor}`}>{text.slice(cursor)}</span>);
  return out;
}

// ─── Toggle ───────────────────────────────────────────────────────────────────

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative w-[38px] h-[22px] rounded-full transition-colors flex-shrink-0 ${
        checked ? "bg-black" : "bg-black/20"
      }`}
    >
      <span
        className={`absolute top-[3px] left-[3px] w-4 h-4 bg-white rounded-full transition-transform shadow-sm ${
          checked ? "translate-x-4" : "translate-x-0"
        }`}
      />
    </button>
  );
}

// ─── Message components ───────────────────────────────────────────────────────

function TypingDots({
  agentKey,
  agentNames,
}: {
  agentKey: AgentKey;
  agentNames: Record<AgentKey, string>;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 6, scale: 0.98 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      className="w-fit"
    >
      <div className="flex items-center gap-2 mb-1">
        <div className="w-[7px] h-[7px] rounded-[1.5px] flex-shrink-0 bg-black" />
        <span className="text-[11px] tracking-widest text-black" style={monoFont}>
          {agentNames[agentKey]}
        </span>
      </div>
      <div className="ml-4 inline-flex items-center gap-1 rounded-[16px] border border-black/10 bg-[#fffdfa] px-3 py-2 shadow-[0_10px_24px_rgba(0,0,0,0.08)]">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="h-[6px] w-[6px] rounded-full bg-black/70"
            animate={{ y: [0, -2, 0], opacity: [0.35, 1, 0.35] }}
            transition={{ duration: 1.05, repeat: Infinity, delay: i * 0.14, ease: "easeInOut" }}
          />
        ))}
      </div>
    </motion.div>
  );
}

/** Test mode: click agent name to show read-only info card. Uses getEmotionDecisionSummary for role description. */
const ENABLE_AGENT_INFO_CARD = import.meta.env.DEV;

function AgentInfoCard({
  agentKey,
  name,
  settings,
  anchorRect,
  anchorRef,
  onClose,
}: {
  agentKey: AgentKey;
  name: string;
  settings: AgentCustomSetting;
  anchorRect: DOMRect | null;
  anchorRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => {
      const target = e.target as Node;
      const inCard = ref.current?.contains(target);
      const inAnchor = anchorRef.current?.contains(target);
      if (!inCard && !inAnchor) onClose();
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [onClose, anchorRef]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [onClose]);

  if (!anchorRect || typeof window === "undefined") return null;
  const emotionTag = settings.emotionTag || "joy";
  const decisionBlock = settings.decisionBlock || "Rational";
  const roleLabel = getEmotionDecisionRole(emotionTag, decisionBlock);
  const behaviorDescription = getEmotionDecisionSummary(emotionTag, decisionBlock);
  const panelWidth = 252;
  const viewportPad = 12;
  const left = Math.min(Math.max(anchorRect.left, viewportPad), Math.max(viewportPad, window.innerWidth - panelWidth - viewportPad));
  const top = anchorRect.bottom + 12;
  const placeAbove = false;

  return createPortal(
    <div className="fixed z-50" style={{ left, top }}>
      <div className={placeAbove ? "-translate-y-full" : ""}>
        <motion.div
          ref={ref}
          initial={{ opacity: 0, y: 6, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 4, scale: 0.98 }}
          transition={{ duration: 0.16 }}
          className="relative z-30 w-[252px] rounded-[14px] border border-foreground/[0.08] bg-[var(--background)] px-3 py-3"
          style={{ boxShadow: "0 8px 32px rgba(0,0,0,0.06)" }}
        >
          <div className={`absolute left-5 h-3.5 w-3.5 rotate-45 border-foreground/[0.08] bg-[var(--background)] ${placeAbove ? "bottom-[-7px] border-b border-r" : "top-[-7px] border-l border-t"}`} />
          <div className="flex items-center gap-2 mb-3">
            <div className="w-[6px] h-[6px] rounded-[1.2px] flex-shrink-0" style={{ backgroundColor: settings.accentColor || DEFAULT_AGENT_COLORS[agentKey] }} />
            <span className="text-[11px] tracking-widest text-foreground" style={monoFont}>{name}</span>
          </div>
          <div className="mb-3">
            <div className="mb-2 px-0.5">
              <span className="text-[10px] tracking-widest text-foreground/85 uppercase" style={monoFont}>Emotion</span>
            </div>
            <div className="rounded-[10px] border border-foreground/[0.06] bg-foreground/[0.015] px-3 py-2.5">
              <div
                className="flex items-center gap-2 rounded-[8px] border px-2.5 py-2 text-[10px]"
                style={{
                  ...monoFont,
                  borderColor: (EMOTION_COLORS[emotionTag] || "#111111") + "44",
                  background: (EMOTION_COLORS[emotionTag] || "#111111") + "12",
                  color: EMOTION_COLORS[emotionTag] || "#111111",
                }}
              >
                <EmotionIcon emotion={emotionTag} size={14} />
                <span className="capitalize font-semibold">{emotionTag}</span>
              </div>
            </div>
          </div>
          <div className="mb-3">
            <div className="mb-2 px-0.5">
              <span className="text-[10px] tracking-widest text-foreground/85 uppercase" style={monoFont}>Decision</span>
            </div>
            <div className="rounded-[10px] border border-foreground/[0.06] bg-foreground/[0.015] px-3 py-2.5">
              <div className="text-[10px] text-foreground" style={monoFont}>{decisionBlock}</div>
            </div>
          </div>
          <div className="mb-3">
            <div className="mb-2 px-0.5">
              <span className="text-[10px] tracking-widest text-foreground/85 uppercase" style={monoFont}>Role</span>
            </div>
            <div className="rounded-[10px] border border-foreground/[0.06] bg-foreground/[0.015] px-3 py-2.5">
              <div className="text-[10px] text-foreground" style={monoFont}>{roleLabel}</div>
            </div>
          </div>
          <div>
            <div className="mb-2 px-0.5">
              <span className="text-[10px] tracking-widest text-foreground/85 uppercase" style={monoFont}>Behavior description</span>
            </div>
            <div className="rounded-[10px] border border-foreground/[0.06] bg-foreground/[0.015] px-3 py-2.5">
              <div className="text-[10px] text-foreground/90 leading-relaxed" style={monoFont}>{behaviorDescription}</div>
            </div>
          </div>
        </motion.div>
      </div>
    </div>,
    document.body,
  );
}

function AgentEmotionPopover({
  agentKey,
  settings,
  onAdjustEmotion,
  onOpenAdvanced,
  anchorRect,
  safeRect,
  onHoverStart,
  onHoverEnd,
}: {
  agentKey: AgentKey;
  settings: AgentCustomSetting;
  onAdjustEmotion: (key: AgentKey, patch: Partial<AgentCustomSetting>, shouldAnalyze?: boolean) => void;
  onOpenAdvanced: (key: AgentKey) => void;
  anchorRect: DOMRect | null;
  safeRect: DOMRect | null;
  onHoverStart: () => void;
  onHoverEnd: () => void;
}) {
  if (!anchorRect || typeof window === "undefined") return null;
  const emotionTag = settings.emotionTag || "joy";
  const emotionColor = EMOTION_COLORS[emotionTag] || "#111111";
  const decisionIndex = Math.max(0, DECISION_BLOCKS.indexOf(settings.decisionBlock));
  const emotionDefaults = defaultSetting(agentKey);
  const panelWidth = 252;
  const estimatedPanelHeight = 332;
  const viewportPad = 12;
  const safeTop = Math.max(viewportPad, (safeRect?.top ?? 0) + viewportPad);
  const safeBottom = Math.min(window.innerHeight - viewportPad, (safeRect?.bottom ?? window.innerHeight) - viewportPad);
  const safeLeft = Math.max(viewportPad, safeRect?.left ?? 0);
  const safeRight = Math.min(window.innerWidth - viewportPad, safeRect?.right ?? window.innerWidth);
  const spaceBelow = safeBottom - anchorRect.bottom;
  const spaceAbove = anchorRect.top - safeTop;
  const placeAbove = spaceBelow < estimatedPanelHeight && spaceAbove > spaceBelow;
  const left = Math.min(Math.max(anchorRect.left, safeLeft), Math.max(safeLeft, safeRight - panelWidth));
  const top = placeAbove ? anchorRect.top - 12 : anchorRect.bottom + 12;
  const cycleDecision = (direction: -1 | 1) => {
    const nextIndex = (decisionIndex + direction + DECISION_BLOCKS.length) % DECISION_BLOCKS.length;
    onAdjustEmotion(agentKey, { decisionBlock: DECISION_BLOCKS[nextIndex] }, false);
  };
  return createPortal(
    <div
      className="fixed z-40"
      style={{ left, top }}
      onMouseEnter={onHoverStart}
      onMouseLeave={onHoverEnd}
    >
      <div className={placeAbove ? "-translate-y-full" : ""}>
        <motion.div
          initial={{ opacity: 0, y: placeAbove ? -6 : 6, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: placeAbove ? -4 : 4, scale: 0.98 }}
          transition={{ duration: 0.16 }}
          className="relative z-30 w-[252px] rounded-[14px] border border-foreground/[0.08] bg-[var(--background)] px-3 py-3"
          style={{ boxShadow: "0 8px 32px rgba(0,0,0,0.06)" }}
        >
          <div className={`absolute left-5 h-3.5 w-3.5 rotate-45 border-foreground/[0.08] bg-[var(--background)] ${placeAbove ? "bottom-[-7px] border-b border-r" : "top-[-7px] border-l border-t"}`} />
          {/* EMOTION section */}
          <div className="mb-3">
            <div className="mb-2 px-0.5">
              <span className="text-[10px] tracking-widest text-foreground/85 uppercase" style={monoFont}>Emotion</span>
            </div>
            <div className="rounded-[10px] border border-foreground/[0.06] bg-foreground/[0.015] px-3 py-2.5">
              <div
                className="flex items-center justify-between gap-2 rounded-[8px] border px-2.5 py-2 text-[10px]"
                style={{
                  ...monoFont,
                  borderColor: emotionColor + "44",
                  background: emotionColor + "12",
                  color: emotionColor,
                }}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <EmotionIcon emotion={emotionTag} size={14} />
                  <span className="capitalize font-semibold">{emotionTag}</span>
                </div>
              </div>
              <div className="mt-2.5 flex flex-col gap-2">
                {([
                  { label: "Valence", field: "valence" as const, value: settings.valence },
                  { label: "Arousal", field: "arousal" as const, value: settings.arousal },
                  { label: "Control", field: "control" as const, value: settings.control },
                ] as const).map(({ label, field, value }) => (
                  <div key={field} className="flex min-w-0 items-center gap-2 rounded-[8px] px-1 py-0.5">
                    <span className="w-[54px] flex-shrink-0 text-[10px] text-foreground/80" style={monoFont}>{label}</span>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={Math.round(value * 100)}
                      onChange={(e) => onAdjustEmotion(agentKey, { [field]: parseInt(e.target.value, 10) / 100 } as Partial<AgentCustomSetting>)}
                      onMouseUp={() => onAdjustEmotion(agentKey, { emotionOn: true }, true)}
                      onTouchEnd={() => onAdjustEmotion(agentKey, { emotionOn: true }, true)}
                      className="min-w-0 flex-1 h-[4px] accent-black"
                    />
                    <span className="w-[34px] flex-shrink-0 text-right text-[10px] text-foreground/80" style={monoFont}>{value.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          {/* DECISION section */}
          <div>
            <div className="mb-2 px-0.5">
              <span className="text-[10px] tracking-widest text-foreground/85 uppercase" style={monoFont}>Decision</span>
            </div>
            <div className="rounded-[10px] border border-foreground/[0.06] bg-foreground/[0.015] px-3 py-2.5">
              <div className="flex items-center gap-2 px-1 py-1">
                <button
                  type="button"
                  onClick={() => cycleDecision(-1)}
                  className="flex h-7 w-7 items-center justify-center rounded-[7px] text-foreground/70 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                  aria-label="Previous decision style"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M15 18l-6-6 6-6" />
                  </svg>
                </button>
                <div className="min-w-0 flex-1 text-center">
                  <div className="text-[11px] text-foreground" style={monoFont}>{settings.decisionBlock}</div>
                </div>
                <button
                  type="button"
                  onClick={() => cycleDecision(1)}
                  className="flex h-7 w-7 items-center justify-center rounded-[7px] text-foreground/70 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                  aria-label="Next decision style"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M9 18l6-6-6-6" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
          <div className="mt-3 flex items-center justify-between gap-2 border-t border-foreground/[0.06] pt-2.5">
            <button
              onClick={() => onAdjustEmotion(agentKey, {
                emotionOn: true,
                emotionTag: emotionDefaults.emotionTag,
                valence: emotionDefaults.valence,
                arousal: emotionDefaults.arousal,
                control: emotionDefaults.control,
                emotionText: "",
              }, false)}
              className="text-[10px] text-foreground/65 transition-colors hover:text-foreground"
              style={monoFont}
            >
              reset tag
            </button>
            <button
              onClick={() => onOpenAdvanced(agentKey)}
              className="rounded-[6px] border border-foreground/[0.08] px-2 py-1 text-[10px] text-foreground transition-colors hover:border-foreground/20 hover:bg-foreground/[0.02]"
              style={monoFont}
            >
              advance setting
            </button>
          </div>
        </motion.div>
      </div>
    </div>,
    document.body,
  );
}

const AgentMessage = React.memo(function AgentMessage({
  message,
  agentNames,
  agentBackendNames,
  agentSettings,
  mode,
  nickname,
  onOpenAdvancedAgent,
  onQuickEmotionAdjust,
  onQuickAdjustCommit,
  getPopoverSafeRect,
  compactRepeatedIntro = false,
  emojiRepeatIndex = 0,
  chatAnnotationMode = false,
  layerAnnotations,
  onChatAnnotationDraft,
}: {
  message: Message;
  agentNames: Record<AgentKey, string>;
  agentBackendNames: Record<AgentKey, string>;
  agentSettings?: Record<AgentKey, AgentCustomSetting>;
  mode: ExperimentMode;
  nickname?: string;
  onOpenAdvancedAgent?: (key: AgentKey) => void;
  onQuickEmotionAdjust?: (key: AgentKey, patch: Partial<AgentCustomSetting>, shouldAnalyze?: boolean) => Promise<void> | void;
  onQuickAdjustCommit?: (key: AgentKey, before: AgentCustomSetting) => Promise<void> | void;
  getPopoverSafeRect?: () => DOMRect | null;
  compactRepeatedIntro?: boolean;
  emojiRepeatIndex?: number;
  chatAnnotationMode?: boolean;
  layerAnnotations?: ChatLayerAnnotation[];
  onChatAnnotationDraft?: (d: { messageId: string; start: number; end: number; x: number; y: number }) => void;
}) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [infoCardOpen, setInfoCardOpen] = useState(false);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [safeRect, setSafeRect] = useState<DOMRect | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const hoveredRef = useRef(false);
  const dirtyBaselineRef = useRef<AgentCustomSetting | null>(null);
  const name = message.agentKey ? agentNames[message.agentKey] : "Agent";
  const role = message.agentKey && mode === "limited"
    ? (agentSettings?.[message.agentKey]?.roleDescription || DEFAULT_AGENT_ROLES[message.agentKey])
    : "";
  const isError = !message.agentKey;
  const accentColor = message.agentKey && agentSettings?.[message.agentKey]?.accentColor
    ? agentSettings[message.agentKey].accentColor
    : (message.agentKey ? DEFAULT_AGENT_COLORS[message.agentKey] : "#000");
  const displayContent = message.agentKey
    ? applyDisplayNames(message.content, agentNames, nickname, mode, agentBackendNames)
    : message.content;
  const compactedContent = compactRepeatedIntro ? stripRepeatedFirstTurnIntro(displayContent, name) : displayContent;
  const messageEmotionTag = message.emotionTagSnapshot ?? null;
  const finalContent = message.agentKey
    ? diversifyEmotionEmoji(compactedContent, messageEmotionTag, emojiRepeatIndex, message.agentKey, message.id)
    : compactedContent;
  const quickEmotionEnabled = !isError && mode === "full" && !!message.agentKey && !!onQuickEmotionAdjust && !!onOpenAdvancedAgent;
  const quickHover = quickEmotionEnabled && !chatAnnotationMode;
  const contentRef = useRef<HTMLParagraphElement>(null);
  const currentSettings = message.agentKey ? agentSettings?.[message.agentKey] : null;

  const clearCloseTimer = () => {
    if (closeTimerRef.current) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  };

  const updatePopoverPosition = useCallback(() => {
    if (!triggerRef.current) return;
    setAnchorRect(triggerRef.current.getBoundingClientRect());
    setSafeRect(getPopoverSafeRect?.() ?? null);
  }, [getPopoverSafeRect]);

  const openPopover = () => {
    clearCloseTimer();
    if (!popoverOpen && message.agentKey) {
      dirtyBaselineRef.current = { ...(currentSettings || defaultSetting(message.agentKey)) };
    }
    updatePopoverPosition();
    setPopoverOpen(true);
  };

  const commitQuickAdjust = useCallback(() => {
    if (!message.agentKey || !dirtyBaselineRef.current) return;
    const before = dirtyBaselineRef.current;
    dirtyBaselineRef.current = null;
    void onQuickAdjustCommit?.(message.agentKey, before);
  }, [message.agentKey, onQuickAdjustCommit]);

  const closePopoverSoon = () => {
    clearCloseTimer();
    closeTimerRef.current = window.setTimeout(() => {
      setPopoverOpen(false);
      commitQuickAdjust();
    }, 120);
  };

  useEffect(() => () => {
    clearCloseTimer();
    commitQuickAdjust();
  }, [commitQuickAdjust]);

  useEffect(() => {
    if (!ENABLE_AGENT_INFO_CARD || !message.agentKey) return;
    const h = (e: KeyboardEvent) => {
      if ((e.key === "t" || e.key === "T") && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (infoCardOpen) {
          e.preventDefault();
          setInfoCardOpen(false);
        } else if (hoveredRef.current) {
          e.preventDefault();
          updatePopoverPosition();
          setInfoCardOpen(true);
        }
      }
    };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [message.agentKey, infoCardOpen, updatePopoverPosition]);
  useLayoutEffect(() => {
    if (!popoverOpen) return;
    updatePopoverPosition();
    const handlePosition = () => updatePopoverPosition();
    window.addEventListener("resize", handlePosition);
    window.addEventListener("scroll", handlePosition, true);
    return () => {
      window.removeEventListener("resize", handlePosition);
      window.removeEventListener("scroll", handlePosition, true);
    };
  }, [popoverOpen, updatePopoverPosition]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, layout: { duration: 0.28, ease: [0.22, 1, 0.36, 1] } }}
      className="flex flex-col gap-1 mb-4"
    >
      <div className="flex items-center gap-2 mb-1">
        <span
          className="inline-flex h-[11px] w-[7px] flex-shrink-0 items-center justify-center"
          aria-hidden
        >
          <span
            className="block w-[7px] h-[7px] rounded-[1.5px]"
            style={{ backgroundColor: isError ? "#ef4444" : accentColor }}
          />
        </span>
        <div
          ref={triggerRef}
          className="relative flex items-center"
          onMouseEnter={(e) => {
            if (ENABLE_AGENT_INFO_CARD && message.agentKey) hoveredRef.current = true;
            if (quickHover) openPopover();
          }}
          onMouseLeave={(e) => {
            if (ENABLE_AGENT_INFO_CARD && message.agentKey) hoveredRef.current = false;
            if (quickHover) closePopoverSoon();
          }}
        >
          <button
            className={`inline-flex items-center p-0 m-0 border-0 bg-transparent text-[11px] tracking-widest leading-none ${
              quickHover ? "cursor-default hover:underline underline-offset-2" : "cursor-default"
            }`}
            style={{ ...monoFont, color: isError ? "#ef4444" : "#000" }}
            type="button"
          >
            {name}
          </button>
          {ENABLE_AGENT_INFO_CARD && infoCardOpen && message.agentKey && (
            <AgentInfoCard
              agentKey={message.agentKey}
              name={name}
              settings={currentSettings || defaultSetting(message.agentKey)}
              anchorRect={anchorRect}
              anchorRef={triggerRef}
              onClose={() => setInfoCardOpen(false)}
            />
          )}
          <AnimatePresence>
            {quickHover && popoverOpen && message.agentKey && (
              <div onMouseEnter={openPopover} onMouseLeave={closePopoverSoon}>
                <AgentEmotionPopover
                  agentKey={message.agentKey}
                  settings={currentSettings || defaultSetting(message.agentKey)}
                  anchorRect={anchorRect}
                  safeRect={safeRect}
                  onHoverStart={openPopover}
                  onHoverEnd={closePopoverSoon}
                  onAdjustEmotion={(key, patch, shouldAnalyze) => {
                    void onQuickEmotionAdjust?.(key, patch, shouldAnalyze);
                  }}
                  onOpenAdvanced={(key) => {
                    setPopoverOpen(false);
                    commitQuickAdjust();
                    onOpenAdvancedAgent?.(key);
                  }}
                />
              </div>
            )}
          </AnimatePresence>
        </div>
        {role && (
          <span className="text-[10px] text-[var(--app-muted-text)] ml-1" style={monoFont}>
            · {role}
          </span>
        )}
      </div>
      <div
        className="ml-4 px-4 py-3 border border-black/10 rounded-[10px] rounded-tl-[2px] max-w-[90%]"
        style={isError ? { borderColor: "#fee2e2", background: "#fef2f2" } : {}}
      >
        <p
          ref={contentRef}
          onMouseUp={() => {
            if (!chatAnnotationMode || !contentRef.current || !onChatAnnotationDraft) return;
            const sel = getChatSelectionInElement(contentRef.current);
            if (!sel) return;
            onChatAnnotationDraft({
              messageId: message.id,
              start: sel.start,
              end: sel.end,
              x: sel.rect.left + sel.rect.width / 2,
              y: sel.rect.top - 8,
            });
          }}
          className={`text-[13px] text-black/80 leading-relaxed whitespace-pre-wrap ${chatAnnotationMode ? "select-text cursor-text" : ""}`}
          style={{ ...monoFont, color: isError ? "#ef4444" : undefined }}
        >
          {chatAnnotationMode && (layerAnnotations?.length ?? 0) > 0
            ? renderChatAnnotatedText(finalContent, layerAnnotations!, "agent")
            : finalContent}
        </p>
      </div>
    </motion.div>
  );
});

const SystemMessage = React.memo(function SystemMessage({ message }: { message: Message }) {
  if (!(message.content || "").trim()) return null;
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="flex flex-col items-center gap-1 mb-5"
    >
      <span className="text-[10px] tracking-widest text-[var(--app-muted-text)] uppercase" style={monoFont}>
        System
      </span>
      <div className="px-3 py-2 max-w-[90%] text-center border border-black/10 bg-black/[0.03] rounded-[8px]">
        <p className="text-[12px] text-black/70 leading-relaxed whitespace-pre-wrap" style={monoFont}>
          {message.content}
        </p>
      </div>
    </motion.div>
  );
});

const UserMessage = React.memo(function UserMessage({
  message,
  nickname,
  chatAnnotationMode = false,
  layerAnnotations,
  onChatAnnotationDraft,
}: {
  message: Message;
  nickname: string;
  chatAnnotationMode?: boolean;
  layerAnnotations?: ChatLayerAnnotation[];
  onChatAnnotationDraft?: (d: { messageId: string; start: number; end: number; x: number; y: number }) => void;
}) {
  const contentRef = useRef<HTMLParagraphElement>(null);
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, layout: { duration: 0.28, ease: [0.22, 1, 0.36, 1] } }}
      className="flex flex-col items-end gap-1 mb-6"
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[11px] text-[var(--app-muted-text)] tracking-wider" style={monoFont}>
          {formatTime(message.timestamp)}
        </span>
        <div className="w-[7px] h-[7px] rounded-[1.5px] flex-shrink-0 bg-red-500" />
        <span className="text-[11px] tracking-widest text-black" style={monoFont}>
          {(nickname || "You").toUpperCase()}
        </span>
      </div>
      <div className="px-4 py-3 bg-black rounded-[10px] rounded-tr-[2px] max-w-[85%]">
        <p
          ref={contentRef}
          onMouseUp={() => {
            if (!chatAnnotationMode || !contentRef.current || !onChatAnnotationDraft) return;
            const sel = getChatSelectionInElement(contentRef.current);
            if (!sel) return;
            onChatAnnotationDraft({
              messageId: message.id,
              start: sel.start,
              end: sel.end,
              x: sel.rect.left + sel.rect.width / 2,
              y: sel.rect.top - 8,
            });
          }}
          className={`text-[13px] text-white leading-relaxed whitespace-pre-wrap ${chatAnnotationMode ? "select-text cursor-text" : ""}`}
          style={monoFont}
        >
          {chatAnnotationMode && (layerAnnotations?.length ?? 0) > 0
            ? renderChatAnnotatedText(message.content, layerAnnotations!, "user")
            : message.content}
        </p>
      </div>
    </motion.div>
  );
});

const MODE_LABELS: Record<ExperimentMode, string> = { full: "Multi-1", limited: "Multi-2", single: "Single" };

const ConvItem = React.memo(function ConvItem({ conv, isActive, onSelectConv }: { conv: Conversation; isActive: boolean; onSelectConv: (id: string) => void }) {
  const mode = conv.settings?.mode ?? "full";
  const modeLabel = MODE_LABELS[mode];
  return (
    <button
      onClick={() => onSelectConv(conv.id)}
      className={`w-full text-left px-3 py-3 rounded-[8px] transition-colors flex flex-col gap-1 ${
        isActive ? "bg-black text-white" : "hover:bg-black/5"
      }`}
    >
      <div className="flex items-center justify-between gap-2 min-w-0">
        <span className="text-[12px] truncate flex-1" style={{ ...monoFont, color: isActive ? "#fff" : "#000" }}>
          {conv.title}
        </span>
        <span className="text-[9px] px-1.5 py-0.5 rounded flex-shrink-0" style={{ ...monoFont, color: isActive ? "rgba(255,255,255,0.7)" : "rgba(0,0,0,0.4)", background: isActive ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.06)" }}>
          {modeLabel}
        </span>
      </div>
      <span className="text-[10px] truncate" style={{ ...monoFont, color: isActive ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.4)" }}>
        {conv.timestamp}
      </span>
    </button>
  );
});

// ─── Attach menu (+ button, upload file etc.) ───────────────────────────────────

function AttachMenu({ open, onClose, anchorRef }: { open: boolean; onClose: () => void; anchorRef: React.RefObject<HTMLButtonElement | null> }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node) && anchorRef.current && !anchorRef.current.contains(e.target as Node)) onClose(); };
    if (open) document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open, onClose, anchorRef]);

  if (!open) return null;
  return (
    <motion.div ref={ref} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }}
      className="absolute bottom-full left-0 mb-2 bg-white border border-black/10 rounded-[12px] shadow-[0_2px_12px_rgba(0,0,0,0.06)] py-2 min-w-[200px] z-50">
      <button onClick={() => { onClose(); /* TODO: file upload */ }} className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-black/5 transition-colors text-left">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
        <span className="text-[12px]" style={monoFont}>Add photos and files</span>
      </button>
    </motion.div>
  );
}


// ─── Session summary panel (decision-direction recap for current room) ─

function SummaryPanel({
  open,
  onClose,
  roomId,
  markdown,
  loading,
  error,
  onRefresh,
}: {
  open: boolean;
  onClose: () => void;
  roomId: string;
  markdown: string | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  if (!open) return null;
  return (
    <motion.div
      className="fixed inset-0 z-[220] flex items-center justify-center p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <button type="button" className="absolute inset-0 bg-black/30" aria-label="Close summary" onClick={onClose} />
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.98 }}
        transition={{ duration: 0.2 }}
        className="relative z-10 w-full max-w-[560px] max-h-[min(80vh,720px)] flex flex-col bg-white border border-black/10 rounded-[16px] shadow-[0_8px_40px_rgba(0,0,0,0.12)] overflow-hidden"
      >
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-black/8">
          <div className="min-w-0">
            <p className="text-[13px] text-black" style={monoFont}>Decision summary</p>
            <p className="text-[10px] text-[var(--app-muted-text)] mt-0.5 truncate" style={monoFont}>
              Session {roomId}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="px-2.5 py-1.5 rounded-[8px] border border-black/10 text-[11px] text-black/70 hover:bg-black/5 disabled:opacity-40"
              style={monoFont}
            >
              {loading ? "Generating…" : "Refresh"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-[8px] hover:bg-black/5 text-black/50"
              aria-label="Close"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading && !markdown && (
            <p className="text-[12px] text-[var(--app-muted-text)]" style={monoFont}>
              Reading this session&apos;s log and drafting the direction summary…
            </p>
          )}
          {error && (
            <p className="text-[12px] text-red-600 border border-red-200 bg-red-50 px-3 py-2 rounded-[8px]" style={monoFont}>
              {error}
            </p>
          )}
          {markdown && (
            <pre
              className="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-black/85"
              style={monoFont}
            >
              {markdown}
            </pre>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}

// ─── Settings menu (Customize Agent, Customize Scene, Reload, Export) ─

function SettingsMenu({ open, onClose, anchorRef, onCustomize, onScene, onAppearance, onReloadHistory, onSummary, onExportLog, onPastMemory, hasRoomId, showPastMemory, showFontColor, onToggleFontColor }: {
  open: boolean; onClose: () => void; anchorRef: React.RefObject<HTMLButtonElement | null>;
  onCustomize: () => void; onScene: () => void; onAppearance: () => void;
  onReloadHistory: () => void; onSummary: () => void; onExportLog: () => void;
  onPastMemory?: () => void; hasRoomId: boolean; showPastMemory?: boolean;
  showFontColor: boolean; onToggleFontColor: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node) && anchorRef.current && !anchorRef.current.contains(e.target as Node)) onClose(); };
    if (open) document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open, onClose, anchorRef]);

  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => {
      if ((e.key === "c" || e.key === "C") && !["INPUT", "TEXTAREA"].includes((e.target as HTMLElement)?.tagName)) {
        e.preventDefault();
        onToggleFontColor();
      }
    };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [open, onToggleFontColor]);

  if (!open) return null;
  const Item = ({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) => (
    <button onClick={() => { onClose(); onClick(); }} className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-black/5 transition-colors text-left">
      <span className="opacity-40 flex-shrink-0">{icon}</span>
      <span className="text-[12px]" style={monoFont}>{label}</span>
    </button>
  );
  return (
    <motion.div ref={ref} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }}
      className="absolute bottom-full right-0 mb-2 bg-white border border-black/10 rounded-[12px] shadow-[0_2px_12px_rgba(0,0,0,0.06)] py-2 min-w-[200px] z-50">
      <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>} label="Customize Agent" onClick={onCustomize} />
      <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>} label="Customize Scene" onClick={onScene} />
      {showFontColor && <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3a9 9 0 1 0 9 9"/><circle cx="12" cy="12" r="3"/></svg>} label="字体颜色" onClick={onAppearance} />}
      {hasRoomId && (
        <>
          <Item icon={<svg width="14" height="14" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"><polyline points="17.18 15 8.18 15 8.18 6"/><path d="M10.58,12A18,18,0,1,1,6.23,26.88"/></svg>} label="Reload history" onClick={onReloadHistory} />
          <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="11" x2="14" y2="11"/></svg>} label="Decision summary" onClick={onSummary} />
          <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>} label="Export log" onClick={onExportLog} />
        </>
      )}
      {showPastMemory && onPastMemory && (
        <Item
          icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>}
          label="Past session memory"
          onClick={onPastMemory}
        />
      )}
    </motion.div>
  );
}

// ─── User Menu (Account, Help, Logout) ─────────────────────────────────────────

function UserMenu({ nickname, isAdmin, onAccount, onHelp, onAdmin, onLogout, onClose }: {
  nickname: string; isAdmin?: boolean; onAccount: () => void; onHelp: () => void; onAdmin?: () => void; onLogout: () => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [onClose]);

  const Item = ({ icon, label, onClick, danger = false }: { icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean }) => (
    <button onClick={onClick} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-[8px] transition-colors text-left ${danger ? "hover:bg-red-50 text-red-500" : "hover:bg-black/5 text-black"}`}>
      <span className="opacity-40 flex-shrink-0">{icon}</span>
      <span className="text-[12px]" style={monoFont}>{label}</span>
    </button>
  );

  return (
    <motion.div ref={ref} initial={{ opacity: 0, y: 6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 6, scale: 0.97 }} transition={{ duration: 0.15 }}
      className="absolute bottom-[56px] left-3 right-3 bg-white border border-black/10 rounded-[12px] shadow-[0_2px_12px_rgba(0,0,0,0.06)] z-50 py-2 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 mb-1">
        <div className="w-[7px] h-[7px] rounded-[1.5px] bg-red-500 flex-shrink-0" />
        <span className="text-[12px] tracking-widest text-black" style={monoFont}>{(nickname || "you").toUpperCase()}</span>
      </div>
      <div className="px-1">
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>} label="Account" onClick={() => { onClose(); onAccount(); }} />
        {isAdmin && onAdmin && (
          <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>} label="Admin" onClick={() => { onClose(); onAdmin(); }} />
        )}
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>} label="Help" onClick={() => { onClose(); onHelp(); }} />
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>} label="Logout" onClick={() => { onClose(); onLogout(); }} danger />
      </div>
    </motion.div>
  );
}

// ─── Customizer Modal (paginated cards) ────────────────────────────────────────

const CARD_LABELS = ["Basic", "Emotion", "Behavior"] as const;

function CustomizerModal({
  agentNames,
  agentSettings,
  experimentMode,
  onSave,
  onClose,
  onAnalyze,
  initialOpenCard = null,
  tutorialStep = null,
  onTutorialBack,
  onTutorialNext,
  onTutorialSkip,
  guideGradientPalette,
}: {
  agentNames: Record<AgentKey, string>;
  agentSettings: Record<AgentKey, AgentCustomSetting>;
  experimentMode: ExperimentMode;
  onSave: (names: Record<AgentKey, string>, settings: Record<AgentKey, AgentCustomSetting>) => void;
  onClose: () => void;
  onAnalyze: (key: AgentKey, v: number, a: number, c: number, text?: string) => Promise<{ emotion_tag: string; confidence: number } | null>;
  initialOpenCard?: AgentKey | null;
  tutorialStep?: number | null;
  onTutorialBack?: () => void;
  onTutorialNext?: () => void;
  onTutorialSkip?: () => void;
  guideGradientPalette: GuideGradientPalette;
}) {
  const [localNames, setLocalNames] = useState<Record<AgentKey, string>>({ ...agentNames });
  const [localSettings, setLocalSettings] = useState<Record<AgentKey, AgentCustomSetting>>({ A: { ...agentSettings.A }, B: { ...agentSettings.B }, C: { ...agentSettings.C } });
  const [selectedAgent, setSelectedAgent] = useState<AgentKey>(initialOpenCard || "A");
  const [custTags, setCustTags] = useState<Partial<Record<AgentKey, string>>>({});
  const [custConfs, setCustConfs] = useState<Partial<Record<AgentKey, number>>>({});
  const [page, setPage] = useState(0);
  const [isSaving, setIsSaving] = useState(false);

  const canEditAdvanced = experimentMode === "full";
  const agentOptions = experimentMode === "single" ? [("A" as AgentKey)] : AGENT_KEYS;
  const totalCards = canEditAdvanced ? 3 : 1;
  const tutorialCardIndex = tutorialStep !== null && tutorialStep >= 2 && tutorialStep <= 4 ? tutorialStep - 2 : null;
  const tutorialGuideStep = tutorialStep !== null ? WELCOME_TUTORIAL_STEPS[tutorialStep] : null;

  useEffect(() => { if (initialOpenCard) setSelectedAgent(initialOpenCard); }, [initialOpenCard]);
  useEffect(() => { setPage(0); }, [selectedAgent]);
  useEffect(() => { analyze(selectedAgent); }, [selectedAgent]);
  useEffect(() => {
    if (tutorialCardIndex !== null) setPage(tutorialCardIndex);
  }, [tutorialCardIndex]);

  const upd = (key: AgentKey, field: keyof AgentCustomSetting, value: unknown) =>
    setLocalSettings((prev) => ({ ...prev, [key]: { ...prev[key], [field]: value } }));

  const analyze = async (key: AgentKey, snapshot?: AgentCustomSetting) => {
    const s = snapshot ?? localSettings[key];
    const r = await onAnalyze(key, s.valence, s.arousal, s.control, s.emotionText || "");
    if (r) {
      setCustTags((p) => ({ ...p, [key]: r.emotion_tag }));
      setCustConfs((p) => ({ ...p, [key]: r.confidence }));
      upd(key, "emotionTag", r.emotion_tag);
    }
    return r;
  };

  const handleSave = async () => {
    if (isSaving) return;
    setIsSaving(true);
    try {
      let settingsToSave: Record<AgentKey, AgentCustomSetting> = {
        A: { ...localSettings.A },
        B: { ...localSettings.B },
        C: { ...localSettings.C },
      };
      if (canEditAdvanced) {
        await Promise.all(agentOptions.map(async (key) => {
          const snapshot = settingsToSave[key];
          const r = await analyze(key, snapshot);
          if (r?.emotion_tag) {
            settingsToSave = {
              ...settingsToSave,
              [key]: {
                ...settingsToSave[key],
                emotionOn: true,
                emotionTag: r.emotion_tag,
              },
            };
          }
        }));
      }
      onSave(localNames, settingsToSave);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  const goPrev = () => setPage((p) => Math.max(0, p - 1));
  const goNext = () => setPage((p) => Math.min(totalCards - 1, p + 1));

  const renderCard = (key: AgentKey, cardIndex: number) => {
    const s = localSettings[key];
    const accentColor = s.accentColor || DEFAULT_AGENT_COLORS[key];
    const emotionTag = custTags[key] || s.emotionTag;
    const examples = emotionTag ? (EMOTION_EXAMPLES[emotionTag] || []) : [];

    if (cardIndex === 0) {
      return (
        <div key="basic" className="flex flex-col gap-4 w-full break-words">
          <div>
            <label className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5 block" style={monoFont}>Display Name</label>
            <input type="text" value={localNames[key]} maxLength={24} onChange={(e) => setLocalNames((p) => ({ ...p, [key]: e.target.value }))}
              className="w-full text-[12px] px-3 py-1.5 border border-black/15 rounded-[6px] outline-none focus:border-black/40 transition-colors" style={monoFont} />
          </div>
          <div>
            <label className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5 block" style={monoFont}>Accent Color</label>
            <div className="flex items-center gap-2">
              <input type="color" value={accentColor} onChange={(e) => upd(key, "accentColor", e.target.value)}
                className="w-10 h-8 rounded-[6px] border border-black/15 cursor-pointer p-0" />
              <input type="text" value={accentColor} onChange={(e) => upd(key, "accentColor", e.target.value)}
                className="flex-1 text-[11px] px-3 py-1.5 border border-black/15 rounded-[6px] outline-none focus:border-black/40 font-mono" maxLength={7} />
            </div>
          </div>
        </div>
      );
    }

    if (cardIndex === 1 && canEditAdvanced) {
      return (
        <div key="emotion" className="flex flex-col gap-4 w-full break-words">
          <div>
            <label className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5 block" style={monoFont}>Emotion Status</label>
            <p className="text-[10px] text-[var(--app-muted-text)] mb-2" style={monoFont}>Adjust valence, arousal, control to shape response tone</p>
            <div className="flex flex-col gap-2">
              {emotionTag && (
                <div className="flex items-center gap-2 px-2 py-1.5 border rounded-[6px] text-[11px]"
                  style={{ borderColor: (EMOTION_COLORS[emotionTag] || "#000") + "40", background: (EMOTION_COLORS[emotionTag] || "#000") + "10", color: EMOTION_COLORS[emotionTag] || "#000", ...monoFont }}>
                  <EmotionIcon emotion={emotionTag} size={16} />
                  <span className="capitalize">{emotionTag}</span>
                  <span style={{ color: "var(--app-muted-text)" }}>{Math.round((custConfs[key] || 0) * 100)}%</span>
                </div>
              )}
              {([{ label: "Valence", field: "valence" as const, val: s.valence }, { label: "Arousal", field: "arousal" as const, val: s.arousal }, { label: "Control", field: "control" as const, val: s.control }] as const).map(({ label, field, val }) => (
                <div key={field} className="flex items-center gap-2">
                  <span className="text-[10px] text-[var(--app-muted-text)] w-14 flex-shrink-0" style={monoFont}>{label}</span>
                  <input type="range" min={0} max={100} value={Math.round(val * 100)}
                    onChange={(e) => upd(key, field, parseInt(e.target.value) / 100)} onMouseUp={() => analyze(key)} onTouchEnd={() => analyze(key)}
                    className="flex-1 h-[3px] accent-black" />
                  <span className="text-[10px] text-[var(--app-muted-text)] w-8 text-right" style={monoFont}>{val.toFixed(2)}</span>
                </div>
              ))}
              <div className="mt-2">
                <label className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5 block" style={monoFont}>Emotion from text</label>
                <p className="text-[10px] text-[var(--app-muted-text)] mb-1.5" style={monoFont}>Describe the tone you want (e.g. I feel happy, excited). Leave empty to use sliders only.</p>
                <input type="text" value={s.emotionText ?? ""} onChange={(e) => upd(key, "emotionText", e.target.value)} onBlur={() => analyze(key)}
                  placeholder="e.g. I feel excited, worried..."
                  className="w-full text-[11px] px-3 py-2 border border-black/15 rounded-[6px] outline-none focus:border-black/40 transition-colors" style={monoFont} />
              </div>
            </div>
          </div>
          {examples.length > 0 && (
            <div>
              <p className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5" style={monoFont}>Example responses</p>
              <ul className="text-[10px] text-[var(--app-muted-text)] space-y-1 pl-3 border-l-2 border-black/10" style={{ ...monoFont, borderColor: (EMOTION_COLORS[emotionTag!] || "#000") + "30" }}>
                {examples.slice(0, 3).map((ex, i) => (
                  <li key={i} className="pl-2">"{ex}"</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      );
    }

    if (cardIndex === 2 && canEditAdvanced) {
      return (
        <div key="behavior" className="flex flex-col gap-4 w-full break-words">
          <div>
            <label className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5 block" style={monoFont}>Decision making style</label>
            <p className="text-[10px] text-[var(--app-muted-text)] mb-2" style={monoFont}>Reasoning style for this agent</p>
            <CustomDropdown
              value={s.decisionBlock}
              onChange={(v) => upd(key, "decisionBlock", v as AgentCustomSetting["decisionBlock"])}
              options={DECISION_BLOCKS.map((b) => ({ value: b, label: b }))}
              size="sm"
              style={monoFont}
            />
            <p className="text-[9px] text-[var(--app-muted-text)] mt-1" style={monoFont}>{DECISION_BLOCK_DESCRIPTIONS[s.decisionBlock]}</p>
            {DECISION_BLOCK_EXAMPLES[s.decisionBlock]?.length > 0 && (
              <div className="mt-2">
                <p className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5" style={monoFont}>Example responses</p>
                <ul className="text-[10px] text-[var(--app-muted-text)] space-y-1 pl-3 border-l-2 border-black/10" style={monoFont}>
                  {DECISION_BLOCK_EXAMPLES[s.decisionBlock].slice(0, 3).map((ex, i) => (
                    <li key={i} className="pl-2">"{ex}"</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div>
            <label className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5 block" style={monoFont}>Additional Prompt</label>
            <textarea value={s.additionalPrompt} onChange={(e) => upd(key, "additionalPrompt", e.target.value)} placeholder="Extra instructions for this agent..." rows={3}
              className="w-full text-[11px] px-3 py-2 border border-black/15 rounded-[6px] outline-none resize-none leading-relaxed focus:border-black/40 transition-colors" style={monoFont} />
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
      className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center overflow-y-auto py-8 px-4" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 8 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-[480px] bg-white rounded-[16px] shadow-[0_8px_32px_rgba(0,0,0,0.1)] overflow-hidden flex flex-col max-h-[90vh]" onClick={(e) => e.stopPropagation()}>
        {tutorialCardIndex !== null && (
          <div className="px-5 pt-5 pb-0">
            <div className="relative rounded-[14px] bg-[#fffdfa] p-4">
              <AnimatedGuideFrame active palette={guideGradientPalette} rounded="rounded-[14px]" inset="inset-0" fillColor={GUIDE_FRAME_FILL} pulse />
              <div className="relative z-10">
                <div className="flex items-center justify-between gap-3 mb-2">
                  <p className="text-[11px] tracking-widest text-black uppercase" style={monoFont}>
                    {tutorialStep! + 1}/{WELCOME_TUTORIAL_STEPS.length} · {tutorialGuideStep?.title}
                  </p>
                  <button
                    type="button"
                    onClick={onTutorialSkip}
                    className="text-[10px] text-[var(--app-muted-text)] hover:text-black transition-colors"
                    style={monoFont}
                  >
                    skip
                  </button>
                </div>
                <p className="text-[12px] text-black/75 leading-relaxed" style={monoFont}>
                  {tutorialGuideStep?.body}
                </p>
                <div className="flex items-center justify-between mt-4">
                  <button
                    type="button"
                    onClick={onTutorialBack}
                    className="px-3 py-2 rounded-[10px] border border-black/10 text-[11px] text-[var(--app-muted-text)] hover:text-black hover:border-black/20 transition-colors"
                    style={monoFont}
                  >
                    back
                  </button>
                  <button
                    type="button"
                    onClick={onTutorialNext}
                    className="px-3 py-2 rounded-[10px] bg-black text-white text-[11px] hover:bg-neutral-800 transition-colors"
                    style={monoFont}
                  >
                    {tutorialStep === 3 ? "continue" : "next"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
        <div className="flex items-center justify-between px-5 py-4 border-b border-black/8 flex-shrink-0">
          <div>
            <h2 className="text-[15px]" style={{ ...monoFont, fontWeight: 600 }}>Customize Agent</h2>
            <p className="text-[10px] text-[var(--app-muted-text)] mt-0.5" style={monoFont}>{canEditAdvanced ? `${CARD_LABELS[page]} · ${totalCards} cards` : "Configure name and color"}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px] transition-colors">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div className="px-5 py-4 flex-1 min-h-0 flex flex-col overflow-hidden">
          <div className="mb-3 flex-shrink-0">
            <label className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5 block" style={monoFont}>Select Agent</label>
            <CustomDropdown
              value={selectedAgent}
              onChange={(v) => setSelectedAgent(v as AgentKey)}
              options={agentOptions.map((key) => ({ value: key, label: localNames[key] }))}
              style={monoFont}
            />
          </div>
          <div className="border border-black/10 rounded-[12px] overflow-hidden bg-black/[0.02] flex-1 min-h-0 flex flex-col">
            <div className="overflow-x-hidden overflow-y-auto flex-1 min-h-0 w-full" style={{ minWidth: 0 }}>
              <motion.div
                className="flex"
                animate={{ x: `-${page * 100}%` }}
                transition={{ type: "spring", stiffness: 300, damping: 30 }}
              >
                {Array.from({ length: totalCards }).map((_, i) => (
                  <div key={i} className="shrink-0 grow-0 basis-full p-4">
                    {renderCard(selectedAgent, i)}
                  </div>
                ))}
              </motion.div>
            </div>
            {totalCards > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-black/8 bg-white/50">
                <button onClick={goPrev} disabled={page === 0 || tutorialCardIndex !== null}
                  className="p-2 rounded-[8px] hover:bg-black/5 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6"/></svg>
                </button>
                <div className="flex gap-1.5">
                  {Array.from({ length: totalCards }).map((_, i) => (
                    <button key={i} onClick={() => tutorialCardIndex === null && setPage(i)}
                      disabled={tutorialCardIndex !== null}
                      className={`w-2 h-2 rounded-full transition-all ${i === page ? "bg-black scale-125" : "bg-black/25 hover:bg-black/40"} disabled:cursor-not-allowed`}
                      aria-label={`Card ${i + 1}`} />
                  ))}
                </div>
                <button onClick={goNext} disabled={page === totalCards - 1 || tutorialCardIndex !== null}
                  className="p-2 rounded-[8px] hover:bg-black/5 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6"/></svg>
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-black/8">
          <motion.button onClick={onClose} whileTap={{ scale: 0.97 }} disabled={isSaving} className="px-4 py-2 text-[12px] border border-black/15 rounded-[8px] hover:bg-black/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" style={monoFont}>Cancel</motion.button>
          <motion.button onClick={handleSave} whileTap={{ scale: 0.97 }} disabled={isSaving} className="px-4 py-2 text-[12px] bg-black text-white rounded-[8px] hover:bg-neutral-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" style={monoFont}>{isSaving ? "Saving..." : "Save"}</motion.button>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ─── Scene Selector ───────────────────────────────────────────────────────────

function SceneSelectorModal({ scenes, selectedScene, onSelect, onClose, lang, onLangChange }: {
  scenes: Scene[];
  selectedScene: Scene | null;
  onSelect: (s: Scene) => void;
  onClose: () => void;
  lang: UiLang;
  onLangChange: (lang: UiLang) => void;
}) {
  const SCENE_PAGE_SIZE = 3;
  const scenePages: Scene[][] = Array.from(
    { length: Math.ceil((scenes?.length || 0) / SCENE_PAGE_SIZE) },
    (_, i) => scenes.slice(i * SCENE_PAGE_SIZE, i * SCENE_PAGE_SIZE + SCENE_PAGE_SIZE),
  );
  const [page, setPage] = useState(0);

  useEffect(() => {
    if (!selectedScene || scenes.length === 0) { setPage(0); return; }
    const idx = scenes.findIndex((s) => s.id === selectedScene.id);
    if (idx >= 0) setPage(Math.floor(idx / SCENE_PAGE_SIZE));
  }, [selectedScene?.id, scenes]);

  const goPrev = () => setPage((p) => Math.max(0, p - 1));
  const goNext = () => setPage((p) => Math.min(Math.max(scenePages.length - 1, 0), p + 1));

  return (
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 8 }}
        transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-[720px] bg-white rounded-[16px] shadow-[0_8px_32px_rgba(0,0,0,0.1)] overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-black/8">
          <div>
            <h2 className="text-[16px]" style={{ ...monoFont, fontWeight: 600 }}>
              {lang === "zh" ? "选择场景" : "Choose scenario"}
            </h2>
            <p className="text-[11px] text-[var(--app-muted-text)] mt-0.5" style={monoFont}>
              {lang === "zh" ? "就职 / 亲子 · 先选语言" : "Employment / Parent-Child · pick language first"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex border border-black/15 rounded-[8px] overflow-hidden text-[11px]" style={monoFont}>
              <button
                type="button"
                onClick={() => onLangChange("en")}
                className={`px-2.5 py-1.5 ${lang === "en" ? "bg-black text-white" : "hover:bg-black/5"}`}
              >
                EN
              </button>
              <button
                type="button"
                onClick={() => onLangChange("zh")}
                className={`px-2.5 py-1.5 ${lang === "zh" ? "bg-black text-white" : "hover:bg-black/5"}`}
              >
                中文
              </button>
            </div>
            <button onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px] transition-colors">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
        </div>
        <div className="px-6 py-5 flex-1 min-h-0 flex flex-col overflow-hidden">
          <div className="border border-black/10 rounded-[12px] overflow-hidden bg-black/[0.02] flex-1 min-h-0 flex flex-col">
            <div className="overflow-x-hidden overflow-y-auto flex-1 min-h-0 w-full" style={{ minWidth: 0 }}>
              <motion.div
                className="flex"
                animate={{ x: `-${page * 100}%` }}
                transition={{ type: "spring", stiffness: 300, damping: 30 }}
              >
                {(scenePages.length > 0 ? scenePages : [[]]).map((pageScenes, pageIdx) => (
                  <div key={pageIdx} className="shrink-0 grow-0 basis-full p-4">
                    <div className="grid grid-cols-2 gap-3">
                      {pageScenes.map((s) => (
                        <button key={s.id} onClick={() => onSelect(s)}
                          className={`text-left p-4 border-2 rounded-[12px] transition-all hover:shadow-[0_2px_12px_rgba(0,0,0,0.06)] ${selectedScene?.id === s.id ? "border-black" : "border-black/10 hover:border-black/30"}`}>
                          <div className="text-2xl mb-2">{s.icon}</div>
                          <div className="text-[13px] mb-1" style={{ ...monoFont, fontWeight: 500 }}>{s.title}</div>
                          <div className="text-[10px] text-[var(--app-muted-text)] leading-relaxed" style={monoFont}>{s.description}</div>
                          {isAgora2SceneId(s.id) && (
                            <div className="text-[9px] text-[var(--app-muted-text)] mt-2 tracking-widest uppercase" style={monoFont}>intake required</div>
                          )}
                        </button>
                      ))}
                      <motion.button
                        whileHover={{ y: -2 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => {}}
                        className="border-2 border-dashed border-black/15 rounded-[12px] p-4 flex flex-col items-center justify-center gap-1 hover:border-black/40 hover:bg-black/2 transition-colors group min-h-[120px]"
                      >
                        <svg width="20" height="20" viewBox="0 0 16 16" fill="none" className="opacity-20 group-hover:opacity-50 transition-opacity">
                          <path d="M8 1V15M1 8H15" stroke="black" strokeWidth="1.5" strokeLinecap="round"/>
                        </svg>
                        <span className="text-[10px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={monoFont}>customize</span>
                      </motion.button>
                    </div>
                  </div>
                ))}
              </motion.div>
            </div>
            {(scenePages.length || 0) > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-black/8 bg-white/50">
                <button onClick={goPrev} disabled={page === 0}
                  className="p-2 rounded-[8px] hover:bg-black/5 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6"/></svg>
                </button>
                <div className="flex gap-1.5">
                  {scenePages.map((_, i) => (
                    <button key={i} onClick={() => setPage(i)}
                      className={`w-2 h-2 rounded-full transition-all ${i === page ? "bg-black scale-125" : "bg-black/25 hover:bg-black/40"}`}
                      aria-label={`Scene page ${i + 1}`} />
                  ))}
                </div>
                <button onClick={goNext} disabled={page === scenePages.length - 1}
                  className="p-2 rounded-[8px] hover:bg-black/5 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6"/></svg>
                </button>
              </div>
            )}
          </div>
        </div>
        {selectedScene && (
          <div className="px-6 pb-4">
            <button onClick={() => { onSelect(null as unknown as Scene); }} className="text-[11px] text-[var(--app-muted-text)] hover:text-black transition-colors" style={monoFont}>Clear selection</button>
          </div>
        )}
      </motion.div>
  );
}

// ─── Main Chat Component ──────────────────────────────────────────────────────

export default function Chat() {
  const navigate = useNavigate();
  const auth = getAuth();
  const nickname: string = auth?.user_id || "You";
  const isAdmin = !!auth?.is_admin;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConvId, setCurrentConvId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [typingKeys, setTypingKeys] = useState<AgentKey[]>([]);
  const [msgQueue, setMsgQueue] = useState<Array<{
    agentKey: AgentKey | "system";
    content: string;
    convId: string;
    emotionTagSnapshot: string | null;
    isSystem?: boolean;
  }>>([]);
  const agentNamesRef = useRef<Record<AgentKey, string>>(DEFAULT_AGENT_NAMES);
  const agentSettingsRef = useRef<Record<AgentKey, AgentCustomSetting>>({ A: defaultSetting("A"), B: defaultSetting("B"), C: defaultSetting("C") });
  const quickAdjustPendingRef = useRef<Record<AgentKey, Promise<void> | null>>({ A: null, B: null, C: null });

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [showCustomizer, setShowCustomizer] = useState(false);
  const [customizerInitialAgent, setCustomizerInitialAgent] = useState<AgentKey | null>(null);
  const [showSceneSelector, setShowSceneSelector] = useState(false);
  const [showAppearanceModal, setShowAppearanceModal] = useState(false);
  const [showFontColorInSettings, setShowFontColorInSettings] = useState(false);
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [sessionCreateError, setSessionCreateError] = useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  /** Cached markdown per room_id — summary always follows the active session. */
  const [summaryByRoom, setSummaryByRoom] = useState<Record<string, string>>({});
  const attachBtnRef = useRef<HTMLButtonElement>(null);
  const settingsBtnRef = useRef<HTMLButtonElement>(null);

  const [maxAgentTurns, setMaxAgentTurns] = useState(5);
  const [maxUserGap, setMaxUserGap] = useState(12);
  const [currentPhase, setCurrentPhase] = useState<string | null>(null);
  const [showPhaseIndicator, setShowPhaseIndicator] = useState(false);

  const [agentNames, setAgentNames] = useState<Record<AgentKey, string>>({ ...DEFAULT_AGENT_NAMES });
  const [agentBackendNames, setAgentBackendNames] = useState<Record<AgentKey, string>>({ ...DEFAULT_AGENT_NAMES });
  const [agentSettings, setAgentSettings] = useState<Record<AgentKey, AgentCustomSetting>>({ A: defaultSetting("A"), B: defaultSetting("B"), C: defaultSetting("C") });
  const [limitedSelectedAgents, setLimitedSelectedAgents] = useState<AgentPoolKey[]>([...LIMITED_DEFAULT_SELECTED]);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null);
  const [pendingIntakeScene, setPendingIntakeScene] = useState<Scene | null>(null);
  const [pendingProfileScene, setPendingProfileScene] = useState<Scene | null>(null);
  const [agora2Intake, setAgora2Intake] = useState<Agora2IntakePayload | null>(null);
  const [userProfile, setUserProfile] = useState<Record<string, unknown> | null>(null);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [uiLang, setUiLang] = useState<UiLang>("en");
  const [sessionCountBefore, setSessionCountBefore] = useState(0);
  const [sessionIndex, setSessionIndex] = useState<number | null>(null);
  const [lastIntake, setLastIntake] = useState<Record<string, unknown> | null>(null);
  const [showMemoryHistory, setShowMemoryHistory] = useState(false);
  const [experimentMode, setExperimentMode] = useState<ExperimentMode>("full");
  const [welcomeTutorialStep, setWelcomeTutorialStep] = useState<number | null>(null);

  const [chatAnnotationMode, setChatAnnotationMode] = useState(false);
  const [chatLayerAnnotations, setChatLayerAnnotations] = useState<Record<string, ChatLayerAnnotation[]>>({});
  const [chatAnnotationDraft, setChatAnnotationDraft] = useState<{
    messageId: string;
    start: number;
    end: number;
    x: number;
    y: number;
  } | null>(null);

  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const messagesContentRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const welcomeAgentsRef = useRef<HTMLDivElement>(null);
  const welcomeSceneRef = useRef<HTMLDivElement>(null);
  const welcomePromptsRef = useRef<HTMLDivElement>(null);
  const welcomeInputRef = useRef<HTMLDivElement>(null);
  const currentConv = conversations.find((c) => c.id === currentConvId) || null;
  const appearance = useAppearanceContext();
  const webUserId = useMemo(
    () => auth?.user_id || "web_user",
    [auth?.user_id],
  );
  const suggestedPrompts = selectedScene?.suggestedPrompts?.length
    ? selectedScene.suggestedPrompts
    : [];

  useEffect(() => {
    if (!auth?.token) {
      navigate("/", { replace: true });
    }
  }, [auth?.token, navigate]);

  const openSceneSelector = useCallback(() => {
    setShowSceneSelector(true);
  }, []);

  const beginAgora2Scene = useCallback(async (s: Scene) => {
    setSelectedScene(s);
    setAgora2Intake(null);
    setUserProfile(null);
    setSessionIndex(null);
    setLastIntake(null);
    setSessionCountBefore(0);
    try {
      const res = await authFetch(`/agora2/memory?scenario_type=${encodeURIComponent(s.id)}`);
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setSessionCountBefore(Number(data.session_count) || 0);
        setLastIntake((data.last_intake as Record<string, unknown>) || null);
      }
    } catch {
      /* first session */
    }
    setShowSceneSelector(false);
    setPendingProfileScene(s);
    setShowProfileModal(true);
  }, []);

  const scrollMessagesToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const c = messagesContainerRef.current;
    if (!c) return;
    c.scrollTo({ top: c.scrollHeight, behavior });
  }, []);
  const getPopoverSafeRect = useCallback(() => messagesContainerRef.current?.getBoundingClientRect() ?? null, []);
  const postParamChanges = useCallback((changes: Array<Record<string, unknown>>) => {
    const mode = currentConv?.settings?.mode ?? experimentMode;
    if (mode !== "full" || !currentConv?.roomId || changes.length === 0) return;
    fetch(`${API_BASE}/log-param-change`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ room_id: currentConv.roomId, mode, changes }),
    }).catch(() => {});
  }, [currentConv?.roomId, currentConv?.settings?.mode, experimentMode]);

  const onChatAnnotationDraft = useCallback(
    (d: { messageId: string; start: number; end: number; x: number; y: number }) => {
      setChatAnnotationDraft(d);
    },
    [],
  );

  const clearChatAnnotations = useCallback(() => {
    setChatLayerAnnotations({});
    setChatAnnotationDraft(null);
    window.getSelection()?.removeAllRanges();
  }, []);

  const applyChatLayer = useCallback((layer: ChatLayerKind) => {
    if (!chatAnnotationDraft) return;
    const { messageId, start, end } = chatAnnotationDraft;
    setChatLayerAnnotations((prev) => {
      const existing = prev[messageId] ?? [];
      if (existing.some((a) => chatAnnotationOverlap(a.start, a.end, start, end))) return prev;
      const id = `ca-${messageId}-${start}-${end}-${Date.now()}`;
      return { ...prev, [messageId]: [...existing, { id, start, end, layer }] };
    });
    setChatAnnotationDraft(null);
    window.getSelection()?.removeAllRanges();
  }, [chatAnnotationDraft]);

  useEffect(() => { if (!getAuth()?.token) navigate("/"); }, [navigate]);

  // Restore past rooms from SQLite after re-login
  useEffect(() => {
    if (!getAuth()?.token) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch("/me/rooms?limit=50");
        if (!res.ok) return;
        const data = await res.json();
        const rooms: Array<{
          room_id: string;
          title?: string;
          scenario_type?: string;
          updated_at?: string;
          phase?: string;
          concluded?: boolean;
        }> = data.rooms || [];
        if (cancelled) return;
        // Server list is source of truth for this user — do not keep foreign/stale stubs
        setConversations((prev) => {
          const prevByRoom = new Map(prev.map((c) => [c.roomId, c]));
          const serverIds = new Set(rooms.map((r) => r.room_id).filter(Boolean));
          const restored: Conversation[] = rooms
            .filter((r) => r.room_id)
            .map((r) => {
              const existing = prevByRoom.get(r.room_id);
              if (existing) {
                return {
                  ...existing,
                  title: r.title || existing.title || r.scenario_type || r.room_id,
                  preview: existing.messages.length
                    ? existing.preview
                    : (r.phase ? `Phase: ${r.phase}` : "Past session"),
                  timestamp: r.updated_at
                    ? formatTime(Date.parse(r.updated_at) || Date.now())
                    : existing.timestamp,
                  settings: {
                    ...existing.settings,
                    selectedScene:
                      existing.settings.selectedScene
                      || scenes.find((s) => s.id === r.scenario_type)
                      || null,
                  },
                };
              }
              return {
                id: `room-${r.room_id}`,
                roomId: r.room_id,
                title: r.title || r.scenario_type || r.room_id,
                preview: r.phase ? `Phase: ${r.phase}` : "Past session",
                timestamp: r.updated_at ? formatTime(Date.parse(r.updated_at) || Date.now()) : "earlier",
                messages: [],
                settings: {
                  agentNames: { ...DEFAULT_AGENT_NAMES },
                  agentBackendNames: { ...DEFAULT_AGENT_NAMES },
                  agentSettings: {
                    A: defaultSetting("A"),
                    B: defaultSetting("B"),
                    C: defaultSetting("C"),
                  },
                  limitedSelectedAgents: [...LIMITED_DEFAULT_SELECTED],
                  selectedScene: scenes.find((s) => s.id === r.scenario_type) || null,
                  maxAgentTurns,
                  maxUserGap,
                  mode: experimentMode,
                },
              };
            });
          // Keep only in-progress local chats not yet on the server list
          const localOnly = prev.filter(
            (c) => c.messages.length > 0 && c.roomId && !serverIds.has(c.roomId),
          );
          return [...localOnly, ...restored];
        });
      } catch {
        /* ignore */
      }
    })();
    return () => { cancelled = true; };
  }, [auth?.token, scenes, maxAgentTurns, maxUserGap, experimentMode]);

  useEffect(() => {
    setChatLayerAnnotations({});
    setChatAnnotationDraft(null);
    setChatAnnotationMode(false);
    setSummaryOpen(false);
    setSummaryError(null);
  }, [currentConvId]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key !== "x" && e.key !== "X") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (t?.isContentEditable) return;
      e.preventDefault();
      setChatAnnotationMode((v) => !v);
      setChatAnnotationDraft(null);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  useEffect(() => {
    if (!chatAnnotationDraft) return;
    const h = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setChatAnnotationDraft(null);
      window.getSelection()?.removeAllRanges();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [chatAnnotationDraft]);

  useEffect(() => {
    fetch(`${API_BASE}/health`).then((r) => { if (r.ok) setBackendOnline(true); }).catch(() => {});
    fetch(`${API_BASE}/agora2/scenarios?lang=${uiLang}`)
      .then((r) => {
        if (!r.ok) throw new Error(`scenarios ${r.status}`);
        return r.json();
      })
      .then((d) => {
        const list = (d.scenes || d.scenarios || []) as Scene[];
        setScenes(list);
        // Never auto-pick a scene — user must choose explicitly.
        setSelectedScene((prev) => {
          if (!prev) return null;
          return list.find((s) => s.id === prev.id) || null;
        });
      })
      .catch(() => setScenes([]));
  }, [uiLang]);

  useEffect(() => {
    if (currentConv) {
      setWelcomeTutorialStep(null);
    }
  }, [currentConv]);

  useEffect(() => {
    const c = messagesContainerRef.current;
    if (!c) return;
    const updateStickiness = () => {
      stickToBottomRef.current = c.scrollHeight - c.scrollTop - c.clientHeight < 140;
    };
    updateStickiness();
    c.addEventListener("scroll", updateStickiness, { passive: true });
    return () => c.removeEventListener("scroll", updateStickiness);
  }, [currentConvId]);

  useEffect(() => {
    const content = messagesContentRef.current;
    if (!content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (!stickToBottomRef.current) return;
      scrollMessagesToBottom(typingKeys.length > 0 ? "auto" : "smooth");
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [currentConvId, scrollMessagesToBottom, typingKeys.length]);

  useLayoutEffect(() => {
    if (!currentConvId) return;
    const frame = window.requestAnimationFrame(() => scrollMessagesToBottom("auto"));
    return () => window.cancelAnimationFrame(frame);
  }, [currentConvId, scrollMessagesToBottom]);

  useEffect(() => { agentNamesRef.current = agentNames; }, [agentNames]);
  useEffect(() => { agentSettingsRef.current = agentSettings; }, [agentSettings]);

  useEffect(() => {
    if (welcomeTutorialStep === null || currentConv) return;
    const targetMap: Partial<Record<number, HTMLDivElement | null>> = {
      0: welcomeSceneRef.current,
      1: welcomeAgentsRef.current,
      5: welcomePromptsRef.current,
      6: welcomeInputRef.current,
    };
    const target = targetMap[welcomeTutorialStep];
    if (!target) return;
    const frame = window.requestAnimationFrame(() => {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [welcomeTutorialStep, currentConv]);

  // Queue processor: typing dot → message → next
  useEffect(() => {
    if (msgQueue.length === 0) {
      setTypingKeys([]);
      return;
    }
    const next = msgQueue[0];
    const isSystem = !!next.isSystem || next.agentKey === "system";
    if (!isSystem && next.agentKey !== "system") {
      setTypingKeys([next.agentKey as AgentKey]);
    } else {
      setTypingKeys([]);
    }
    const delay = isSystem ? 200 : 900;
    const timer = setTimeout(() => {
      const agentMsg: Message = {
        id: `msg-${Date.now()}-${next.agentKey}`,
        role: isSystem ? "system" : "agent",
        agentKey: isSystem ? undefined : (next.agentKey as AgentKey),
        content: next.content,
        timestamp: Date.now(),
        emotionTagSnapshot: isSystem ? null : next.emotionTagSnapshot,
      };
      const names = agentNamesRef.current;
      const previewLabel = isSystem ? "System" : names[next.agentKey as AgentKey];
      setConversations((prev) => prev.map((c) => c.id === next.convId ? { ...c, messages: [...c.messages, agentMsg], preview: `${previewLabel}: ${next.content.slice(0, 60)}…`, timestamp: "just now" } : c));
      setMsgQueue((q) => {
        const rest = q.slice(1);
        const n0 = rest[0];
        setTypingKeys(rest.length > 0 && n0 && !n0.isSystem && n0.agentKey !== "system" ? [n0.agentKey as AgentKey] : []);
        return rest;
      });
    }, delay);
    return () => clearTimeout(timer);
  }, [msgQueue]);

  const analyzeEmotionForAgent = useCallback(async (_key: AgentKey, v: number, a: number, c: number, text = "") => {
    try {
      const res = await fetch(`${API_BASE}/emotion/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: (text || "").trim(), valence: v, arousal: a, control: c }) });
      if (!res.ok) return null;
      return await res.json();
    } catch { return null; }
  }, []);

  const handleQuickEmotionAdjust = useCallback((key: AgentKey, patch: Partial<AgentCustomSetting>, shouldAnalyze?: boolean) => {
    setAgentSettings((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        ...patch,
      },
    }));
    if (!shouldAnalyze) return Promise.resolve();
    const next = {
      ...agentSettingsRef.current[key],
      ...patch,
    };
    const pending = (async () => {
      const result = await analyzeEmotionForAgent(key, next.valence, next.arousal, next.control, next.emotionText || "");
      if (!result) return;
      setAgentSettings((prev) => ({
        ...prev,
        [key]: {
          ...prev[key],
          emotionOn: true,
          emotionTag: result.emotion_tag,
        },
      }));
    })();
    quickAdjustPendingRef.current[key] = pending.finally(() => {
      if (quickAdjustPendingRef.current[key] === pending) {
        quickAdjustPendingRef.current[key] = null;
      }
    });
    return pending;
  }, [analyzeEmotionForAgent]);

  const commitQuickAdjustChanges = useCallback(async (key: AgentKey, before: AgentCustomSetting) => {
    const mode = currentConv?.settings?.mode ?? experimentMode;
    if (mode !== "full" || !currentConv?.roomId) return;
    await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    if (quickAdjustPendingRef.current[key]) {
      await quickAdjustPendingRef.current[key];
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    }
    const after = agentSettingsRef.current[key];
    if (!after) return;
    const changes: Array<Record<string, unknown>> = [];
    if (!sameEmotionSnapshot(before, after)) {
      changes.push({
        type: "emotion",
        source: "hover_menu",
        agent: FULL_AGENT_NAMES[key],
        before: {
          emotionOn: before.emotionOn,
          emotionTag: before.emotionTag,
          valence: before.valence,
          arousal: before.arousal,
          control: before.control,
        },
        after: {
          emotionOn: after.emotionOn,
          emotionTag: after.emotionTag,
          valence: after.valence,
          arousal: after.arousal,
          control: after.control,
        },
      });
    }
    if (before.decisionBlock !== after.decisionBlock) {
      changes.push({
        type: "decision",
        source: "hover_menu",
        agent: FULL_AGENT_NAMES[key],
        before: before.decisionBlock,
        after: after.decisionBlock,
      });
    }
    postParamChanges(changes);
  }, [currentConv?.roomId, currentConv?.settings?.mode, experimentMode, postParamChanges]);

  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text || isLoading) return;
    if (!currentConvId && !selectedScene) {
      setSessionCreateError("Select a scene first — do not start without choosing your scenario.");
      openSceneSelector();
      return;
    }
    if (!currentConvId && experimentMode === "limited" && limitedSelectedAgents.length !== 3) {
      setSessionCreateError("Limited mode requires selecting exactly 3 agents.");
      return;
    }
    setSessionCreateError(null);
    setInputValue("");
    setIsLoading(true);

    const userMsg: Message = { id: `msg-${Date.now()}`, role: "user", content: text, timestamp: Date.now() };
    let convId = currentConvId;
    let roomId = currentConv?.roomId || "";
    const isNewConv = !convId;
    let nextNamesForConv: Record<AgentKey, string> = { ...agentNamesRef.current };
    let nextBackendNamesForConv: Record<AgentKey, string> = { ...agentBackendNames };
    let nextSettingsForConv: Record<AgentKey, AgentCustomSetting> = {
      A: { ...agentSettingsRef.current.A },
      B: { ...agentSettingsRef.current.B },
      C: { ...agentSettingsRef.current.C },
    };

    if (!convId) {
      if (isAgora2SceneId(selectedScene?.id) && (!userProfile || !agora2Intake)) {
        if (!userProfile) {
          setSessionCreateError("Complete your profile before chatting.");
          setShowProfileModal(true);
        } else {
          setSessionCreateError("Complete session intake for this scene before chatting.");
          if (selectedScene) setPendingIntakeScene(selectedScene);
        }
        setInputValue(text);
        setIsLoading(false);
        return;
      }
      try {
        const res = await fetch(`${API_BASE}/start`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(auth?.token ? { Authorization: `Bearer ${auth.token}` } : {}),
          },
          body: JSON.stringify({
            scene_id: selectedScene!.id,
            mode: experimentMode,
            limited_selected_agent_keys: experimentMode === "limited" ? limitedSelectedAgents : undefined,
            ...(isAgora2SceneId(selectedScene.id) && userProfile && agora2Intake
              ? {
                  scenario_type: selectedScene.id,
                  lang: agora2Intake.lang || uiLang,
                  profile: userProfile,
                  intake: agora2Intake.intake,
                  hint: agora2Intake.hint || "",
                  session_update: agora2Intake.session_update || "",
                  user_id: webUserId,
                  use_demo_intake: false,
                }
              : {}),
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          setSessionCreateError((data?.error as string) || `Failed to create session (${res.status}). Please try again.`);
          setInputValue(text);
          setIsLoading(false);
          return;
        }
        roomId = data.room_id || "";
        if (!roomId) {
          setSessionCreateError("No room_id from server. Please try again.");
          setInputValue(text);
          setIsLoading(false);
          return;
        }
        if (typeof data.session_index === "number") setSessionIndex(data.session_index);
        // Apply agent defaults from info.jsonl (decision, emotion)
        const agentsFromApi = data.agents || [];
        if (agentsFromApi.length > 0) {
          agentsFromApi.forEach((a: { key?: string; pool_key?: string; name?: string; decision?: string; emotion?: string; role?: string }) => {
            const k = a.key as AgentKey;
            if (k && (k === "A" || k === "B" || k === "C")) {
              const defaultCfg = defaultSetting(k);
              const shouldApplyApiBehaviorDefaults =
                experimentMode !== "full" ||
                (
                  sameEmotionSnapshot(nextSettingsForConv[k], defaultCfg) &&
                  nextSettingsForConv[k].decisionBlock === defaultCfg.decisionBlock
                );
              if (a.name) nextBackendNamesForConv[k] = a.name;
              if (experimentMode === "limited") {
                const profile = LIMITED_AGENT_POOL.find((p) => p.key === (a.pool_key as AgentPoolKey));
                nextNamesForConv[k] = profile?.defaultName || a.name || nextNamesForConv[k];
              }
              nextSettingsForConv[k] = {
                ...nextSettingsForConv[k],
                decisionBlock: shouldApplyApiBehaviorDefaults
                  ? ((a.decision as AgentCustomSetting["decisionBlock"]) || nextSettingsForConv[k].decisionBlock || "Rational")
                  : nextSettingsForConv[k].decisionBlock,
                emotionTag: shouldApplyApiBehaviorDefaults
                  ? (a.emotion ? String(a.emotion).toLowerCase() : nextSettingsForConv[k].emotionTag)
                  : nextSettingsForConv[k].emotionTag,
                roleDescription: experimentMode === "limited"
                  ? (LIMITED_AGENT_POOL.find((p) => p.key === (a.pool_key as AgentPoolKey))?.roleDescription || a.role || nextSettingsForConv[k].roleDescription)
                  : nextSettingsForConv[k].roleDescription,
                accentColor: experimentMode === "limited"
                  ? (LIMITED_POOL_ACCENT_MAP[(a.pool_key as AgentPoolKey) || "A"] || nextSettingsForConv[k].accentColor)
                  : nextSettingsForConv[k].accentColor,
              };
            }
          });
          setAgentNames(nextNamesForConv);
          setAgentBackendNames(nextBackendNamesForConv);
          setAgentSettings(nextSettingsForConv);
        }
      } catch {
        setSessionCreateError(backendOnline ? "Failed to create session. Please try again." : "Backend is not running. Start with: python app.py");
        setInputValue(text);
        setIsLoading(false);
        return;
      }
      const newConv: Conversation = {
        id: `conv-${Date.now()}`, roomId, title: text.length > 48 ? text.slice(0, 48) + "…" : text, preview: text, timestamp: "just now", messages: [userMsg],
        settings: { agentNames: nextNamesForConv, agentBackendNames: nextBackendNamesForConv, agentSettings: nextSettingsForConv, limitedSelectedAgents, selectedScene, maxAgentTurns, maxUserGap, mode: experimentMode },
      };
      setConversations((prev) => [newConv, ...prev]);
      convId = newConv.id;
      setCurrentConvId(convId);
      setCurrentPhase(null);
    } else {
      setConversations((prev) => prev.map((c) => c.id === convId ? { ...c, messages: [...c.messages, userMsg], timestamp: "just now" } : c));
    }

    const activeMode: ExperimentMode = isNewConv ? experimentMode : (currentConv?.settings?.mode ?? "full");
    const requestAgentSettings: Record<AgentKey, AgentCustomSetting> = isNewConv
      ? nextSettingsForConv
      : agentSettingsRef.current;
    const agentEmotionOverrides: Record<string, string> = {};
    const additionalRules: Record<string, string> = {};
    const agentDecisionBlock: Record<string, string> = {};
    const useNeutral = activeMode === "limited" || activeMode === "single";
    if (useNeutral) {
      if (activeMode === "single") agentDecisionBlock["A"] = "Rational";
    } else {
      AGENT_KEYS.forEach((k) => {
        if (requestAgentSettings[k].emotionOn && requestAgentSettings[k].emotionTag) agentEmotionOverrides[k] = requestAgentSettings[k].emotionTag!;
        if (requestAgentSettings[k].additionalPrompt) additionalRules[k] = requestAgentSettings[k].additionalPrompt;
        agentDecisionBlock[k] = requestAgentSettings[k].decisionBlock;
      });
    }

    const maxTurns = activeMode === "single" ? 1 : maxAgentTurns;
    setTypingKeys(activeMode === "single" ? ["A"] : ["A"]);

    const postMessage = async (rid: string) => {
      const res = await fetch(`${API_BASE}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          room_id: rid,
          message: text,
          scene_id: selectedScene?.id || currentConv?.settings?.selectedScene?.id || "",
          emotion_tag: null,
          emotion_target: null,
          agent_emotion_overrides: agentEmotionOverrides,
          additional_rules: additionalRules,
          agent_decision_block: agentDecisionBlock,
          max_agent_turns_before_user: maxTurns,
          max_user_gap: maxUserGap,
          single_mode: activeMode === "single",
        }),
      });
      const data = await res.json().catch(() => ({}));
      return { res, data };
    };

    const recreateRoom = async (): Promise<string | null> => {
      // Backend restarted → in-memory room gone; recreate with same profile/intake.
      const sceneForRecreate = selectedScene || currentConv?.settings?.selectedScene || null;
      if (!sceneForRecreate?.id) return null;
      if (isAgora2SceneId(sceneForRecreate.id) && (!userProfile || !agora2Intake)) {
        return null;
      }
      const res = await fetch(`${API_BASE}/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(auth?.token ? { Authorization: `Bearer ${auth.token}` } : {}),
        },
        body: JSON.stringify({
          scene_id: sceneForRecreate.id,
          mode: activeMode,
          limited_selected_agent_keys: activeMode === "limited" ? limitedSelectedAgents : undefined,
          ...(isAgora2SceneId(sceneForRecreate.id) && userProfile && agora2Intake
            ? {
                scenario_type: sceneForRecreate.id,
                lang: agora2Intake.lang || uiLang,
                profile: userProfile,
                intake: agora2Intake.intake,
                hint: agora2Intake.hint || "",
                session_update: agora2Intake.session_update || "",
                user_id: webUserId,
                use_demo_intake: false,
              }
            : {}),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.room_id) return null;
      if (typeof data.session_index === "number") setSessionIndex(data.session_index);
      return String(data.room_id);
    };

    try {
      let { res, data } = await postMessage(roomId);
      if (!res.ok && String((data as { error?: string })?.error || "").includes("Invalid room_id")) {
        const newRoom = await recreateRoom();
        if (!newRoom) {
          throw new Error("Session expired after server restart. Re-select the scene and try again.");
        }
        roomId = newRoom;
        setConversations((prev) =>
          prev.map((c) => (c.id === convId ? { ...c, roomId: newRoom } : c)),
        );
        ({ res, data } = await postMessage(roomId));
      }
      if (!res.ok) {
        throw new Error((data as { error?: string })?.error || `HTTP ${res.status}`);
      }
      setCurrentPhase(data.phase || null);
      const responses: Array<{
        agent_key: string;
        message: string;
       
      }> = data.responses || [];
      if (responses.length === 0) { setTypingKeys([]); }
      else {
        const mapped = responses
          .filter((r) => !!(r.message || "").trim())
          .map((r) => {
            const isSystem = r.agent_key === "system" || r.agent_key === "System";
            const agentKey = (isSystem ? "system" : (r.agent_key || "A")) as AgentKey | "system";
            const currentSetting = !isSystem ? agentSettingsRef.current[agentKey as AgentKey] : null;
            return {
              agentKey,
              content: r.message || "",
              convId: convId as string,
              emotionTagSnapshot: currentSetting?.emotionOn ? (currentSetting.emotionTag ?? "joy") : null,
              isSystem,
            };
          });
        const filtered = activeMode === "single"
          ? mapped.filter((m) => m.isSystem || m.agentKey === "A").slice(0, 2)
          : mapped;
        setMsgQueue(filtered);
      }
    } catch (err) {
      setTypingKeys([]);
      const detail = err instanceof Error && err.message ? err.message : "Something went wrong. Please try again.";
      const errMsg: Message = { id: `msg-err-${Date.now()}`, role: "agent", content: backendOnline ? detail : "Backend is not running. Start with: python app.py", timestamp: Date.now() };
      setConversations((prev) => prev.map((c) => c.id === convId ? { ...c, messages: [...c.messages, errMsg] } : c));
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };


  const handleLoadHistory = async () => {
    if (!currentConv?.roomId) return;
    try {
      const res = await authFetch(`/history/${currentConv.roomId}`);
      if (!res.ok) return;
      const data = await res.json();
      const runtimeMap: Record<string, AgentKey> = {};
      const runtimeBackendNames: Partial<Record<AgentKey, string>> = {};
      const runtimeNames: Partial<Record<AgentKey, string>> = {};
      const modeForHistory: ExperimentMode = currentConv?.settings?.mode ?? experimentMode;
      (data.active_agents || []).forEach((a: { key?: string; name?: string }) => {
        const k = a.key as AgentKey;
        if ((k === "A" || k === "B" || k === "C") && a.name) {
          runtimeMap[a.name] = k;
          runtimeBackendNames[k] = a.name;
          if (modeForHistory !== "limited") {
            runtimeNames[k] = a.name;
          }
        }
      });
      if (Object.keys(runtimeNames).length > 0) {
        setAgentNames((prev) => ({ ...prev, ...runtimeNames }));
      }
      if (Object.keys(runtimeBackendNames).length > 0) {
        setAgentBackendNames((prev) => ({ ...prev, ...runtimeBackendNames }));
      }
      const hist = data.history || [];
      const messages: Message[] = hist.map((
        h: { character: string; txt: string },
        i: number,
      ) => {
        if (h.character === "user") return { id: `h-${i}`, role: "user" as const, content: h.txt, timestamp: Date.now() - (hist.length - i) * 1000 };
        if (h.character === "system") {
          return {
            id: `h-${i}`,
            role: "system" as const,
            content: h.txt,
            timestamp: Date.now() - (hist.length - i) * 1000,
          };
        }
        const agentKey = runtimeMap[h.character] ?? BACKEND_NAME_TO_KEY[h.character] ?? "A";
        const currentSetting = agentSettingsRef.current[agentKey];
        return {
          id: `h-${i}`,
          role: "agent" as const,
          agentKey,
          content: h.txt,
          timestamp: Date.now() - (hist.length - i) * 1000,
          emotionTagSnapshot: currentSetting?.emotionOn ? (currentSetting.emotionTag ?? "joy") : null,
        };
      });
      setConversations((prev) => prev.map((c) => c.id === currentConvId ? { ...c, messages } : c));
      if (data.phase) setCurrentPhase(data.phase);
    } catch {}
  };

  const handleExportLog = async () => {
    if (!currentConv?.roomId) return;
    try {
      const res = await fetch(`${API_BASE}/export-logs/${currentConv.roomId}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert((err as { error?: string }).error || "Export failed");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `agora_logs_${currentConv.roomId}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Export failed — is the backend running?");
    }
  };

  const fetchSessionSummary = async (force = false) => {
    const roomId = currentConv?.roomId;
    if (!roomId) return;
    if (!force && summaryByRoom[roomId]) {
      setSummaryError(null);
      setSummaryOpen(true);
      return;
    }
    setSummaryOpen(true);
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const res = await fetch(`${API_BASE}/summary/${roomId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lang: uiLang }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setSummaryError((data as { error?: string }).error || "Could not generate summary");
        return;
      }
      setSummaryByRoom((prev) => ({ ...prev, [roomId]: (data as { markdown?: string }).markdown || "" }));
    } catch {
      setSummaryError("Summary failed — is the backend running?");
    } finally {
      setSummaryLoading(false);
    }
  };

  const handleOpenSummary = () => {
    void fetchSessionSummary(false);
  };

  const defaultConvSettings = (mode: ExperimentMode = "full"): ConvSettings => ({
    agentNames: { ...DEFAULT_AGENT_NAMES },
    agentBackendNames: { ...DEFAULT_AGENT_NAMES },
    agentSettings: { A: defaultSetting("A"), B: defaultSetting("B"), C: defaultSetting("C") },
    limitedSelectedAgents: [...LIMITED_DEFAULT_SELECTED],
    selectedScene: null,
    maxAgentTurns: 5,
    maxUserGap: 12,
    mode,
  });

  const getConvSettings = (conv: Conversation | null): ConvSettings => {
    const def = defaultConvSettings(experimentMode);
    if (!conv?.settings) return def;
    return { ...def, ...conv.settings, mode: conv.settings.mode ?? "full" };
  };

  const saveCurrentConvSettings = useCallback(() => {
    if (!currentConvId) return;
    const existingMode = currentConv?.settings?.mode ?? "full";
    const s: ConvSettings = { agentNames, agentBackendNames, agentSettings, limitedSelectedAgents, selectedScene, maxAgentTurns, maxUserGap, mode: existingMode };
    setConversations((prev) => prev.map((c) => c.id === currentConvId ? { ...c, settings: s } : c));
  }, [currentConvId, currentConv?.settings?.mode, experimentMode, agentNames, agentBackendNames, agentSettings, limitedSelectedAgents, selectedScene, maxAgentTurns, maxUserGap]);

  const loadConvSettings = useCallback((conv: Conversation | null) => {
    const s = getConvSettings(conv);
    setAgentNames(s.agentNames);
    setAgentBackendNames(s.agentBackendNames || { ...DEFAULT_AGENT_NAMES });
    const merged = (k: AgentKey) => ({ ...defaultSetting(k), ...s.agentSettings[k] });
    const mergedSettings = { A: merged("A"), B: merged("B"), C: merged("C") };
    setAgentSettings(mergedSettings);
    agentNamesRef.current = { ...s.agentNames };
    agentSettingsRef.current = {
      A: { ...mergedSettings.A },
      B: { ...mergedSettings.B },
      C: { ...mergedSettings.C },
    };
    setLimitedSelectedAgents(normalizeLimitedSelection(s.limitedSelectedAgents || LIMITED_DEFAULT_SELECTED));
    setSelectedScene(s.selectedScene);
    setMaxAgentTurns(s.maxAgentTurns);
    setMaxUserGap(s.maxUserGap);
  }, [experimentMode]);

  useEffect(() => {
    if (!currentConvId) {
      loadConvSettings(null);
      return;
    }
    if (currentConv) {
      loadConvSettings(currentConv);
    }
  }, [currentConvId, currentConv?.id]);

  useEffect(() => {
    if (currentConvId) saveCurrentConvSettings();
  }, [agentNames, agentBackendNames, agentSettings, limitedSelectedAgents, selectedScene, maxAgentTurns, maxUserGap]);

  const handleNewChat = () => {
    setCurrentConvId(null);
    loadConvSettings(null);
    setTypingKeys([]);
    setMsgQueue([]);
    setSidebarOpen(false);
    inputRef.current?.focus();
  };
  const handleSelectConv = useCallback((id: string) => {
    const conv = conversations.find((c) => c.id === id);
    setCurrentConvId(id);
    loadConvSettings(conv || null);
    setTypingKeys([]);
    setMsgQueue([]);
    setSidebarOpen(false);
    // Past rooms restored from DB often have empty messages — pull history
    if (conv?.roomId && (!conv.messages || conv.messages.length === 0)) {
      void (async () => {
        try {
          const res = await authFetch(`/history/${conv.roomId}`);
          if (!res.ok) return;
          const data = await res.json();
          const hist = data.history || [];
          const messages: Message[] = hist.map((
            h: { character: string; txt: string },
            i: number,
          ) => {
            if (h.character === "user") {
              return { id: `h-${i}`, role: "user" as const, content: h.txt, timestamp: Date.now() - (hist.length - i) * 1000 };
            }
            if (h.character === "system") {
              return { id: `h-${i}`, role: "system" as const, content: h.txt, timestamp: Date.now() - (hist.length - i) * 1000 };
            }
            const agentKey = (BACKEND_NAME_TO_KEY[h.character] ?? "A") as AgentKey;
            return {
              id: `h-${i}`,
              role: "agent" as const,
              agentKey,
              content: h.txt,
              timestamp: Date.now() - (hist.length - i) * 1000,
                };
          });
          setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, messages } : c)));
          if (data.phase) setCurrentPhase(data.phase);
        } catch {
          /* ignore */
        }
      })();
    }
  }, [conversations, loadConvSettings]);
  const handleOpenAdvancedAgent = useCallback((key: AgentKey) => {
    setCustomizerInitialAgent(key);
    setShowCustomizer(true);
  }, []);
  const handleLogout = async () => {
    await logoutRequest();
    navigate("/");
  };
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === "Enter" && (e.metaKey || e.altKey)) { e.preventDefault(); handleSend(); } };
  const autoResizeInput = useCallback((el: HTMLTextAreaElement | null) => {
    if (!el) return;
    const maxHeight = 120;
    el.style.height = "auto";
    const nextHeight = Math.min(el.scrollHeight, maxHeight);
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? "auto" : "hidden";
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== "p") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
      }
      setShowPhaseIndicator((prev) => !prev);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    autoResizeInput(inputRef.current);
  }, [inputValue, autoResizeInput]);

  const dismissWelcomeGuide = useCallback(() => {
    setWelcomeTutorialStep(null);
    setShowCustomizer(false);
    setCustomizerInitialAgent(null);
  }, []);

  const startWelcomeTutorial = useCallback(() => {
    setWelcomeTutorialStep(0);
  }, []);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key !== "t" && e.key !== "T") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (el && ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)) return;
      if (el?.isContentEditable) return;
      if (currentConv) return;
      e.preventDefault();
      if (welcomeTutorialStep !== null) {
        dismissWelcomeGuide();
      } else {
        startWelcomeTutorial();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [currentConv, welcomeTutorialStep, dismissWelcomeGuide, startWelcomeTutorial]);

  const shouldGuideThroughCustomizer = experimentMode !== "limited";

  const openCustomizerTutorial = useCallback((agent: AgentKey = "A") => {
    setCustomizerInitialAgent(agent);
    setShowCustomizer(true);
    setWelcomeTutorialStep(2);
  }, []);

  const advanceWelcomeTutorial = useCallback(() => {
    setWelcomeTutorialStep((prev) => {
      if (prev === null) return prev;
      if (prev === 0) {
        return 1;
      }
      if (prev === 1) {
        if (!shouldGuideThroughCustomizer) {
          return 5;
        }
        setCustomizerInitialAgent("A");
        setShowCustomizer(true);
        return 2;
      }
      if (prev >= 2 && prev <= 3) {
        return prev + 1;
      }
      if (prev === 4) {
        setShowCustomizer(false);
        setCustomizerInitialAgent(null);
        return 5;
      }
      if (prev >= WELCOME_TUTORIAL_STEPS.length - 1) {
        return null;
      }
      return prev + 1;
    });
  }, [shouldGuideThroughCustomizer]);

  const rewindWelcomeTutorial = useCallback(() => {
    setWelcomeTutorialStep((prev) => {
      if (prev === null) return prev;
      if (!shouldGuideThroughCustomizer && prev === 5) {
        return 1;
      }
      if (prev === 2) {
        setShowCustomizer(false);
        setCustomizerInitialAgent(null);
        return 1;
      }
      return Math.max(0, prev - 1);
    });
  }, [shouldGuideThroughCustomizer]);

  const isWelcomeStepActive = (stepIndex: number) => welcomeTutorialStep === stepIndex;
  const currentWelcomeTutorialBody =
    welcomeTutorialStep === 1 && !shouldGuideThroughCustomizer
      ? "In limited mode, choose exactly three preset agents first. After that, the guide moves on to prompts and chat controls."
      : welcomeTutorialStep !== null
        ? WELCOME_TUTORIAL_STEPS[welcomeTutorialStep].body
        : "";
  const guideGradientPalette = DEFAULT_GUIDE_GRADIENT;

  return (
    <>
    <div className="h-screen bg-white flex overflow-hidden">
      <AnimatePresence>
        {showCustomizer && (
          <CustomizerModal agentNames={agentNames} agentSettings={agentSettings} experimentMode={currentConv?.settings?.mode ?? experimentMode}
            onSave={(names, settings) => {
              const mode = currentConv?.settings?.mode ?? experimentMode;
              if (mode === "full" && currentConv?.roomId) {
                const agentFullNames: Record<AgentKey, string> = { A: "ChatbotA", B: "ChatbotB", C: "ChatbotC" };
                const changes: Array<{ type: string; agent: string; before: string | null; after: string | null }> = [];
                AGENT_KEYS.forEach((k) => {
                  const agent = agentFullNames[k];
                  if (names[k] !== agentNames[k]) changes.push({ type: "agent_name", agent, before: agentNames[k] ?? null, after: names[k] ?? null });
                  if (settings[k]?.accentColor !== agentSettings[k]?.accentColor) changes.push({ type: "accent_color", agent, before: agentSettings[k]?.accentColor ?? null, after: settings[k]?.accentColor ?? null });
                  if (settings[k]?.emotionOn !== agentSettings[k]?.emotionOn || settings[k]?.emotionTag !== agentSettings[k]?.emotionTag) changes.push({ type: "emotion", agent, before: agentSettings[k]?.emotionTag ?? null, after: settings[k]?.emotionTag ?? null });
                  if (settings[k]?.decisionBlock !== agentSettings[k]?.decisionBlock) changes.push({ type: "decision", agent, before: agentSettings[k]?.decisionBlock ?? null, after: settings[k]?.decisionBlock ?? null });
                  if ((settings[k]?.additionalPrompt ?? "") !== (agentSettings[k]?.additionalPrompt ?? "")) changes.push({ type: "additional_prompt", agent, before: agentSettings[k]?.additionalPrompt ?? null, after: settings[k]?.additionalPrompt ?? null });
                });
              if (changes.length > 0) {
                  fetch(`${API_BASE}/log-param-change`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ room_id: currentConv.roomId, mode, changes }) }).catch(() => {});
                }
              }
              setAgentNames(names);
              setAgentSettings(settings);
              agentNamesRef.current = { ...names };
              agentSettingsRef.current = { A: { ...settings.A }, B: { ...settings.B }, C: { ...settings.C } };
            }}
            onClose={() => {
              setShowCustomizer(false);
              setCustomizerInitialAgent(null);
              if (welcomeTutorialStep !== null && welcomeTutorialStep >= 2 && welcomeTutorialStep <= 4) {
                setWelcomeTutorialStep(1);
              }
            }}
            onAnalyze={analyzeEmotionForAgent}
            initialOpenCard={customizerInitialAgent}
            tutorialStep={welcomeTutorialStep}
            onTutorialBack={rewindWelcomeTutorial}
            onTutorialNext={advanceWelcomeTutorial}
            onTutorialSkip={dismissWelcomeGuide}
            guideGradientPalette={guideGradientPalette}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showProfileModal && pendingProfileScene && (
          <motion.div
            key="profile-overlay"
            className="fixed inset-0 bg-black/30 z-[60] flex items-center justify-center p-6"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => {
              if (userProfile) {
                setShowProfileModal(false);
                setPendingProfileScene(null);
              }
            }}
          >
            <ProfileModal
              userId={webUserId}
              scenarioType={pendingProfileScene.id}
              lang={uiLang}
              dismissible={!!userProfile}
              onClose={userProfile ? () => {
                setShowProfileModal(false);
                setPendingProfileScene(null);
              } : undefined}
              onConfirm={(profile) => {
                setUserProfile(profile);
                setShowProfileModal(false);
                setPendingIntakeScene(pendingProfileScene);
                setPendingProfileScene(null);
              }}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {(showSceneSelector || !!pendingIntakeScene) && (
          <motion.div
            key="scene-flow-overlay"
            className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-6"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => {
              if (pendingIntakeScene) setPendingIntakeScene(null);
              else setShowSceneSelector(false);
            }}
          >
            <AnimatePresence mode="wait" initial={false}>
              {pendingIntakeScene ? (
                <IntakeModal
                  key={`intake-${pendingIntakeScene.id}`}
                  scene={pendingIntakeScene}
                  lang={uiLang}
                  sessionCount={sessionCountBefore}
                  lastIntake={lastIntake}
                  onClose={() => setPendingIntakeScene(null)}
                  onConfirm={(payload) => {
                    setSelectedScene(pendingIntakeScene);
                    setAgora2Intake(payload);
                    setSessionIndex(sessionCountBefore + 1);
                    setPendingIntakeScene(null);
                    setShowSceneSelector(false);
                  }}
                />
              ) : (
                <SceneSelectorModal
                  key="scene-selector"
                  scenes={scenes}
                  selectedScene={selectedScene}
                  lang={uiLang}
                  onLangChange={setUiLang}
                  onSelect={(s) => {
                    if (isAgora2SceneId(s.id)) {
                      void beginAgora2Scene(s);
                      return;
                    }
                    setAgora2Intake(null);
                    setSelectedScene(s);
                    setShowSceneSelector(false);
                  }}
                  onClose={() => setShowSceneSelector(false)}
                />
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showMemoryHistory && selectedScene && isAgora2SceneId(selectedScene.id) && (
          <motion.div
            key="memory-history"
            className="fixed inset-0 bg-black/30 z-[70] flex items-center justify-center p-6"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setShowMemoryHistory(false)}
          >
            <MemoryHistoryPanel
              scenarioType={selectedScene.id}
              lang={uiLang}
              onClose={() => setShowMemoryHistory(false)}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showAppearanceModal && (
          <AppearanceModal
            open={showAppearanceModal}
            onClose={() => setShowAppearanceModal(false)}
            mutedColor={appearance.mutedColor}
            setMutedColor={appearance.setMutedColor}
            reset={appearance.reset}
            defaultColor={appearance.defaultColor}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {sidebarOpen && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/20 z-20" onClick={() => setSidebarOpen(false)} />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <aside className={`fixed z-30 h-full bg-white border-r border-black/8 flex flex-col w-[260px] min-w-0 overflow-hidden transition-transform duration-300 ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="px-4 pt-6 pb-4 flex items-center justify-between border-b border-black/8 flex-shrink-0">
          <AgoraLogoFull height={28} />
          <button className="p-1 hover:bg-black/5 rounded" onClick={() => setSidebarOpen(false)}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 3L13 13M3 13L13 3" stroke="black" strokeWidth="1.5" strokeLinecap="round"/></svg>
          </button>
        </div>
        <div className="px-3 pt-4 pb-2 flex-shrink-0">
          <button onClick={handleNewChat} className="w-full h-[40px] border border-black/20 rounded-[8px] flex items-center justify-center gap-2 hover:bg-black hover:text-white hover:border-black transition-all duration-200 group">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 1V11M1 6H11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
            <span className="text-[12px]" style={monoFont}>new chat</span>
          </button>
        </div>
        {!currentConvId && (
          <div className="px-3 py-3 border-b border-black/8 flex-shrink-0">
            <p className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-2" style={monoFont}>MODE</p>
            <div className="flex flex-col gap-1.5">
              {(["full", "limited", "single"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setExperimentMode(m)}
                  className={`w-full text-left px-3 py-2 rounded-[6px] text-[11px] transition-colors border ${
                    experimentMode === m ? "bg-black text-white border-black" : "border-black/10 hover:bg-black/5"
                  }`}
                  style={monoFont}
                >
                  {m === "full" && "Multi-1"}
                  {m === "limited" && "Multi-2"}
                  {m === "single" && "Single"}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-2 min-h-0 min-w-0">
          {conversations.length === 0 ? (
            <p className="text-center text-[var(--app-muted-text)] text-[11px] mt-8" style={monoFont}>no conversations yet</p>
          ) : (
            <div className="flex flex-col gap-1">
              {conversations.map((conv) => <ConvItem key={conv.id} conv={conv} isActive={conv.id === currentConvId} onSelectConv={handleSelectConv} />)}
            </div>
          )}
        </div>
        <div className="relative flex-shrink-0">
          <AnimatePresence>
            {userMenuOpen && (
              <UserMenu
                nickname={nickname}
                isAdmin={isAdmin}
                onAccount={() => {
                  const s = selectedScene && isAgora2SceneId(selectedScene.id) ? selectedScene : null;
                  if (s) {
                    setPendingProfileScene(s);
                    setShowProfileModal(true);
                  } else {
                    openSceneSelector();
                  }
                }}
                onHelp={() => {}}
                onAdmin={() => navigate("/admin")}
                onLogout={() => void handleLogout()}
                onClose={() => setUserMenuOpen(false)}
              />
            )}
          </AnimatePresence>
          <button onClick={() => setUserMenuOpen((v) => !v)} className="w-full flex items-center gap-2 px-3 py-4 border-t border-black/8 hover:bg-black/3 transition-colors">
            <div className="w-[7px] h-[7px] rounded-[1.5px] bg-red-500 flex-shrink-0" />
            <span className="flex-1 text-left text-[11px] text-[var(--app-muted-text)] truncate" style={monoFont}>{(nickname || "you").toUpperCase()}</span>
            {!backendOnline && <span className="text-[9px] text-amber-400 flex-shrink-0" style={monoFont}>offline</span>}
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2" className="opacity-30 flex-shrink-0"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="relative flex-1 flex flex-col min-w-0">
      <AnimatePresence>
          {!currentConv && welcomeTutorialStep !== null && !(showCustomizer && welcomeTutorialStep >= 2 && welcomeTutorialStep <= 4) && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}
              className="absolute top-[72px] right-4 sm:right-8 z-30 w-[300px] rounded-[14px] bg-[#fffdfa] p-4"
            >
              <AnimatedGuideFrame active palette={guideGradientPalette} rounded="rounded-[14px]" inset="inset-0" fillColor={GUIDE_FRAME_FILL} pulse />
              <div className="relative z-10">
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <p className="text-[11px] tracking-widest text-black uppercase" style={monoFont}>
                      {welcomeTutorialStep + 1}/{WELCOME_TUTORIAL_STEPS.length} · {WELCOME_TUTORIAL_STEPS[welcomeTutorialStep].title}
                    </p>
                    <button
                      type="button"
                      onClick={dismissWelcomeGuide}
                      className="text-[10px] text-[var(--app-muted-text)] hover:text-black transition-colors"
                      style={monoFont}
                    >
                      skip
                    </button>
                  </div>
                  <p className="text-[12px] text-black/75 leading-relaxed" style={monoFont}>
                    {currentWelcomeTutorialBody}
                  </p>
                  <div className="flex items-center justify-between mt-4">
                    <button
                      type="button"
                      onClick={rewindWelcomeTutorial}
                      disabled={welcomeTutorialStep === 0}
                      className="px-3 py-2 rounded-[10px] border border-black/10 text-[11px] text-[var(--app-muted-text)] hover:text-black hover:border-black/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                      style={monoFont}
                    >
                      back
                    </button>
                    <button
                      type="button"
                      onClick={welcomeTutorialStep === 1 && shouldGuideThroughCustomizer ? () => openCustomizerTutorial("A") : advanceWelcomeTutorial}
                      className="px-3 py-2 rounded-[10px] bg-black text-white text-[11px] hover:bg-neutral-800 transition-colors"
                      style={monoFont}
                    >
                      {welcomeTutorialStep === 1 && shouldGuideThroughCustomizer ? "open" : welcomeTutorialStep === WELCOME_TUTORIAL_STEPS.length - 1 ? "done" : "next"}
                    </button>
                  </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <header className="relative z-10 h-[56px] flex-shrink-0 flex items-center border-b border-black/8 bg-white px-4 gap-4">
          <button className="p-1.5 hover:bg-black/5 rounded-md transition-colors" onClick={() => setSidebarOpen(true)}>
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M2 4.5H16M2 9H16M2 13.5H16" stroke="black" strokeWidth="1.5" strokeLinecap="round"/></svg>
          </button>
          <div className="flex-1 flex items-center min-w-0 gap-3 relative">
            {currentConv ? (
              <span className="text-[13px] text-black/70 truncate" style={monoFont}>{currentConv.title}</span>
            ) : (
              <span className="text-[13px] text-[var(--app-muted-text)]" style={monoFont}>new conversation_</span>
            )}
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            {currentConv && (
              <div className="flex items-center gap-1.5 pr-3 border-r border-black/10" style={monoFont}>
                <span className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest">Turn {currentConv.messages?.filter((m) => m.role === "user").length ?? 0}</span>
                {showPhaseIndicator && currentPhase && (
                  <span className="text-[10px] text-[var(--app-muted-text)]">· Phase: {currentPhase}</span>
                )}
              </div>
            )}
            {(currentConv?.settings?.mode === "single" ? ["A"] : AGENT_KEYS).map((key) => (
              <div key={key} className="flex items-center gap-1.5" title={agentNames[key as AgentKey]}>
                <div className="w-[7px] h-[7px] rounded-[1.5px] flex-shrink-0" style={{ backgroundColor: agentSettings[key as AgentKey]?.accentColor || DEFAULT_AGENT_COLORS[key as AgentKey] }} />
                <span className="hidden sm:block text-[10px] tracking-widest text-black" style={monoFont}>{agentNames[key as AgentKey]}</span>
              </div>
            ))}
            <div className="flex items-center gap-1.5 ml-1 pl-3 border-l border-black/10" title={nickname || "You"}>
              <div className="w-[7px] h-[7px] rounded-[1.5px] bg-red-500" />
              <span className="hidden sm:block text-[10px] tracking-widest text-black" style={monoFont}>{(nickname || "You").toUpperCase()}</span>
            </div>
          </div>
        </header>

        <div ref={messagesContainerRef} className="relative flex-1 overflow-y-auto px-4 sm:px-8 pt-6 pb-28">
          {currentConv && chatAnnotationMode && (
            <div
              className="max-w-[680px] sm:max-w-[800px] lg:max-w-[960px] xl:max-w-[1100px] mx-auto mb-4 flex flex-wrap items-center justify-between gap-2 px-3 py-2 rounded-[10px] border border-black/10 bg-white/95 text-[11px] text-neutral-700 shadow-sm"
              style={monoFont}
            >
              <span>
                Layer annotation: select text, then choose Decision, Emotion, or Scene. Press{" "}
                <kbd className="px-1 rounded border border-black/15 bg-black/5 font-mono">x</kbd> to exit.
              </span>
              <button
                type="button"
                onClick={clearChatAnnotations}
                className="shrink-0 rounded-md border border-black/15 bg-black/[0.04] px-2.5 py-1 text-[11px] hover:bg-black/[0.08] transition-colors"
                style={monoFont}
              >
                Clear all
              </button>
            </div>
          )}
          <AnimatePresence mode="wait" initial={false}>
          {!currentConv ? (
            <motion.div
              key="welcome"
              initial={{ opacity: 0, y: 18, scale: 0.985 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -12, scale: 0.99 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
              className="w-full max-w-[440px] sm:max-w-[560px] lg:max-w-[680px] xl:max-w-[800px] mx-auto flex flex-col items-center justify-start gap-8 pt-2 pb-12"
            >
              <div className="flex flex-col items-center gap-4 w-full">
                <AgoraLogo size={96} />
                {!backendOnline && (
                  <p className="text-center text-[11px] text-amber-500 w-full leading-relaxed border border-amber-200 bg-amber-50 px-3 py-2 rounded-[8px]" style={monoFont}>
                    Backend offline — start with: <strong>python app.py</strong>
                  </p>
                )}
              </div>
              <div
                ref={welcomeAgentsRef}
                className="relative isolate order-2 w-full transition-all duration-200"
              >
                <AnimatedGuideFrame active={isWelcomeStepActive(1)} palette={guideGradientPalette} rounded="rounded-[12px]" fillColor={GUIDE_FRAME_FILL} pulse />
                <div className="relative z-10 px-2 py-2">
                  <p className="text-[10px] text-[var(--app-muted-text)] mb-3 text-center tracking-widest" style={monoFont}>AGENTS</p>
                  {experimentMode === "limited" ? (
                    <>
                      <motion.div
                        key={`agent-grid-${experimentMode}`}
                        className="grid gap-3 w-full grid-cols-2"
                        initial="hidden"
                        animate="visible"
                        variants={{ visible: { transition: { staggerChildren: 0.06, delayChildren: 0.08 } } }}
                      >
                        {LIMITED_AGENT_POOL.map((profile) => {
                          const selected = limitedSelectedAgents.includes(profile.key);
                          const atLimit = limitedSelectedAgents.length >= 3 && !selected;
                          return (
                            <motion.button
                              key={`${experimentMode}-${profile.key}`}
                              variants={{ hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0, transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] } } }}
                              whileHover={{ y: -2, boxShadow: "0 4px 14px rgba(0,0,0,0.07)" }}
                              whileTap={{ scale: 0.98 }}
                              onClick={() => {
                                if (isWelcomeStepActive(1) && shouldGuideThroughCustomizer) {
                                  openCustomizerTutorial("A");
                                  return;
                                }
                                setLimitedSelectedAgents((prev) => {
                                  const has = prev.includes(profile.key);
                                  if (has) return prev.filter((k) => k !== profile.key);
                                  if (prev.length >= 3) return prev;
                                  return [...prev, profile.key];
                                });
                              }}
                              className={`border rounded-[10px] px-3 py-3 text-left transition-colors group ${selected ? "border-black bg-black/[0.03]" : "border-black/8"} ${atLimit ? "opacity-50" : ""}`}
                            >
                              <div className="flex items-center gap-1.5 min-w-0 mb-1">
                                <div className="w-[6px] h-[6px] rounded-[1.2px] flex-shrink-0" style={{ backgroundColor: LIMITED_POOL_ACCENT_MAP[profile.key] || "#000000" }} />
                                <span className="text-[10px] tracking-widest text-black truncate" style={monoFont}>{profile.defaultName}</span>
                              </div>
                              <p className="text-[10px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={monoFont}>{profile.roleDescription}</p>
                              <p
                                className="mt-1.5 text-[8px] leading-relaxed text-[var(--app-muted-text)]/80 group-hover:text-black/55 transition-colors"
                                style={monoFont}
                              >
                                {profile.behaviorSummary}
                              </p>
                            </motion.button>
                          );
                        })}
                      </motion.div>
                      <p className="text-[10px] text-center text-[var(--app-muted-text)] mt-2" style={monoFont}>Selected {limitedSelectedAgents.length}/3</p>
                    </>
                  ) : (
                    <motion.div
                      key={`agent-grid-${experimentMode}`}
                      className={`grid gap-3 w-full ${experimentMode === "single" ? "grid-cols-1" : "grid-cols-2"}`}
                      initial="hidden"
                      animate="visible"
                      variants={{ visible: { transition: { staggerChildren: 0.07, delayChildren: 0.1 } } }}
                    >
                      {(experimentMode === "single" ? ["A"] : AGENT_KEYS).map((key) => (
                        <motion.button
                          key={`${experimentMode}-${key}`}
                          variants={{ hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0, transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] } } }}
                          whileHover={{ y: -2, boxShadow: "0 4px 14px rgba(0,0,0,0.07)" }}
                          whileTap={{ scale: 0.98 }}
                          onClick={() => {
                            if (isWelcomeStepActive(1)) {
                              openCustomizerTutorial(key as AgentKey);
                              return;
                            }
                            setCustomizerInitialAgent(key as AgentKey);
                            setShowCustomizer(true);
                          }}
                          className="border border-black/8 rounded-[10px] px-3 py-3 text-left transition-colors group"
                        >
                          <div className="flex items-center gap-1.5 mb-1">
                            <div className="w-[6px] h-[6px] rounded-[1.2px] flex-shrink-0" style={{ backgroundColor: agentSettings[key as AgentKey]?.accentColor || DEFAULT_AGENT_COLORS[key as AgentKey] }} />
                            <span className="text-[10px] tracking-widest text-black" style={monoFont}>{agentNames[key as AgentKey]}</span>
                          </div>
                          <p className="text-[10px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={monoFont}>{getEmotionDecisionSummary(agentSettings[key as AgentKey]?.emotionTag ?? null, agentSettings[key as AgentKey]?.decisionBlock ?? "Rational")}</p>
                          <p className="text-[9px] text-[var(--app-muted-text)] mt-2 group-hover:text-black/70 transition-colors" style={monoFont}>click to customize →</p>
                        </motion.button>
                      ))}
                      {experimentMode !== "single" && (
                        <motion.button
                          variants={{ hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0, transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] } } }}
                          whileHover={{ y: -2 }}
                          whileTap={{ scale: 0.98 }}
                          onClick={() => { setCustomizerInitialAgent(null); setShowCustomizer(true); }}
                          className="border border-dashed border-black/15 rounded-[10px] px-3 py-3 flex flex-col items-center justify-center gap-1 hover:border-black/40 hover:bg-black/2 transition-colors group min-h-[72px]"
                        >
                          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="opacity-20 group-hover:opacity-50 transition-opacity">
                            <path d="M8 1V15M1 8H15" stroke="black" strokeWidth="1.5" strokeLinecap="round"/>
                          </svg>
                          <span className="text-[9px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={monoFont}>customize</span>
                        </motion.button>
                      )}
                    </motion.div>
                  )}
                </div>
              </div>
              <div
                ref={welcomeSceneRef}
                className="relative isolate order-1 w-full transition-all duration-200"
              >
                <AnimatedGuideFrame active={isWelcomeStepActive(0)} palette={guideGradientPalette} rounded="rounded-[12px]" fillColor={GUIDE_FRAME_FILL} pulse />
                <div className="relative z-10 px-2 py-2">
                  <p className="text-[10px] text-[var(--app-muted-text)] mb-3 text-center tracking-widest" style={monoFont}>SCENE</p>
                  <motion.button
                    whileHover={{ y: -2, boxShadow: "0 4px 14px rgba(0,0,0,0.07)" }}
                    whileTap={{ scale: 0.98 }}
                    onClick={openSceneSelector}
                    className="w-full text-left px-4 py-3 border border-black/8 rounded-[10px] transition-colors group"
                  >
                    <div className="flex items-center gap-1.5 mb-1">
                      <div className="w-[6px] h-[6px] rounded-[1.2px] flex-shrink-0" style={{ backgroundColor: selectedScene?.color || "#000000" }} />
                      <span className="text-[10px] tracking-widest text-black" style={monoFont}>{selectedScene?.title || "Select a scene"}</span>
                      {sessionIndex != null && (
                        <span className="text-[9px] text-black/50 ml-1" style={monoFont}>· Session {sessionIndex}</span>
                      )}
                      <span className="text-[9px] text-black/40 ml-auto" style={monoFont}>{uiLang === "zh" ? "中文" : "EN"}</span>
                    </div>
                    <p className="text-[10px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={monoFont}>{selectedScene?.description || "Choose employment, parent-child, or another scenario before chatting. Nothing starts until you pick one."}</p>
                    <p className="text-[9px] text-[var(--app-muted-text)] mt-2 group-hover:text-black/70 transition-colors" style={monoFont}>
                      {selectedScene
                        ? (agora2Intake ? "intake ready · click to change →" : "click to change scenario →")
                        : "click to choose scenario →"}
                    </p>
                  </motion.button>
                </div>
              </div>
              <div
                ref={welcomePromptsRef}
                className="relative isolate order-3 w-full transition-all duration-200"
              >
                <AnimatedGuideFrame active={isWelcomeStepActive(5)} palette={guideGradientPalette} rounded="rounded-[12px]" fillColor={GUIDE_FRAME_FILL} pulse />
                <div className="relative z-10 px-2 py-2">
                  <p className="text-[10px] text-[var(--app-muted-text)] mb-3 text-center tracking-widest" style={monoFont}>SUGGESTED PROMPTS</p>
                  <div className="flex flex-col gap-2">
                    {suggestedPrompts.map((prompt, i) => (
                      <motion.button
                        key={i}
                        whileHover={{ y: -2, boxShadow: "0 4px 14px rgba(0,0,0,0.07)" }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => { setInputValue(prompt); inputRef.current?.focus(); }}
                        className="text-left px-4 py-3 border border-black/8 rounded-[10px] hover:border-black hover:bg-black/[0.03] transition-colors group"
                      >
                        <span className="text-[12px] text-[var(--app-muted-text)] group-hover:text-black/80 transition-colors" style={monoFont}>{prompt}</span>
                      </motion.button>
                    ))}
                  </div>
                </div>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="chat"
              ref={messagesContentRef}
              layout
              initial={{ opacity: 0, y: 20, scale: 0.992 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.995 }}
              transition={{ layout: { duration: 0.3, ease: [0.22, 1, 0.36, 1] } }}
              className="max-w-[680px] sm:max-w-[800px] lg:max-w-[960px] xl:max-w-[1100px] mx-auto"
            >
              {(() => {
                let userTurnCount = 0;
                const firstTurnAgentSeen: Partial<Record<AgentKey, boolean>> = {};
                const emotionTagCounts: Record<string, number> = {};
                return currentConv.messages.map((msg) => {
                  if (msg.role === "user") {
                    userTurnCount += 1;
                    return (
                      <UserMessage
                        key={msg.id}
                        message={msg}
                        nickname={nickname}
                        chatAnnotationMode={chatAnnotationMode}
                        layerAnnotations={chatLayerAnnotations[msg.id]}
                        onChatAnnotationDraft={onChatAnnotationDraft}
                      />
                    );
                  }
                  if (msg.role === "system") {
                    return <SystemMessage key={msg.id} message={msg} />;
                  }
                  const compactRepeatedIntro = !!(msg.agentKey && userTurnCount === 1 && firstTurnAgentSeen[msg.agentKey]);
                  if (msg.agentKey && userTurnCount === 1) {
                    firstTurnAgentSeen[msg.agentKey] = true;
                  }
                  const emotionTag = msg.agentKey ? (msg.emotionTagSnapshot ?? "") : "";
                  const emojiRepeatIndex = emotionTag ? (emotionTagCounts[emotionTag] || 0) : 0;
                  if (emotionTag) emotionTagCounts[emotionTag] = emojiRepeatIndex + 1;
                  return (
                    <AgentMessage
                      key={msg.id}
                      message={msg}
                      agentNames={agentNames}
                      agentBackendNames={agentBackendNames}
                      agentSettings={agentSettings}
                      mode={currentConv?.settings?.mode ?? experimentMode}
                      nickname={nickname}
                      getPopoverSafeRect={getPopoverSafeRect}
                      compactRepeatedIntro={compactRepeatedIntro}
                      emojiRepeatIndex={emojiRepeatIndex}
                      onOpenAdvancedAgent={handleOpenAdvancedAgent}
                      onQuickEmotionAdjust={handleQuickEmotionAdjust}
                      onQuickAdjustCommit={commitQuickAdjustChanges}
                      chatAnnotationMode={chatAnnotationMode}
                      layerAnnotations={chatLayerAnnotations[msg.id]}
                      onChatAnnotationDraft={onChatAnnotationDraft}
                    />
                  );
                });
              })()}
              <div />
            </motion.div>
          )}
          </AnimatePresence>
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-[148px] z-20 px-4 sm:px-8">
          <div
            className={`mx-auto transition-all duration-200 ${currentConv ? "max-w-[680px] sm:max-w-[800px] lg:max-w-[960px] xl:max-w-[1100px]" : "max-w-[440px] sm:max-w-[560px] lg:max-w-[680px] xl:max-w-[800px]"}`}
          >
            <AnimatePresence initial={false} mode="wait">
              {currentConv && typingKeys[0] && (
                <TypingDots
                  key={`status-typing-${typingKeys[0]}-${msgQueue[0]?.content ?? "pending"}`}
                  agentKey={typingKeys[0]}
                  agentNames={agentNames}
                />
              )}
            </AnimatePresence>
          </div>
        </div>

        <div className="flex-shrink-0 border-t border-black/8 px-4 sm:px-8 py-4">
          <div className={`mx-auto ${currentConv ? "max-w-[680px] sm:max-w-[800px] lg:max-w-[960px] xl:max-w-[1100px]" : "max-w-[440px] sm:max-w-[560px] lg:max-w-[680px] xl:max-w-[800px]"}`}>
            {sessionCreateError && (
              <p className="text-center text-[11px] text-amber-600 bg-amber-50 border border-amber-200 px-3 py-2 rounded-[8px] mb-3" style={monoFont}>{sessionCreateError}</p>
            )}
            <div
              ref={!currentConv ? welcomeInputRef : undefined}
              className="relative"
            >
              <AnimatedGuideFrame
                active={!currentConv && isWelcomeStepActive(6)}
                palette={guideGradientPalette}
                rounded="rounded-[16px]"
                inset="-inset-[3px]"
                fillColor={GUIDE_FRAME_FILL}
                pulse
              />
              <div className="relative z-10 flex gap-2 items-end min-h-[48px]">
              <div className="relative flex">
                <motion.button ref={attachBtnRef} onClick={() => setAttachMenuOpen((v) => !v)} type="button"
                  whileTap={{ scale: 0.95 }}
                  className="h-[48px] w-[48px] min-h-[48px] bg-black rounded-[12px] flex items-center justify-center flex-shrink-0 transition-colors hover:bg-neutral-800 group">
                  <span className="inline-flex transition-transform duration-200 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-white"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                  </span>
                </motion.button>
                <AnimatePresence>
                  <AttachMenu open={attachMenuOpen} onClose={() => setAttachMenuOpen(false)} anchorRef={attachBtnRef} />
                </AnimatePresence>
              </div>
              <div className="flex-1 min-h-[48px] bg-black rounded-[12px] flex items-center px-4 py-3">
                <textarea ref={inputRef} value={inputValue} onChange={(e) => setInputValue(e.target.value)} onKeyDown={handleKeyDown}
                  placeholder="Enter a question or topic to explore..."
                  rows={1} disabled={isLoading}
                  className="flex-1 min-h-[24px] bg-transparent resize-none outline-none text-white placeholder-[#828282] leading-relaxed disabled:opacity-50"
                  style={{ ...monoFont, fontSize: "13px", maxHeight: "120px" }}
                  onInput={(e) => autoResizeInput(e.currentTarget)} />
              </div>
              <motion.button onClick={handleSend} disabled={!inputValue.trim() || isLoading}
                whileTap={!inputValue.trim() || isLoading ? {} : { scale: 0.95 }}
                transition={{ type: "spring", stiffness: 400, damping: 25 }}
                className="h-[48px] w-[48px] min-h-[48px] bg-black rounded-[12px] flex items-center justify-center flex-shrink-0 hover:bg-neutral-800 transition-colors disabled:opacity-30 disabled:cursor-not-allowed group">
                {isLoading ? (
                  <div className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                ) : (
                  <span className="inline-flex transition-transform duration-200 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 13V3M3 8L8 3L13 8" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </span>
                )}
              </motion.button>
              <div className="relative flex">
                <motion.button ref={settingsBtnRef} onClick={() => setSettingsMenuOpen((v) => !v)} type="button"
                  whileTap={{ scale: 0.95 }}
                  className="h-[48px] w-[48px] min-h-[48px] bg-black rounded-[12px] flex items-center justify-center flex-shrink-0 transition-colors hover:bg-neutral-800 group">
                  <span className="inline-flex transition-transform duration-200 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-white"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                  </span>
                </motion.button>
                <AnimatePresence>
                  <SettingsMenu open={settingsMenuOpen} onClose={() => setSettingsMenuOpen(false)} anchorRef={settingsBtnRef}
                    onCustomize={() => setShowCustomizer(true)} onScene={openSceneSelector}
                    onAppearance={() => setShowAppearanceModal(true)}
                    onReloadHistory={handleLoadHistory}
                    onSummary={handleOpenSummary}
                    onExportLog={handleExportLog}
                    onPastMemory={() => setShowMemoryHistory(true)}
                    hasRoomId={!!currentConv?.roomId}
                    showPastMemory={!!selectedScene && isAgora2SceneId(selectedScene.id)}
                    showFontColor={showFontColorInSettings} onToggleFontColor={() => setShowFontColorInSettings((v) => !v)} />
                </AnimatePresence>
              </div>
              </div>
            </div>
            <p className="text-center text-[10px] text-[var(--app-muted-text)] mt-2" style={monoFont}>Enter for new line · ⌘+Enter / Alt+Enter to send</p>
          </div>
        </div>
      </div>
    </div>
    {chatAnnotationDraft &&
      createPortal(
        <div
          className="fixed z-[300] -translate-x-1/2 -translate-y-full rounded-lg border border-neutral-300 bg-white shadow-xl p-2 min-w-[220px]"
          style={{ left: chatAnnotationDraft.x, top: chatAnnotationDraft.y }}
          onMouseDown={(e) => e.preventDefault()}
        >
          <p className="text-[11px] text-neutral-500 mb-2 line-clamp-2 px-1" style={monoFont}>
            Select layer for this span
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => applyChatLayer("expression")}
              className="min-w-[100px] flex-1 rounded-md border border-[#e07a5f]/40 bg-[#e07a5f]/10 px-2 py-1.5 text-xs font-medium text-[#9f3f26] hover:bg-[#e07a5f]/20"
              style={monoFont}
            >
              Emotion Layer
            </button>
            <button
              type="button"
              onClick={() => applyChatLayer("decision")}
              className="min-w-[100px] flex-1 rounded-md border border-[#7c3aed]/40 bg-[#7c3aed]/10 px-2 py-1 text-xs font-medium text-[#5b21b6] hover:bg-[#7c3aed]/20"
              style={monoFont}
            >
              Decision Layer
            </button>
            <button
              type="button"
              onClick={() => applyChatLayer("scene")}
              className="min-w-[100px] flex-1 rounded-md border border-[#7BC3FF]/70 bg-[#7BC3FF]/20 px-2 py-1.5 text-xs font-medium text-[#1560a8] hover:bg-[#7BC3FF]/35"
              style={monoFont}
            >
              Scene Layer
            </button>
          </div>
        </div>,
        document.body,
      )}
    <AnimatePresence>
      {summaryOpen && currentConv?.roomId && (
        <SummaryPanel
          open={summaryOpen}
          onClose={() => setSummaryOpen(false)}
          roomId={currentConv.roomId}
          markdown={summaryByRoom[currentConv.roomId] || null}
          loading={summaryLoading}
          error={summaryError}
          onRefresh={() => void fetchSessionSummary(true)}
        />
      )}
    </AnimatePresence>
    </>
  );
}
