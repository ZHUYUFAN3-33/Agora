export type AgentKey = "A" | "B" | "C";
export type AgentPoolKey = "A" | "B" | "C" | "D" | "E" | "F";

/** Experiment mode: full = all options, limited = color/name only, single = Agent A only, neutral */
export type ExperimentMode = "full" | "limited" | "single";

export const AGENT_KEYS: AgentKey[] = ["A", "B", "C"];
export const LIMITED_DEFAULT_SELECTED: AgentPoolKey[] = ["A", "D", "E"];

export interface LimitedAgentProfile {
  key: AgentPoolKey;
  defaultName: string;
  roleDescription: string;
}

export const LIMITED_AGENT_POOL: LimitedAgentProfile[] = [
  { key: "A", defaultName: "Mia", roleDescription: "Opportunity Spotter" },
  { key: "B", defaultName: "Ethan", roleDescription: "Evidence Analyzer" },
  { key: "C", defaultName: "Noah", roleDescription: "Constraint Checker" },
  { key: "D", defaultName: "Olivia", roleDescription: "Scope Keeper" },
  { key: "E", defaultName: "Grace", roleDescription: "Policy Enforcer" },
  { key: "F", defaultName: "Liam", roleDescription: "System Protector" },
];

export const DEFAULT_AGENT_NAMES: Record<AgentKey, string> = {
  A: "ChatbotA",
  B: "ChatbotB",
  C: "ChatbotC",
};

export const DEFAULT_AGENT_ROLES: Record<AgentKey, string> = {
  A: "+ + + + +",
  B: "+ + + + +",
  C: "+ + + + +",
};

export const DEFAULT_AGENT_COLORS: Record<AgentKey, string> = {
  A: "#000000",
  B: "#000000",
  C: "#000000",
};

export const API_BASE = "http://localhost:5001/api";

export const BACKEND_NAME_TO_KEY: Record<string, AgentKey> = {
  ChatbotA: "A",
  ChatbotB: "B",
  ChatbotC: "C",
};

export const SCENE_SUGGESTED_PROMPTS: Record<string, string[]> = {
  scene1: [
    "I need a Black Friday laptop under $1200 for coding and light gaming. What should I prioritize?",
    "Should I buy now during Black Friday or wait for next-gen models in spring?",
    "I'm choosing between battery life and performance. How do I decide for daily office work?",
    "Can you compare MacBook Air, ThinkPad, and gaming laptops for a 3-year horizon?",
  ],
  scene4: [
    "I need a Black Friday phone under $800 with a great camera. What should I compare first?",
    "Should I prioritize battery longevity or camera system for everyday use?",
    "Is last year's flagship a better deal than this year's mid-range phone?",
    "How much should software update policy affect my phone decision?",
  ],
  scene5: [
    "I want Black Friday headphones under $200 for commuting and calls. What should I compare first?",
    "Should I prioritize noise cancellation, comfort, or sound quality for daily use?",
    "Is an older premium ANC model better than a new mid-range option this year?",
    "How should I choose between over-ear headphones and ANC earbuds on a budget?",
  ],
  scene2: [
    "We only have 6 days and mixed budgets. How should we choose an Asia destination everyone accepts?",
    "Can you compare one low-cost, one mid-range, and one premium Asia trip direction?",
    "How should we decide between an urban Asia trip and a nature-focused Asia route?",
    "What is a fair way to split costs when people want different hotel standards?",
  ],
  scene6: [
    "We are planning Europe with limited days. Should we do one country deeply or multiple cities quickly?",
    "Can you compare Western Europe vs Eastern Europe for budget, crowd levels, and logistics?",
    "How do we choose between culture-focused cities and nature-heavy routes in Europe?",
    "What itinerary style is better for first-time Europe travel: structured or flexible?",
  ],
  scene7: [
    "We are considering Oceania. How should we choose between Australia, New Zealand, and Pacific islands?",
    "Can you compare one urban, one nature, and one beach-focused Oceania trip option?",
    "How should we handle long-haul flight fatigue and budget trade-offs for Oceania?",
    "What is a realistic 7-day Oceania plan direction with clear priorities?",
  ],
  scene3: [
    "Which wildfire policy should be prioritized first: fuel reduction, early warning, or evacuation infrastructure?",
    "How can a city balance wildfire resilience with budget limits over the next 3 years?",
    "What policy package could reduce risk without causing strong public pushback?",
    "How should we measure whether a wildfire mitigation policy is actually working?",
  ],
  scene8: [
    "What should a city prioritize first for flood preparedness with limited funding?",
    "How do drainage upgrades compare with zoning reform in near-term flood risk reduction?",
    "Can you outline a 3-year flood resilience roadmap with practical milestones?",
    "How should we evaluate whether flood policies are improving response outcomes?",
  ],
  scene9: [
    "With limited budget, should drought policy prioritize demand controls or supply expansion first?",
    "How can we balance agricultural water needs with municipal and environmental priorities?",
    "Can you propose a phased drought policy package with short-term and long-term actions?",
    "What indicators should we track to evaluate drought resilience policy outcomes?",
  ],
};

