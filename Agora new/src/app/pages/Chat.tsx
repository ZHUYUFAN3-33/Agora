import React, { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router";
import { motion, AnimatePresence } from "motion/react";
import { AgoraLogo, AgoraLogoFull } from "../components/AgoraLogo";
import {
  type AgentKey,
  type AgentCustomSetting,
  type Scene,
  AGENT_KEYS,
  DEFAULT_AGENT_NAMES,
  DEFAULT_AGENT_ROLES,
  API_BASE,
  BACKEND_NAME_TO_KEY,
  SUGGESTED_PROMPTS,
  EMOTION_EMOJI,
  EMOTION_COLORS,
  EMOTION_EXAMPLES,
  defaultSetting,
} from "../data/agents";

const monoFont = { fontFamily: "'Share Tech Mono', monospace" };
const condensedFont = { fontFamily: "'Barlow Condensed', sans-serif" };

// ─── Types ────────────────────────────────────────────────────────────────────

interface Message {
  id: string;
  role: "user" | "agent";
  agentKey?: AgentKey;
  content: string;
  timestamp: number;
}

interface Conversation {
  id: string;
  roomId: string;
  title: string;
  preview: string;
  timestamp: string;
  messages: Message[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

// Replace backend names (ChatbotA/B/C) with user-defined display names
function applyDisplayNames(content: string, names: Record<AgentKey, string>): string {
  return content
    .replace(/\bChatbotA\b/g, names.A)
    .replace(/\bChatbotB\b/g, names.B)
    .replace(/\bChatbotC\b/g, names.C);
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
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
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

function AgentMessage({
  message,
  agentNames,
  onClickAgent,
}: {
  message: Message;
  agentNames: Record<AgentKey, string>;
  onClickAgent?: (key: AgentKey) => void;
}) {
  const name = message.agentKey ? agentNames[message.agentKey] : "Agent";
  const role = message.agentKey ? DEFAULT_AGENT_ROLES[message.agentKey] : "";
  const isError = !message.agentKey;
  const displayContent = message.agentKey
    ? applyDisplayNames(message.content, agentNames)
    : message.content;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-col gap-1 mb-4"
    >
      <div className="flex items-center gap-2 mb-1">
        <div
          className="w-[7px] h-[7px] rounded-[1.5px] flex-shrink-0"
          style={{ backgroundColor: isError ? "#ef4444" : "#000" }}
        />
        <button
          className={`text-[11px] tracking-widest leading-none ${
            !isError && onClickAgent ? "hover:underline underline-offset-2 cursor-pointer" : "cursor-default"
          }`}
          style={{ ...monoFont, color: isError ? "#ef4444" : "#000" }}
          onClick={() => message.agentKey && onClickAgent?.(message.agentKey)}
          disabled={isError || !onClickAgent}
        >
          {name}
        </button>
        {role && (
          <span className="text-[10px] text-black/30 ml-1" style={monoFont}>
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
          {displayContent}
        </p>
      </div>
    </motion.div>
  );
}

function UserMessage({ message, nickname }: { message: Message; nickname: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex flex-col items-end gap-1 mb-6"
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[11px] text-black/40 tracking-wider" style={monoFont}>
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

function ConvItem({ conv, isActive, onClick }: { conv: Conversation; isActive: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-3 rounded-[8px] transition-colors flex flex-col gap-1 ${
        isActive ? "bg-black text-white" : "hover:bg-black/5"
      }`}
    >
      <span className="text-[12px] truncate" style={{ ...monoFont, color: isActive ? "#fff" : "#000" }}>
        {conv.title}
      </span>
      <span className="text-[10px] truncate" style={{ ...monoFont, color: isActive ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.4)" }}>
        {conv.timestamp}
      </span>
    </button>
  );
}

// ─── Emotion Panel ────────────────────────────────────────────────────────────

interface EmotionPanelProps {
  emotionOn: boolean; setEmotionOn: (v: boolean) => void;
  emotionTarget: string; setEmotionTarget: (v: string) => void;
  emotionText: string; setEmotionText: (v: string) => void;
  emotionTag: string | null; emotionConf: number; emotionProbs: Record<string, number>;
  valence: number; setValence: (v: number) => void;
  arousal: number; setArousal: (v: number) => void;
  control: number; setControl: (v: number) => void;
  agentNames: Record<AgentKey, string>;
  onAnalyze: (text: string, v: number, a: number, c: number) => void;
}

function EmotionPanel(props: EmotionPanelProps) {
  const { emotionOn, setEmotionOn, emotionTarget, setEmotionTarget, emotionText, setEmotionText,
    emotionTag, emotionConf, emotionProbs, valence, setValence, arousal, setArousal,
    control, setControl, agentNames, onAnalyze } = props;
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const trigger = useCallback((t: string, v: number, a: number, c: number) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => onAnalyze(t, v, a, c), 300);
  }, [onAnalyze]);
  const emoColor = emotionTag ? EMOTION_COLORS[emotionTag] || "#000" : "#000";

  return (
    <div className="border-t border-black/8 px-3 pt-3 pb-3 flex-shrink-0">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-black/40 tracking-widest uppercase" style={monoFont}>Emotion Mode</span>
        <Toggle checked={emotionOn} onChange={(v) => { setEmotionOn(v); if (v) trigger(emotionText, valence, arousal, control); }} />
      </div>
      {emotionOn && (
        <div className="flex flex-col gap-2 mt-2">
          <select value={emotionTarget} onChange={(e) => setEmotionTarget(e.target.value)}
            className="w-full text-[11px] px-2 py-1.5 border border-black/12 rounded-[6px] bg-white outline-none cursor-pointer" style={monoFont}>
            <option value="all">All Agents</option>
            {AGENT_KEYS.map((k) => <option key={k} value={k}>{agentNames[k]}</option>)}
          </select>
          <textarea value={emotionText} onChange={(e) => { setEmotionText(e.target.value); trigger(e.target.value, valence, arousal, control); }}
            placeholder="Describe the emotional context..." rows={2}
            className="w-full text-[11px] px-2 py-2 border border-black/12 rounded-[6px] bg-white outline-none resize-none leading-relaxed" style={monoFont} />
          {emotionTag && (
            <div className="flex items-center gap-2 px-2 py-2 border rounded-[8px]"
              style={{ borderColor: emoColor + "40", background: emoColor + "12" }}>
              <span className="text-lg leading-none">{EMOTION_EMOJI[emotionTag] || "😐"}</span>
              <div className="flex flex-col leading-tight">
                <span className="text-[11px] font-semibold capitalize" style={{ ...monoFont, color: emoColor }}>{emotionTag}</span>
                <span className="text-[10px] text-black/30" style={monoFont}>{Math.round(emotionConf * 100)}% conf.</span>
              </div>
            </div>
          )}
          {([
            { label: "Valence", val: valence, set: setValence, emoji: "😊" },
            { label: "Arousal", val: arousal, set: setArousal, emoji: "⚡" },
            { label: "Control", val: control, set: setControl, emoji: "🎯" },
          ] as const).map(({ label, val, set, emoji }) => (
            <div key={label} className="flex items-center gap-2">
              <span className="text-[10px] text-black/40 w-[72px] flex-shrink-0 leading-none" style={monoFont}>{emoji} {label}</span>
              <input type="range" min={0} max={100} value={Math.round(val * 100)}
                onChange={(e) => { const nv = parseInt(e.target.value) / 100; set(nv); trigger(emotionText, label === "Valence" ? nv : valence, label === "Arousal" ? nv : arousal, label === "Control" ? nv : control); }}
                className="flex-1 h-[3px] accent-black" />
              <span className="text-[10px] text-black/40 w-[28px] text-right" style={monoFont}>{val.toFixed(2)}</span>
            </div>
          ))}
          {Object.keys(emotionProbs).length > 0 && (
            <div className="flex flex-col gap-1 mt-1">
              {(["joy","anger","fear","sadness","surprise","disgust"] as const).map((em) => (
                <div key={em} className="flex items-center gap-2">
                  <span className="text-[10px] text-black/40 w-[66px] flex-shrink-0" style={monoFont}>{EMOTION_EMOJI[em]} {em}</span>
                  <div className="flex-1 h-[3px] bg-black/8 rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-300"
                      style={{ width: `${Math.round((emotionProbs[em] || 0) * 100)}%`, backgroundColor: em === emotionTag ? EMOTION_COLORS[em] || "#000" : "#00000030" }} />
                  </div>
                </div>
              ))}
            </div>
          )}
          {emotionTag && EMOTION_EXAMPLES[emotionTag] && (
            <div className="mt-1 pl-2 border-l-2 border-black/10">
              <p className="text-[9px] text-black/30 uppercase tracking-widest mb-1" style={monoFont}>Examples</p>
              {EMOTION_EXAMPLES[emotionTag].slice(0, 3).map((ex, i) => (
                <p key={i} className="text-[10px] text-black/50 italic leading-relaxed" style={monoFont}>"{ex}"</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── User Menu ────────────────────────────────────────────────────────────────

function UserMenu({ nickname, onCustomize, onScene, onLogout, onClose }: {
  nickname: string; onCustomize: () => void; onScene: () => void; onLogout: () => void; onClose: () => void;
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
      className="absolute bottom-[56px] left-3 right-3 bg-white border border-black/10 rounded-[12px] shadow-xl z-50 py-2 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 mb-1">
        <div className="w-[7px] h-[7px] rounded-[1.5px] bg-red-500 flex-shrink-0" />
        <span className="text-[12px] tracking-widest text-black" style={monoFont}>{(nickname || "you").toUpperCase()}</span>
      </div>
      <div className="h-px bg-black/8 mx-2 mb-1" />
      <div className="px-1">
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 1 0-16 0"/></svg>} label="Customize Agents" onClick={() => { onClose(); onCustomize(); }} />
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>} label="Select / Customize Scene" onClick={() => { onClose(); onScene(); }} />
      </div>
      <div className="h-px bg-black/8 mx-2 my-1" />
      <div className="px-1">
        <Item icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>} label="Log out" onClick={onLogout} danger />
      </div>
    </motion.div>
  );
}

// ─── Customizer Modal ─────────────────────────────────────────────────────────

const CARD_ACCENT: Record<AgentKey, string> = { A: "#3b82f6", B: "#f59e0b", C: "#8b5cf6" };

function CustomizerModal({ agentNames, agentSettings, onSave, onClose, onAnalyze, initialOpenCard = null }: {
  agentNames: Record<AgentKey, string>;
  agentSettings: Record<AgentKey, AgentCustomSetting>;
  onSave: (names: Record<AgentKey, string>, settings: Record<AgentKey, AgentCustomSetting>) => void;
  onClose: () => void;
  onAnalyze: (key: AgentKey, v: number, a: number, c: number) => Promise<{ emotion_tag: string; confidence: number } | null>;
  initialOpenCard?: AgentKey | null;
}) {
  const [localNames, setLocalNames] = useState<Record<AgentKey, string>>({ ...agentNames });
  const [localSettings, setLocalSettings] = useState<Record<AgentKey, AgentCustomSetting>>({ A: { ...agentSettings.A }, B: { ...agentSettings.B }, C: { ...agentSettings.C } });
  const [openCard, setOpenCard] = useState<AgentKey | null>(initialOpenCard);
  const [custTags, setCustTags] = useState<Partial<Record<AgentKey, string>>>({});
  const [custConfs, setCustConfs] = useState<Partial<Record<AgentKey, number>>>({});

  const upd = (key: AgentKey, field: keyof AgentCustomSetting, value: unknown) =>
    setLocalSettings((prev) => ({ ...prev, [key]: { ...prev[key], [field]: value } }));

  const analyze = async (key: AgentKey) => {
    const s = localSettings[key];
    const r = await onAnalyze(key, s.valence, s.arousal, s.control);
    if (r) { setCustTags((p) => ({ ...p, [key]: r.emotion_tag })); setCustConfs((p) => ({ ...p, [key]: r.confidence })); upd(key, "emotionTag", r.emotion_tag); }
  };

  const fields = (key: AgentKey) => {
    const s = localSettings[key];
    return (
      <div className="flex flex-col gap-4">
        <div>
          <label className="text-[10px] text-black/40 uppercase tracking-widest mb-1.5 block" style={monoFont}>Display Name</label>
          <input type="text" value={localNames[key]} maxLength={24} onChange={(e) => setLocalNames((p) => ({ ...p, [key]: e.target.value }))}
            className="w-full text-[12px] px-3 py-1.5 border border-black/15 rounded-[6px] outline-none focus:border-black/40 transition-colors" style={monoFont} />
        </div>
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-[10px] text-black/40 uppercase tracking-widest" style={monoFont}>Emotion Mode</label>
            <Toggle checked={s.emotionOn} onChange={(v) => { upd(key, "emotionOn", v); if (v) analyze(key); }} />
          </div>
          {s.emotionOn && (
            <div className="flex flex-col gap-2">
              {custTags[key] && (
                <div className="flex items-center gap-2 px-2 py-1.5 border rounded-[6px] text-[11px]"
                  style={{ borderColor: (EMOTION_COLORS[custTags[key]!] || "#000") + "40", background: (EMOTION_COLORS[custTags[key]!] || "#000") + "10", color: EMOTION_COLORS[custTags[key]!] || "#000", ...monoFont }}>
                  <span>{EMOTION_EMOJI[custTags[key]!] || "😐"}</span>
                  <span className="capitalize">{custTags[key]}</span>
                  <span style={{ color: "#00000050" }}>{Math.round((custConfs[key] || 0) * 100)}%</span>
                </div>
              )}
              {([{ label: "Valence", field: "valence" as const, val: s.valence }, { label: "Arousal", field: "arousal" as const, val: s.arousal }, { label: "Control", field: "control" as const, val: s.control }] as const).map(({ label, field, val }) => (
                <div key={field} className="flex items-center gap-2">
                  <span className="text-[10px] text-black/40 w-14 flex-shrink-0" style={monoFont}>{label}</span>
                  <input type="range" min={0} max={100} value={Math.round(val * 100)}
                    onChange={(e) => upd(key, field, parseInt(e.target.value) / 100)} onMouseUp={() => analyze(key)} onTouchEnd={() => analyze(key)}
                    className="flex-1 h-[3px] accent-black" />
                  <span className="text-[10px] text-black/40 w-8 text-right" style={monoFont}>{val.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <label className="text-[10px] text-black/40 uppercase tracking-widest mb-1.5 block" style={monoFont}>Additional Prompt</label>
          <textarea value={s.additionalPrompt} onChange={(e) => upd(key, "additionalPrompt", e.target.value)} placeholder="Extra instructions for this agent..." rows={3}
            className="w-full text-[11px] px-3 py-2 border border-black/15 rounded-[6px] outline-none resize-none leading-relaxed focus:border-black/40 transition-colors" style={monoFont} />
        </div>
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-[10px] text-black/40 uppercase tracking-widest" style={monoFont}>Decision Summary</label>
            <Toggle checked={s.decisionOn} onChange={(v) => upd(key, "decisionOn", v)} />
          </div>
          {s.decisionOn && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-black/40 flex-shrink-0" style={monoFont}>After</span>
                <input type="range" min={2} max={15} value={s.decisionTrigger} onChange={(e) => upd(key, "decisionTrigger", parseInt(e.target.value))} className="flex-1 h-[3px] accent-black" />
                <span className="text-[10px] text-black/40 flex-shrink-0" style={monoFont}>{s.decisionTrigger} turns</span>
              </div>
              <select value={s.decisionStyle} onChange={(e) => upd(key, "decisionStyle", e.target.value as AgentCustomSetting["decisionStyle"])}
                className="text-[11px] px-2 py-1.5 border border-black/15 rounded-[6px] outline-none cursor-pointer" style={monoFont}>
                <option value="brief">Brief</option>
                <option value="detailed">Detailed</option>
                <option value="structured">Structured</option>
              </select>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/30 z-50 flex items-start justify-center overflow-y-auto py-8 px-4" onClick={onClose}>
      <div className="w-full max-w-[860px] bg-white rounded-[16px] shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-black/8">
          <div>
            <h2 className="text-[16px]" style={{ ...monoFont, fontWeight: 600 }}>Customize Agent</h2>
            <p className="text-[11px] text-black/40 mt-0.5" style={monoFont}>Configure name, emotion, prompt, and decision summary</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px] transition-colors">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div className={`p-6 grid gap-4 ${initialOpenCard ? "grid-cols-1 max-w-[480px] mx-auto" : "grid-cols-1 md:grid-cols-3"}`}>
          {(initialOpenCard ? [initialOpenCard] : AGENT_KEYS).map((key) => {
            const isOpen = openCard === key;
            if (initialOpenCard) return <div key={key}>{fields(key)}</div>;
            return (
              <div key={key} className="border border-black/10 rounded-[12px] overflow-hidden">
                <button className="w-full flex items-center gap-3 px-4 py-3 hover:bg-black/2 transition-colors" onClick={() => setOpenCard(isOpen ? null : key)}>
                  <div className="w-[8px] h-[8px] rounded-[2px] flex-shrink-0" style={{ background: CARD_ACCENT[key] }} />
                  <span className="flex-1 text-left text-[13px] truncate" style={{ ...monoFont, fontWeight: 500 }}>{localNames[key]}</span>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2" style={{ transform: isOpen ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s", opacity: 0.4 }}>
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </button>
                {isOpen && <div className="px-4 pb-4 border-t border-black/8 pt-4">{fields(key)}</div>}
              </div>
            );
          })}
        </div>
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-black/8">
          <button onClick={onClose} className="px-4 py-2 text-[12px] border border-black/15 rounded-[8px] hover:bg-black/5 transition-colors" style={monoFont}>Cancel</button>
          <button onClick={() => { onSave(localNames, localSettings); onClose(); }} className="px-4 py-2 text-[12px] bg-black text-white rounded-[8px] hover:bg-neutral-800 transition-colors" style={monoFont}>Save</button>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Scene Selector ───────────────────────────────────────────────────────────

function SceneSelectorModal({ scenes, selectedScene, onSelect, onClose }: { scenes: Scene[]; selectedScene: Scene | null; onSelect: (s: Scene) => void; onClose: () => void }) {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-6" onClick={onClose}>
      <div className="w-full max-w-[640px] bg-white rounded-[16px] shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-black/8">
          <div>
            <h2 className="text-[16px]" style={{ ...monoFont, fontWeight: 600 }}>Select Scene</h2>
            <p className="text-[11px] text-black/40 mt-0.5" style={monoFont}>Choose a consultation scenario</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-black/5 rounded-[8px] transition-colors">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div className="p-6 grid grid-cols-2 gap-3">
          {scenes.map((scene) => (
            <button key={scene.id} onClick={() => { onSelect(scene); onClose(); }}
              className={`text-left p-4 border-2 rounded-[12px] transition-all hover:shadow-md ${selectedScene?.id === scene.id ? "border-black" : "border-black/10 hover:border-black/30"}`}>
              <div className="text-2xl mb-2">{scene.icon}</div>
              <div className="text-[13px] mb-1" style={{ ...monoFont, fontWeight: 500 }}>{scene.title}</div>
              <div className="text-[10px] text-black/50 leading-relaxed" style={monoFont}>{scene.description}</div>
            </button>
          ))}
        </div>
        {selectedScene && (
          <div className="px-6 pb-4">
            <button onClick={() => { onSelect(null as unknown as Scene); onClose(); }} className="text-[11px] text-black/30 hover:text-black transition-colors" style={monoFont}>Clear selection</button>
          </div>
        )}
      </div>
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
  const [msgQueue, setMsgQueue] = useState<Array<{ agentKey: AgentKey; content: string; convId: string }>>([]);
  const agentNamesRef = useRef<Record<AgentKey, string>>(DEFAULT_AGENT_NAMES);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [showCustomizer, setShowCustomizer] = useState(false);
  const [customizerInitialAgent, setCustomizerInitialAgent] = useState<AgentKey | null>(null);
  const [showSceneSelector, setShowSceneSelector] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);

  const [emotionOn, setEmotionOn] = useState(false);
  const [emotionTarget, setEmotionTarget] = useState("all");
  const [emotionText, setEmotionText] = useState("");
  const [emotionTag, setEmotionTag] = useState<string | null>(null);
  const [emotionConf, setEmotionConf] = useState(0);
  const [emotionProbs, setEmotionProbs] = useState<Record<string, number>>({});
  const [valence, setValence] = useState(0.5);
  const [arousal, setArousal] = useState(0.5);
  const [control, setControl] = useState(0.5);

  const [agentNames, setAgentNames] = useState<Record<AgentKey, string>>({ ...DEFAULT_AGENT_NAMES });
  const [agentSettings, setAgentSettings] = useState<Record<AgentKey, AgentCustomSetting>>({ A: defaultSetting(), B: defaultSetting(), C: defaultSetting() });
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null);

  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const currentConv = conversations.find((c) => c.id === currentConvId) || null;

  useEffect(() => { if (!localStorage.getItem("agora_auth")) navigate("/"); }, [navigate]);

  useEffect(() => {
    fetch(`${API_BASE}/health`).then((r) => { if (r.ok) setBackendOnline(true); }).catch(() => {});
    fetch("/scenes_config.json").then((r) => r.json()).then((d) => setScenes(d.scenes || [])).catch(() => {});
  }, []);

  useEffect(() => {
    const c = messagesContainerRef.current;
    if (!c) return;
    if (c.scrollHeight - c.scrollTop - c.clientHeight < 120) c.scrollTop = c.scrollHeight;
  }, [conversations, typingKeys]);

  useEffect(() => { agentNamesRef.current = agentNames; }, [agentNames]);

  // Queue processor: typing dot → message → next
  useEffect(() => {
    if (msgQueue.length === 0) { setTypingKeys([]); return; }
    const next = msgQueue[0];
    setTypingKeys([next.agentKey]);
    const timer = setTimeout(() => {
      const agentMsg: Message = { id: `msg-${Date.now()}-${next.agentKey}`, role: "agent", agentKey: next.agentKey, content: next.content, timestamp: Date.now() };
      const names = agentNamesRef.current;
      setConversations((prev) => prev.map((c) => c.id === next.convId ? { ...c, messages: [...c.messages, agentMsg], preview: `${names[next.agentKey]}: ${next.content.slice(0, 60)}…`, timestamp: "just now" } : c));
      setMsgQueue((q) => q.slice(1));
    }, 900);
    return () => clearTimeout(timer);
  }, [msgQueue]);

  const analyzeEmotion = useCallback(async (text: string, v: number, a: number, c: number) => {
    try {
      const res = await fetch(`${API_BASE}/emotion/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, valence: v, arousal: a, control: c }) });
      if (!res.ok) return null;
      const data = await res.json();
      setEmotionTag(data.emotion_tag); setEmotionConf(data.confidence); setEmotionProbs(data.probabilities || {});
      return data;
    } catch { return null; }
  }, []);

  const analyzeEmotionForAgent = useCallback(async (_key: AgentKey, v: number, a: number, c: number) => {
    try {
      const res = await fetch(`${API_BASE}/emotion/analyze`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: "", valence: v, arousal: a, control: c }) });
      if (!res.ok) return null;
      return await res.json();
    } catch { return null; }
  }, []);

  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text || isLoading) return;
    setInputValue("");
    setIsLoading(true);

    const userMsg: Message = { id: `msg-${Date.now()}`, role: "user", content: text, timestamp: Date.now() };
    let convId = currentConvId;
    let roomId = currentConv?.roomId || "";

    if (!convId) {
      try {
        const res = await fetch(`${API_BASE}/start`, { method: "POST", headers: { "Content-Type": "application/json" } });
        roomId = (await res.json()).room_id || "";
      } catch { roomId = ""; }
      const newConv: Conversation = { id: `conv-${Date.now()}`, roomId, title: text.length > 48 ? text.slice(0, 48) + "…" : text, preview: text, timestamp: "just now", messages: [userMsg] };
      setConversations((prev) => [newConv, ...prev]);
      convId = newConv.id;
      setCurrentConvId(convId);
    } else {
      setConversations((prev) => prev.map((c) => c.id === convId ? { ...c, messages: [...c.messages, userMsg], timestamp: "just now" } : c));
    }

    if (emotionOn) analyzeEmotion(text, valence, arousal, control);

    const agentEmotionOverrides: Record<string, string> = {};
    const additionalRules: Record<string, string> = {};
    AGENT_KEYS.forEach((k) => {
      if (agentSettings[k].emotionOn && agentSettings[k].emotionTag) agentEmotionOverrides[k] = agentSettings[k].emotionTag!;
      if (agentSettings[k].additionalPrompt) additionalRules[k] = agentSettings[k].additionalPrompt;
    });

    setTypingKeys(["A"]);
    try {
      const res = await fetch(`${API_BASE}/message`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ room_id: roomId, message: text, emotion_tag: emotionOn ? emotionTag : null, emotion_target: emotionOn ? emotionTarget : null, agent_emotion_overrides: agentEmotionOverrides, additional_rules: additionalRules }) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const responses: Array<{ agent_key: string; message: string }> = data.responses || [];
      if (responses.length === 0) { setTypingKeys([]); }
      else { setMsgQueue(responses.map((r) => ({ agentKey: (r.agent_key || "A") as AgentKey, content: r.message, convId: convId as string }))); }
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
      const messages: Message[] = (data.history || []).map((h: { character: string; txt: string }, i: number) => {
        if (h.character === "user") return { id: `h-${i}`, role: "user" as const, content: h.txt, timestamp: Date.now() - (data.history.length - i) * 1000 };
        const agentKey = BACKEND_NAME_TO_KEY[h.character] ?? "A";
        return { id: `h-${i}`, role: "agent" as const, agentKey, content: h.txt, timestamp: Date.now() - (data.history.length - i) * 1000 };
      });
      setConversations((prev) => prev.map((c) => c.id === currentConvId ? { ...c, messages } : c));
    } catch {}
  };

  const handleNewChat = () => { setCurrentConvId(null); setTypingKeys([]); setMsgQueue([]); setSidebarOpen(false); inputRef.current?.focus(); };
  const handleSelectConv = (id: string) => { setCurrentConvId(id); setTypingKeys([]); setMsgQueue([]); setSidebarOpen(false); };
  const handleLogout = () => { localStorage.removeItem("agora_auth"); navigate("/"); };
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } };

  return (
    <div className="h-screen bg-white flex overflow-hidden">
      <AnimatePresence>
        {showCustomizer && (
          <CustomizerModal agentNames={agentNames} agentSettings={agentSettings}
            onSave={(names, settings) => { setAgentNames(names); setAgentSettings(settings); }}
            onClose={() => { setShowCustomizer(false); setCustomizerInitialAgent(null); }}
            onAnalyze={analyzeEmotionForAgent} initialOpenCard={customizerInitialAgent} />
        )}
        {showSceneSelector && (
          <SceneSelectorModal scenes={scenes} selectedScene={selectedScene} onSelect={setSelectedScene} onClose={() => setShowSceneSelector(false)} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {sidebarOpen && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/20 z-20" onClick={() => setSidebarOpen(false)} />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <aside className={`fixed z-30 h-full bg-white border-r border-black/8 flex flex-col w-[260px] transition-transform duration-300 ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}`}>
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
        <div className="flex-1 overflow-y-auto px-2 py-2 min-h-0">
          {conversations.length === 0 ? (
            <p className="text-center text-black/30 text-[11px] mt-8" style={monoFont}>no conversations yet</p>
          ) : (
            <div className="flex flex-col gap-1">
              {conversations.map((conv) => <ConvItem key={conv.id} conv={conv} isActive={conv.id === currentConvId} onClick={() => handleSelectConv(conv.id)} />)}
            </div>
          )}
        </div>
        <EmotionPanel emotionOn={emotionOn} setEmotionOn={setEmotionOn} emotionTarget={emotionTarget} setEmotionTarget={setEmotionTarget}
          emotionText={emotionText} setEmotionText={setEmotionText} emotionTag={emotionTag} emotionConf={emotionConf} emotionProbs={emotionProbs}
          valence={valence} setValence={setValence} arousal={arousal} setArousal={setArousal} control={control} setControl={setControl}
          agentNames={agentNames} onAnalyze={analyzeEmotion} />
        <div className="relative flex-shrink-0">
          <AnimatePresence>
            {userMenuOpen && <UserMenu nickname={nickname} onCustomize={() => setShowCustomizer(true)} onScene={() => setShowSceneSelector(true)} onLogout={handleLogout} onClose={() => setUserMenuOpen(false)} />}
          </AnimatePresence>
          <button onClick={() => setUserMenuOpen((v) => !v)} className="w-full flex items-center gap-2 px-3 py-4 border-t border-black/8 hover:bg-black/3 transition-colors">
            <div className="w-[7px] h-[7px] rounded-[1.5px] bg-red-500 flex-shrink-0" />
            <span className="flex-1 text-left text-[11px] text-black/50 truncate" style={monoFont}>{(nickname || "you").toUpperCase()}</span>
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
          <div className="flex-1 flex items-center min-w-0">
            {currentConv ? <span className="text-[13px] text-black/70 truncate" style={monoFont}>{currentConv.title}</span>
              : <span className="text-[13px] text-black/30" style={monoFont}>new conversation_</span>}
          </div>
          {currentConv?.roomId && (
            <button onClick={handleLoadHistory} className="text-[10px] text-black/30 hover:text-black border border-black/10 px-2 py-1 rounded-[6px] transition-colors flex-shrink-0 hidden sm:block" style={monoFont}>reload history</button>
          )}
          <div className="flex items-center gap-3 flex-shrink-0">
            {AGENT_KEYS.map((key) => (
              <div key={key} className="flex items-center gap-1.5" title={agentNames[key]}>
                <div className="w-[7px] h-[7px] rounded-[1.5px] bg-black" />
                <span className="hidden sm:block text-[10px] tracking-widest text-black" style={monoFont}>{agentNames[key]}</span>
              </div>
            ))}
          </div>
        </header>

        <div ref={messagesContainerRef} className="flex-1 overflow-y-auto px-4 sm:px-8 py-6">
          {!currentConv ? (
            <div className="w-full max-w-[440px] mx-auto flex flex-col items-center justify-center min-h-[60vh] gap-8">
              <div className="flex flex-col items-center gap-4 w-full">
                <AgoraLogo size={64} />
                <p className="text-center text-[22px] text-black" style={{ ...condensedFont, fontWeight: 500, letterSpacing: "0.12em" }}>agora</p>
                <p className="text-center text-[13px] text-black/40 leading-relaxed" style={monoFont}>
                  {selectedScene ? selectedScene.title : "three agents. one question. controlled divergence."}
                </p>
                {!backendOnline && (
                  <p className="text-center text-[11px] text-amber-500 w-full leading-relaxed border border-amber-200 bg-amber-50 px-3 py-2 rounded-[8px]" style={monoFont}>
                    Backend offline — start with: <strong>python app.py</strong>
                  </p>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3 w-full">
                {AGENT_KEYS.map((key) => (
                  <button key={key} onClick={() => { setCustomizerInitialAgent(key); setShowCustomizer(true); }}
                    className="border border-black/8 rounded-[10px] px-3 py-3 text-left hover:border-black/30 hover:bg-black/2 transition-all group">
                    <div className="flex items-center gap-1.5 mb-1">
                      <div className="w-[6px] h-[6px] rounded-[1.2px] bg-black" />
                      <span className="text-[10px] tracking-widest text-black" style={monoFont}>{agentNames[key]}</span>
                    </div>
                    <p className="text-[10px] text-black/40 group-hover:text-black/60 transition-colors" style={monoFont}>{DEFAULT_AGENT_ROLES[key]}</p>
                    <p className="text-[9px] text-black/20 mt-2 group-hover:text-black/40 transition-colors" style={monoFont}>click to customize →</p>
                  </button>
                ))}
                <button onClick={() => { setCustomizerInitialAgent(null); setShowCustomizer(true); }}
                  className="border border-dashed border-black/15 rounded-[10px] px-3 py-3 flex flex-col items-center justify-center gap-1 hover:border-black/40 hover:bg-black/2 transition-all group min-h-[72px]">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="opacity-20 group-hover:opacity-50 transition-opacity">
                    <path d="M8 1V15M1 8H15" stroke="black" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                  <span className="text-[9px] text-black/20 group-hover:text-black/50 transition-colors" style={monoFont}>customize</span>
                </button>
              </div>
              <div className="w-full">
                <p className="text-[10px] text-black/30 mb-3 text-center tracking-widest" style={monoFont}>SUGGESTED PROMPTS</p>
                <div className="flex flex-col gap-2">
                  {SUGGESTED_PROMPTS.map((prompt, i) => (
                    <button key={i} onClick={() => { setInputValue(prompt); inputRef.current?.focus(); }}
                      className="text-left px-4 py-3 border border-black/8 rounded-[10px] hover:bg-black hover:text-white hover:border-black transition-all duration-200 group">
                      <span className="text-[12px] text-black/60 group-hover:text-white transition-colors" style={monoFont}>{prompt}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="max-w-[680px] mx-auto">
              {currentConv.messages.map((msg) =>
                msg.role === "user" ? <UserMessage key={msg.id} message={msg} nickname={nickname} />
                  : <AgentMessage key={msg.id} message={msg} agentNames={agentNames} onClickAgent={(key) => { setCustomizerInitialAgent(key); setShowCustomizer(true); }} />
              )}
              <AnimatePresence>
                {typingKeys.map((k) => <TypingDots key={k} agentKey={k} agentNames={agentNames} />)}
              </AnimatePresence>
              <div />
            </div>
          )}
        </div>

        <div className="flex-shrink-0 border-t border-black/8 px-4 sm:px-8 py-4">
          <div className="max-w-[680px] mx-auto">
            <div className="flex gap-3 items-end">
              <div className="flex-1 bg-black rounded-[12px] flex items-end px-4 py-3 gap-2">
                <textarea ref={inputRef} value={inputValue} onChange={(e) => setInputValue(e.target.value)} onKeyDown={handleKeyDown}
                  placeholder="Enter a question or topic to explore..." rows={1} disabled={isLoading}
                  className="flex-1 bg-transparent resize-none outline-none text-white placeholder-[#828282] leading-relaxed disabled:opacity-50"
                  style={{ ...monoFont, fontSize: "13px", maxHeight: "120px" }}
                  onInput={(e) => { const el = e.currentTarget; el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; }} />
              </div>
              <button onClick={handleSend} disabled={!inputValue.trim() || isLoading}
                className="h-[48px] w-[48px] bg-black rounded-[12px] flex items-center justify-center flex-shrink-0 hover:bg-neutral-800 transition-colors disabled:opacity-30 disabled:cursor-not-allowed">
                {isLoading ? (
                  <motion.div className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full" animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: "linear" }} />
                ) : (
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 13V3M3 8L8 3L13 8" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                )}
              </button>
            </div>
            <p className="text-center text-[10px] text-black/20 mt-2" style={monoFont}>shift+enter for new line · enter to send</p>
          </div>
        </div>
      </div>
    </div>
  );
}
