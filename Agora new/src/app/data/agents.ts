export type AgentKey = "A" | "B" | "C";

export const AGENT_KEYS: AgentKey[] = ["A", "B", "C"];

export const DEFAULT_AGENT_NAMES: Record<AgentKey, string> = {
  A: "ChatbotA",
  B: "ChatbotB",
  C: "ChatbotC",
};

export const DEFAULT_AGENT_ROLES: Record<AgentKey, string> = {
  A: "Enthusiastic Advisor",
  B: "Analytical Consultant",
  C: "Skeptical Risk Guard",
};

export const API_BASE = "http://localhost:5001/api";

export const BACKEND_NAME_TO_KEY: Record<string, AgentKey> = {
  ChatbotA: "A",
  ChatbotB: "B",
  ChatbotC: "C",
};

export const SUGGESTED_PROMPTS = [
  "Is free will compatible with determinism?",
  "What makes a life worth living?",
  "Can morality exist without religion?",
  "Is privacy possible in the digital age?",
  "Should humans colonize other planets?",
];

export const EMOTION_EMOJI: Record<string, string> = {
  joy: "😄", anger: "😠", fear: "😨", sadness: "😢", surprise: "😲", disgust: "🤢", neutral: "😐",
};

export const EMOTION_COLORS: Record<string, string> = {
  joy: "#f59e0b", anger: "#ef4444", fear: "#8b5cf6", sadness: "#3b82f6", surprise: "#f97316", disgust: "#22c55e",
};

export const EMOTION_EXAMPLES: Record<string, string[]> = {
  joy: ["Nice! I love that direction.", "This could turn out really well.", "Awesome—let's build on that.", "That sounds exciting!", "Yes! That's the energy."],
  anger: ["No. That's not the right move.", "Stop hesitating and act.", "This is inefficient—fix it now.", "You already know what needs to happen.", "Act. Don't overthink it."],
  fear: ["I'm not fully comfortable with that yet.", "What if this goes wrong?", "Maybe we should double-check first.", "There's uncertainty here.", "Can we reduce the risk?"],
  sadness: ["That feels heavy…", "Let's slow down.", "We don't need to rush.", "One small step at a time.", "It's okay to move gently."],
  surprise: ["Wait—really?", "That wasn't expected.", "Wow, that changes things.", "Interesting twist.", "Okay, that's new."],
  disgust: ["That doesn't feel right.", "I wouldn't go near that.", "This feels off.", "Let's not entertain that.", "No. Drop it."],
};

export interface AgentCustomSetting {
  emotionOn: boolean;
  emotionTag: string | null;
  valence: number;
  arousal: number;
  control: number;
  additionalPrompt: string;
  decisionOn: boolean;
  decisionTrigger: number;
  decisionStyle: "brief" | "detailed" | "structured";
}

export const defaultSetting = (): AgentCustomSetting => ({
  emotionOn: false,
  emotionTag: null,
  valence: 0.5,
  arousal: 0.5,
  control: 0.5,
  additionalPrompt: "",
  decisionOn: false,
  decisionTrigger: 5,
  decisionStyle: "brief",
});

export interface Scene {
  id: string;
  title: string;
  description: string;
  icon: string;
  color: string;
}
