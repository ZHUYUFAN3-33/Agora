import type { AgentKey, AgentPoolKey } from "../data/agents";

export const monoFont = { fontFamily: "'Share Tech Mono', monospace" as const };
export const condensedFont = { fontFamily: "'Barlow Condensed', sans-serif" as const };

export const FULL_AGENT_NAMES: Record<AgentKey, string> = { A: "ChatbotA", B: "ChatbotB", C: "ChatbotC" };

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

export const WELCOME_TUTORIAL_STEPS = [
  { title: "Scene", body: "The scene changes the decision context and swaps the suggested prompts to match that situation." },
  { title: "Agents", body: "These cards define who joins the discussion. Open one agent card first, then I will walk through each setup page before we move on." },
  { title: "Basic", body: "This page sets the display name and accent color. It controls how that agent appears in the workspace and chat header." },
  { title: "Emotion", body: "This page shapes tone. Use the sliders to set valence, arousal, and control, or describe a tone in text to infer an emotion tag." },
  { title: "Behavior", body: "This page controls how the agent reasons. Decision style changes response structure, and additional prompt adds extra instructions." },
  { title: "Suggested Prompts", body: "Use one of these to start quickly, or ignore them and write your own question." },
  { title: "Input", body: "Type here to start. Enter sends, Shift+Enter adds a new line, and the settings button opens advanced controls." },
] as const;
