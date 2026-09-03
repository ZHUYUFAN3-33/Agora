import React, { useState, useRef, useEffect, useCallback, useLayoutEffect, useMemo, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { motion, AnimatePresence } from "motion/react";
import { createPortal } from "react-dom";
import { AgoraLogo, AgoraLogoFull } from "../components/AgoraLogo";
import { CustomDropdown } from "../components/ui/CustomDropdown";
import { AppearanceModal } from "../components/AppearanceModal";
import {
  DecisionNavi,
  buildDecisionNaviNodes,
  type PhaseChangeMarker,
} from "../components/DecisionNavi";
import {
  DecisionMapPanel,
  type DecisionMapData,
} from "../components/DecisionMapPanel";
import {
  IntakeModal,
  ProfileModal,
  MemoryHistoryPanel,
  type Agora2IntakePayload,
  type UiLang,
} from "../components/IntakeModal";
import {
  applyDocumentLang,
  defaultsForTone,
  getTutorialSteps,
  getUiFont,
  labelCaseClass,
  loadUiLang,
  phaseLabel,
  saveUiLang,
  t,
  toneLabel,
  toneOptions,
} from "../i18n/ui";
import { authFetch, getAuth, logoutRequest } from "../auth";
import { clearIntakeDraft, loadIntakeDraft, saveIntakeDraft } from "../intakeDraft";
import { emit, flush as flushTelemetry, setTelemetryRoom, DwellTracker } from "../telemetry";
import { useAppearanceContext } from "../context/AppearanceContext";
import {
  type AgentKey,
  type AgentPoolKey,
  type AgentCustomSetting,
  type ExperimentMode,
  type Scene,
  AGENT_KEYS,
  ALL_AGENT_KEYS,
  DEFAULT_ACTIVE_AGENT_KEYS,
  MIN_ROSTER_AGENTS,
  MAX_ROSTER_AGENTS,
  LIMITED_AGENT_POOL,
  LIMITED_DEFAULT_SELECTED,
  DEFAULT_AGENT_NAMES,
  DEFAULT_AGENT_ROLES,
  DEFAULT_AGENT_COLORS,
  API_BASE,
  BACKEND_NAME_TO_KEY,
  DECISION_BLOCKS,
  EMOTION_EMOJI,
  EMOTION_COLORS,
  EMOTION_IMAGES,
  defaultSetting,
  getEmotionDecisionSummary,
  getEmotionDecisionRole,
  getEmotionExamples,
  getDecisionExamples,
  getSuggestedPrompts,
  isAgora2SceneId,
  nextFreeAgentKey,
  backendLabelForKey,
  SCENARIO_STANCES,
  defaultStanceForKey,
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

export type ChatOptionChip = { id: string; label: string };
export type KnowledgeReference = { id: string; tag: string; source?: string };

interface Message {
  id: string;
  role: "user" | "agent" | "system";
  agentKey?: AgentKey;
  content: string;
  timestamp: number;
  emotionTagSnapshot?: string | null;
  /** Curated background actually injected for this exact agent response. */
  knowledge?: KnowledgeReference;
  /** Structured choice chips from agent [OPTIONS] block */
  options?: ChatOptionChip[];
  /** Selected option id within this message's group (locked) */
  chosenOptionId?: string | null;
}

function historyTimestamp(raw: string | undefined, index: number, total: number): number {
  if (raw) {
    const parsed = Date.parse(raw);
    if (Number.isFinite(parsed)) return parsed;
  }
  return Date.now() - (total - index) * 1000;
}

function phaseMarkersFromApi(
  changes: Array<{ from?: string; to?: string; time?: string }> | undefined,
): PhaseChangeMarker[] {
  if (!Array.isArray(changes)) return [];
  return changes
    .filter((c) => !!(c?.to))
    .map((c) => ({
      from: c.from || "",
      to: String(c.to),
      time: c.time,
    }));
}

interface ConvSettings {
  agentNames: Record<AgentKey, string>;
  agentBackendNames: Record<AgentKey, string>;
  agentSettings: Record<AgentKey, AgentCustomSetting>;
  activeAgentKeys: AgentKey[];
  limitedSelectedAgents: AgentPoolKey[];
  selectedScene: Scene | null;
  maxAgentTurns: number;
  maxUserGap: number;
  mode: ExperimentMode;
}

function blankAgentSettings(): Record<AgentKey, AgentCustomSetting> {
  return {
    A: defaultSetting("A"),
    B: defaultSetting("B"),
    C: defaultSetting("C"),
    D: defaultSetting("D"),
    E: defaultSetting("E"),
    F: defaultSetting("F"),
  };
}

function cloneAgentSettings(src: Partial<Record<AgentKey, AgentCustomSetting>>): Record<AgentKey, AgentCustomSetting> {
  const out = blankAgentSettings();
  for (const k of ALL_AGENT_KEYS) {
    if (src[k]) out[k] = { ...defaultSetting(k), ...src[k] };
  }
  return out;
}

function normalizeActiveKeys(keys: AgentKey[] | undefined, mode: ExperimentMode): AgentKey[] {
  if (mode === "single") return ["A"];
  const valid = (keys || []).filter((k): k is AgentKey => ALL_AGENT_KEYS.includes(k));
  const unique: AgentKey[] = [];
  for (const k of valid) {
    if (!unique.includes(k)) unique.push(k);
  }
  if (unique.length === 0) return [...DEFAULT_ACTIVE_AGENT_KEYS];
  return unique.slice(0, MAX_ROSTER_AGENTS);
}

function buildStartAgentsPayload(
  keys: AgentKey[],
  names: Record<AgentKey, string>,
  settings: Record<AgentKey, AgentCustomSetting>,
  scenarioId?: string | null,
) {
  return keys.map((key) => {
    const s = settings[key];
    const stance = s?.stance || defaultStanceForKey(scenarioId, key, keys);
    return {
      key,
      name: (names[key] || backendLabelForKey(key)).trim() || backendLabelForKey(key),
      decision: s?.decisionBlock || "Rational",
      emotion: s?.emotionTag || "Joy",
      accent_color: s?.accentColor || DEFAULT_AGENT_COLORS[key],
      stance: stance || undefined,
      hint: s?.hint?.trim() || undefined,
    };
  });
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

// Replace backend names (ChatbotA/B/C) with user-defined display names; replace @U / "user" with nickname.
function applyDisplayNames(
  content: string,
  names: Record<AgentKey, string>,
  nickname?: string,
  mode: ExperimentMode = "full",
  backendNames?: Record<AgentKey, string>,
): string {
  let out = content;
  for (const k of ALL_AGENT_KEYS) {
    const display = names[k];
    if (display) {
      out = out.replace(new RegExp(`\\bChatbot${k}\\b`, "g"), display);
    }
  }
  if (backendNames) {
    const keys = mode === "limited" ? (["A", "B", "C"] as AgentKey[]) : ALL_AGENT_KEYS;
    keys.forEach((k) => {
      const internalName = (backendNames[k] || "").trim();
      if (!internalName || internalName === names[k]) return;
      const escaped = internalName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      out = out.replace(new RegExp(`\\b${escaped}\\b`, "g"), names[k] || internalName);
    });
  }
  const label = (nickname || "").trim() || "You";
  out = out.replace(/@U\b/gi, `@${label}`);
  if (nickname && nickname.trim()) {
    out = out.replace(/\buser\b/gi, nickname.trim());
  }
  return out;
}

/**
 * The `**` of a bold run, kept in the DOM but not shown.
 *
 * Chat-layer annotations store offsets measured off the *rendered* text
 * (`getChatSelectionInElement` counts `Range.toString()`), while
 * `renderChatAnnotatedText` slices the *raw* string with them. Dropping the
 * markers outright would shorten the rendered text and shift every annotation
 * after a bold run by two characters per marker. `display:none` still counts
 * in `Range.toString()`, so the two stay aligned.
 */
function boldMarker(key: string): ReactNode {
  return (
    <span key={key} className="hidden">
      **
    </span>
  );
}

/** Highlight @userName (and leftover @U) in red, and render **bold** runs. */
function highlightUserMentions(text: string, nickname?: string): ReactNode {
  const label = (nickname || "").trim() || "You";
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // Either a mention, or a bold run that opens on a non-space, non-star char.
  const re = new RegExp(`@(?:${escaped}|U)\\b|\\*\\*(?=[^\\s*])([\\s\\S]+?)\\*\\*`, "gi");
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[1] !== undefined) {
      // Colour is inherited on purpose: this renders inside the white agent
      // card and inside the black user bubble.
      nodes.push(boldMarker(`bo-${i}`));
      nodes.push(
        <strong key={`b-${i}`} className="font-semibold">
          {highlightUserMentions(m[1], nickname)}
        </strong>,
      );
      nodes.push(boldMarker(`bc-${i}`));
      i += 1;
    } else {
      nodes.push(
        <span key={`um-${i++}`} className="text-red-500">
          {m[0].replace(/^@U$/i, `@${label}`)}
        </span>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last === 0) return text;
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
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
  const agentOffset = agentKey ? ALL_AGENT_KEYS.indexOf(agentKey) + 1 : 0;
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
  nickname?: string,
): ReactNode {
  if (!annotations.length) return highlightUserMentions(text, nickname);
  const sorted = [...annotations].sort((a, b) => a.start - b.start);
  let cursor = 0;
  const out: React.ReactNode[] = [];
  sorted.forEach((a) => {
    if (cursor < a.start) {
      out.push(
        <span key={`p-${a.id}-${cursor}`}>
          {highlightUserMentions(text.slice(cursor, a.start), nickname)}
        </span>,
      );
    }
    out.push(
      <span
        key={a.id}
        className={layerSpanClass(a.layer, variant)}
        title={layerTitle(a.layer)}
      >
        {highlightUserMentions(text.slice(a.start, a.end), nickname)}
      </span>,
    );
    cursor = a.end;
  });
  if (cursor < text.length) {
    out.push(
      <span key={`tail-${cursor}`}>
        {highlightUserMentions(text.slice(cursor), nickname)}
      </span>,
    );
  }
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
  label,
}: {
  // Display label, not an agent key: before the server answers, the client
  // cannot know which agent the scheduler will pick, so the pre-response
  // indicator shows a neutral "thinking" label instead of naming ChatbotA.
  // (It used to hardcode ["A"], so P41 watched "ChatbotA is typing" for 40-50s
  // while the backend was actually running B and C.)
  label: string;
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
          {label}
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
  uiLang = "en",
}: {
  agentKey: AgentKey;
  name: string;
  settings: AgentCustomSetting;
  anchorRect: DOMRect | null;
  anchorRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
  uiLang?: UiLang;
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
  const roleLabel = getEmotionDecisionRole(emotionTag, decisionBlock, uiLang);
  const behaviorDescription = getEmotionDecisionSummary(emotionTag, decisionBlock, uiLang);
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
  uiLang = "en",
}: {
  agentKey: AgentKey;
  settings: AgentCustomSetting;
  onAdjustEmotion: (key: AgentKey, patch: Partial<AgentCustomSetting>, shouldAnalyze?: boolean) => void;
  onOpenAdvanced: (key: AgentKey) => void;
  anchorRect: DOMRect | null;
  safeRect: DOMRect | null;
  onHoverStart: () => void;
  onHoverEnd: () => void;
  uiLang?: UiLang;
}) {
  if (!anchorRect || typeof window === "undefined") return null;
  const font = getUiFont(uiLang);
  const emotionTag = settings.emotionTag || "joy";
  const emotionColor = EMOTION_COLORS[emotionTag] || "#111111";
  const decisionIndex = Math.max(0, DECISION_BLOCKS.indexOf(settings.decisionBlock));
  const emotionDefaults = defaultSetting(agentKey);
  const panelWidth = 252;
  const estimatedPanelHeight = 260;
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
          {/* TONE section */}
          <div className="mb-3">
            <div className="mb-2 px-0.5">
              <span className={`text-[10px] text-foreground/85 ${labelCaseClass(uiLang)}`} style={font}>{t(uiLang, "hover.emotion")}</span>
            </div>
            <div className="rounded-[10px] border border-foreground/[0.06] bg-foreground/[0.015] px-3 py-2.5">
              <div
                className="flex items-center justify-between gap-2 rounded-[8px] border px-2.5 py-2 text-[10px] mb-2"
                style={{
                  ...font,
                  borderColor: emotionColor + "44",
                  background: emotionColor + "12",
                  color: emotionColor,
                }}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <EmotionIcon emotion={emotionTag} size={14} />
                  <span className="font-semibold">{toneLabel(uiLang, emotionTag)}</span>
                </div>
              </div>
              <CustomDropdown
                value={emotionTag}
                onChange={(v) => {
                  const d = defaultsForTone(v);
                  onAdjustEmotion(agentKey, {
                    emotionOn: true,
                    emotionTag: v,
                    valence: d.valence,
                    arousal: d.arousal,
                    control: d.control,
                    emotionText: "",
                  }, false);
                }}
                options={toneOptions(uiLang)}
                size="sm"
                style={font}
              />
            </div>
          </div>
          {/* DECISION section */}
          <div>
            <div className="mb-2 px-0.5">
              <span className={`text-[10px] text-foreground/85 ${labelCaseClass(uiLang)}`} style={font}>{t(uiLang, "hover.decision")}</span>
            </div>
            <div className="rounded-[10px] border border-foreground/[0.06] bg-foreground/[0.015] px-3 py-2.5">
              <div className="flex items-center gap-2 px-1 py-1">
                <button
                  type="button"
                  onClick={() => cycleDecision(-1)}
                  className="flex h-7 w-7 items-center justify-center rounded-[7px] text-foreground/70 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                  aria-label={t(uiLang, "hover.prevDecision")}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M15 18l-6-6 6-6" />
                  </svg>
                </button>
                <div className="min-w-0 flex-1 text-center">
                  <div className="text-[11px] text-foreground" style={font}>{t(uiLang, `decision.${settings.decisionBlock}`)}</div>
                </div>
                <button
                  type="button"
                  onClick={() => cycleDecision(1)}
                  className="flex h-7 w-7 items-center justify-center rounded-[7px] text-foreground/70 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                  aria-label={t(uiLang, "hover.nextDecision")}
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
              style={font}
            >
              {t(uiLang, "hover.resetTag")}
            </button>
            <button
              onClick={() => onOpenAdvanced(agentKey)}
              className="rounded-[6px] border border-foreground/[0.08] px-2 py-1 text-[10px] text-foreground transition-colors hover:border-foreground/20 hover:bg-foreground/[0.02]"
              style={font}
            >
              {t(uiLang, "hover.advanced")}
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
  uiLang = "en",
  highlighted = false,
  highlightToken = 0,
  onChooseOption,
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
  uiLang?: UiLang;
  highlighted?: boolean;
  highlightToken?: number;
  onChooseOption?: (message: Message, option: ChatOptionChip) => void;
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
      data-message-id={message.id}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, layout: { duration: 0.28, ease: [0.22, 1, 0.36, 1] } }}
      className="flex flex-col gap-1 mb-4 rounded-[10px]"
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
              uiLang={uiLang}
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
                  uiLang={uiLang}
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
          key={highlighted ? `flash-${highlightToken}` : "body"}
          className={`text-[13px] text-black/80 leading-relaxed whitespace-pre-wrap ${chatAnnotationMode ? "select-text cursor-text" : ""} ${highlighted ? "agora-msg-flash" : ""}`}
          style={{ ...monoFont, color: isError ? "#ef4444" : undefined }}
        >
          {chatAnnotationMode && (layerAnnotations?.length ?? 0) > 0
            ? renderChatAnnotatedText(finalContent, layerAnnotations!, "agent", nickname)
            : highlightUserMentions(finalContent, nickname)}
        </p>
        {/*
          The card's tag is always visible; its citation opens on hover.

          It used to be a native title= tooltip, which is not the same thing: the
          browser one is unstyled, delayed, truncated by some browsers, and never
          fires on touch. This is a real panel — styled, immediate, and its text
          is selectable because it sits inside the hovered group rather than
          being pointer-events-none, so a participant can copy the reference.
          focus-within carries the same panel to keyboard users, which the chip's
          tabIndex makes reachable.
        */}
        {message.knowledge && (
          <div className="relative group/src mt-2.5 pt-2 border-t border-black/[0.07] flex flex-wrap items-center gap-1.5">
            <span className="text-[9px] text-black/40" style={getUiFont(uiLang)}>
              {t(uiLang, "chat.knowledgeUsed")}
            </span>
            <span
              className="text-[9px] px-2 py-0.5 rounded-[4px] border border-black/10 bg-black/[0.03] text-black/65 cursor-help"
              style={getUiFont(uiLang)}
              tabIndex={message.knowledge.source ? 0 : undefined}
            >
              {message.knowledge.tag}
            </span>
            {message.knowledge.source && (
              <span
                role="tooltip"
                className="pointer-events-none group-hover/src:pointer-events-auto absolute bottom-full left-0 right-0 mb-1.5 z-20 rounded-[4px] border border-black/10 bg-white px-2.5 py-2 text-[10px] leading-relaxed text-black/70 shadow-[0_2px_10px_rgba(0,0,0,0.10)] opacity-0 invisible transition-opacity duration-100 group-hover/src:opacity-100 group-hover/src:visible group-focus-within/src:opacity-100 group-focus-within/src:visible group-focus-within/src:pointer-events-auto"
                style={getUiFont(uiLang)}
              >
                {message.knowledge.source}
              </span>
            )}
          </div>
        )}
        {(message.options?.length || 0) >= 2 && (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <span className={`w-full text-[9px] text-black/40 ${labelCaseClass(uiLang)}`} style={getUiFont(uiLang)}>
              {message.chosenOptionId ? t(uiLang, "chat.optionLocked") : t(uiLang, "chat.optionsPickHint")}
            </span>
            {message.options!.map((opt) => {
              const chosen = message.chosenOptionId === opt.id;
              const locked = !!message.chosenOptionId;
              return (
                <button
                  key={opt.id}
                  type="button"
                  disabled={locked || !onChooseOption}
                  onClick={() => onChooseOption?.(message, opt)}
                  className={`px-2.5 py-1 rounded-[6px] text-[11px] border transition-colors ${
                    chosen
                      ? "border-black bg-black text-white"
                      : locked
                        ? "border-black/10 text-black/35 bg-black/[0.02] cursor-default"
                        : "border-black/15 text-black/75 hover:border-black/40 hover:bg-black/[0.03]"
                  }`}
                  style={getUiFont(uiLang)}
                >
                  {chosen ? `✓ ${opt.label}` : opt.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </motion.div>
  );
});

const SystemMessage = React.memo(function SystemMessage({
  message,
  highlighted = false,
  highlightToken = 0,
}: {
  message: Message;
  highlighted?: boolean;
  highlightToken?: number;
}) {
  if (!(message.content || "").trim()) return null;
  return (
    <motion.div
      layout
      data-message-id={message.id}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="flex flex-col items-center gap-1 mb-5 rounded-[10px]"
    >
      <span className="text-[10px] tracking-widest text-[var(--app-muted-text)] uppercase" style={monoFont}>
        System
      </span>
      <div className="px-3 py-2 max-w-[90%] text-center border border-black/10 bg-black/[0.03] rounded-[8px]">
        <p
          key={highlighted ? `flash-${highlightToken}` : "body"}
          className={`text-[12px] text-black/70 leading-relaxed whitespace-pre-wrap ${highlighted ? "agora-msg-flash" : ""}`}
          style={monoFont}
        >
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
  highlighted = false,
  highlightToken = 0,
}: {
  message: Message;
  nickname: string;
  chatAnnotationMode?: boolean;
  layerAnnotations?: ChatLayerAnnotation[];
  onChatAnnotationDraft?: (d: { messageId: string; start: number; end: number; x: number; y: number }) => void;
  highlighted?: boolean;
  highlightToken?: number;
}) {
  const contentRef = useRef<HTMLParagraphElement>(null);
  return (
    <motion.div
      layout
      data-message-id={message.id}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, layout: { duration: 0.28, ease: [0.22, 1, 0.36, 1] } }}
      className="flex flex-col items-end gap-1 mb-6 rounded-[10px]"
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
          key={highlighted ? `flash-${highlightToken}` : "body"}
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
          className={`text-[13px] text-white leading-relaxed whitespace-pre-wrap ${chatAnnotationMode ? "select-text cursor-text" : ""} ${highlighted ? "agora-msg-flash" : ""}`}
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

const ConvItem = React.memo(function ConvItem({ conv, isActive, onSelectConv, lang = "en" }: { conv: Conversation; isActive: boolean; onSelectConv: (id: string) => void; lang?: UiLang }) {
  const mode = conv.settings?.mode ?? "full";
  const modeLabel = t(lang, mode === "full" ? "chat.multi" : mode === "limited" ? "chat.multi2" : "chat.single");
  const font = getUiFont(lang);
  return (
    <button
      onClick={() => onSelectConv(conv.id)}
      className={`w-full text-left px-3 py-3 rounded-[8px] transition-colors flex flex-col gap-1 ${
        isActive ? "bg-black text-white" : "hover:bg-black/5"
      }`}
    >
      <div className="flex items-center justify-between gap-2 min-w-0">
        <span className="text-[12px] truncate flex-1" style={{ ...font, color: isActive ? "#fff" : "#000" }}>
          {conv.title}
        </span>
        <span className="text-[9px] px-1.5 py-0.5 rounded flex-shrink-0" style={{ ...font, color: isActive ? "rgba(255,255,255,0.7)" : "rgba(0,0,0,0.4)", background: isActive ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.06)" }}>
          {modeLabel}
        </span>
      </div>
      <span className="text-[10px] truncate" style={{ ...font, color: isActive ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.4)" }}>
        {conv.timestamp}
      </span>
    </button>
  );
});

// ─── Attach menu (+ button, upload file etc.) ───────────────────────────────────

function AttachMenu({ open, onClose, anchorRef, lang = "en" }: { open: boolean; onClose: () => void; anchorRef: React.RefObject<HTMLButtonElement | null>; lang?: UiLang }) {
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
        <span className="text-[12px]" style={getUiFont(lang)}>{t(lang, "chat.addFiles")}</span>
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
  onGenerate,
  lang = "en",
}: {
  open: boolean;
  onClose: () => void;
  roomId: string;
  markdown: string | null;
  loading: boolean;
  error: string | null;
  onGenerate: () => void;
  lang?: UiLang;
}) {
  if (!open) return null;
  const font = getUiFont(lang);
  const hasMarkdown = !!(markdown || "").trim();
  return (
    <motion.div
      className="fixed inset-0 z-[220] flex items-center justify-center p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <button type="button" className="absolute inset-0 bg-black/30" aria-label={t(lang, "summary.close")} onClick={onClose} />
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.98 }}
        transition={{ duration: 0.2 }}
        className="relative z-10 w-full max-w-[560px] max-h-[min(80vh,720px)] flex flex-col bg-white border border-black/10 rounded-[16px] shadow-[0_8px_40px_rgba(0,0,0,0.12)] overflow-hidden"
      >
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-black/8">
          <div className="min-w-0">
            <p className="text-[13px] text-black" style={font}>{t(lang, "summary.title")}</p>
            <p className="text-[10px] text-[var(--app-muted-text)] mt-0.5 truncate" style={font}>
              {t(lang, "summary.session", { id: roomId })}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {hasMarkdown && (
              <button
                type="button"
                onClick={onGenerate}
                disabled={loading}
                className="px-2.5 py-1.5 rounded-[8px] border border-black/10 text-[11px] text-black/70 hover:bg-black/5 disabled:opacity-40"
                style={font}
              >
                {loading ? t(lang, "summary.generating") : t(lang, "summary.regenerate")}
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-[8px] hover:bg-black/5 text-black/50"
              aria-label={t(lang, "summary.close")}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading && (
            <p className="text-[12px] text-[var(--app-muted-text)]" style={font}>
              {t(lang, "summary.reading")}
            </p>
          )}
          {!loading && error && (
            <div className="space-y-3">
              <p className="text-[12px] text-red-600 border border-red-200 bg-red-50 px-3 py-2 rounded-[8px]" style={font}>
                {error}
              </p>
              <button
                type="button"
                onClick={onGenerate}
                className="h-[36px] px-4 bg-black text-white rounded-[8px] text-[12px] hover:bg-neutral-800"
                style={font}
              >
                {t(lang, "summary.tryAgain")}
              </button>
            </div>
          )}
          {!loading && !error && !hasMarkdown && (
            <div className="flex flex-col items-start gap-3 py-2">
              <p className="text-[12px] text-[var(--app-muted-text)] leading-relaxed" style={font}>
                {t(lang, "summary.idle")}
              </p>
              <button
                type="button"
                onClick={onGenerate}
                className="h-[36px] px-4 bg-black text-white rounded-[8px] text-[12px] hover:bg-neutral-800"
                style={font}
              >
                {t(lang, "summary.generate")}
              </button>
            </div>
          )}
          {!loading && hasMarkdown && (
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

function GlobeIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20" />
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </svg>
  );
}

function SettingsMenu({ open, onClose, anchorRef, onCustomize, onScene, onAppearance, onReloadHistory, onSummary, onExportLog, onPastMemory, hasRoomId, showSummary = true, showPastMemory, showFontColor, onToggleFontColor, lang, onLangChange }: {
  open: boolean; onClose: () => void; anchorRef: React.RefObject<HTMLButtonElement | null>;
  onCustomize: () => void; onScene: () => void; onAppearance: () => void;
  onReloadHistory: () => void; onSummary: () => void; onExportLog: () => void;
  onPastMemory?: () => void; hasRoomId: boolean; showSummary?: boolean; showPastMemory?: boolean;
  showFontColor: boolean; onToggleFontColor: () => void;
  lang: UiLang;
  onLangChange: (lang: UiLang) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const font = getUiFont(lang);
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
      <span className="text-[12px]" style={font}>{label}</span>
    </button>
  );
  return (
    <motion.div ref={ref} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }}
      className="absolute bottom-full right-0 mb-2 bg-white border border-black/10 rounded-[12px] shadow-[0_2px_12px_rgba(0,0,0,0.06)] py-2 min-w-[220px] z-50">
      {/* Language is frozen once a session exists: the transcript was generated in
          it, and the summary / decision map are extracted in it. Letting it change
          mid-session produced a Chinese chat with an English map. */}
      <div className="flex items-center gap-3 px-3 py-2.5">
        <span className="opacity-40 flex-shrink-0"><GlobeIcon /></span>
        <span className={`text-[12px] flex-1 ${hasRoomId ? "text-black/35" : ""}`} style={font}>
          {t(lang, "settings.language")}
        </span>
        <div className="flex items-center gap-1.5 text-[11px] tracking-wide" style={getUiFont("en")}>
          <button
            type="button"
            disabled={hasRoomId}
            onClick={() => onLangChange("en")}
            className={`px-0.5 transition-colors ${
              lang === "en" ? "text-black font-semibold" : "text-black/35"
            } ${hasRoomId ? "cursor-not-allowed opacity-45" : "hover:text-black/60"}`}
          >
            EN
          </button>
          <span className="text-black/20">/</span>
          <button
            type="button"
            disabled={hasRoomId}
            onClick={() => onLangChange("zh")}
            className={`px-0.5 transition-colors ${
              lang === "zh" ? "text-black font-semibold" : "text-black/35"
            } ${hasRoomId ? "cursor-not-allowed opacity-45" : "hover:text-black/60"}`}
          >
            CN
          </button>
        </div>
      </div>
      {hasRoomId && (
        <p className="px-3 pb-2 -mt-1 text-[10px] leading-snug text-black/40" style={font}>
          {t(lang, "settings.languageLocked")}
        </p>
      )}
      <div className="my-1 border-t border-black/8" />
      <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>} label={t(lang, "settings.customizeAgent")} onClick={onCustomize} />
      <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>} label={t(lang, "settings.customizeScene")} onClick={onScene} />
      {showFontColor && <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3a9 9 0 1 0 9 9"/><circle cx="12" cy="12" r="3"/></svg>} label={t(lang, "settings.fontColor")} onClick={onAppearance} />}
      {hasRoomId && (
        <>
          <Item icon={<svg width="14" height="14" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"><polyline points="17.18 15 8.18 15 8.18 6"/><path d="M10.58,12A18,18,0,1,1,6.23,26.88"/></svg>} label={t(lang, "settings.reloadHistory")} onClick={onReloadHistory} />
          {showSummary && (
            <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="11" x2="14" y2="11"/></svg>} label={t(lang, "settings.decisionSummary")} onClick={onSummary} />
          )}
          <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>} label={t(lang, "settings.exportLog")} onClick={onExportLog} />
        </>
      )}
      {showPastMemory && onPastMemory && (
        <Item
          icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>}
          label={t(lang, "settings.pastMemory")}
          onClick={onPastMemory}
        />
      )}
    </motion.div>
  );
}

// ─── User Menu (Account, Help, Logout) ─────────────────────────────────────────

function UserMenu({ nickname, isAdmin, onAccount, onHelp, onAdmin, onLogout, onClose, lang = "en" }: {
  nickname: string; isAdmin?: boolean; onAccount: () => void; onHelp: () => void; onAdmin?: () => void; onLogout: () => void; onClose: () => void; lang?: UiLang;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const font = getUiFont(lang);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [onClose]);

  const Item = ({ icon, label, onClick, danger = false }: { icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean }) => (
    <button onClick={onClick} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-[8px] transition-colors text-left ${danger ? "hover:bg-red-50 text-red-500" : "hover:bg-black/5 text-black"}`}>
      <span className="opacity-40 flex-shrink-0">{icon}</span>
      <span className="text-[12px]" style={font}>{label}</span>
    </button>
  );

  return (
    <motion.div ref={ref} initial={{ opacity: 0, y: 6, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 6, scale: 0.97 }} transition={{ duration: 0.15 }}
      className="absolute bottom-[56px] left-3 right-3 bg-white border border-black/10 rounded-[12px] shadow-[0_2px_12px_rgba(0,0,0,0.06)] z-50 py-2 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 mb-1">
        <div className="w-[7px] h-[7px] rounded-[1.5px] bg-red-500 flex-shrink-0" />
        <span className="text-[12px] tracking-widest text-black" style={font}>{(nickname || t(lang, "chat.you")).toUpperCase()}</span>
      </div>
      <div className="px-1">
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>} label={t(lang, "settings.account")} onClick={() => { onClose(); onAccount(); }} />
        {isAdmin && onAdmin && (
          <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>} label={t(lang, "settings.admin")} onClick={() => { onClose(); onAdmin(); }} />
        )}
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>} label={t(lang, "settings.help")} onClick={() => { onClose(); onHelp(); }} />
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>} label={t(lang, "settings.logout")} onClick={() => { onClose(); onLogout(); }} danger />
      </div>
    </motion.div>
  );
}

// ─── Customizer Modal (paginated cards) ────────────────────────────────────────

function CustomizerModal({
  agentNames,
  agentSettings,
  experimentMode,
  agentKeys = AGENT_KEYS,
  scenarioId = null,
  uiLang = "en",
  onSave,
  onClose,
  onAnalyze: _onAnalyze,
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
  agentKeys?: AgentKey[];
  scenarioId?: string | null;
  uiLang?: UiLang;
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
  const font = getUiFont(uiLang);
  const cardLabels = [t(uiLang, "custom.cardBasic"), t(uiLang, "custom.cardTone"), t(uiLang, "custom.cardBehavior")] as const;
  const tutorialSteps = getTutorialSteps(uiLang);
  const [localNames, setLocalNames] = useState<Record<AgentKey, string>>({ ...agentNames });
  const [localSettings, setLocalSettings] = useState<Record<AgentKey, AgentCustomSetting>>(() => cloneAgentSettings(agentSettings));
  const [selectedAgent, setSelectedAgent] = useState<AgentKey>(initialOpenCard || agentKeys[0] || "A");
  const [page, setPage] = useState(0);
  const [isSaving, setIsSaving] = useState(false);
  // Per-card scroll positions so switching pages does not share one scrollbar offset
  const cardScrollRef = useRef<HTMLDivElement>(null);
  const cardScrollPosRef = useRef<Record<string, number>>({});
  const pageRef = useRef(page);
  pageRef.current = page;

  // Mid-session add opens this modal in the same paint as new keys — resync local
  // copies when the roster key set changes so Save cannot drop a just-added agent.
  // Do NOT depend on agentNames/agentSettings broadly or in-progress edits get wiped.
  useEffect(() => {
    setLocalNames({ ...agentNames });
    setLocalSettings(cloneAgentSettings(agentSettings));
    if (initialOpenCard && agentKeys.includes(initialOpenCard)) {
      setSelectedAgent(initialOpenCard);
    } else {
      setSelectedAgent((prev) => (agentKeys.includes(prev) ? prev : (agentKeys[0] || "A")));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when roster membership changes
  }, [agentKeys.join(",")]);

  const canEditAdvanced = experimentMode === "full";
  const agentOptions = experimentMode === "single" ? (["A"] as AgentKey[]) : agentKeys;
  // Stance UI is always available in full mode. If no agora2 scene is selected yet,
  // fall back to employment options so Basic card is not empty (preview/start bind to real scene later).
  const stanceScenarioId =
    scenarioId && SCENARIO_STANCES[scenarioId] ? scenarioId : (canEditAdvanced ? "employment" : null);
  const stanceOptions = stanceScenarioId ? SCENARIO_STANCES[stanceScenarioId] : [];
  const showStanceFields = canEditAdvanced && stanceOptions.length > 0;
  const stanceSceneBound = !!(scenarioId && SCENARIO_STANCES[scenarioId]);
  const totalCards = canEditAdvanced ? 3 : 1;
  const tutorialCardIndex = tutorialStep !== null && tutorialStep >= 2 && tutorialStep <= 4 ? tutorialStep - 2 : null;
  const tutorialGuideStep = tutorialStep !== null ? tutorialSteps[tutorialStep] : null;

  const scrollKey = (agent: AgentKey, card: number) => `${agent}:${card}`;
  const goToPage = useCallback((next: number) => {
    const el = cardScrollRef.current;
    if (el) cardScrollPosRef.current[scrollKey(selectedAgent, pageRef.current)] = el.scrollTop;
    setPage(next);
  }, [selectedAgent]);

  useEffect(() => { if (initialOpenCard) setSelectedAgent(initialOpenCard); }, [initialOpenCard]);
  useEffect(() => { setPage(0); }, [selectedAgent]);
  useEffect(() => {
    if (tutorialCardIndex !== null) goToPage(tutorialCardIndex);
  }, [tutorialCardIndex, goToPage]);
  useEffect(() => {
    const el = cardScrollRef.current;
    if (!el) return;
    el.scrollTop = cardScrollPosRef.current[scrollKey(selectedAgent, page)] ?? 0;
  }, [page, selectedAgent]);

  // Seed default stance when opening an agent without one
  useEffect(() => {
    if (!showStanceFields || !stanceScenarioId) return;
    setLocalSettings((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const k of agentOptions) {
        if (!next[k]?.stance) {
          const st = defaultStanceForKey(stanceScenarioId, k, agentOptions);
          if (st) {
            next[k] = { ...next[k], stance: st };
            changed = true;
          }
        }
      }
      return changed ? next : prev;
    });
  }, [showStanceFields, stanceScenarioId, agentOptions.join(",")]);

  const upd = (key: AgentKey, field: keyof AgentCustomSetting, value: unknown) =>
    setLocalSettings((prev) => ({ ...prev, [key]: { ...prev[key], [field]: value } }));

  const applyTone = (key: AgentKey, tone: string) => {
    const d = defaultsForTone(tone);
    setLocalSettings((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        emotionOn: true,
        emotionTag: tone,
        valence: d.valence,
        arousal: d.arousal,
        control: d.control,
        emotionText: "",
      },
    }));
  };

  const handleSave = async () => {
    if (isSaving) return;
    setIsSaving(true);
    try {
      const settingsToSave: Record<AgentKey, AgentCustomSetting> = cloneAgentSettings(localSettings);
      for (const key of agentOptions) {
        const tag = settingsToSave[key]?.emotionTag || "joy";
        const d = defaultsForTone(tag);
        settingsToSave[key] = {
          ...settingsToSave[key],
          emotionOn: true,
          emotionTag: tag,
          valence: d.valence,
          arousal: d.arousal,
          control: d.control,
        };
      }
      onSave(localNames, settingsToSave);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  const goPrev = () => goToPage(Math.max(0, pageRef.current - 1));
  const goNext = () => goToPage(Math.min(totalCards - 1, pageRef.current + 1));

  const renderCard = (key: AgentKey, cardIndex: number) => {
    const s = localSettings[key];
    const accentColor = s.accentColor || DEFAULT_AGENT_COLORS[key];
    const emotionTag = s.emotionTag || "joy";
    const examples = getEmotionExamples(emotionTag, uiLang);
    const decisionExamples = getDecisionExamples(s.decisionBlock, uiLang);
    const lbl = labelCaseClass(uiLang);

    if (cardIndex === 0) {
      return (
        <div key="basic" className="flex flex-col gap-4 w-full break-words" style={uiLang === "zh" ? { lineHeight: 1.55 } : undefined}>
          <div>
            <label className={`text-[10px] text-[var(--app-muted-text)] ${lbl} mb-1.5 block`} style={font}>{t(uiLang, "custom.displayName")}</label>
            <input type="text" value={localNames[key]} maxLength={24} onChange={(e) => setLocalNames((p) => ({ ...p, [key]: e.target.value }))}
              className="w-full text-[12px] px-3 py-1.5 border border-black/15 rounded-[6px] outline-none focus:border-black/40 transition-colors" style={font} />
          </div>
          <div>
            <label className={`text-[10px] text-[var(--app-muted-text)] ${lbl} mb-1.5 block`} style={font}>{t(uiLang, "custom.accentColor")}</label>
            <div className="flex items-center gap-2">
              <input type="color" value={accentColor} onChange={(e) => upd(key, "accentColor", e.target.value)}
                className="w-10 h-8 rounded-[6px] border border-black/15 cursor-pointer p-0" />
              <input type="text" value={accentColor} onChange={(e) => upd(key, "accentColor", e.target.value)}
                className="flex-1 text-[11px] px-3 py-1.5 border border-black/15 rounded-[6px] outline-none focus:border-black/40 font-mono" maxLength={7} />
            </div>
          </div>
          {showStanceFields && (
            <>
              {!stanceSceneBound && (
                <p className="text-[10px] text-[var(--app-muted-text)] leading-relaxed" style={font}>
                  {t(uiLang, "custom.stanceHintUnbound")}
                </p>
              )}
              <div>
                <label className={`text-[10px] text-[var(--app-muted-text)] ${lbl} mb-1.5 block`} style={font}>{t(uiLang, "custom.basicStance")}</label>
                {stanceSceneBound ? (
                  // A scene that binds stances partitions the interests at issue,
                  // and the panel only works if each one keeps a voice. Offering a
                  // picker here let a user set every agent to the same stance --
                  // and the backend now drops the override anyway, so the control
                  // was promising something it could not deliver.
                  <div
                    className="text-[11px] px-3 py-1.5 border border-black/10 rounded-[6px] bg-black/[0.03] text-[var(--app-muted-text)] cursor-default select-none"
                    style={font}
                    aria-readonly="true"
                  >
                    {t(uiLang, `stance.${s.stance || stanceOptions[0]?.value || ""}`)}
                  </div>
                ) : (
                  <CustomDropdown
                    value={s.stance || stanceOptions[0]?.value || ""}
                    onChange={(v) => upd(key, "stance", v)}
                    options={stanceOptions.map((o) => ({ value: o.value, label: t(uiLang, `stance.${o.value}`) }))}
                    size="sm"
                    style={font}
                  />
                )}
              </div>
              <div>
                <label className={`text-[10px] text-[var(--app-muted-text)] ${lbl} mb-1.5 block`} style={font}>{t(uiLang, "custom.knowledgeHint")}</label>
                <p className="text-[10px] text-[var(--app-muted-text)] mb-2 leading-relaxed" style={font}>{t(uiLang, "custom.knowledgeHelp")}</p>
                <textarea
                  value={s.hint}
                  maxLength={240}
                  rows={3}
                  onChange={(e) => upd(key, "hint", e.target.value)}
                  placeholder={t(uiLang, "custom.knowledgePh")}
                  className="w-full resize-none text-[11px] px-3 py-2 border border-black/15 rounded-[6px] outline-none focus:border-black/40 transition-colors"
                  style={font}
                />
              </div>
            </>
          )}
        </div>
      );
    }

    if (cardIndex === 1 && canEditAdvanced) {
      return (
        <div key="tone" className="flex flex-col gap-4 w-full break-words" style={uiLang === "zh" ? { lineHeight: 1.55 } : undefined}>
          <div>
            <label className={`text-[10px] text-[var(--app-muted-text)] ${lbl} mb-1.5 block`} style={font}>{t(uiLang, "custom.tone")}</label>
            <p className="text-[10px] text-[var(--app-muted-text)] mb-2" style={font}>{t(uiLang, "custom.toneHelp")}</p>
            <div
              className="flex items-center gap-2 px-2 py-1.5 border rounded-[6px] text-[11px] mb-2"
              style={{ borderColor: (EMOTION_COLORS[emotionTag] || "#000") + "40", background: (EMOTION_COLORS[emotionTag] || "#000") + "10", color: EMOTION_COLORS[emotionTag] || "#000", ...font }}
            >
              <EmotionIcon emotion={emotionTag} size={16} />
              <span>{toneLabel(uiLang, emotionTag)}</span>
            </div>
            <CustomDropdown
              value={emotionTag}
              onChange={(v) => applyTone(key, v)}
              options={toneOptions(uiLang)}
              size="sm"
              style={font}
            />
          </div>
          {examples.length > 0 && (
            <div>
              <p className={`text-[10px] text-[var(--app-muted-text)] ${lbl} mb-1.5`} style={font}>{t(uiLang, "custom.examples")}</p>
              <ul className="text-[10px] text-[var(--app-muted-text)] space-y-1 pl-3 border-l-2 border-black/10" style={{ ...font, borderColor: (EMOTION_COLORS[emotionTag] || "#000") + "30" }}>
                {examples.slice(0, 3).map((ex, i) => (
                  <li key={i} className="pl-2">&ldquo;{ex}&rdquo;</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      );
    }

    if (cardIndex === 2 && canEditAdvanced) {
      return (
        <div key="behavior" className="flex flex-col gap-4 w-full break-words" style={uiLang === "zh" ? { lineHeight: 1.55 } : undefined}>
          <div>
            <label className={`text-[10px] text-[var(--app-muted-text)] ${lbl} mb-1.5 block`} style={font}>{t(uiLang, "custom.decisionStyle")}</label>
            <p className="text-[10px] text-[var(--app-muted-text)] mb-2" style={font}>{t(uiLang, "custom.decisionHelp")}</p>
            <CustomDropdown
              value={s.decisionBlock}
              onChange={(v) => upd(key, "decisionBlock", v as AgentCustomSetting["decisionBlock"])}
              options={DECISION_BLOCKS.map((b) => ({ value: b, label: t(uiLang, `decision.${b}`) }))}
              size="sm"
              style={font}
            />
            <p className="text-[9px] text-[var(--app-muted-text)] mt-1" style={font}>{t(uiLang, `decision.desc.${s.decisionBlock}`)}</p>
            {decisionExamples.length > 0 && (
              <div className="mt-2">
                <p className={`text-[10px] text-[var(--app-muted-text)] ${lbl} mb-1.5`} style={font}>{t(uiLang, "custom.examples")}</p>
                <ul className="text-[10px] text-[var(--app-muted-text)] space-y-1 pl-3 border-l-2 border-black/10" style={font}>
                  {decisionExamples.slice(0, 3).map((ex, i) => (
                    <li key={i} className="pl-2">&ldquo;{ex}&rdquo;</li>
                  ))}
                </ul>
              </div>
            )}
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
                  <p className={`text-[11px] text-black ${labelCaseClass(uiLang)}`} style={font}>
                    {tutorialStep! + 1}/{tutorialSteps.length} · {tutorialGuideStep?.title}
                  </p>
                  <button
                    type="button"
                    onClick={onTutorialSkip}
                    className="text-[10px] text-[var(--app-muted-text)] hover:text-black transition-colors"
                    style={font}
                  >
                    {t(uiLang, "tutorial.skip")}
                  </button>
                </div>
                <p className="text-[12px] text-black/75 leading-relaxed" style={font}>
                  {tutorialGuideStep?.body}
                </p>
                <div className="flex items-center justify-between mt-4">
                  <button
                    type="button"
                    onClick={onTutorialBack}
                    className="px-3 py-2 rounded-[10px] border border-black/10 text-[11px] text-[var(--app-muted-text)] hover:text-black hover:border-black/20 transition-colors"
                    style={font}
                  >
                    {t(uiLang, "tutorial.back")}
                  </button>
                  <button
                    type="button"
                    onClick={onTutorialNext}
                    className="px-3 py-2 rounded-[10px] bg-black text-white text-[11px] hover:bg-neutral-800 transition-colors"
                    style={font}
                  >
                    {tutorialStep === 3 ? t(uiLang, "tutorial.continue") : t(uiLang, "tutorial.next")}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
        <div className="flex items-center justify-between px-5 py-4 border-b border-black/8 flex-shrink-0">
          <div>
            <h2 className="text-[15px]" style={{ ...font, fontWeight: 600 }}>{t(uiLang, "custom.title")}</h2>
            <p className="text-[10px] text-[var(--app-muted-text)] mt-0.5" style={font}>
              {canEditAdvanced
                ? `${cardLabels[page]} ${t(uiLang, "custom.cardsSuffix", { n: totalCards })}`
                : t(uiLang, "custom.subtitleSimple")}
            </p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px] transition-colors">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div className="px-5 py-4 flex-1 min-h-0 flex flex-col overflow-hidden">
          <div className="mb-3 flex-shrink-0">
            <label className={`text-[10px] text-[var(--app-muted-text)] ${labelCaseClass(uiLang)} mb-1.5 block`} style={font}>{t(uiLang, "custom.selectAgent")}</label>
            <CustomDropdown
              value={selectedAgent}
              onChange={(v) => setSelectedAgent(v as AgentKey)}
              options={agentOptions.map((key) => ({ value: key, label: localNames[key] }))}
              style={font}
            />
          </div>
          <div className="border border-black/10 rounded-[12px] overflow-hidden bg-black/[0.02] flex-1 min-h-0 flex flex-col">
            <div ref={cardScrollRef} className="overflow-x-hidden overflow-y-auto flex-1 min-h-0 w-full" style={{ minWidth: 0 }}>
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
                    <button key={i} onClick={() => tutorialCardIndex === null && goToPage(i)}
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
          <motion.button onClick={onClose} whileTap={{ scale: 0.97 }} disabled={isSaving} className="px-4 py-2 text-[12px] border border-black/15 rounded-[8px] hover:bg-black/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" style={font}>{t(uiLang, "custom.cancel")}</motion.button>
          <motion.button onClick={handleSave} whileTap={{ scale: 0.97 }} disabled={isSaving} className="px-4 py-2 text-[12px] bg-black text-white rounded-[8px] hover:bg-neutral-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" style={font}>{isSaving ? t(uiLang, "custom.saving") : t(uiLang, "custom.save")}</motion.button>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ─── Scene Selector ───────────────────────────────────────────────────────────

function SceneSelectorModal({ scenes, selectedScene, onSelect, onClose, lang }: {
  scenes: Scene[];
  selectedScene: Scene | null;
  onSelect: (s: Scene) => void;
  onClose: () => void;
  lang: UiLang;
}) {
  const SCENE_PAGE_SIZE = 3;
  const font = getUiFont(lang);
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
            <h2 className="text-[16px]" style={{ ...font, fontWeight: 600 }}>
              {t(lang, "welcome.chooseScenario")}
            </h2>
            <p className="text-[11px] text-[var(--app-muted-text)] mt-0.5" style={font}>
              {t(lang, "welcome.scenarioSubtitle")}
            </p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px] transition-colors">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
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
                      {pageScenes.map((s) => {
                        // available === false: this deployment does not run the
                        // scene. Kept on the board, greyed and inert, so the
                        // roster stays the one participants were briefed on.
                        const unavailable = s.available === false;
                        return (
                        <button key={s.id} onClick={() => { if (!unavailable) onSelect(s); }}
                          disabled={unavailable}
                          aria-disabled={unavailable}
                          title={unavailable ? t(lang, "welcome.sceneUnavailable") : undefined}
                          className={`text-left p-4 border-2 rounded-[12px] transition-all ${
                            unavailable
                              ? "border-black/8 bg-black/[0.03] opacity-45 cursor-not-allowed"
                              : `hover:shadow-[0_2px_12px_rgba(0,0,0,0.06)] ${selectedScene?.id === s.id ? "border-black" : "border-black/10 hover:border-black/30"}`
                          }`}>
                          <div className="text-2xl mb-2 grayscale-0">{s.icon}</div>
                          <div className="text-[13px] mb-1" style={{ ...font, fontWeight: 500 }}>{s.title}</div>
                          <div className="text-[10px] text-[var(--app-muted-text)] leading-relaxed" style={font}>{s.description}</div>
                          {unavailable ? (
                            <div className={`text-[9px] text-[var(--app-muted-text)] mt-2 ${labelCaseClass(lang)}`} style={font}>{t(lang, "welcome.sceneUnavailable")}</div>
                          ) : isAgora2SceneId(s.id) && (
                            <div className={`text-[9px] text-[var(--app-muted-text)] mt-2 ${labelCaseClass(lang)}`} style={font}>{t(lang, "welcome.intakeRequired")}</div>
                          )}
                        </button>
                        );
                      })}
                      <motion.button
                        whileHover={{ y: -2 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => {}}
                        className="border-2 border-dashed border-black/15 rounded-[12px] p-4 flex flex-col items-center justify-center gap-1 hover:border-black/40 hover:bg-black/2 transition-colors group min-h-[120px]"
                      >
                        <svg width="20" height="20" viewBox="0 0 16 16" fill="none" className="opacity-20 group-hover:opacity-50 transition-opacity">
                          <path d="M8 1V15M1 8H15" stroke="black" strokeWidth="1.5" strokeLinecap="round"/>
                        </svg>
                        <span className="text-[10px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={font}>{t(lang, "welcome.customize")}</span>
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
            <button onClick={() => { onSelect(null as unknown as Scene); }} className="text-[11px] text-[var(--app-muted-text)] hover:text-black transition-colors" style={font}>{t(lang, "welcome.clearSelection")}</button>
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
  // "pending" = a turn is in flight but the speaker is unknown (the scheduler
  // picks server-side); real keys appear once responses arrive and drain.
  const [typingKeys, setTypingKeys] = useState<(AgentKey | "pending")[]>([]);
  const [msgQueue, setMsgQueue] = useState<Array<{
    agentKey: AgentKey | "system";
    content: string;
    convId: string;
    emotionTagSnapshot: string | null;
    isSystem?: boolean;
    messageId?: string;
    options?: ChatOptionChip[];
    knowledge?: KnowledgeReference;
  }>>([]);
  const agentNamesRef = useRef<Record<AgentKey, string>>(DEFAULT_AGENT_NAMES);
  const agentSettingsRef = useRef<Record<AgentKey, AgentCustomSetting>>(blankAgentSettings());
  const activeAgentKeysRef = useRef<AgentKey[]>([...DEFAULT_ACTIVE_AGENT_KEYS]);
  const quickAdjustPendingRef = useRef<Partial<Record<AgentKey, Promise<void> | null>>>({});

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [showCustomizer, setShowCustomizer] = useState(false);
  const [customizerInitialAgent, setCustomizerInitialAgent] = useState<AgentKey | null>(null);
  const [showSceneSelector, setShowSceneSelector] = useState(false);
  const [showAppearanceModal, setShowAppearanceModal] = useState(false);
  const [showFontColorInSettings, setShowFontColorInSettings] = useState(false);
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);
  const [agentsOpen, setAgentsOpen] = useState(false);
  const agentsBtnRef = useRef<HTMLButtonElement>(null);
  const agentsPanelRef = useRef<HTMLDivElement>(null);
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
  /** Phase boundaries for Decision Navi, keyed by room_id. */
  const [phaseMarkersByRoom, setPhaseMarkersByRoom] = useState<Record<string, PhaseChangeMarker[]>>({});
  const lastPhaseByRoomRef = useRef<Record<string, string | null>>({});
  const [naviActiveMessageId, setNaviActiveMessageId] = useState<string | null>(null);
  const [highlightedMessageId, setHighlightedMessageId] = useState<string | null>(null);
  const [highlightedMessageIds, setHighlightedMessageIds] = useState<string[]>([]);
  const [highlightToken, setHighlightToken] = useState(0);
  const highlightTimerRef = useRef<number | null>(null);
  /** Ignore scroll-spy while smooth-scrolling from a Decision Navi click. */
  const naviJumpLockRef = useRef(false);
  const naviJumpUnlockTimerRef = useRef<number | null>(null);

  const [decisionMapOpen, setDecisionMapOpen] = useState(false);
  // Docked: map collapsed to a floating pill while the user reads evidence in
  // chat; the panel stays mounted so selection/zoom survive the round trip.
  const [decisionMapDocked, setDecisionMapDocked] = useState(false);
  // Telemetry timing state. Refs, not state: none of this should trigger a render, and
  // Chat.tsx re-renders often enough that state would both cost paints and lose precision.
  const mapDwellRef = useRef(new DwellTracker());
  const decisionMapTopicCountRef = useRef(0);
  const lastBotMessageAtRef = useRef<number | null>(null);
  // True from the moment a /message request goes out until it resolves. The
  // queue processor reads it so an in-flight turn keeps its pending indicator
  // even while the previous turn's queue finishes draining.
  const requestInFlightRef = useRef(false);
  const firstKeystrokeAtRef = useRef<number | null>(null);
  const keystrokesRef = useRef(0);
  const backspacesRef = useRef(0);
  const lastInputLenRef = useRef(0);
  // message id -> when its option chips first appeared, for chip dwell.
  const optionShownAtRef = useRef<Map<string, number>>(new Map());
  const [decisionMap, setDecisionMap] = useState<DecisionMapData | null>(null);
  const [decisionMapLoading, setDecisionMapLoading] = useState(false);
  const [decisionMapError, setDecisionMapError] = useState<string | null>(null);
  const [decisionMapExtracting, setDecisionMapExtracting] = useState(false);
  const [selectedMapTopicId, setSelectedMapTopicId] = useState<string | null>(null);

  const [agentNames, setAgentNames] = useState<Record<AgentKey, string>>({ ...DEFAULT_AGENT_NAMES });
  const [agentBackendNames, setAgentBackendNames] = useState<Record<AgentKey, string>>({ ...DEFAULT_AGENT_NAMES });
  const [agentSettings, setAgentSettings] = useState<Record<AgentKey, AgentCustomSetting>>(() => blankAgentSettings());
  const [activeAgentKeys, setActiveAgentKeys] = useState<AgentKey[]>([...DEFAULT_ACTIVE_AGENT_KEYS]);
  const [limitedSelectedAgents, setLimitedSelectedAgents] = useState<AgentPoolKey[]>([...LIMITED_DEFAULT_SELECTED]);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null);
  const [pendingIntakeScene, setPendingIntakeScene] = useState<Scene | null>(null);
  const [pendingProfileScene, setPendingProfileScene] = useState<Scene | null>(null);
  /** Profile → intake handoff: keep one backdrop, skip profile exit flash */
  const [profileHandoff, setProfileHandoff] = useState(false);
  const [agora2Intake, setAgora2Intake] = useState<Agora2IntakePayload | null>(null);
  const [userProfile, setUserProfile] = useState<Record<string, unknown> | null>(null);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [uiLang, setUiLang] = useState<UiLang>(() => loadUiLang());
  const setLang = useCallback((lang: UiLang) => {
    saveUiLang(lang);
    setUiLang(lang);
  }, []);
  useEffect(() => {
    applyDocumentLang(uiLang);
  }, [uiLang]);
  const [sessionCountBefore, setSessionCountBefore] = useState(0);
  const [sessionIndex, setSessionIndex] = useState<number | null>(null);
  const [lastIntake, setLastIntake] = useState<Record<string, unknown> | null>(null);
  const [showMemoryHistory, setShowMemoryHistory] = useState(false);
  const [experimentMode, setExperimentMode] = useState<ExperimentMode>("full");
  // Which conditions this participant may run. Server-assigned by participant id
  // (AGORA_MODE_POLICY, see backend/study_policy.py); everything until the fetch
  // lands, and on any older backend, so nothing is locked by a failed request.
  const [allowedModes, setAllowedModes] = useState<ExperimentMode[]>(["full", "limited", "single"]);
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
  // What the intake form actually renders. lastIntake covers the paths that run
  // through beginAgora2Scene(); the send-time guard (err.intake) opens the form
  // directly and leaves it null, which is how a participant who already filled
  // the form is handed a blank one and retypes answers the browser still holds.
  // Memoised because IntakeModal keys its prefill effect on this prop's identity
  // -- a fresh loadIntakeDraft() object per render would reset the form as they type.
  const intakePrefill = useMemo(() => {
    if (lastIntake) return lastIntake;
    if (!pendingIntakeScene) return null;
    const draft = loadIntakeDraft(webUserId);
    return draft && draft.scenario_type === pendingIntakeScene.id ? draft.intake : null;
  }, [lastIntake, pendingIntakeScene, webUserId]);
  const suggestedPrompts = useMemo(() => {
    const id = selectedScene?.id;
    const local = getSuggestedPrompts(id, uiLang);
    if (uiLang === "zh") return local;
    if (selectedScene?.suggestedPrompts?.length) return selectedScene.suggestedPrompts;
    if (id) {
      const fromScenes = scenes.find((s) => s.id === id)?.suggestedPrompts;
      if (fromScenes?.length) return fromScenes;
    }
    return local;
  }, [selectedScene, scenes, uiLang]);
  const welcomeTutorialSteps = useMemo(() => getTutorialSteps(uiLang), [uiLang]);
  const uiFont = getUiFont(uiLang);
  const modeLabelFor = (m: ExperimentMode) =>
    t(uiLang, m === "full" ? "chat.multi" : m === "limited" ? "chat.multi2" : "chat.single");

  useEffect(() => {
    if (!auth?.token) {
      navigate("/", { replace: true });
    }
  }, [auth?.token, navigate]);

  const openSceneSelector = useCallback(() => {
    setShowSceneSelector(true);
  }, []);

  const beginAgora2Scene = useCallback(async (s: Scene) => {
    // Re-opening the SAME scenario with both forms already filled must not throw them
    // away. The welcome card reads "intake ready" and clicking it ran the wipe below:
    // intake, profile and the prefill all to null, then the participant walked the
    // profile form and the intake form again to get back exactly where they were.
    // Several of them reported having to fill the intake repeatedly, and the database
    // shows it -- P45 opened three rooms in five and a half minutes carrying a
    // byte-identical intake payload. Go straight to the intake form with their own
    // answers in it, so the click edits what they have instead of restarting from
    // nothing. Closing that form leaves everything untouched.
    if (s.id === selectedScene?.id && agora2Intake && userProfile) {
      setSelectedScene(s);
      setLastIntake(agora2Intake.intake);
      setShowSceneSelector(false);
      setProfileHandoff(false);
      setPendingIntakeScene(s);
      return;
    }
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
    // Reopening the form after filling it this sitting should bring back their own
    // answers, not last session's -- the draft is newer than most_recent_intake.
    const draft = loadIntakeDraft(webUserId);
    if (draft && draft.scenario_type === s.id) setLastIntake(draft.intake);
    setShowSceneSelector(false);
    setProfileHandoff(false);
    setPendingProfileScene(s);
    setShowProfileModal(true);
  }, [webUserId, selectedScene?.id, agora2Intake, userProfile]);

  const scrollMessagesToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const c = messagesContainerRef.current;
    if (!c) return;
    c.scrollTo({ top: c.scrollHeight, behavior });
  }, []);
  const getPopoverSafeRect = useCallback(() => messagesContainerRef.current?.getBoundingClientRect() ?? null, []);
  // No mode gate: customization in limited/single mode used to be discarded on both ends,
  // which is why not a single _params.jsonl exists on disk. mode is sent as a field now.
  // authFetch, not fetch: the endpoint validates the room id and authorizes the caller.
  const postParamChanges = useCallback((changes: Array<Record<string, unknown>>) => {
    const mode = currentConv?.settings?.mode ?? experimentMode;
    if (!currentConv?.roomId || changes.length === 0) return;
    authFetch(`/log-param-change`, {
      method: "POST",
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

  // Multi-2 is admin-only — bounce non-admins off limited mode
  useEffect(() => {
    if (!isAdmin && experimentMode === "limited") {
      setExperimentMode("full");
    }
  }, [isAdmin, experimentMode]);

  useEffect(() => {
    if (!auth?.token) return;
    let cancelled = false;
    authFetch("/study/policy")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d) return;
        const modes = (d.allowed_modes as unknown[] | undefined)?.filter(
          (m): m is ExperimentMode => m === "full" || m === "limited" || m === "single",
        );
        if (modes && modes.length) setAllowedModes(modes);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [auth?.token]);

  // A participant assigned a single condition must not sit in another one — the
  // default is "full", so anyone assigned single starts out in the wrong mode.
  useEffect(() => {
    if (allowedModes.length === 0 || allowedModes.includes(experimentMode)) return;
    const next = allowedModes[0];
    setExperimentMode(next);
    if (next === "single") {
      setActiveAgentKeys(["A"]);
      activeAgentKeysRef.current = ["A"];
    }
  }, [allowedModes, experimentMode]);

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
                  agentSettings: blankAgentSettings(),
                  activeAgentKeys: [...DEFAULT_ACTIVE_AGENT_KEYS],
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
    setAgentsOpen(false);
  }, [currentConvId]);

  useEffect(() => {
    if (!agentsOpen) return;
    const h = (e: MouseEvent) => {
      const node = e.target as Node;
      if (agentsPanelRef.current?.contains(node) || agentsBtnRef.current?.contains(node)) return;
      setAgentsOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [agentsOpen]);

  useEffect(() => {
    setChatLayerAnnotations({});
    setChatAnnotationDraft(null);
    setChatAnnotationMode(false);
    setSummaryOpen(false);
    setSummaryError(null);
    setNaviActiveMessageId(null);
    setHighlightedMessageId(null);
    setHighlightedMessageIds([]);
    // Close out the OUTGOING room's telemetry before repointing the buffer, otherwise a
    // map left open on conversation switch never produces a close event and an abandoned
    // draft is attributed to the wrong room.
    const pendingDwell = mapDwellRef.current.close();
    if (pendingDwell) emit("map_closed", { ...pendingDwell, reason: "room_switch" });
    // lastInputLenRef, not inputValue: this effect is keyed on currentConvId, so reading
    // the state here would close over whichever value that render happened to see.
    if (lastInputLenRef.current > 0) {
      emit("composer_draft_abandoned", {
        chars: lastInputLenRef.current,
        keystrokes: keystrokesRef.current,
        backspaces: backspacesRef.current,
        age_ms: firstKeystrokeAtRef.current ? Date.now() - firstKeystrokeAtRef.current : null,
      });
    }
    void flushTelemetry();
    setTelemetryRoom(currentConv?.roomId ?? null);
    lastBotMessageAtRef.current = null;
    firstKeystrokeAtRef.current = null;
    keystrokesRef.current = 0;
    backspacesRef.current = 0;
    lastInputLenRef.current = 0;
    optionShownAtRef.current.clear();

    setDecisionMapOpen(false);
    setDecisionMapDocked(false);
    setDecisionMap(null);
    setDecisionMapError(null);
    setSelectedMapTopicId(null);
    naviJumpLockRef.current = false;
    if (naviJumpUnlockTimerRef.current) {
      window.clearTimeout(naviJumpUnlockTimerRef.current);
      naviJumpUnlockTimerRef.current = null;
    }
  }, [currentConvId]);

  const decisionNaviNodes = useMemo(() => {
    if (!currentConv?.messages?.length) return [];
    return buildDecisionNaviNodes(
      currentConv.messages,
      phaseMarkersByRoom[currentConv.roomId] || [],
      currentPhase,
      uiLang,
    );
  }, [currentConv?.messages, currentConv?.roomId, phaseMarkersByRoom, currentPhase, uiLang]);

  // The decision map is drawn from the stance / option-board apparatus, and in the
  // single-agent condition that apparatus never runs: app.py:1481 answers the turn
  // itself and never reaches run_user_turn. The navi pill, though, is built from the
  // user's own messages (DecisionNavi.tsx:70), so it does not know that and used to
  // appear anyway -- opening a map with an empty advisor lane. Gated like the
  // Decision summary in SettingsMenu below.
  const mapAvailable = (currentConv?.settings?.mode ?? experimentMode) !== "single";

  const jumpToMessage = useCallback((messageId: string) => {
    const root = messagesContainerRef.current;
    if (!root) return;
    const safeId = typeof CSS !== "undefined" && typeof CSS.escape === "function"
      ? CSS.escape(messageId)
      : messageId.replace(/["\\]/g, "\\$&");
    const el = root.querySelector(`[data-message-id="${safeId}"]`) as HTMLElement | null;
    if (!el) return;
    stickToBottomRef.current = false;

    // Lock scroll-spy so intermediate nodes don't flash as "active" during smooth scroll.
    naviJumpLockRef.current = true;
    if (naviJumpUnlockTimerRef.current) window.clearTimeout(naviJumpUnlockTimerRef.current);
    const unlockSpy = () => {
      naviJumpLockRef.current = false;
      naviJumpUnlockTimerRef.current = null;
      setNaviActiveMessageId(messageId);
    };
    const onScrollEnd = () => {
      root.removeEventListener("scrollend", onScrollEnd);
      unlockSpy();
    };
    root.addEventListener("scrollend", onScrollEnd);
    naviJumpUnlockTimerRef.current = window.setTimeout(() => {
      root.removeEventListener("scrollend", onScrollEnd);
      unlockSpy();
    }, 900);

    setNaviActiveMessageId(messageId);
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightToken((n) => n + 1);
    setHighlightedMessageId(messageId);
    setHighlightedMessageIds([messageId]);
    if (highlightTimerRef.current) window.clearTimeout(highlightTimerRef.current);
    highlightTimerRef.current = window.setTimeout(() => {
      setHighlightedMessageId((prev) => (prev === messageId ? null : prev));
      setHighlightedMessageIds([]);
      highlightTimerRef.current = null;
    }, 1000);
  }, []);

  const jumpToRange = useCallback((indexes: number[]) => {
    const messages = currentConv?.messages || [];
    const ids = indexes
      .map((i) => messages[i]?.id)
      .filter((id): id is string => !!id);
    if (ids.length === 0) return;
    jumpToMessage(ids[0]);
    if (ids.length > 1) {
      setHighlightedMessageIds(ids);
      setHighlightToken((n) => n + 1);
      if (highlightTimerRef.current) window.clearTimeout(highlightTimerRef.current);
      highlightTimerRef.current = window.setTimeout(() => {
        setHighlightedMessageIds([]);
        setHighlightedMessageId((prev) => (prev === ids[0] ? null : prev));
        highlightTimerRef.current = null;
      }, 1200);
    }
  }, [currentConv?.messages, jumpToMessage]);

  const fetchDecisionMap = useCallback(async (opts?: { extract?: boolean }) => {
    const roomId = currentConv?.roomId;
    if (!roomId) return;
    const wantExtract = opts?.extract !== false;
    if (wantExtract) setDecisionMapExtracting(true);
    else setDecisionMapLoading(true);
    setDecisionMapError(null);
    try {
      const qs = new URLSearchParams({
        lang: uiLang,
        smart: "1",
        extract: wantExtract ? "1" : "0",
      });
      const res = await authFetch(`/decision-map/${roomId}?${qs}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setDecisionMapError((data as { error?: string }).error || t(uiLang, "map.errorLoad"));
        return;
      }
      const map = data as DecisionMapData;
      setDecisionMap(map);
      setSelectedMapTopicId((prev) => {
        if (prev) return prev;
        const issues = map.issues || [];
        if (!issues.length) return prev;
        const active = issues.find((i) => i.status === "leaning" || i.status === "open") || issues[0];
        return active.id;
      });
    } catch {
      setDecisionMapError(t(uiLang, "map.errorLoad"));
    } finally {
      setDecisionMapLoading(false);
      setDecisionMapExtracting(false);
    }
  }, [currentConv?.roomId, uiLang]);

  const handleOpenDecisionMap = useCallback(() => {
    // Second gate, on the same reasoning as study_policy.py: hiding the control is
    // not enough on its own, since a stale render or a re-entered callback would
    // still put a participant in front of a panel their condition does not have.
    if (!mapAvailable) return;
    setDecisionMapOpen(true);
    setDecisionMapDocked(false);
    mapDwellRef.current.open();
    // decision_map.jsonl only gets a row when the extract cache misses, so it undercounts
    // opens. This event is the actual open count.
    emit("map_opened", { topic_count: decisionMapTopicCountRef.current });
    // Open → smart extract only if transcript changed (backend skips when cache is fresh).
    void fetchDecisionMap({ extract: true });
  }, [fetchDecisionMap, mapAvailable]);

  // Jump from the map: dock it (chat becomes visible), then scroll+flash the
  // evidence. The pill rendered by DecisionMapPanel is the way back.
  const handleMapJumpIndexes = useCallback(
    (indexes: number[]) => {
      setDecisionMapDocked(true);
      // Docked means mounted but not being read -- excluded from focused_ms.
      mapDwellRef.current.dock();
      emit("map_docked", { evidence_count: indexes.length });
      jumpToRange(indexes);
    },
    [jumpToRange],
  );

  const handleChooseOption = useCallback(async (message: Message, option: ChatOptionChip) => {
    const roomId = currentConv?.roomId;
    const convId = currentConvId;
    if (!roomId || !convId || message.chosenOptionId) return;
    // Which chip was picked already reaches choices.jsonl. What it cannot record is how
    // long the user sat with the choice before making it.
    const shownAt = optionShownAtRef.current.get(message.id);
    emit("option_clicked", {
      message_id: message.id,
      option_id: option.id,
      option_count: message.options?.length ?? null,
      dwell_ms: shownAt ? Date.now() - shownAt : null,
    });
    const confirmText = t(uiLang, "chat.choseOption", { label: option.label });
    // Optimistic lock + confirmation bubble
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id !== convId) return c;
        const msgs = c.messages.map((m) =>
          m.id === message.id ? { ...m, chosenOptionId: option.id } : m,
        );
        const confirm: Message = {
          id: `msg-choice-${Date.now()}`,
          role: "user",
          content: confirmText,
          timestamp: Date.now(),
        };
        return { ...c, messages: [...msgs, confirm], preview: confirmText, timestamp: "just now" };
      }),
    );
    try {
      const res = await authFetch(`/decision-map/${roomId}/choices`, {
        method: "POST",
        body: JSON.stringify({
          lang: uiLang,
          choice_group_id: message.id,
          option_id: option.id,
          label: option.label,
          proposed_by: message.agentKey,
          options: message.options,
          confirm_text: confirmText,
          message_index: currentConv?.messages.findIndex((m) => m.id === message.id) ?? undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        // Roll back lock on conflict/error
        setConversations((prev) =>
          prev.map((c) =>
            c.id !== convId
              ? c
              : {
                  ...c,
                  messages: c.messages
                    .filter((m) => m.content !== confirmText || m.role !== "user")
                    .map((m) => (m.id === message.id ? { ...m, chosenOptionId: null } : m)),
                },
          ),
        );
        return;
      }
      if (data.map) {
        setDecisionMap(data.map as DecisionMapData);
      } else if (decisionMapOpen) {
        void fetchDecisionMap({ extract: false });
      }
    } catch {
      /* keep optimistic UI */
    }
  }, [currentConv?.roomId, currentConv?.messages, currentConvId, uiLang, decisionMapOpen, fetchDecisionMap]);

  // UI language switch → load/extract for that lang (skipped if same-lang cache still fresh).
  useEffect(() => {
    if (!decisionMapOpen || !currentConv?.roomId) return;
    void fetchDecisionMap({ extract: true });
  }, [uiLang]); // eslint-disable-line react-hooks/exhaustive-deps -- only on lang change

  const handleExtractDecisionMap = useCallback(async () => {
    const roomId = currentConv?.roomId;
    if (!roomId) return;
    setDecisionMapExtracting(true);
    setDecisionMapError(null);
    try {
      const res = await authFetch(`/decision-map/${roomId}/extract`, {
        method: "POST",
        body: JSON.stringify({ lang: uiLang }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setDecisionMapError((data as { error?: string }).error || t(uiLang, "map.errorExtract"));
        return;
      }
      setDecisionMap(data as DecisionMapData);
    } catch {
      setDecisionMapError(t(uiLang, "map.errorExtract"));
    } finally {
      setDecisionMapExtracting(false);
    }
  }, [currentConv?.roomId, uiLang]);

  useEffect(() => {
    const root = messagesContainerRef.current;
    if (!root || decisionNaviNodes.length === 0) return;
    const ids = new Set(decisionNaviNodes.map((n) => n.messageId));
    const elements = [...root.querySelectorAll<HTMLElement>("[data-message-id]")].filter((el) =>
      ids.has(el.dataset.messageId || ""),
    );
    if (elements.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (naviJumpLockRef.current) return;
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        const top = visible[0]?.target as HTMLElement | undefined;
        const mid = top?.dataset.messageId;
        if (mid) setNaviActiveMessageId(mid);
      },
      { root, threshold: [0.35, 0.6], rootMargin: "-10% 0px -45% 0px" },
    );
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [decisionNaviNodes, currentConvId]);

  const notePhaseChange = useCallback((roomId: string, nextPhase: string | null | undefined, messageId?: string) => {
    if (!roomId || !nextPhase) return;
    const prev = lastPhaseByRoomRef.current[roomId] ?? null;
    lastPhaseByRoomRef.current[roomId] = nextPhase;
    if (!prev || prev === nextPhase) return;
    setPhaseMarkersByRoom((markers) => {
      const list = markers[roomId] || [];
      if (list.some((m) => m.to === nextPhase && (m.messageId === messageId || !messageId))) {
        return markers;
      }
      return {
        ...markers,
        [roomId]: [...list, { from: prev, to: nextPhase, messageId }],
      };
    });
  }, []);

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

  // Intake and profile live in React state until the first message creates the room,
  // so a reload used to throw away a finished pair of forms and drop the participant
  // back at "intake required". Put them back before the welcome screen can say that.
  // Not the auto-pick the effect above refuses to make: this replays a choice the
  // participant already confirmed, and only inside the draft's one-sitting window.
  const draftRestoredRef = useRef(false);
  useEffect(() => {
    if (draftRestoredRef.current || scenes.length === 0) return;
    draftRestoredRef.current = true;
    const draft = loadIntakeDraft(webUserId);
    const scene = draft && scenes.find((s) => s.id === draft.scenario_type);
    if (!draft || !scene || scene.available === false) return;
    setSelectedScene((prev) => prev || scene);
    setUserProfile((prev) => prev || draft.profile);
    setAgora2Intake((prev) => prev || {
      scenario_type: draft.scenario_type,
      lang: draft.lang,
      intake: draft.intake,
      session_update: draft.session_update,
    });
    // The payload above is what /api/start sends; lastIntake is what the FORM
    // renders. Restoring only the former left "intake ready" on the welcome
    // screen while `click to change` opened a blank form -- and confirming that
    // blank form overwrote the restored answers with nothing.
    setLastIntake((prev) => prev || draft.intake);
  }, [scenes, webUserId]);

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
  useEffect(() => { activeAgentKeysRef.current = activeAgentKeys; }, [activeAgentKeys]);

  const syncRosterToBackend = useCallback(async (
    keys: AgentKey[],
    names: Record<AgentKey, string>,
    settings: Record<AgentKey, AgentCustomSetting>,
  ) => {
    const roomId = currentConv?.roomId;
    if (!roomId) return true;
    const mode = currentConv?.settings?.mode ?? experimentMode;
    if (mode === "limited") return true;
    try {
      const res = await fetch(`${API_BASE}/roster`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(auth?.token ? { Authorization: `Bearer ${auth.token}` } : {}),
        },
        body: JSON.stringify({
          room_id: roomId,
          mode,
          agents: buildStartAgentsPayload(
            keys,
            names,
            settings,
            selectedScene?.id || currentConv?.settings?.selectedScene?.id,
          ),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        console.warn("roster sync failed", data);
        return false;
      }
      const apiAgents = (data as { agents?: Array<{ key?: string; name?: string; stance?: string; hint?: string; decision?: string; emotion?: string }> }).agents || [];
      if (apiAgents.length > 0) {
        const apiKeys = apiAgents.map((a) => a.key as AgentKey).filter((k) => ALL_AGENT_KEYS.includes(k));
        setActiveAgentKeys(apiKeys);
        activeAgentKeysRef.current = apiKeys;
        setAgentNames((prev) => {
          const next = { ...prev };
          apiAgents.forEach((a) => {
            const k = a.key as AgentKey;
            if (k && a.name) next[k] = a.name;
          });
          return next;
        });
        setAgentSettings((prev) => {
          const next = cloneAgentSettings(prev);
          apiAgents.forEach((a) => {
            const k = a.key as AgentKey;
            if (!k || !next[k]) return;
            if (a.stance) next[k].stance = a.stance;
            if (typeof a.hint === "string") next[k].hint = a.hint;
            if (a.decision) next[k].decisionBlock = a.decision as AgentCustomSetting["decisionBlock"];
            if (a.emotion) next[k].emotionTag = String(a.emotion).toLowerCase();
          });
          return next;
        });
      }
      return true;
    } catch (e) {
      console.warn("roster sync error", e);
      return false;
    }
  }, [currentConv?.roomId, currentConv?.settings?.mode, currentConv?.settings?.selectedScene?.id, experimentMode, auth?.token, selectedScene?.id]);

  const addAgent = useCallback(() => {
    if (experimentMode === "single" || experimentMode === "limited") return;
    setActiveAgentKeys((prev) => {
      if (prev.length >= MAX_ROSTER_AGENTS) return prev;
      const nextKey = nextFreeAgentKey(prev);
      if (!nextKey) return prev;
      const next = [...prev, nextKey];
      const sceneId = selectedScene?.id || currentConv?.settings?.selectedScene?.id;
      const seeded = {
        ...defaultSetting(nextKey),
        stance: defaultStanceForKey(sceneId, nextKey, next),
      };
      const nextNames = { ...agentNamesRef.current, [nextKey]: backendLabelForKey(nextKey) };
      const nextSettings = { ...agentSettingsRef.current, [nextKey]: seeded };
      setAgentNames(nextNames);
      setAgentSettings(nextSettings);
      agentNamesRef.current = nextNames;
      agentSettingsRef.current = nextSettings;
      activeAgentKeysRef.current = next;
      setCustomizerInitialAgent(nextKey);
      setShowCustomizer(true);
      void syncRosterToBackend(next, nextNames, nextSettings);
      return next;
    });
  }, [experimentMode, selectedScene?.id, currentConv?.settings?.selectedScene?.id, syncRosterToBackend]);

  const removeAgent = useCallback((key: AgentKey) => {
    if (experimentMode === "single" || experimentMode === "limited") return;
    setActiveAgentKeys((prev) => {
      if (prev.length <= MIN_ROSTER_AGENTS) return prev;
      if (!prev.includes(key)) return prev;
      const next = prev.filter((k) => k !== key);
      activeAgentKeysRef.current = next;
      void syncRosterToBackend(next, agentNamesRef.current, agentSettingsRef.current);
      return next;
    });
  }, [experimentMode, syncRosterToBackend]);

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
      // A request can be in flight while the PREVIOUS turn's queue is still
      // draining (the composer re-enables as soon as the fetch resolves, not
      // when the queue empties). Clearing unconditionally here wiped the
      // pending indicator for that in-flight turn, putting the user back on a
      // silent screen — the exact state that made P41 re-send.
      setTypingKeys(requestInFlightRef.current ? ["pending"] : []);
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
        id: next.messageId || `msg-${Date.now()}-${next.agentKey}`,
        role: isSystem ? "system" : "agent",
        agentKey: isSystem ? undefined : (next.agentKey as AgentKey),
        content: next.content,
        timestamp: Date.now(),
        emotionTagSnapshot: isSystem ? null : next.emotionTagSnapshot,
        options: next.options && next.options.length >= 2 ? next.options : undefined,
        knowledge: isSystem ? undefined : next.knowledge,
      };
      const names = agentNamesRef.current;
      const previewLabel = isSystem ? "System" : names[next.agentKey as AgentKey];
      setConversations((prev) => prev.map((c) => c.id === next.convId ? { ...c, messages: [...c.messages, agentMsg], preview: `${previewLabel}: ${next.content.slice(0, 60)}…`, timestamp: "just now" } : c));
      // Emitted from the drain, not from the chip render block: AgentMessage is React.memo
      // and re-renders on unrelated prop changes, so rendering would fire this repeatedly.
      // Here it runs exactly once, when the message first appears.
      if (agentMsg.options) {
        optionShownAtRef.current.set(agentMsg.id, Date.now());
        emit("option_group_shown", {
          message_id: agentMsg.id,
          option_ids: agentMsg.options.map((o) => o.id),
          option_count: agentMsg.options.length,
        });
      }
      setMsgQueue((q) => {
        const rest = q.slice(1);
        const n0 = rest[0];
        // Last message of the turn: this is the moment the user can start replying, so
        // it is the zero point for reply latency.
        if (rest.length === 0) lastBotMessageAtRef.current = Date.now();
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
      setSessionCreateError(t(uiLang, "err.selectScene"));
      openSceneSelector();
      return;
    }
    if (!currentConvId && experimentMode === "limited" && limitedSelectedAgents.length !== 3) {
      setSessionCreateError(t(uiLang, "err.limited3"));
      return;
    }
    setSessionCreateError(null);
    // Emitted before the refs are reset below. reply_latency_ms is the pause before the
    // user started typing; compose_ms is how long they spent writing it.
    emit("composer_send", {
      reply_latency_ms:
        lastBotMessageAtRef.current && firstKeystrokeAtRef.current
          ? firstKeystrokeAtRef.current - lastBotMessageAtRef.current
          : null,
      compose_ms: firstKeystrokeAtRef.current ? Date.now() - firstKeystrokeAtRef.current : null,
      keystrokes: keystrokesRef.current,
      backspaces: backspacesRef.current,
      chars: text.length,
      is_new_conv: !currentConvId,
    });
    firstKeystrokeAtRef.current = null;
    keystrokesRef.current = 0;
    backspacesRef.current = 0;
    lastInputLenRef.current = 0;
    setInputValue("");
    setIsLoading(true);

    const userMsg: Message = { id: `msg-${Date.now()}`, role: "user", content: text, timestamp: Date.now() };
    let convId = currentConvId;
    let roomId = currentConv?.roomId || "";
    const isNewConv = !convId;
    let nextNamesForConv: Record<AgentKey, string> = { ...agentNamesRef.current };
    let nextBackendNamesForConv: Record<AgentKey, string> = { ...agentBackendNames };
    let nextSettingsForConv: Record<AgentKey, AgentCustomSetting> = cloneAgentSettings(agentSettingsRef.current);
    let nextActiveKeys: AgentKey[] = normalizeActiveKeys(
      experimentMode === "single" ? ["A"] : activeAgentKeysRef.current,
      experimentMode,
    );

    if (!convId) {
      if (isAgora2SceneId(selectedScene?.id) && (!userProfile || !agora2Intake)) {
        if (!userProfile) {
          setSessionCreateError(t(uiLang, "err.profile"));
          setProfileHandoff(false);
          setShowProfileModal(true);
        } else {
          setSessionCreateError(t(uiLang, "err.intake"));
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
            agents: experimentMode === "limited"
              ? undefined
              : buildStartAgentsPayload(
                  nextActiveKeys,
                  nextNamesForConv,
                  nextSettingsForConv,
                  selectedScene.id,
                ),
            ...(isAgora2SceneId(selectedScene.id) && userProfile && agora2Intake
              ? {
                  scenario_type: selectedScene.id,
                  lang: agora2Intake.lang || uiLang,
                  profile: userProfile,
                  intake: agora2Intake.intake,
                  session_update: agora2Intake.session_update || "",
                  user_id: webUserId,
                  use_demo_intake: false,
                }
              : {}),
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          setSessionCreateError((data?.error as string) || t(uiLang, "err.createSession"));
          setInputValue(text);
          setIsLoading(false);
          return;
        }
        roomId = data.room_id || "";
        if (!roomId) {
          setSessionCreateError(t(uiLang, "err.noRoom"));
          setInputValue(text);
          setIsLoading(false);
          return;
        }
        if (typeof data.session_index === "number") setSessionIndex(data.session_index);
        // Apply agent defaults from info.jsonl (decision, emotion)
        const agentsFromApi = data.agents || [];
        if (agentsFromApi.length > 0) {
          const apiKeys: AgentKey[] = [];
          agentsFromApi.forEach((a: { key?: string; pool_key?: string; name?: string; decision?: string; emotion?: string; role?: string }) => {
            const k = a.key as AgentKey;
            if (k && ALL_AGENT_KEYS.includes(k)) {
              apiKeys.push(k);
              const defaultCfg = defaultSetting(k);
              const shouldApplyApiBehaviorDefaults =
                experimentMode !== "full" ||
                (
                  sameEmotionSnapshot(nextSettingsForConv[k], defaultCfg) &&
                  nextSettingsForConv[k].decisionBlock === defaultCfg.decisionBlock
                );
              if (a.name) nextBackendNamesForConv[k] = a.name;
              if (experimentMode === "full" && a.name) {
                nextNamesForConv[k] = a.name;
              }
              if (experimentMode === "limited") {
                const profile = LIMITED_AGENT_POOL.find((p) => p.key === (a.pool_key as AgentPoolKey));
                nextNamesForConv[k] = profile?.defaultName || a.name || nextNamesForConv[k];
              }
              const apiAgent = a as { stance?: string; hint?: string; decision?: string; emotion?: string; role?: string; pool_key?: string; name?: string };
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
                stance: apiAgent.stance || nextSettingsForConv[k].stance,
                hint: typeof apiAgent.hint === "string" ? apiAgent.hint : nextSettingsForConv[k].hint,
              };
            }
          });
          if (apiKeys.length > 0) {
            nextActiveKeys = normalizeActiveKeys(apiKeys, experimentMode);
          }
          setAgentNames(nextNamesForConv);
          setAgentBackendNames(nextBackendNamesForConv);
          setAgentSettings(nextSettingsForConv);
          setActiveAgentKeys(nextActiveKeys);
          activeAgentKeysRef.current = nextActiveKeys;
        }
      } catch {
        setSessionCreateError(backendOnline ? t(uiLang, "err.createSession") : t(uiLang, "err.backendDown"));
        setInputValue(text);
        setIsLoading(false);
        return;
      }
      const newConv: Conversation = {
        id: `conv-${Date.now()}`, roomId, title: text.length > 48 ? text.slice(0, 48) + "…" : text, preview: text, timestamp: "just now", messages: [userMsg],
        settings: {
          agentNames: nextNamesForConv,
          agentBackendNames: nextBackendNamesForConv,
          agentSettings: nextSettingsForConv,
          activeAgentKeys: nextActiveKeys,
          limitedSelectedAgents,
          selectedScene,
          maxAgentTurns,
          maxUserGap,
          mode: experimentMode,
        },
      };
      setConversations((prev) => [newConv, ...prev]);
      convId = newConv.id;
      setCurrentConvId(convId);
      setCurrentPhase("Exploration");
      lastPhaseByRoomRef.current[roomId] = "Exploration";
      setPhaseMarkersByRoom((prev) => ({ ...prev, [roomId]: prev[roomId] || [] }));
    } else {
      setConversations((prev) => prev.map((c) => c.id === convId ? { ...c, messages: [...c.messages, userMsg], timestamp: "just now" } : c));
    }

    const activeMode: ExperimentMode = isNewConv ? experimentMode : (currentConv?.settings?.mode ?? "full");
    const requestAgentSettings: Record<AgentKey, AgentCustomSetting> = isNewConv
      ? nextSettingsForConv
      : agentSettingsRef.current;
    const agentEmotionOverrides: Record<string, string> = {};
    const agentDecisionBlock: Record<string, string> = {};
    const useNeutral = activeMode === "limited" || activeMode === "single";
    if (useNeutral) {
      if (activeMode === "single") agentDecisionBlock["A"] = "Rational";
    } else {
      const rosterKeys = isNewConv
        ? nextActiveKeys
        : normalizeActiveKeys(currentConv?.settings?.activeAgentKeys || activeAgentKeysRef.current, activeMode);
      rosterKeys.forEach((k) => {
        const cfg = requestAgentSettings[k];
        if (!cfg) return;
        if (cfg.emotionOn && cfg.emotionTag) agentEmotionOverrides[k] = cfg.emotionTag;
        agentDecisionBlock[k] = cfg.decisionBlock;
      });
    }

    const maxTurns = activeMode === "single" ? 1 : maxAgentTurns;
    // Speaker unknown until the server answers — show a neutral indicator.
    requestInFlightRef.current = true;
    setTypingKeys(["pending"]);

    const postMessage = async (rid: string) => {
      const res = await fetch(`${API_BASE}/message`, {
        method: "POST",
        // The token is what lets the server rebuild a room it no longer holds in
        // memory: _rehydrate_session refuses to restore a room to anyone who cannot be
        // shown to own it, and without this header there is nobody to check against.
        // /api/start and the recreate path have always sent it; this one had not, so
        // the first message after a restart 400'd and the client silently started a
        // NEW room instead -- losing the transcript the old one already had.
        headers: {
          "Content-Type": "application/json",
          ...(auth?.token ? { Authorization: `Bearer ${auth.token}` } : {}),
        },
        body: JSON.stringify({
          room_id: rid,
          message: text,
          scene_id: selectedScene?.id || currentConv?.settings?.selectedScene?.id || "",
          emotion_tag: null,
          emotion_target: null,
          agent_emotion_overrides: agentEmotionOverrides,
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
          agents: activeMode === "limited"
            ? undefined
            : buildStartAgentsPayload(
                normalizeActiveKeys(currentConv?.settings?.activeAgentKeys || activeAgentKeysRef.current, activeMode),
                agentNamesRef.current,
                agentSettingsRef.current,
                sceneForRecreate.id,
              ),
          ...(isAgora2SceneId(sceneForRecreate.id) && userProfile && agora2Intake
            ? {
                scenario_type: sceneForRecreate.id,
                lang: agora2Intake.lang || uiLang,
                profile: userProfile,
                intake: agora2Intake.intake,
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
          throw new Error(t(uiLang, "err.sessionExpired"));
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
      notePhaseChange(roomId, data.phase || null, userMsg.id);
      const responses: Array<{
        agent_key: string;
        message: string;
        message_id?: string;
        options?: ChatOptionChip[];
        knowledge?: KnowledgeReference;
      }> = data.responses || [];
      if (responses.length === 0) {
        // Every scheduled turn was dropped server-side. Silently clearing the
        // indicator here is what made rooms 675008/894275 look frozen: P41
        // re-sent the same 271-char message byte-for-byte because nothing
        // acknowledged the first one. Show the same visible feedback the
        // catch-path uses so the user knows to re-send.
        setTypingKeys([]);
        const noRespMsg: Message = {
          id: `msg-noresp-${Date.now()}`,
          role: "agent",
          content: t(uiLang, "err.noResponse"),
          timestamp: Date.now(),
        };
        setConversations((prev) => prev.map((c) => c.id === convId ? { ...c, messages: [...c.messages, noRespMsg] } : c));
        // This notice is what the user actually replies to, so it is the zero
        // point for reply latency — the same role the last queued bot message
        // plays in the drain. Without it, the re-send this notice solicits is
        // measured from the PREVIOUS successful turn and reply_latency_ms is
        // inflated by the whole dead interval.
        lastBotMessageAtRef.current = Date.now();
      }
      else {
        const mapped = responses
          .filter((r) => !!(r.message || "").trim())
          .map((r) => {
            const isSystem = r.agent_key === "system" || r.agent_key === "System";
            const agentKey = (isSystem ? "system" : (r.agent_key || "A")) as AgentKey | "system";
            const currentSetting = !isSystem ? agentSettingsRef.current[agentKey as AgentKey] : null;
            const opts = Array.isArray(r.options)
              ? r.options.filter((o) => o && o.id && o.label).map((o) => ({ id: String(o.id), label: String(o.label) }))
              : undefined;
            return {
              agentKey,
              content: r.message || "",
              convId: convId as string,
              emotionTagSnapshot: currentSetting?.emotionOn ? (currentSetting.emotionTag ?? "joy") : null,
              isSystem,
              messageId: r.message_id,
              options: opts && opts.length >= 2 ? opts : undefined,
              knowledge: r.knowledge?.id && r.knowledge?.tag
                ? { id: String(r.knowledge.id), tag: String(r.knowledge.tag), source: String(r.knowledge.source || "") }
                : undefined,
            };
          });
        const filtered = activeMode === "single"
          ? mapped.filter((m) => m.isSystem || m.agentKey === "A").slice(0, 2)
          : mapped;
        setMsgQueue(filtered);
      }
    } catch (err) {
      requestInFlightRef.current = false;
      setTypingKeys([]);
      const detail = err instanceof Error && err.message ? err.message : t(uiLang, "err.generic");
      const errMsg: Message = { id: `msg-err-${Date.now()}`, role: "agent", content: backendOnline ? detail : t(uiLang, "err.backendDown"), timestamp: Date.now() };
      setConversations((prev) => prev.map((c) => c.id === convId ? { ...c, messages: [...c.messages, errMsg] } : c));
      // Same reasoning as the no-response notice: the error is what the user
      // replies to, so it is the reply-latency zero point.
      lastBotMessageAtRef.current = Date.now();
    } finally {
      requestInFlightRef.current = false;
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
      const histKeys: AgentKey[] = [];
      (data.active_agents || []).forEach((a: { key?: string; name?: string }) => {
        const k = a.key as AgentKey;
        if (k && ALL_AGENT_KEYS.includes(k) && a.name) {
          histKeys.push(k);
          runtimeMap[a.name] = k;
          runtimeBackendNames[k] = a.name;
          if (modeForHistory !== "limited") {
            runtimeNames[k] = a.name;
          }
        }
      });
      if (histKeys.length > 0) {
        const normalized = normalizeActiveKeys(histKeys, modeForHistory);
        setActiveAgentKeys(normalized);
        activeAgentKeysRef.current = normalized;
      }
      if (Object.keys(runtimeNames).length > 0) {
        setAgentNames((prev) => ({ ...prev, ...runtimeNames }));
      }
      if (Object.keys(runtimeBackendNames).length > 0) {
        setAgentBackendNames((prev) => ({ ...prev, ...runtimeBackendNames }));
      }
      const hist = data.history || [];
      const choices: Array<{ choice_group_id?: string; option_id?: string }> = data.choices || [];
      const chosenByGroup = new Map(
        choices
          .filter((c) => c.choice_group_id && c.option_id)
          .map((c) => [String(c.choice_group_id), String(c.option_id)]),
      );
      const messages: Message[] = hist.map((
        h: { id?: string; character: string; txt: string; time?: string; options?: ChatOptionChip[]; knowledge?: KnowledgeReference },
        i: number,
      ) => {
        const ts = historyTimestamp(h.time, i, hist.length);
        const mid = h.id || `h-${i}`;
        if (h.character === "user") return { id: mid, role: "user" as const, content: h.txt, timestamp: ts };
        if (h.character === "system") {
          return {
            id: mid,
            role: "system" as const,
            content: h.txt,
            timestamp: ts,
          };
        }
        const agentKey = runtimeMap[h.character] ?? BACKEND_NAME_TO_KEY[h.character] ?? "A";
        const currentSetting = agentSettingsRef.current[agentKey];
        const opts = Array.isArray(h.options) && h.options.length >= 2
          ? h.options.map((o) => ({ id: String(o.id), label: String(o.label) }))
          : undefined;
        return {
          id: mid,
          role: "agent" as const,
          agentKey,
          content: h.txt,
          timestamp: ts,
          emotionTagSnapshot: currentSetting?.emotionOn ? (currentSetting.emotionTag ?? "joy") : null,
          options: opts,
          chosenOptionId: opts ? (chosenByGroup.get(mid) || null) : null,
          knowledge: h.knowledge?.id && h.knowledge?.tag ? h.knowledge : undefined,
        };
      });
      setConversations((prev) => prev.map((c) => c.id === currentConvId ? { ...c, messages } : c));
      if (data.phase) setCurrentPhase(data.phase);
      const roomId = currentConv.roomId;
      lastPhaseByRoomRef.current[roomId] = data.phase || lastPhaseByRoomRef.current[roomId] || "Exploration";
      const markers = phaseMarkersFromApi(data.phase_changes);
      if (markers.length > 0) {
        setPhaseMarkersByRoom((prev) => ({ ...prev, [roomId]: markers }));
      }
    } catch {}
  };

  const handleExportLog = async () => {
    if (!currentConv?.roomId) return;
    try {
      // authFetch, not fetch: the endpoint enforces owner-or-admin now. It used to skip
      // its own ownership check whenever the caller sent no token at all.
      const res = await authFetch(`/export-logs/${currentConv.roomId}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert((err as { error?: string }).error || t(uiLang, "err.export"));
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      // Server decides the name (it carries a timestamp); this is only the fallback.
      const cd = res.headers.get("Content-Disposition") || "";
      a.download = /filename="?([^"]+)"?/i.exec(cd)?.[1] || `agora_logs_${currentConv.roomId}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert(t(uiLang, "err.exportBackend"));
    }
  };

  const fetchSessionSummary = async () => {
    const roomId = currentConv?.roomId;
    if (!roomId) return;
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
        setSummaryError((data as { error?: string }).error || t(uiLang, "err.summary"));
        return;
      }
      setSummaryByRoom((prev) => ({ ...prev, [roomId]: (data as { markdown?: string }).markdown || "" }));
      // Summary caches overall JSON for the decision map — refresh if the panel is open.
      if (decisionMapOpen) void fetchDecisionMap({ extract: false });
    } catch {
      setSummaryError(t(uiLang, "err.summaryBackend"));
    } finally {
      setSummaryLoading(false);
    }
  };

  /** Open panel only — API runs when user presses Generate. */
  const handleOpenSummary = () => {
    const mode = currentConv?.settings?.mode ?? experimentMode;
    if (mode === "single") return;
    setSummaryError(null);
    setSummaryLoading(false);
    setSummaryOpen(true);
  };

  const defaultConvSettings = (mode: ExperimentMode = "full"): ConvSettings => ({
    agentNames: { ...DEFAULT_AGENT_NAMES },
    agentBackendNames: { ...DEFAULT_AGENT_NAMES },
    agentSettings: blankAgentSettings(),
    activeAgentKeys: mode === "single" ? ["A"] : [...DEFAULT_ACTIVE_AGENT_KEYS],
    limitedSelectedAgents: [...LIMITED_DEFAULT_SELECTED],
    selectedScene: null,
    maxAgentTurns: 5,
    maxUserGap: 12,
    mode,
  });

  const getConvSettings = (conv: Conversation | null): ConvSettings => {
    const def = defaultConvSettings(experimentMode);
    if (!conv?.settings) return def;
    const mode = conv.settings.mode ?? "full";
    return {
      ...def,
      ...conv.settings,
      mode,
      activeAgentKeys: normalizeActiveKeys(conv.settings.activeAgentKeys, mode),
      agentSettings: cloneAgentSettings(conv.settings.agentSettings || {}),
    };
  };

  const saveCurrentConvSettings = useCallback(() => {
    if (!currentConvId) return;
    const existingMode = currentConv?.settings?.mode ?? "full";
    const s: ConvSettings = {
      agentNames,
      agentBackendNames,
      agentSettings,
      activeAgentKeys,
      limitedSelectedAgents,
      selectedScene,
      maxAgentTurns,
      maxUserGap,
      mode: existingMode,
    };
    setConversations((prev) => prev.map((c) => c.id === currentConvId ? { ...c, settings: s } : c));
  }, [currentConvId, currentConv?.settings?.mode, experimentMode, agentNames, agentBackendNames, agentSettings, activeAgentKeys, limitedSelectedAgents, selectedScene, maxAgentTurns, maxUserGap]);

  const loadConvSettings = useCallback((conv: Conversation | null) => {
    const s = getConvSettings(conv);
    setAgentNames({ ...DEFAULT_AGENT_NAMES, ...s.agentNames });
    setAgentBackendNames({ ...DEFAULT_AGENT_NAMES, ...(s.agentBackendNames || {}) });
    const mergedSettings = cloneAgentSettings(s.agentSettings);
    setAgentSettings(mergedSettings);
    const keys = normalizeActiveKeys(s.activeAgentKeys, s.mode);
    setActiveAgentKeys(keys);
    agentNamesRef.current = { ...DEFAULT_AGENT_NAMES, ...s.agentNames };
    agentSettingsRef.current = cloneAgentSettings(mergedSettings);
    activeAgentKeysRef.current = keys;
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
  }, [agentNames, agentBackendNames, agentSettings, activeAgentKeys, limitedSelectedAgents, selectedScene, maxAgentTurns, maxUserGap]);

  const handleNewChat = () => {
    setCurrentConvId(null);
    loadConvSettings(null);
    setActiveAgentKeys([...DEFAULT_ACTIVE_AGENT_KEYS]);
    activeAgentKeysRef.current = [...DEFAULT_ACTIVE_AGENT_KEYS];
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
    if (conv?.roomId && lastPhaseByRoomRef.current[conv.roomId] == null) {
      lastPhaseByRoomRef.current[conv.roomId] = "Exploration";
    }
    // Past rooms restored from DB often have empty messages — pull history
    if (conv?.roomId && (!conv.messages || conv.messages.length === 0)) {
      void (async () => {
        try {
          const res = await authFetch(`/history/${conv.roomId}`);
          if (!res.ok) return;
          const data = await res.json();
          const hist = data.history || [];
          const choices: Array<{ choice_group_id?: string; option_id?: string }> = data.choices || [];
          const chosenByGroup = new Map(
            choices
              .filter((c) => c.choice_group_id && c.option_id)
              .map((c) => [String(c.choice_group_id), String(c.option_id)]),
          );
          const messages: Message[] = hist.map((
            h: { id?: string; character: string; txt: string; time?: string; options?: ChatOptionChip[]; knowledge?: KnowledgeReference },
            i: number,
          ) => {
            const ts = historyTimestamp(h.time, i, hist.length);
            const mid = h.id || `h-${i}`;
            if (h.character === "user") {
              return { id: mid, role: "user" as const, content: h.txt, timestamp: ts };
            }
            if (h.character === "system") {
              return { id: mid, role: "system" as const, content: h.txt, timestamp: ts };
            }
            const agentKey = (BACKEND_NAME_TO_KEY[h.character] ?? "A") as AgentKey;
            const opts = Array.isArray(h.options) && h.options.length >= 2
              ? h.options.map((o) => ({ id: String(o.id), label: String(o.label) }))
              : undefined;
            return {
              id: mid,
              role: "agent" as const,
              agentKey,
              content: h.txt,
              timestamp: ts,
              options: opts,
              chosenOptionId: opts ? (chosenByGroup.get(mid) || null) : null,
              knowledge: h.knowledge?.id && h.knowledge?.tag ? h.knowledge : undefined,
            };
          });
          setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, messages } : c)));
          if (data.phase) setCurrentPhase(data.phase);
          lastPhaseByRoomRef.current[conv.roomId] = data.phase || lastPhaseByRoomRef.current[conv.roomId] || "Exploration";
          const markers = phaseMarkersFromApi(data.phase_changes);
          if (markers.length > 0) {
            setPhaseMarkersByRoom((prev) => ({ ...prev, [conv.roomId]: markers }));
          }
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
    clearIntakeDraft(webUserId);
    await logoutRequest();
    navigate("/");
  };
  // --- @-mention picker -------------------------------------------------
  // Typing "@" opens the roster; picking an agent completes the handle. The
  // composer then states who will reply, so a mistyped handle can no longer
  // fail silently (the backend hard-routes only names it recognises).
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionHighlight, setMentionHighlight] = useState(0);

  const mentionCandidates = useMemo(() => {
    if (mentionQuery === null) return [];
    const q = mentionQuery.toLowerCase();
    return activeAgentKeys
      .map((k) => ({ key: k, name: agentNames[k] || `Chatbot${k}` }))
      .filter((a) => !q || a.name.toLowerCase().startsWith(q) || a.key.toLowerCase() === q);
  }, [mentionQuery, activeAgentKeys, agentNames]);

  /** Agents the current draft would summon, in the backend's own order. */
  const draftMentions = useMemo(() => {
    const byAlias = new Map<string, AgentKey>();
    activeAgentKeys.forEach((k) => {
      byAlias.set(k.toLowerCase(), k);
      byAlias.set((agentNames[k] || `Chatbot${k}`).toLowerCase(), k);
    });
    const out: AgentKey[] = [];
    // Mirrors backend _MENTION_RE: an @ only counts at a boundary.
    const re = /(?:^|[\s(（[【,，。;；:：!！?？'"“”])@(\w+)/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(inputValue)) !== null) {
      const key = byAlias.get(m[1].toLowerCase());
      if (key && !out.includes(key)) out.push(key);
      if (out.length >= 4) break; // backend MAX_MENTIONS_PER_MESSAGE
    }
    return out;
  }, [inputValue, activeAgentKeys, agentNames]);

  const syncMentionQuery = useCallback((el: HTMLTextAreaElement) => {
    const upto = el.value.slice(0, el.selectionStart ?? el.value.length);
    const m = /(?:^|[\s(（[【])@(\w*)$/.exec(upto);
    setMentionQuery(m ? m[1] : null);
    setMentionHighlight(0);
  }, []);

  const applyMention = useCallback(
    (name: string) => {
      const el = inputRef.current;
      if (!el) return;
      const caret = el.selectionStart ?? inputValue.length;
      const head = inputValue.slice(0, caret);
      const replaced = head.replace(/@(\w*)$/, `@${name} `);
      const next = replaced + inputValue.slice(caret);
      setInputValue(next);
      setMentionQuery(null);
      requestAnimationFrame(() => {
        el.focus();
        const pos = replaced.length;
        el.setSelectionRange(pos, pos);
      });
    },
    [inputValue],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionQuery !== null && mentionCandidates.length > 0) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setMentionHighlight((i) => {
          const n = mentionCandidates.length;
          return (i + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
        });
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        applyMention(mentionCandidates[mentionHighlight].name);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMentionQuery(null);
        return;
      }
    }
    if (e.key === "Enter" && (e.metaKey || e.altKey)) { e.preventDefault(); handleSend(); }
  };
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
      if (prev >= welcomeTutorialSteps.length - 1) {
        return null;
      }
      return prev + 1;
    });
  }, [shouldGuideThroughCustomizer, welcomeTutorialSteps.length]);

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
        ? welcomeTutorialSteps[welcomeTutorialStep].body
        : "";
  const guideGradientPalette = DEFAULT_GUIDE_GRADIENT;

  return (
    <>
    <div className="h-screen bg-white flex overflow-hidden">
      <AnimatePresence>
        {showCustomizer && (
          <CustomizerModal
            agentNames={agentNames}
            agentSettings={agentSettings}
            experimentMode={currentConv?.settings?.mode ?? experimentMode}
            agentKeys={
              (currentConv?.settings?.mode ?? experimentMode) === "single"
                ? ["A"]
                : activeAgentKeys
            }
            scenarioId={selectedScene?.id || currentConv?.settings?.selectedScene?.id || null}
            uiLang={uiLang}
            onSave={(names, settings) => {
              const mode = currentConv?.settings?.mode ?? experimentMode;
              // Prefer live activeAgentKeys (and ref) — conv.settings can lag one paint behind mid-session add/remove.
              const roster = mode === "single"
                ? (["A"] as AgentKey[])
                : (activeAgentKeysRef.current.length ? activeAgentKeysRef.current : activeAgentKeys);
              // Was a second, independent POST to /log-param-change with its own
              // mode === "full" gate, duplicating postParamChanges. One writer now.
              if (currentConv?.roomId) {
                const changes: Array<{ type: string; agent: string; before: string | null; after: string | null }> = [];
                roster.forEach((k) => {
                  const agent = backendLabelForKey(k);
                  if (names[k] !== agentNames[k]) changes.push({ type: "agent_name", agent, before: agentNames[k] ?? null, after: names[k] ?? null });
                  if (settings[k]?.accentColor !== agentSettings[k]?.accentColor) changes.push({ type: "accent_color", agent, before: agentSettings[k]?.accentColor ?? null, after: settings[k]?.accentColor ?? null });
                  if (settings[k]?.emotionOn !== agentSettings[k]?.emotionOn || settings[k]?.emotionTag !== agentSettings[k]?.emotionTag) changes.push({ type: "emotion", agent, before: agentSettings[k]?.emotionTag ?? null, after: settings[k]?.emotionTag ?? null });
                  if (settings[k]?.decisionBlock !== agentSettings[k]?.decisionBlock) changes.push({ type: "decision", agent, before: agentSettings[k]?.decisionBlock ?? null, after: settings[k]?.decisionBlock ?? null });
                  if ((settings[k]?.stance ?? null) !== (agentSettings[k]?.stance ?? null)) changes.push({ type: "stance", agent, before: agentSettings[k]?.stance ?? null, after: settings[k]?.stance ?? null });
                });
                postParamChanges(changes);
              }
              setAgentNames(names);
              setAgentSettings(settings);
              agentNamesRef.current = { ...names };
              agentSettingsRef.current = cloneAgentSettings(settings);
              void syncRosterToBackend(roster, names, settings);
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
        {(showSceneSelector || !!pendingIntakeScene || (showProfileModal && !!pendingProfileScene)) && (
          <motion.div
            key="scene-flow-overlay"
            className="fixed inset-0 bg-black/30 z-[60] flex items-center justify-center p-6"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => {
              if (showProfileModal && pendingProfileScene) {
                if (userProfile) {
                  setShowProfileModal(false);
                  setPendingProfileScene(null);
                  setProfileHandoff(false);
                }
                return;
              }
              if (pendingIntakeScene) setPendingIntakeScene(null);
              else setShowSceneSelector(false);
            }}
          >
            <AnimatePresence mode="wait" initial={false}>
              {showProfileModal && pendingProfileScene ? (
                <ProfileModal
                  key={`profile-${pendingProfileScene.id}`}
                  userId={webUserId}
                  scenarioType={pendingProfileScene.id}
                  lang={uiLang}
                  dismissible={!!userProfile}
                  instantExit={profileHandoff}
                  onClose={userProfile ? () => {
                    setShowProfileModal(false);
                    setPendingProfileScene(null);
                    setProfileHandoff(false);
                  } : undefined}
                  onConfirm={(profile) => {
                    const scene = pendingProfileScene;
                    setUserProfile(profile);
                    setProfileHandoff(true);
                    setPendingIntakeScene(scene);
                    setShowProfileModal(false);
                    setPendingProfileScene(null);
                  }}
                />
              ) : pendingIntakeScene ? (
                <IntakeModal
                  key={`intake-${pendingIntakeScene.id}`}
                  scene={pendingIntakeScene}
                  lang={uiLang}
                  sessionCount={sessionCountBefore}
                  lastIntake={intakePrefill}
                  onClose={() => setPendingIntakeScene(null)}
                  onConfirm={(payload) => {
                    setSelectedScene(pendingIntakeScene);
                    setAgora2Intake(payload);
                    // Until the first message creates the room, these answers exist
                    // nowhere but this tab. Write them down before anything can eat them.
                    saveIntakeDraft(webUserId, { ...payload, profile: userProfile });
                    setSessionIndex(sessionCountBefore + 1);
                    setPendingIntakeScene(null);
                    setShowSceneSelector(false);
                    setProfileHandoff(false);
                  }}
                />
              ) : (
                <SceneSelectorModal
                  key="scene-selector"
                  scenes={scenes}
                  selectedScene={selectedScene}
                  lang={uiLang}
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
            lang={uiLang}
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
            <span className="text-[12px]" style={uiFont}>{t(uiLang, "chat.newChat")}</span>
          </button>
        </div>
        {!currentConvId && (
          <div className="px-3 py-3 border-b border-black/8 flex-shrink-0">
            <p className={`text-[10px] text-[var(--app-muted-text)] mb-2 ${labelCaseClass(uiLang)}`} style={uiFont}>{t(uiLang, "chat.mode")}</p>
            <div className="flex flex-col gap-1.5">
              {(["full", "limited", "single"] as const)
                .filter((m) => m !== "limited" || isAdmin)
                .map((m) => {
                const locked = !allowedModes.includes(m);
                return (
                <button
                  key={m}
                  disabled={locked}
                  aria-disabled={locked}
                  title={locked ? t(uiLang, "chat.modeLocked") : undefined}
                  onClick={() => {
                    if (locked) return;
                    setExperimentMode(m);
                    if (m === "single") {
                      setActiveAgentKeys(["A"]);
                      activeAgentKeysRef.current = ["A"];
                    } else if (m === "full" && (experimentMode === "single" || activeAgentKeys.length < MIN_ROSTER_AGENTS)) {
                      setActiveAgentKeys([...DEFAULT_ACTIVE_AGENT_KEYS]);
                      activeAgentKeysRef.current = [...DEFAULT_ACTIVE_AGENT_KEYS];
                    }
                  }}
                  className={`w-full text-left px-3 py-2 rounded-[6px] text-[11px] transition-colors border ${
                    locked
                      ? "border-black/8 bg-black/[0.03] text-black/35 opacity-60 cursor-not-allowed"
                      : experimentMode === m ? "bg-black text-white border-black" : "border-black/10 hover:bg-black/5"
                  }`}
                  style={uiFont}
                >
                  {modeLabelFor(m)}
                </button>
                );
              })}
            </div>
          </div>
        )}
        <div className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-2 min-h-0 min-w-0">
          {conversations.length === 0 ? (
            <p className="text-center text-[var(--app-muted-text)] text-[11px] mt-8" style={uiFont}>{t(uiLang, "chat.noConversations")}</p>
          ) : (
            <div className="flex flex-col gap-1">
              {conversations.map((conv) => <ConvItem key={conv.id} conv={conv} isActive={conv.id === currentConvId} onSelectConv={handleSelectConv} lang={uiLang} />)}
            </div>
          )}
        </div>
        <div className="relative flex-shrink-0">
          <AnimatePresence>
            {userMenuOpen && (
              <UserMenu
                nickname={nickname}
                isAdmin={isAdmin}
                lang={uiLang}
                onAccount={() => {
                  const s = selectedScene && isAgora2SceneId(selectedScene.id) ? selectedScene : null;
                  if (s) {
                    setProfileHandoff(false);
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
            {!backendOnline && <span className="text-[9px] text-amber-400 flex-shrink-0" style={uiFont}>{t(uiLang, "chat.offline")}</span>}
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
                    <p className={`text-[11px] text-black ${labelCaseClass(uiLang)}`} style={uiFont}>
                      {welcomeTutorialStep + 1}/{welcomeTutorialSteps.length} · {welcomeTutorialSteps[welcomeTutorialStep].title}
                    </p>
                    <button
                      type="button"
                      onClick={dismissWelcomeGuide}
                      className="text-[10px] text-[var(--app-muted-text)] hover:text-black transition-colors"
                      style={uiFont}
                    >
                      {t(uiLang, "tutorial.skip")}
                    </button>
                  </div>
                  <p className="text-[12px] text-black/75 leading-relaxed" style={uiFont}>
                    {currentWelcomeTutorialBody}
                  </p>
                  <div className="flex items-center justify-between mt-4">
                    <button
                      type="button"
                      onClick={rewindWelcomeTutorial}
                      disabled={welcomeTutorialStep === 0}
                      className="px-3 py-2 rounded-[10px] border border-black/10 text-[11px] text-[var(--app-muted-text)] hover:text-black hover:border-black/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                      style={uiFont}
                    >
                      {t(uiLang, "tutorial.back")}
                    </button>
                    <button
                      type="button"
                      onClick={welcomeTutorialStep === 1 && shouldGuideThroughCustomizer ? () => openCustomizerTutorial("A") : advanceWelcomeTutorial}
                      className="px-3 py-2 rounded-[10px] bg-black text-white text-[11px] hover:bg-neutral-800 transition-colors"
                      style={uiFont}
                    >
                      {welcomeTutorialStep === 1 && shouldGuideThroughCustomizer
                        ? t(uiLang, "tutorial.open")
                        : welcomeTutorialStep === welcomeTutorialSteps.length - 1
                          ? t(uiLang, "tutorial.done")
                          : t(uiLang, "tutorial.next")}
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
              <span className="text-[13px] text-[var(--app-muted-text)]" style={uiFont}>{t(uiLang, "chat.newConversation")}</span>
            )}
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            {currentConv && (
              <div className="flex items-center gap-1.5 pr-3 border-r border-black/10" style={uiFont}>
                <span className={`text-[10px] text-[var(--app-muted-text)] ${labelCaseClass(uiLang)}`}>{t(uiLang, "chat.turnN", { n: currentConv.messages?.filter((m) => m.role === "user").length ?? 0 })}</span>
                {showPhaseIndicator && currentPhase && (
                  <span className="text-[10px] text-[var(--app-muted-text)]">{t(uiLang, "chat.phase", { phase: phaseLabel(uiLang, currentPhase) })}</span>
                )}
              </div>
            )}
            {currentConv && mapAvailable && decisionNaviNodes.length > 0 && (
              <div className="pr-3 border-r border-black/10">
                <DecisionNavi
                  nodes={decisionNaviNodes}
                  count={decisionMap?.issues?.length || decisionNaviNodes.length}
                  lang={uiLang}
                  open={decisionMapOpen}
                  onOpen={handleOpenDecisionMap}
                />
              </div>
            )}
            {(() => {
              const headerMode = currentConv?.settings?.mode ?? experimentMode;
              const rosterKeys: AgentKey[] =
                headerMode === "single" ? (["A"] as AgentKey[]) : activeAgentKeys;
              const canEditRoster = !!currentConv && headerMode === "full";
              return (
                <div className="relative flex items-center">
                  <button
                    ref={agentsBtnRef}
                    type="button"
                    onClick={() => setAgentsOpen((v) => !v)}
                    className="flex items-center gap-1.5 h-4 hover:opacity-80 transition-opacity"
                    aria-expanded={agentsOpen}
                    title={t(uiLang, "chat.agents")}
                  >
                    <span className="flex items-center -space-x-0.5">
                      {rosterKeys.slice(0, 3).map((key) => (
                        <span
                          key={key}
                          className="w-[7px] h-[7px] rounded-[1.5px] ring-1 ring-white"
                          style={{
                            backgroundColor:
                              agentSettings[key]?.accentColor || DEFAULT_AGENT_COLORS[key],
                          }}
                        />
                      ))}
                    </span>
                    <span
                      className={`text-[10px] tracking-widest text-black ${labelCaseClass(uiLang)}`}
                      style={monoFont}
                    >
                      {t(uiLang, "chat.agents")}
                    </span>
                    <svg
                      width="8"
                      height="8"
                      viewBox="0 0 12 12"
                      fill="none"
                      aria-hidden
                      className={`opacity-40 transition-transform ${agentsOpen ? "rotate-180" : ""}`}
                    >
                      <path d="M2 4L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                  <AnimatePresence>
                    {agentsOpen && (
                      <motion.div
                        ref={agentsPanelRef}
                        initial={{ opacity: 0, y: -4, scale: 0.98 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: -4, scale: 0.98 }}
                        transition={{ duration: 0.15, ease: [0.22, 1, 0.36, 1] }}
                        className="absolute top-[calc(100%+8px)] right-0 z-50 min-w-[180px] rounded-[10px] border border-black/10 bg-white shadow-[0_8px_28px_rgba(0,0,0,0.1)] py-1.5 px-1.5"
                      >
                        <ul className="flex flex-col gap-0.5">
                          {rosterKeys.map((key) => (
                            <li
                              key={key}
                              className="group/chip flex items-center gap-2 px-2 py-1.5 rounded-[6px] hover:bg-black/[0.03]"
                            >
                              <span
                                className="w-[7px] h-[7px] rounded-[1.5px] flex-shrink-0"
                                style={{
                                  backgroundColor:
                                    agentSettings[key]?.accentColor || DEFAULT_AGENT_COLORS[key],
                                }}
                              />
                              <span
                                className="flex-1 text-[11px] tracking-widest text-black truncate"
                                style={monoFont}
                                title={agentNames[key]}
                              >
                                {agentNames[key]}
                              </span>
                              <button
                                type="button"
                                aria-label={t(uiLang, "settings.customizeAgent")}
                                title={t(uiLang, "settings.customizeAgent")}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setCustomizerInitialAgent(key);
                                  setShowCustomizer(true);
                                  setAgentsOpen(false);
                                }}
                                className="w-4 h-4 rounded-full flex items-center justify-center opacity-0 group-hover/chip:opacity-100 hover:bg-black/8 text-black/40 hover:text-black/70 transition-opacity"
                              >
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                                  <circle cx="12" cy="12" r="3" />
                                  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                                </svg>
                              </button>
                              {canEditRoster && activeAgentKeys.length > MIN_ROSTER_AGENTS && (
                                <button
                                  type="button"
                                  aria-label={t(uiLang, "chat.removeAgent", { name: agentNames[key] })}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    removeAgent(key);
                                  }}
                                  className="w-4 h-4 rounded-full flex items-center justify-center opacity-0 group-hover/chip:opacity-100 hover:bg-black/8 text-black/40 hover:text-black/70 transition-opacity"
                                >
                                  <svg width="8" height="8" viewBox="0 0 12 12" fill="none" aria-hidden>
                                    <path d="M2 2L10 10M10 2L2 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                                  </svg>
                                </button>
                              )}
                            </li>
                          ))}
                        </ul>
                        {canEditRoster && activeAgentKeys.length < MAX_ROSTER_AGENTS && (
                          <button
                            type="button"
                            onClick={() => addAgent()}
                            className="mt-1 w-full flex items-center gap-2 px-2 py-1.5 rounded-[6px] text-[11px] text-black/45 hover:text-black/70 hover:bg-black/[0.03] transition-colors border border-dashed border-black/15"
                            style={monoFont}
                          >
                            <span className="w-4 h-4 flex items-center justify-center">
                              <svg width="8" height="8" viewBox="0 0 16 16" fill="none" aria-hidden>
                                <path d="M8 1V15M1 8H15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                              </svg>
                            </span>
                            {t(uiLang, "chat.addAgent")}
                          </button>
                        )}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            })()}
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
              style={uiFont}
            >
              <span>
                {t(uiLang, "layer.hint")}
              </span>
              <button
                type="button"
                onClick={clearChatAnnotations}
                className="shrink-0 rounded-md border border-black/15 bg-black/[0.04] px-2.5 py-1 text-[11px] hover:bg-black/[0.08] transition-colors"
                style={uiFont}
              >
                {t(uiLang, "layer.clearAll")}
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
                  <p className="text-center text-[11px] text-amber-500 w-full leading-relaxed border border-amber-200 bg-amber-50 px-3 py-2 rounded-[8px]" style={uiFont}>
                    {t(uiLang, "welcome.backendOffline")}
                  </p>
                )}
              </div>
              <div
                ref={welcomeAgentsRef}
                className="relative isolate order-2 w-full transition-all duration-200"
              >
                <AnimatedGuideFrame active={isWelcomeStepActive(1)} palette={guideGradientPalette} rounded="rounded-[12px]" fillColor={GUIDE_FRAME_FILL} pulse />
                <div className="relative z-10 px-2 py-2">
                  <p className={`text-[10px] text-[var(--app-muted-text)] mb-3 text-center ${labelCaseClass(uiLang)}`} style={uiFont}>{t(uiLang, "welcome.agents")}</p>
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
                      <p className="text-[10px] text-center text-[var(--app-muted-text)] mt-2" style={uiFont}>{t(uiLang, "welcome.selectedN", { n: limitedSelectedAgents.length })}</p>
                    </>
                  ) : (
                    <motion.div
                      key={`agent-grid-${experimentMode}`}
                      className={`grid gap-3 w-full items-stretch ${experimentMode === "single" ? "grid-cols-1" : "grid-cols-2"}`}
                      initial="hidden"
                      animate="visible"
                      variants={{ visible: { transition: { staggerChildren: 0.07, delayChildren: 0.1 } } }}
                    >
                      {(experimentMode === "single" ? (["A"] as AgentKey[]) : activeAgentKeys).map((key) => (
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
                          className="relative h-full min-h-[97px] border border-black/8 rounded-[10px] px-3 py-3 text-left transition-colors group"
                        >
                          {experimentMode !== "single" && activeAgentKeys.length > MIN_ROSTER_AGENTS && (
                            <span
                              role="button"
                              tabIndex={0}
                              aria-label={t(uiLang, "chat.removeAgent", { name: agentNames[key] })}
                              onClick={(e) => {
                                e.stopPropagation();
                                removeAgent(key);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  removeAgent(key);
                                }
                              }}
                              className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-black/8 text-black/40 hover:text-black/70 transition-opacity"
                            >
                              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden>
                                <path d="M2 2L10 10M10 2L2 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                              </svg>
                            </span>
                          )}
                          <div className="flex items-center gap-1.5 mb-1 pr-4">
                            <div className="w-[6px] h-[6px] rounded-[1.2px] flex-shrink-0" style={{ backgroundColor: agentSettings[key as AgentKey]?.accentColor || DEFAULT_AGENT_COLORS[key as AgentKey] }} />
                            <span className="text-[10px] tracking-widest text-black" style={monoFont}>{agentNames[key as AgentKey]}</span>
                          </div>
                          <p className="text-[10px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={uiFont}>{getEmotionDecisionSummary(agentSettings[key as AgentKey]?.emotionTag ?? null, agentSettings[key as AgentKey]?.decisionBlock ?? "Rational", uiLang)}</p>
                          <p className="text-[9px] text-[var(--app-muted-text)] mt-2 group-hover:text-black/70 transition-colors" style={uiFont}>{t(uiLang, "welcome.clickCustomize")}</p>
                        </motion.button>
                      ))}
                      {experimentMode !== "single" && activeAgentKeys.length < MAX_ROSTER_AGENTS && (
                        <motion.button
                          variants={{ hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0, transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] } } }}
                          whileHover={{ y: -2 }}
                          whileTap={{ scale: 0.98 }}
                          onClick={() => addAgent()}
                          className="h-full min-h-[97px] self-stretch border border-dashed border-black/15 rounded-[10px] px-3 py-3 flex flex-col items-center justify-center gap-1 hover:border-black/40 hover:bg-black/2 transition-colors group"
                        >
                          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="opacity-20 group-hover:opacity-50 transition-opacity">
                            <path d="M8 1V15M1 8H15" stroke="black" strokeWidth="1.5" strokeLinecap="round"/>
                          </svg>
                          <span className="text-[9px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={uiFont}>{t(uiLang, "welcome.addAgent")}</span>
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
                  <p className={`text-[10px] text-[var(--app-muted-text)] mb-3 text-center ${labelCaseClass(uiLang)}`} style={uiFont}>{t(uiLang, "welcome.scene")}</p>
                  <motion.button
                    whileHover={{ y: -2, boxShadow: "0 4px 14px rgba(0,0,0,0.07)" }}
                    whileTap={{ scale: 0.98 }}
                    onClick={openSceneSelector}
                    className="w-full text-left px-4 py-3 border border-black/8 rounded-[10px] transition-colors group"
                  >
                    <div className="flex items-center gap-1.5 mb-1">
                      <div className="w-[6px] h-[6px] rounded-[1.2px] flex-shrink-0" style={{ backgroundColor: selectedScene?.color || "#000000" }} />
                      <span className="text-[10px] tracking-widest text-black" style={uiFont}>{selectedScene?.title || t(uiLang, "welcome.selectScene")}</span>
                      {sessionIndex != null && (
                        <span className="text-[9px] text-black/50 ml-1" style={uiFont}>{t(uiLang, "welcome.sessionN", { n: sessionIndex })}</span>
                      )}
                      <span className="text-[9px] text-black/40 ml-auto" style={uiFont}>{uiLang === "zh" ? "中文" : "EN"}</span>
                    </div>
                    <p className="text-[10px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={uiFont}>{selectedScene?.description || t(uiLang, "welcome.chooseSceneHint")}</p>
                    <p className="text-[9px] text-[var(--app-muted-text)] mt-2 group-hover:text-black/70 transition-colors" style={uiFont}>
                      {selectedScene
                        ? (agora2Intake ? t(uiLang, "welcome.intakeReady") : t(uiLang, "welcome.clickChange"))
                        : t(uiLang, "welcome.clickChoose")}
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
                  <p className={`text-[10px] text-[var(--app-muted-text)] mb-3 text-center ${labelCaseClass(uiLang)}`} style={uiFont}>{t(uiLang, "welcome.prompts")}</p>
                  <div className="flex flex-col gap-2">
                    {suggestedPrompts.map((prompt, i) => (
                      <motion.button
                        key={`${selectedScene?.id || "default"}-${i}`}
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
                  const isHighlighted =
                    highlightedMessageId === msg.id || highlightedMessageIds.includes(msg.id);
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
                        highlighted={isHighlighted}
                        highlightToken={highlightToken}
                      />
                    );
                  }
                  if (msg.role === "system") {
                    return (
                      <SystemMessage
                        key={msg.id}
                        message={msg}
                        highlighted={isHighlighted}
                        highlightToken={highlightToken}
                      />
                    );
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
                      uiLang={uiLang}
                      highlighted={isHighlighted}
                      highlightToken={highlightToken}
                      onChooseOption={handleChooseOption}
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
                  label={typingKeys[0] === "pending"
                    ? t(uiLang, "chat.thinking")
                    : agentNames[typingKeys[0]]}
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
              {/* Who this draft will summon — stated before sending, so a
                  handle the backend does not recognise is visibly absent. */}
              {currentConv && (draftMentions.length > 0 || mentionQuery !== null) && (
                <div className="relative z-10 flex items-center gap-1.5 flex-wrap mb-1.5 px-1" style={uiFont}>
                  <span className={`text-[10px] text-[var(--app-muted-text)] ${labelCaseClass(uiLang)}`}>
                    {t(uiLang, "chat.willReply")}
                  </span>
                  {draftMentions.length > 0 ? (
                    draftMentions.map((k) => (
                      <span
                        key={k}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-[5px] text-[10px] text-black bg-black/[0.06]"
                      >
                        <span
                          className="w-1.5 h-1.5 rounded-[1px]"
                          style={{ backgroundColor: agentSettings[k]?.accentColor || DEFAULT_AGENT_COLORS[k] }}
                        />
                        {agentNames[k]}
                      </span>
                    ))
                  ) : (
                    <span className="text-[10px] text-[var(--app-muted-text)]">
                      {t(uiLang, "chat.willReplyAuto")}
                    </span>
                  )}
                </div>
              )}

              {/* @-picker */}
              {mentionQuery !== null && mentionCandidates.length > 0 && (
                <div
                  className="absolute bottom-[calc(100%+8px)] left-[56px] z-30 min-w-[190px] rounded-[10px] border border-white/10 bg-black shadow-[0_8px_28px_rgba(0,0,0,0.32)] py-1"
                  style={uiFont}
                >
                  {mentionCandidates.map((a, i) => (
                    <button
                      key={a.key}
                      type="button"
                      onMouseEnter={() => setMentionHighlight(i)}
                      onMouseDown={(e) => { e.preventDefault(); applyMention(a.name); }}
                      className={`w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-[11px] ${
                        i === mentionHighlight ? "bg-white/[0.16]" : "hover:bg-white/[0.08]"
                      }`}
                    >
                      {/* The default accent is pure black, which would vanish on
                          this panel — the inset ring keeps the swatch readable. */}
                      <span
                        className="w-2 h-2 rounded-[2px] flex-shrink-0"
                        style={{
                          backgroundColor: agentSettings[a.key]?.accentColor || DEFAULT_AGENT_COLORS[a.key],
                          boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.55)",
                        }}
                      />
                      <span className="text-white">{a.name}</span>
                    </button>
                  ))}
                </div>
              )}

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
                  <AttachMenu open={attachMenuOpen} onClose={() => setAttachMenuOpen(false)} anchorRef={attachBtnRef} lang={uiLang} />
                </AnimatePresence>
              </div>
              <div className="flex-1 min-h-[48px] bg-black rounded-[12px] flex items-center px-4 py-3">
                <textarea ref={inputRef} value={inputValue}
                  onChange={(e) => {
                    // Counts only -- never the text, never per-key timestamps.
                    const len = e.target.value.length;
                    if (firstKeystrokeAtRef.current === null && len > 0) {
                      firstKeystrokeAtRef.current = Date.now();
                      emit("composer_first_keystroke", {
                        reply_latency_ms: lastBotMessageAtRef.current
                          ? Date.now() - lastBotMessageAtRef.current
                          : null,
                      });
                    }
                    keystrokesRef.current += 1;
                    if (len < lastInputLenRef.current) backspacesRef.current += 1;
                    lastInputLenRef.current = len;
                    setInputValue(e.target.value);
                    syncMentionQuery(e.currentTarget);
                  }}
                  onClick={(e) => syncMentionQuery(e.currentTarget)}
                  onBlur={() => setMentionQuery(null)}
                  onKeyDown={handleKeyDown}
                  placeholder={t(uiLang, "chat.inputPh")}
                  rows={1} disabled={isLoading}
                  className="flex-1 min-h-[24px] bg-transparent resize-none outline-none text-white placeholder-[#828282] leading-relaxed disabled:opacity-50"
                  style={{ ...uiFont, fontSize: "13px", maxHeight: "120px" }}
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
                    showSummary={(currentConv?.settings?.mode ?? experimentMode) !== "single"}
                    showPastMemory={!!(selectedScene || currentConv?.settings?.selectedScene) && isAgora2SceneId((selectedScene || currentConv?.settings?.selectedScene)!.id)}
                    showFontColor={showFontColorInSettings} onToggleFontColor={() => setShowFontColorInSettings((v) => !v)}
                    lang={uiLang}
                    onLangChange={setLang} />
                </AnimatePresence>
              </div>
              </div>
            </div>
            <p className="text-center text-[10px] text-[var(--app-muted-text)] mt-2" style={uiFont}>{t(uiLang, "chat.inputHint")}</p>
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
          onGenerate={() => void fetchSessionSummary()}
          lang={uiLang}
        />
      )}
    </AnimatePresence>
    <DecisionMapPanel
      open={decisionMapOpen}
      onClose={() => {
        const dwell = mapDwellRef.current.close();
        if (dwell) emit("map_closed", dwell);
        setDecisionMapOpen(false);
        setDecisionMapDocked(false);
      }}
      docked={decisionMapDocked}
      onUndock={() => {
        mapDwellRef.current.undock();
        emit("map_undocked", {});
        setDecisionMapDocked(false);
      }}
      onEvent={emit}
      data={decisionMap}
      loading={decisionMapLoading}
      error={decisionMapError}
      lang={uiLang}
      selectedTopicId={selectedMapTopicId}
      onSelectTopic={setSelectedMapTopicId}
      onJumpIndexes={handleMapJumpIndexes}
      onRefresh={() => void fetchDecisionMap({ extract: true })}
      onExtract={() => void handleExtractDecisionMap()}
      extracting={decisionMapExtracting}
      userName={auth?.user_id || undefined}
    />
  </>
  );
}
