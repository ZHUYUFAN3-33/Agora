import React, { useState, useRef, useEffect, useCallback, useLayoutEffect } from "react";
import { useNavigate } from "react-router";
import { motion, AnimatePresence } from "motion/react";
import { createPortal } from "react-dom";
import { AgoraLogo, AgoraLogoFull } from "../components/AgoraLogo";
import { CustomDropdown } from "../components/ui/CustomDropdown";
import { AppearanceModal } from "../components/AppearanceModal";
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
  SCENE_SUGGESTED_PROMPTS,
  EMOTION_EMOJI,
  EMOTION_COLORS,
  EMOTION_EXAMPLES,
  EMOTION_IMAGES,
  defaultSetting,
} from "../data/agents";

const monoFont = { fontFamily: "'Share Tech Mono', monospace" };
const condensedFont = { fontFamily: "'Barlow Condensed', sans-serif" };
const LIMITED_POOL_ACCENT_MAP: Record<AgentPoolKey, string> = {
  A: "#005f73",
  B: "#e9d8a6",
  C: "#ae2012",
  D: "#94d2bd",
  E: "#ee9b00",
  F: "#bb3e03",
};
const EMOTION_EMOJI_VARIANTS: Record<string, string[]> = {
  joy: ["😊", "😄", "😌", "🙂"],
  fear: ["😟", "😰", "😬", "🫣"],
  anger: ["😠", "😤", "🙄", "😒"],
  sadness: ["😔", "😞", "🥲", "😢"],
  surprise: ["😮", "😲", "🤯", "🫢"],
  disgust: ["😬", "🙃", "😑", "🤢"],
};

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

// ─── Types ────────────────────────────────────────────────────────────────────

interface Message {
  id: string;
  role: "user" | "agent";
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
): string {
  const tag = (emotionTag || "").toLowerCase();
  const variants = EMOTION_EMOJI_VARIANTS[tag];
  if (!variants || variants.length === 0 || repeatIndex < 2) return content;
  const firstMatch = content.match(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/u);
  if (!firstMatch || typeof firstMatch.index !== "number") return content;
  const currentEmoji = firstMatch[0];
  const variantPool = variants.includes(currentEmoji) ? variants : [currentEmoji, ...variants];
  const agentOffset = agentKey ? AGENT_KEYS.indexOf(agentKey) + 1 : 0;
  const nextEmoji = variantPool[(repeatIndex + agentOffset) % variantPool.length];
  if (nextEmoji === currentEmoji) return content;
  return `${content.slice(0, firstMatch.index)}${nextEmoji}${content.slice(firstMatch.index + currentEmoji.length)}`;
}

