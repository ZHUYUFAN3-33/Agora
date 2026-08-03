import type { AgentKey, AgentPoolKey } from "../data/agents";
import { getCondensedFont, getTutorialSteps, getUiFont, type UiLang } from "../i18n/ui";

/** @deprecated Prefer getUiFont(lang) — kept for EN-default call sites during migration. */
export const monoFont = { fontFamily: "'Share Tech Mono', monospace" as const };
export const condensedFont = { fontFamily: "'Barlow Condensed', sans-serif" as const };

export function uiFont(lang: UiLang = "en") {
  return getUiFont(lang);
}
export function uiCondensedFont(lang: UiLang = "en") {
  return getCondensedFont(lang);
}

export const FULL_AGENT_NAMES: Record<AgentKey, string> = {
  A: "ChatbotA",
  B: "ChatbotB",
  C: "ChatbotC",
  D: "ChatbotD",
  E: "ChatbotE",
  F: "ChatbotF",
};

export type GuideGradientPalette = {
  edge: string;
  primary: string;
  accent: string;
  shadow: string;
  speed: number;
};
export type GuideGradientColorKey = Exclude<keyof GuideGradientPalette, "speed">;

export const DEFAULT_GUIDE_GRADIENT: GuideGradientPalette = {
  edge: "#111111",
  primary: "#3a3a3a",
  accent: "#8a8a8a",
  shadow: "#111111",
  speed: 4.8,
};
export const GUIDE_FRAME_FILL = "rgba(255,255,255,0.96)";

export const LIMITED_POOL_ACCENT_MAP: Record<AgentPoolKey, string> = {
  A: "#005f73",
  B: "#e9d8a6",
  C: "#ae2012",
  D: "#94d2bd",
  E: "#ee9b00",
  F: "#bb3e03",
};

export type EmotionEmojiPalette = {
  primary: string[];
  accent: string[];
  replaceable: string[];
};

export const EMOTION_EMOJI_VARIANTS: Record<string, EmotionEmojiPalette> = {
  joy: {
    primary: ["😊", "😄", "🙂", "😌", "😁", "😎"],
    accent: ["✨", "🎉", "💫", "🌟", "🥳", "🙌"],
    replaceable: ["😊", "😄", "🙂", "😌", "😁", "😃", "😎", "✨", "🎉", "💫", "🌟", "🥳", "🙌"],
  },
  fear: {
    primary: ["😟", "😰", "😬", "🫣", "😧", "😥"],
    accent: ["⚠️", "💭", "🌀", "❗"],
    replaceable: ["😟", "😰", "😬", "🫣", "😧", "😥", "⚠️", "💭", "🌀", "❗"],
  },
  anger: {
    primary: ["😠", "😤", "🙄", "😒", "😑", "🤨"],
    accent: ["🔥", "💥", "⚡", "‼️"],
    replaceable: ["😠", "😤", "🙄", "😒", "😑", "🤨", "🔥", "💥", "⚡", "‼️"],
  },
  sadness: {
    primary: ["😔", "😞", "🥲", "😢", "😕", "😪"],
    accent: ["💧", "🌧️", "🫧", "🫠"],
    replaceable: ["😔", "😞", "🥲", "😢", "😕", "😪", "💧", "🌧️", "🫧", "🫠"],
  },
  surprise: {
    primary: ["😮", "😲", "🤯", "🫢", "😯", "😳"],
    accent: ["✨", "⚡", "❗", "🪄"],
    replaceable: ["😮", "😲", "🤯", "🫢", "😯", "😳", "✨", "⚡", "❗", "🪄"],
  },
  disgust: {
    primary: ["😬", "🙃", "😑", "🤢", "😖", "😵"],
    accent: ["🚫", "🛑", "⚠️", "🧪"],
    replaceable: ["😬", "🙃", "😑", "🤢", "😖", "😵", "🚫", "🛑", "⚠️", "🧪"],
  },
};

export const EMOJI_REGEX = /[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu;

/** English fallback; prefer getTutorialSteps(lang) from i18n/ui. */
export const WELCOME_TUTORIAL_STEPS = getTutorialSteps("en");