export const SUGGESTED_PROMPTS = SCENE_SUGGESTED_PROMPTS.scene1;

export const EMOTION_EMOJI: Record<string, string> = {
  joy: "😄", anger: "😠", fear: "😨", sadness: "😢", surprise: "😲", disgust: "🤢", neutral: "😐",
};

// Emotion images in public/Assets/ (fallback to emoji if missing)
export const EMOTION_IMAGES: Record<string, string> = {
  joy: "/Assets/Joy.png",
  anger: "/Assets/Mad.png",
  fear: "/Assets/Fear.png",
  sadness: "/Assets/Sad.png",
  surprise: "/Assets/Suprise.png",
  disgust: "/Assets/Disguted.png",
};

export const EMOTION_COLORS: Record<string, string> = {
  joy: "#f59e0b", anger: "#ef4444", fear: "#8b5cf6", sadness: "#3b82f6", surprise: "#f97316", disgust: "#22c55e",
};

export const DECISION_BLOCKS = ["Rational", "Intuitive", "Dependent", "Avoidant", "Spontaneous"] as const;
export type DecisionBlock = (typeof DECISION_BLOCKS)[number];

export const DECISION_BLOCK_DESCRIPTIONS: Record<DecisionBlock, string> = {
  Rational: "Structured comparison: objective → criteria → trade-offs → conclusion",
  Intuitive: "Fit-driven: anchor to context → pick aligned → light justification",
  Dependent: "Guided support: validate uncertainty → narrow paths → recommend",
  Avoidant: "Simplify: at most two paths → emphasize reversibility",
  Spontaneous: "Fast action: choose quickly → minimal deliberation",
};

export const DECISION_BLOCK_EXAMPLES: Record<DecisionBlock, string[]> = {
  Rational: ["Let's weigh the pros and cons first.", "Here are the main criteria to consider.", "Based on the trade-offs, I'd recommend...", "We need to compare options systematically.", "The objective is clear—now let's evaluate."],
  Intuitive: ["This one just feels right.", "I'd go with that—it fits.", "Trust your gut on this.", "Something about this option clicks.", "It aligns with what you need."],
  Dependent: ["What matters most to you?", "Let me help narrow it down.", "I can suggest a few solid paths.", "Let's focus on what you're comfortable with.", "I'd recommend option A or B."],
  Avoidant: ["Keep it simple—two choices max.", "You can always change later.", "Let's not overcomplicate.", "Either way works—you can reverse.", "Stick to the basics."],
  Spontaneous: ["Just pick one.", "Go for it.", "Don't overthink—decide.", "Quick call: take it.", "Act now."],
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
  emotionText: string;
  additionalPrompt: string;
  decisionBlock: DecisionBlock;
  roleDescription: string;
  accentColor: string;
}

export const defaultSetting = (key?: AgentKey): AgentCustomSetting => ({
  emotionOn: true,
  emotionTag: "joy",
  valence: 0.5,
  arousal: 0.5,
  control: 0.5,
  emotionText: "",
  additionalPrompt: "",
  decisionBlock: "Rational",
  roleDescription: key ? DEFAULT_AGENT_ROLES[key] : "",
  accentColor: key ? DEFAULT_AGENT_COLORS[key] : "#000000",
});

export interface Scene {
  id: string;
  title: string;
  description: string;
  icon: string;
  color: string;
}