function normalizeLimitedSelection(keys: AgentPoolKey[]): AgentPoolKey[] {
  const valid = keys.filter((k): k is AgentPoolKey => LIMITED_AGENT_POOL.some((p) => p.key === k));
  const unique = Array.from(new Set(valid));
  if (unique.length >= 3) return unique.slice(0, 3);
  const padding = LIMITED_AGENT_POOL.map((p) => p.key).filter((k) => !unique.includes(k));
  return [...unique, ...padding].slice(0, 3);
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

function TypingDots({ agentKey, agentNames }: { agentKey: AgentKey; agentNames: Record<AgentKey, string> }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      transition={{ duration: 0.22, layout: { duration: 0.26, ease: [0.22, 1, 0.36, 1] } }}
      className="flex flex-col gap-1 mb-2"
    >
      <div className="flex items-center gap-2 mb-1">
        <div className="w-[7px] h-[7px] rounded-[1.5px] flex-shrink-0 bg-black" />
        <span className="text-[11px] tracking-widest text-black" style={monoFont}>
          {agentNames[agentKey]}
        </span>
      </div>
      <div className="ml-4 flex items-center gap-1 h-8 px-4 bg-transparent border border-black/10 rounded-[10px] w-fit">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-[5px] h-[5px] bg-black rounded-full"
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.25 }}
          />
        ))}
      </div>
    </motion.div>
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
          className="relative z-30 w-[252px] rounded-[14px] border border-black/20 bg-[#fffdfa] px-3 py-3 shadow-[0_14px_36px_rgba(0,0,0,0.16)]"
        >
          <div className={`absolute left-5 h-3.5 w-3.5 rotate-45 border-black/20 bg-[#fffdfa] ${placeAbove ? "bottom-[-7px] border-b border-r" : "top-[-7px] border-l border-t"}`} />
          <div className="mb-3 px-0.5">
            <span className="text-[10px] tracking-widest text-black/85 uppercase" style={monoFont}>Emotion</span>
          </div>
          <div className="rounded-[12px] border border-black/10 bg-black/[0.02] px-3 py-3">
            <div className="mb-3">
              <div
                className="flex items-center justify-between gap-2 rounded-[10px] border px-2.5 py-2 text-[10px]"
                style={{
                  ...monoFont,
                  borderColor: emotionColor + "66",
                  background: emotionColor + "22",
                  color: emotionColor,
                }}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <EmotionIcon emotion={emotionTag} size={14} />
                  <span className="capitalize font-semibold">{emotionTag}</span>
                </div>
              </div>
            </div>
            <div className="border-t border-black/8 pt-3">
              <div className="flex flex-col gap-2">
                {([
                  { label: "Valence", field: "valence" as const, value: settings.valence },
                  { label: "Arousal", field: "arousal" as const, value: settings.arousal },
                  { label: "Control", field: "control" as const, value: settings.control },
                ] as const).map(({ label, field, value }) => (
                  <div key={field} className="flex min-w-0 items-center gap-2 rounded-[8px] px-1 py-0.5">
                    <span className="w-[54px] flex-shrink-0 text-[10px] text-black/80" style={monoFont}>{label}</span>
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
                    <span className="w-[34px] flex-shrink-0 text-right text-[10px] text-black/80" style={monoFont}>{value.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="mt-3 border-t border-black/8 pt-3">
              <div className="mb-1 text-[9px] uppercase tracking-widest text-black/55" style={monoFont}>Decision</div>
              <div className="flex items-center gap-2 px-1 py-1">
                <button
                  type="button"
                  onClick={() => cycleDecision(-1)}
                  className="flex h-7 w-7 items-center justify-center rounded-[7px] text-black/70 transition-colors hover:bg-black/[0.03] hover:text-black"
                  aria-label="Previous decision style"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M15 18l-6-6 6-6" />
                  </svg>
                </button>
                <div className="min-w-0 flex-1 text-center">
                  <div className="text-[11px] text-black" style={monoFont}>{settings.decisionBlock}</div>
                </div>
                <button
                  type="button"
                  onClick={() => cycleDecision(1)}
                  className="flex h-7 w-7 items-center justify-center rounded-[7px] text-black/70 transition-colors hover:bg-black/[0.03] hover:text-black"
                  aria-label="Next decision style"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M9 18l6-6-6-6" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
          <div className="mt-3 flex items-center justify-between gap-2 border-t border-black/10 pt-2.5">
            <button
              onClick={() => onAdjustEmotion(agentKey, {
                emotionOn: true,
                emotionTag: emotionDefaults.emotionTag,
                valence: emotionDefaults.valence,
                arousal: emotionDefaults.arousal,
                control: emotionDefaults.control,
                emotionText: "",
              }, false)}
              className="text-[10px] text-black/65 transition-colors hover:text-black"
              style={monoFont}
            >
              reset tag
            </button>
            <button
              onClick={() => onOpenAdvanced(agentKey)}
              className="rounded-[6px] border border-black/12 px-2 py-1 text-[10px] text-black transition-colors hover:border-black/25 hover:bg-black/[0.03]"
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

function AgentMessage({
  message,
  agentNames,
  agentBackendNames,
  agentSettings,
  mode,
  nickname,
  onOpenAdvancedAgent,
  onQuickEmotionAdjust,
  getPopoverSafeRect,
  compactRepeatedIntro = false,
  emojiRepeatIndex = 0,
}: {
  message: Message;
  agentNames: Record<AgentKey, string>;
  agentBackendNames: Record<AgentKey, string>;
  agentSettings?: Record<AgentKey, AgentCustomSetting>;
  mode: ExperimentMode;
  nickname?: string;
  onOpenAdvancedAgent?: (key: AgentKey) => void;
  onQuickEmotionAdjust?: (key: AgentKey, patch: Partial<AgentCustomSetting>, shouldAnalyze?: boolean) => void;
  getPopoverSafeRect?: () => DOMRect | null;
  compactRepeatedIntro?: boolean;
  emojiRepeatIndex?: number;
}) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [safeRect, setSafeRect] = useState<DOMRect | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const name = message.agentKey ? agentNames[message.agentKey] : "Agent";
  const role = message.agentKey
    ? (mode === "limited"
      ? (agentSettings?.[message.agentKey]?.roleDescription || DEFAULT_AGENT_ROLES[message.agentKey])
      : DEFAULT_AGENT_ROLES[message.agentKey])
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
    ? diversifyEmotionEmoji(compactedContent, messageEmotionTag, emojiRepeatIndex, message.agentKey)
    : compactedContent;
  const quickEmotionEnabled = !isError && mode === "full" && !!message.agentKey && !!onQuickEmotionAdjust && !!onOpenAdvancedAgent;
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
    updatePopoverPosition();
    setPopoverOpen(true);
  };

  const closePopoverSoon = () => {
    clearCloseTimer();
    closeTimerRef.current = window.setTimeout(() => setPopoverOpen(false), 120);
  };

  useEffect(() => () => clearCloseTimer(), []);
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
        <div
          className="w-[7px] h-[7px] rounded-[1.5px] flex-shrink-0"
          style={{ backgroundColor: isError ? "#ef4444" : accentColor }}
        />
        <div
          ref={triggerRef}
          className="relative"
          onMouseEnter={quickEmotionEnabled ? openPopover : undefined}
          onMouseLeave={quickEmotionEnabled ? closePopoverSoon : undefined}
        >
          <button
            className={`text-[11px] tracking-widest leading-none ${
              quickEmotionEnabled ? "cursor-default hover:underline underline-offset-2" : "cursor-default"
            }`}
            style={{ ...monoFont, color: isError ? "#ef4444" : "#000" }}
            type="button"
          >
            {name}
          </button>
          <AnimatePresence>
            {quickEmotionEnabled && popoverOpen && message.agentKey && (
              <div onMouseEnter={openPopover} onMouseLeave={closePopoverSoon}>
                <AgentEmotionPopover
                  agentKey={message.agentKey}
                  settings={currentSettings || defaultSetting(message.agentKey)}
                  anchorRect={anchorRect}
                  safeRect={safeRect}
                  onHoverStart={openPopover}
                  onHoverEnd={closePopoverSoon}
                  onAdjustEmotion={(key, patch, shouldAnalyze) => {
                    onQuickEmotionAdjust?.(key, patch, shouldAnalyze);
                  }}
                  onOpenAdvanced={(key) => {
                    setPopoverOpen(false);
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
          className="text-[13px] text-black/80 leading-relaxed whitespace-pre-wrap"
          style={{ ...monoFont, color: isError ? "#ef4444" : undefined }}
        >
          {finalContent}
        </p>
      </div>
    </motion.div>
  );
}

function UserMessage({ message, nickname }: { message: Message; nickname: string }) {
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
        <p className="text-[13px] text-white leading-relaxed whitespace-pre-wrap" style={monoFont}>
          {message.content}
        </p>
      </div>
    </motion.div>
  );
}

const MODE_LABELS: Record<ExperimentMode, string> = { full: "Full", limited: "Limited", single: "Single" };

function ConvItem({ conv, isActive, onClick }: { conv: Conversation; isActive: boolean; onClick: () => void }) {
  const mode = conv.settings?.mode ?? "full";
  const modeLabel = MODE_LABELS[mode];
  return (
    <button
      onClick={onClick}
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
}

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


// ─── Settings menu (Customize Agent, Customize Scene, Turn Cap, Reload, Export) ─

function SettingsMenu({ open, onClose, anchorRef, onCustomize, onScene, onTurn, onAppearance, onReloadHistory, onExportLog, hasRoomId, showFontColor, onToggleFontColor }: {
  open: boolean; onClose: () => void; anchorRef: React.RefObject<HTMLButtonElement | null>;
  onCustomize: () => void; onScene: () => void; onTurn: () => void; onAppearance: () => void;
  onReloadHistory: () => void; onExportLog: () => void; hasRoomId: boolean;
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
      <Item icon={<svg width="14" height="14" viewBox="0 0 17 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.4182 14H15.4182V19M6.41824 6H1.41824V1M15.8358 7.0034C15.2751 5.61566 14.3364 4.41304 13.1262 3.53223C11.9161 2.65141 10.4834 2.12752 8.9905 2.02051C7.4976 1.9135 6.0043 2.2274 4.68093 2.92661C3.35756 3.62582 2.25706 4.68254 1.50417 5.97612M1.00027 12.9971C1.56095 14.3848 2.4997 15.5874 3.70981 16.4682C4.91992 17.3491 6.35412 17.8723 7.84701 17.9793C9.33991 18.0863 10.832 17.7725 12.1554 17.0732C13.4787 16.374 14.5785 15.3175 15.3314 14.0239"/></svg>} label="Turn Cap" onClick={onTurn} />
      {showFontColor && <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3a9 9 0 1 0 9 9"/><circle cx="12" cy="12" r="3"/></svg>} label="字体颜色" onClick={onAppearance} />}
      {hasRoomId && (
        <>
          <Item icon={<svg width="14" height="14" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"><polyline points="17.18 15 8.18 15 8.18 6"/><path d="M10.58,12A18,18,0,1,1,6.23,26.88"/></svg>} label="Reload history" onClick={onReloadHistory} />
          <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>} label="Export log" onClick={onExportLog} />
        </>
      )}
    </motion.div>
  );
}

// ─── Turn Cap settings modal (per-conversation pacing) ──────────────────────────

function TurnSettingsModal({ maxAgentTurns, setMaxAgentTurns, maxUserGap, setMaxUserGap, onClose }: {
  maxAgentTurns: number; setMaxAgentTurns: (v: number) => void;
  maxUserGap: number; setMaxUserGap: (v: number) => void;
  onClose: () => void;
}) {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
      className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-6" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 8 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-[440px] bg-white rounded-[16px] shadow-[0_8px_32px_rgba(0,0,0,0.1)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-black/8">
          <div>
            <h2 className="text-[16px]" style={{ ...monoFont, fontWeight: 600 }}>Turn Cap</h2>
            <p className="text-[11px] text-[var(--app-muted-text)] mt-0.5" style={monoFont}>Per-conversation pacing — when to let user speak</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px] transition-colors">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div className="p-6 flex flex-col gap-4">
          <div>
            <label className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5 block" style={monoFont}>Agent turns</label>
            <p className="text-[10px] text-[var(--app-muted-text)] mb-2" style={monoFont}>Max agent messages before prompting user</p>
            <div className="flex items-center gap-2">
              <input type="range" min={2} max={10} value={maxAgentTurns} onChange={(e) => setMaxAgentTurns(parseInt(e.target.value))} className="flex-1 h-[3px] accent-black" />
              <span className="text-[11px] text-[var(--app-muted-text)] w-6 text-right" style={monoFont}>{maxAgentTurns}</span>
            </div>
          </div>
          <div>
            <label className="text-[10px] text-[var(--app-muted-text)] uppercase tracking-widest mb-1.5 block" style={monoFont}>User gap</label>
            <p className="text-[10px] text-[var(--app-muted-text)] mb-2" style={monoFont}>Max messages before user should respond</p>
            <div className="flex items-center gap-2">
              <input type="range" min={4} max={20} value={maxUserGap} onChange={(e) => setMaxUserGap(parseInt(e.target.value))} className="flex-1 h-[3px] accent-black" />
              <span className="text-[11px] text-[var(--app-muted-text)] w-6 text-right" style={monoFont}>{maxUserGap}</span>
            </div>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ─── User Menu (Account, Help, Logout) ─────────────────────────────────────────

function UserMenu({ nickname, onAccount, onHelp, onLogout, onClose }: {
  nickname: string; onAccount: () => void; onHelp: () => void; onLogout: () => void; onClose: () => void;
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
      <div className="h-px bg-black/8 mx-2 mb-1" />
      <div className="px-1">
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>} label="Account" onClick={() => { onClose(); onAccount(); }} />
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>} label="Help" onClick={() => { onClose(); onHelp(); }} />
      </div>
      <div className="h-px bg-black/8 mx-2 my-1" />
      <div className="px-1">
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>} label="Log out" onClick={onLogout} danger />
      </div>
    </motion.div>
  );
}

// ─── Customizer Modal (paginated cards) ────────────────────────────────────────

const CARD_LABELS = ["Basic", "Emotion", "Behavior"] as const;

function CustomizerModal({ agentNames, agentSettings, experimentMode, onSave, onClose, onAnalyze, initialOpenCard = null }: {
  agentNames: Record<AgentKey, string>;
  agentSettings: Record<AgentKey, AgentCustomSetting>;
  experimentMode: ExperimentMode;
  onSave: (names: Record<AgentKey, string>, settings: Record<AgentKey, AgentCustomSetting>) => void;
  onClose: () => void;
  onAnalyze: (key: AgentKey, v: number, a: number, c: number, text?: string) => Promise<{ emotion_tag: string; confidence: number } | null>;
  initialOpenCard?: AgentKey | null;
}) {
  const [localNames, setLocalNames] = useState<Record<AgentKey, string>>({ ...agentNames });
  const [localSettings, setLocalSettings] = useState<Record<AgentKey, AgentCustomSetting>>({ A: { ...agentSettings.A }, B: { ...agentSettings.B }, C: { ...agentSettings.C } });
  const [selectedAgent, setSelectedAgent] = useState<AgentKey>(initialOpenCard || "A");
  const [custTags, setCustTags] = useState<Partial<Record<AgentKey, string>>>({});
  const [custConfs, setCustConfs] = useState<Partial<Record<AgentKey, number>>>({});
  const [page, setPage] = useState(0);

  const canEditAdvanced = experimentMode === "full";
  const agentOptions = experimentMode === "single" ? [("A" as AgentKey)] : AGENT_KEYS;
  const totalCards = canEditAdvanced ? 3 : 1;

  useEffect(() => { if (initialOpenCard) setSelectedAgent(initialOpenCard); }, [initialOpenCard]);
  useEffect(() => { setPage(0); }, [selectedAgent]);
  useEffect(() => { analyze(selectedAgent); }, [selectedAgent]);

  const upd = (key: AgentKey, field: keyof AgentCustomSetting, value: unknown) =>
    setLocalSettings((prev) => ({ ...prev, [key]: { ...prev[key], [field]: value } }));

  const analyze = async (key: AgentKey) => {
    const s = localSettings[key];
    const r = await onAnalyze(key, s.valence, s.arousal, s.control, s.emotionText || "");
    if (r) { setCustTags((p) => ({ ...p, [key]: r.emotion_tag })); setCustConfs((p) => ({ ...p, [key]: r.confidence })); upd(key, "emotionTag", r.emotion_tag); }
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
                <button onClick={goPrev} disabled={page === 0}
                  className="p-2 rounded-[8px] hover:bg-black/5 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6"/></svg>
                </button>
                <div className="flex gap-1.5">
                  {Array.from({ length: totalCards }).map((_, i) => (
                    <button key={i} onClick={() => setPage(i)}
                      className={`w-2 h-2 rounded-full transition-all ${i === page ? "bg-black scale-125" : "bg-black/25 hover:bg-black/40"}`}
                      aria-label={`Card ${i + 1}`} />
                  ))}
                </div>
                <button onClick={goNext} disabled={page === totalCards - 1}
                  className="p-2 rounded-[8px] hover:bg-black/5 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 18l6-6-6-6"/></svg>
                </button>
              </div>
            )}
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-black/8">
          <motion.button onClick={onClose} whileTap={{ scale: 0.97 }} className="px-4 py-2 text-[12px] border border-black/15 rounded-[8px] hover:bg-black/5 transition-colors" style={monoFont}>Cancel</motion.button>
          <motion.button onClick={() => { onSave(localNames, localSettings); onClose(); }} whileTap={{ scale: 0.97 }} className="px-4 py-2 text-[12px] bg-black text-white rounded-[8px] hover:bg-neutral-800 transition-colors" style={monoFont}>Save</motion.button>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ─── Scene Selector ───────────────────────────────────────────────────────────

function SceneSelectorModal({ scenes, selectedScene, onSelect, onClose }: { scenes: Scene[]; selectedScene: Scene | null; onSelect: (s: Scene) => void; onClose: () => void }) {
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
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}
      className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-6" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 8 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-[720px] bg-white rounded-[16px] shadow-[0_8px_32px_rgba(0,0,0,0.1)] overflow-hidden flex flex-col max-h-[90vh]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-black/8">
          <div>
            <h2 className="text-[16px]" style={{ ...monoFont, fontWeight: 600 }}>Customize Scene</h2>
            <p className="text-[11px] text-[var(--app-muted-text)] mt-0.5" style={monoFont}>Choose or add a consultation scenario · {scenePages.length || 1} pages</p>
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
                      {pageScenes.map((s) => (
                        <button key={s.id} onClick={() => { onSelect(s); onClose(); }}
                          className={`text-left p-4 border-2 rounded-[12px] transition-all hover:shadow-[0_2px_12px_rgba(0,0,0,0.06)] ${selectedScene?.id === s.id ? "border-black" : "border-black/10 hover:border-black/30"}`}>
                          <div className="text-2xl mb-2">{s.icon}</div>
                          <div className="text-[13px] mb-1" style={{ ...monoFont, fontWeight: 500 }}>{s.title}</div>
                          <div className="text-[10px] text-[var(--app-muted-text)] leading-relaxed" style={monoFont}>{s.description}</div>
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
            <button onClick={() => { onSelect(null as unknown as Scene); onClose(); }} className="text-[11px] text-[var(--app-muted-text)] hover:text-black transition-colors" style={monoFont}>Clear selection</button>
          </div>
        )}
      </motion.div>
    </motion.div>
  );
}

// ─── Main Chat Component ──────────────────────────────────────────────────────

export default function Chat() {
  const navigate = useNavigate();
  const authData = JSON.parse(localStorage.getItem("agora_auth") || "{}");
  const nickname: string = authData.nickname || "You";

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConvId, setCurrentConvId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [typingKeys, setTypingKeys] = useState<AgentKey[]>([]);
  const [msgQueue, setMsgQueue] = useState<Array<{ agentKey: AgentKey; content: string; convId: string; emotionTagSnapshot: string | null }>>([]);
  const agentNamesRef = useRef<Record<AgentKey, string>>(DEFAULT_AGENT_NAMES);
  const agentSettingsRef = useRef<Record<AgentKey, AgentCustomSetting>>({ A: defaultSetting("A"), B: defaultSetting("B"), C: defaultSetting("C") });

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [showCustomizer, setShowCustomizer] = useState(false);
  const [customizerInitialAgent, setCustomizerInitialAgent] = useState<AgentKey | null>(null);
  const [showSceneSelector, setShowSceneSelector] = useState(false);
  const [showTurnModal, setShowTurnModal] = useState(false);
  const [showAppearanceModal, setShowAppearanceModal] = useState(false);
  const [showFontColorInSettings, setShowFontColorInSettings] = useState(false);
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [settingsMenuOpen, setSettingsMenuOpen] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [sessionCreateError, setSessionCreateError] = useState<string | null>(null);
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
  const [experimentMode, setExperimentMode] = useState<ExperimentMode>("full");

  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const messagesContentRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const currentConv = conversations.find((c) => c.id === currentConvId) || null;
  const appearance = useAppearanceContext();
  const activeSceneId = selectedScene?.id || "scene1";
  const suggestedPrompts = SCENE_SUGGESTED_PROMPTS[activeSceneId] || SCENE_SUGGESTED_PROMPTS.scene1;

  const scrollMessagesToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const c = messagesContainerRef.current;
    if (!c) return;
    c.scrollTo({ top: c.scrollHeight, behavior });
  }, []);
  const getPopoverSafeRect = useCallback(() => messagesContainerRef.current?.getBoundingClientRect() ?? null, []);

  useEffect(() => { if (!localStorage.getItem("agora_auth")) navigate("/"); }, [navigate]);

  useEffect(() => {
    fetch(`${API_BASE}/health`).then((r) => { if (r.ok) setBackendOnline(true); }).catch(() => {});
    fetch("/scenes_config.json").then((r) => r.json()).then((d) => setScenes(d.scenes || [])).catch(() => {});
  }, []);

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

  // Queue processor: typing dot → message → next
  useEffect(() => {
    if (msgQueue.length === 0) {
      setTypingKeys([]);
      return;
    }
    const next = msgQueue[0];
    setTypingKeys([next.agentKey]);
    const timer = setTimeout(() => {
      const agentMsg: Message = {
        id: `msg-${Date.now()}-${next.agentKey}`,
        role: "agent",
        agentKey: next.agentKey,
        content: next.content,
        timestamp: Date.now(),
        emotionTagSnapshot: next.emotionTagSnapshot,
      };
      const names = agentNamesRef.current;
      setConversations((prev) => prev.map((c) => c.id === next.convId ? { ...c, messages: [...c.messages, agentMsg], preview: `${names[next.agentKey]}: ${next.content.slice(0, 60)}…`, timestamp: "just now" } : c));
      setMsgQueue((q) => {
        const rest = q.slice(1);
        setTypingKeys(rest.length > 0 ? [rest[0].agentKey] : []);
        return rest;
      });
    }, 900);
    return () => clearTimeout(timer);
  }, [msgQueue]);

  const analyzeEmotionForAgent = useCallback(async (_key: AgentKey, v: number, a: number, c: number, text = "") => {
    try {
      const res = await fetch(`${API_BASE}/emotion/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: (text || "").trim(), valence: v, arousal: a, control: c }) });
      if (!res.ok) return null;
      return await res.json();
    } catch { return null; }
  }, []);

  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text || isLoading) return;
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
      try {
        const res = await fetch(`${API_BASE}/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            scene_id: selectedScene?.id || "scene1",
            mode: experimentMode,
            limited_selected_agent_keys: experimentMode === "limited" ? limitedSelectedAgents : undefined,
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
        // Apply agent defaults from info.jsonl (decision, emotion)
        const agentsFromApi = data.agents || [];
        if (agentsFromApi.length > 0) {
          const applyApiDefaults = experimentMode !== "full";
          agentsFromApi.forEach((a: { key?: string; pool_key?: string; name?: string; decision?: string; emotion?: string; role?: string }) => {
            const k = a.key as AgentKey;
            if (k && (k === "A" || k === "B" || k === "C")) {
              if (a.name) nextBackendNamesForConv[k] = a.name;
              if (experimentMode === "limited") {
                const profile = LIMITED_AGENT_POOL.find((p) => p.key === (a.pool_key as AgentPoolKey));
                nextNamesForConv[k] = profile?.defaultName || a.name || nextNamesForConv[k];
              }
              nextSettingsForConv[k] = {
                ...nextSettingsForConv[k],
                decisionBlock: applyApiDefaults
                  ? ((a.decision as AgentCustomSetting["decisionBlock"]) || nextSettingsForConv[k].decisionBlock || "Rational")
                  : nextSettingsForConv[k].decisionBlock,
                emotionTag: applyApiDefaults
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
    const agentEmotionOverrides: Record<string, string> = {};
    const additionalRules: Record<string, string> = {};
    const agentDecisionBlock: Record<string, string> = {};
    const useNeutral = activeMode === "limited" || activeMode === "single";
    if (useNeutral) {
      if (activeMode === "single") agentDecisionBlock["A"] = "Rational";
    } else {
      AGENT_KEYS.forEach((k) => {
        if (agentSettings[k].emotionOn && agentSettings[k].emotionTag) agentEmotionOverrides[k] = agentSettings[k].emotionTag!;
        if (agentSettings[k].additionalPrompt) additionalRules[k] = agentSettings[k].additionalPrompt;
        agentDecisionBlock[k] = agentSettings[k].decisionBlock;
      });
    }

    const maxTurns = activeMode === "single" ? 1 : maxAgentTurns;
    setTypingKeys(activeMode === "single" ? ["A"] : ["A"]);
    try {
      const res = await fetch(`${API_BASE}/message`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ room_id: roomId, message: text, scene_id: selectedScene?.id || "scene1", emotion_tag: null, emotion_target: null, agent_emotion_overrides: agentEmotionOverrides, additional_rules: additionalRules, agent_decision_block: agentDecisionBlock, max_agent_turns_before_user: maxTurns, max_user_gap: maxUserGap, single_mode: activeMode === "single" }) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setCurrentPhase(data.phase || null);
      const responses: Array<{ agent_key: string; message: string }> = data.responses || [];
      if (responses.length === 0) { setTypingKeys([]); }
      else {
        const mapped = responses.map((r) => {
          const agentKey = (r.agent_key || "A") as AgentKey;
          const currentSetting = agentSettingsRef.current[agentKey];
          return {
            agentKey,
            content: r.message,
            convId: convId as string,
            emotionTagSnapshot: currentSetting?.emotionOn ? (currentSetting.emotionTag ?? "joy") : null,
          };
        });
        const filtered = activeMode === "single" ? mapped.filter((m) => m.agentKey === "A").slice(0, 1) : mapped;
        setMsgQueue(filtered);
      }
    } catch {
      setTypingKeys([]);
      const errMsg: Message = { id: `msg-err-${Date.now()}`, role: "agent", content: backendOnline ? "Something went wrong. Please try again." : "Backend is not running. Start with: python app.py", timestamp: Date.now() };
      setConversations((prev) => prev.map((c) => c.id === convId ? { ...c, messages: [...c.messages, errMsg] } : c));
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleLoadHistory = async () => {
    if (!currentConv?.roomId) return;
    try {
      const res = await fetch(`${API_BASE}/history/${currentConv.roomId}`);
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
      const messages: Message[] = (data.history || []).map((h: { character: string; txt: string }, i: number) => {
        if (h.character === "user") return { id: `h-${i}`, role: "user" as const, content: h.txt, timestamp: Date.now() - (data.history.length - i) * 1000 };
        const agentKey = runtimeMap[h.character] ?? BACKEND_NAME_TO_KEY[h.character] ?? "A";
        const currentSetting = agentSettingsRef.current[agentKey];
        return {
          id: `h-${i}`,
          role: "agent" as const,
          agentKey,
          content: h.txt,
          timestamp: Date.now() - (data.history.length - i) * 1000,
          emotionTagSnapshot: currentSetting?.emotionOn ? (currentSetting.emotionTag ?? "joy") : null,
        };
      });
      setConversations((prev) => prev.map((c) => c.id === currentConvId ? { ...c, messages } : c));
    } catch {}
  };

  const handleExportLog = async () => {
    if (!currentConv?.roomId) return;
    try {
      const res = await fetch(`${API_BASE}/export-logs/${currentConv.roomId}`);
      if (!res.ok) throw new Error(res.statusText);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `agora_logs_${currentConv.roomId}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {}
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
  const handleSelectConv = (id: string) => {
    const conv = conversations.find((c) => c.id === id);
    setCurrentConvId(id);
    loadConvSettings(conv || null);
    setTypingKeys([]);
    setMsgQueue([]);
    setSidebarOpen(false);
  };
  const handleLogout = () => { localStorage.removeItem("agora_auth"); navigate("/"); };
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } };
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

  return (
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
            onClose={() => { setShowCustomizer(false); setCustomizerInitialAgent(null); }}
            onAnalyze={analyzeEmotionForAgent} initialOpenCard={customizerInitialAgent} />
        )}
        {showSceneSelector && (
          <SceneSelectorModal scenes={scenes} selectedScene={selectedScene} onSelect={setSelectedScene} onClose={() => setShowSceneSelector(false)} />
        )}
        {showTurnModal && (
          <AnimatePresence mode="wait">
            <TurnSettingsModal key="turn" maxAgentTurns={maxAgentTurns} setMaxAgentTurns={setMaxAgentTurns} maxUserGap={maxUserGap} setMaxUserGap={setMaxUserGap} onClose={() => setShowTurnModal(false)} />
          </AnimatePresence>
        )}
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
                  {m === "full" && "Full — all options"}
                  {m === "limited" && "Limited — choose 3 of 6"}
                  {m === "single" && "Single — Agent A, neutral only"}
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
              {conversations.map((conv) => <ConvItem key={conv.id} conv={conv} isActive={conv.id === currentConvId} onClick={() => handleSelectConv(conv.id)} />)}
            </div>
          )}
        </div>
        <div className="relative flex-shrink-0">
          <AnimatePresence>
            {userMenuOpen && <UserMenu nickname={nickname} onAccount={() => {}} onHelp={() => {}} onLogout={handleLogout} onClose={() => setUserMenuOpen(false)} />}
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
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-[56px] border-b border-black/8 flex items-center px-4 gap-4 flex-shrink-0">
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
                {showPhaseIndicator && currentPhase && <span className="text-[10px] text-[var(--app-muted-text)]">· Phase: {currentPhase}</span>}
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

        <div ref={messagesContainerRef} className="flex-1 overflow-y-auto px-4 sm:px-8 py-6">
          <AnimatePresence mode="wait" initial={false}>
          {!currentConv ? (
            <motion.div
              key="welcome"
              initial={{ opacity: 0, y: 18, scale: 0.985 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -12, scale: 0.99 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
              className="w-full max-w-[440px] sm:max-w-[560px] lg:max-w-[680px] xl:max-w-[800px] mx-auto flex flex-col items-center justify-center min-h-[60vh] gap-8"
            >
              <div className="flex flex-col items-center gap-4 w-full">
                <AgoraLogo size={96} />
                {!backendOnline && (
                  <p className="text-center text-[11px] text-amber-500 w-full leading-relaxed border border-amber-200 bg-amber-50 px-3 py-2 rounded-[8px]" style={monoFont}>
                    Backend offline — start with: <strong>python app.py</strong>
                  </p>
                )}
              </div>
              <div className="w-full">
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
                        onClick={() => { setCustomizerInitialAgent(key as AgentKey); setShowCustomizer(true); }}
                        className="border border-black/8 rounded-[10px] px-3 py-3 text-left transition-colors group"
                      >
                        <div className="flex items-center gap-1.5 mb-1">
                          <div className="w-[6px] h-[6px] rounded-[1.2px] flex-shrink-0" style={{ backgroundColor: agentSettings[key as AgentKey]?.accentColor || DEFAULT_AGENT_COLORS[key as AgentKey] }} />
                          <span className="text-[10px] tracking-widest text-black" style={monoFont}>{agentNames[key as AgentKey]}</span>
                        </div>
                        <p className="text-[10px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={monoFont}>{agentSettings[key as AgentKey]?.roleDescription || DEFAULT_AGENT_ROLES[key as AgentKey]}</p>
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
              <div className="w-full">
                <p className="text-[10px] text-[var(--app-muted-text)] mb-3 text-center tracking-widest" style={monoFont}>SCENE</p>
                <motion.button
                  whileHover={{ y: -2, boxShadow: "0 4px 14px rgba(0,0,0,0.07)" }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => setShowSceneSelector(true)}
                  className="w-full text-left px-4 py-3 border border-black/8 rounded-[10px] transition-colors group"
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <div className="w-[6px] h-[6px] rounded-[1.2px] flex-shrink-0" style={{ backgroundColor: selectedScene?.color || "#000000" }} />
                    <span className="text-[10px] tracking-widest text-black" style={monoFont}>{selectedScene?.title || scenes[0]?.title || "Laptop Purchase Advisory"}</span>
                  </div>
                  <p className="text-[10px] text-[var(--app-muted-text)] group-hover:text-black/70 transition-colors" style={monoFont}>{selectedScene?.description || scenes[0]?.description || "Professional advice for Black Friday laptop shopping. Three AI agents analyze from different perspectives."}</p>
                  <p className="text-[9px] text-[var(--app-muted-text)] mt-2 group-hover:text-black/70 transition-colors" style={monoFont}>click to customize →</p>
                </motion.button>
              </div>
              <div className="w-full">
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
                    return <UserMessage key={msg.id} message={msg} nickname={nickname} />;
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
                      onOpenAdvancedAgent={(key) => { setCustomizerInitialAgent(key); setShowCustomizer(true); }}
                      onQuickEmotionAdjust={async (key, patch, shouldAnalyze) => {
                        setAgentSettings((prev) => ({
                          ...prev,
                          [key]: {
                            ...prev[key],
                            ...patch,
                          },
                        }));
                        if (!shouldAnalyze) return;
                        const next = {
                          ...agentSettingsRef.current[key],
                          ...patch,
                        };
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
                      }}
                    />
                  );
                });
              })()}
              <AnimatePresence initial={false} mode="popLayout">
                {typingKeys.map((k) => <TypingDots key={k} agentKey={k} agentNames={agentNames} />)}
              </AnimatePresence>
              <div />
            </motion.div>
          )}
          </AnimatePresence>
        </div>

        <div className="flex-shrink-0 border-t border-black/8 px-4 sm:px-8 py-4">
          <div className={`mx-auto ${currentConv ? "max-w-[680px] sm:max-w-[800px] lg:max-w-[960px] xl:max-w-[1100px]" : "max-w-[440px] sm:max-w-[560px] lg:max-w-[680px] xl:max-w-[800px]"}`}>
            {sessionCreateError && (
              <p className="text-center text-[11px] text-amber-600 bg-amber-50 border border-amber-200 px-3 py-2 rounded-[8px] mb-3" style={monoFont}>{sessionCreateError}</p>
            )}
            <div className="flex gap-2 items-end min-h-[48px]">
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
                  placeholder="Enter a question or topic to explore..." rows={1} disabled={isLoading}
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
                    onCustomize={() => setShowCustomizer(true)} onScene={() => setShowSceneSelector(true)} onTurn={() => setShowTurnModal(true)}
                    onAppearance={() => setShowAppearanceModal(true)}
                    onReloadHistory={handleLoadHistory} onExportLog={handleExportLog} hasRoomId={!!currentConv?.roomId}
                    showFontColor={showFontColorInSettings} onToggleFontColor={() => setShowFontColorInSettings((v) => !v)} />
                </AnimatePresence>
              </div>
            </div>
            <p className="text-center text-[10px] text-[var(--app-muted-text)] mt-2" style={monoFont}>shift+enter for new line · enter to send</p>
          </div>
        </div>
      </div>
    </div>
  );
}
