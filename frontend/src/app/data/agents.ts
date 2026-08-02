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
  behaviorSummary: string;
}

export const LIMITED_AGENT_POOL: LimitedAgentProfile[] = [
  {
    key: "A",
    defaultName: "Mia",
    roleDescription: "Opportunity Spotter",
    behaviorSummary: "Bright, upbeat, and quick to spot upside.",
  },
  {
    key: "B",
    defaultName: "Ethan",
    roleDescription: "Evidence Analyzer",
    behaviorSummary: "Cool-headed, skeptical, and hungry for proof.",
  },
  {
    key: "C",
    defaultName: "Noah",
    roleDescription: "Constraint Checker",
    behaviorSummary: "Cautious, tense, and quick to flag risk.",
  },
  {
    key: "D",
    defaultName: "Olivia",
    roleDescription: "Scope Keeper",
    behaviorSummary: "Calm but firm when the group starts drifting.",
  },
  {
    key: "E",
    defaultName: "Grace",
    roleDescription: "Policy Enforcer",
    behaviorSummary: "Strict, uneasy with blur, and checks the rules.",
  },
  {
    key: "F",
    defaultName: "Liam",
    roleDescription: "System Protector",
    behaviorSummary: "Guarded, steady, and protective of stability.",
  },
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

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "/api";

export const BACKEND_NAME_TO_KEY: Record<string, AgentKey> = {
  ChatbotA: "A",
  ChatbotB: "B",
  ChatbotC: "C",
};

export const SCENE_SUGGESTED_PROMPTS: Record<string, string[]> = {
  employment: [
    "I'm choosing between two offers. Can you help me compare growth vs stability vs work-life balance?",
    "What risks am I underweighting if I switch companies within two weeks?",
    "How should I rank salary, growth, and location for this decision?",
    "What clarifying questions should I ask each company before deciding?",
  ],
  parent_child: [
    "I need to decide on a rule for my child's phone use. How do we balance autonomy and safety?",
    "How should I weigh what my child wants against practical constraints?",
    "What does a respectful decision process look like for this parenting choice?",
    "Can you help me separate my child's stated preference from typical age-based assumptions?",
  ],
  scene1: [
    "I need a Black Friday laptop under $1200 for coding and light gaming. What should I prioritize?",
    "Should I buy now during Black Friday or wait for next-gen models in spring?",
    "I'm choosing between battery life and performance. How do I decide for daily office work?",
    "Can you compare MacBook Air, ThinkPad, and gaming laptops for a 3-year horizon?",
  ],
  scene2: [
    "I need a Black Friday phone under $800 with a great camera. What should I compare first?",
    "Should I prioritize battery longevity or camera system for everyday use?",
    "Is last year's flagship a better deal than this year's mid-range phone?",
    "How much should software update policy affect my phone decision?",
  ],
  scene3: [
    "I want Black Friday headphones under $200 for commuting and calls. What should I compare first?",
    "Should I prioritize noise cancellation, comfort, or sound quality for daily use?",
    "Is an older premium ANC model better than a new mid-range option this year?",
    "How should I choose between over-ear headphones and ANC earbuds on a budget?",
  ],
  scene4: [
    "We only have 6 days and mixed budgets. How should we choose an Asia destination everyone accepts?",
    "Can you compare one low-cost, one mid-range, and one premium Asia trip direction?",
    "How should we decide between an urban Asia trip and a nature-focused Asia route?",
    "What is a fair way to split Asia trip costs when people want different hotel standards?",
  ],
  scene5: [
    "We are planning Europe with limited days. Should we do one country deeply or multiple cities quickly?",
    "Can you compare Western Europe vs Eastern Europe for budget, crowd levels, and logistics?",
    "How do we choose between culture-focused cities and nature-heavy routes in Europe?",
    "What itinerary style is better for first-time Europe travel: structured or flexible?",
  ],
  scene6: [
    "We are considering Oceania. How should we choose between Australia, New Zealand, and Pacific islands?",
    "Can you compare one urban, one nature, and one beach-focused Oceania trip option?",
    "How should we handle long-haul flight fatigue and budget trade-offs for Oceania?",
    "What is a realistic 7-day Oceania plan direction with clear priorities?",
  ],
  scene7: [
    "Which wildfire policy should be prioritized first: fuel reduction, early warning, or evacuation infrastructure?",
    "How can a city balance wildfire resilience with budget limits over the next 3 years?",
    "What wildfire policy package could reduce risk without causing strong public pushback?",
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

/** One-line summary for each emotion × decision combination. Used in full-mode agent cards. */
export const EMOTION_DECISION_SUMMARIES: Record<string, Record<DecisionBlock, string>> = {
  joy: {
    Rational: "Upbeat and methodical; weighs pros and cons with clarity.",
    Intuitive: "Cheerful and gut-driven; picks what feels right quickly.",
    Dependent: "Warm and supportive; helps narrow options with care.",
    Avoidant: "Positive and light; keeps it simple, two choices max.",
    Spontaneous: "Eager and decisive; acts fast, minimal deliberation.",
  },
  anger: {
    Rational: "Sharp and direct; cuts through noise with structured logic.",
    Intuitive: "Impatient and instinctive; trusts gut, no second-guessing.",
    Dependent: "Firm but guiding; pushes for clarity with few options.",
    Avoidant: "Blunt and minimal; keeps options limited, moves on.",
    Spontaneous: "Urgent and decisive; acts now, no hesitation.",
  },
  fear: {
    Rational: "Cautious and analytical; weighs risk before deciding.",
    Intuitive: "Anxious but trusting gut; picks despite uncertainty.",
    Dependent: "Uncertain; seeks validation and guidance.",
    Avoidant: "Wary and minimal; keeps choices few, reversible.",
    Spontaneous: "Nervous but quick; decides fast to reduce anxiety.",
  },
  sadness: {
    Rational: "Melancholic but thorough; weighs options carefully.",
    Intuitive: "Gentle and intuitive; picks what feels less heavy.",
    Dependent: "Tender and supportive; seeks shared direction.",
    Avoidant: "Quiet and low; keeps it simple, two paths only.",
    Spontaneous: "Muted but quick; decides fast to reduce burden.",
  },
  surprise: {
    Rational: "Curious and methodical; explores new angles systematically.",
    Intuitive: "Open and instinctive; picks what's unexpectedly right.",
    Dependent: "Intrigued and collaborative; seeks guidance on novelty.",
    Avoidant: "Startled but minimal; keeps choices few, reversible.",
    Spontaneous: "Excited and snap; decides quickly on the twist.",
  },
  disgust: {
    Rational: "Cold and analytical; cuts through what offends.",
    Intuitive: "Dismissive and gut-driven; rejects what feels wrong.",
    Dependent: "Firm but guiding; steers away from bad options.",
    Avoidant: "Rejecting and minimal; keeps options few, clean.",
    Spontaneous: "Sharp and decisive; rejects fast, no fuss.",
  },
  neutral: {
    Rational: "Balanced and methodical; weighs options objectively.",
    Intuitive: "Calm and instinctive; picks what fits context.",
    Dependent: "Even and supportive; helps narrow with guidance.",
    Avoidant: "Neutral and minimal; keeps it simple, reversible.",
    Spontaneous: "Calm and quick; decides fast without bias.",
  },
};

export function getEmotionDecisionSummary(emotionTag: string | null, decisionBlock: DecisionBlock): string {
  const key = (emotionTag || "neutral").toLowerCase();
  const row = EMOTION_DECISION_SUMMARIES[key];
  if (!row) return EMOTION_DECISION_SUMMARIES.neutral[decisionBlock];
  return row[decisionBlock] ?? EMOTION_DECISION_SUMMARIES.neutral[decisionBlock];
}

/** Short role labels for each emotion × decision, used in test-mode agent cards. */
export const EMOTION_DECISION_ROLES: Record<string, Record<DecisionBlock, string>> = {
  joy: {
    Rational: "Opportunity Spotter",
    Intuitive: "Momentum Seeker",
    Dependent: "Encouragement Giver",
    Avoidant: "Lightweight Simplifier",
    Spontaneous: "Energy Booster",
  },
  anger: {
    Rational: "Inefficiency Cutter",
    Intuitive: "Gut Enforcer",
    Dependent: "Pressure Driver",
    Avoidant: "Noise Trimmer",
    Spontaneous: "Action Forcer",
  },
  fear: {
    Rational: "Risk Assessor",
    Intuitive: "Caution Checker",
    Dependent: "Reassurance Seeker",
    Avoidant: "Safety Keeper",
    Spontaneous: "Tension Releaser",
  },
  sadness: {
    Rational: "Burden Weigher",
    Intuitive: "Gentle Guider",
    Dependent: "Support Holder",
    Avoidant: "Load Minimizer",
    Spontaneous: "Relief Seeker",
  },
  surprise: {
    Rational: "Angle Explorer",
    Intuitive: "Novelty Finder",
    Dependent: "Discovery Partner",
    Avoidant: "Scope Containment Keeper",
    Spontaneous: "Twist Chaser",
  },
  disgust: {
    Rational: "Quality Filter",
    Intuitive: "Red-Flag Caller",
    Dependent: "Boundary Setter",
    Avoidant: "Clarity Protector",
    Spontaneous: "Fast Rejector",
  },
  neutral: {
    Rational: "Evidence Balancer",
    Intuitive: "Fit Matcher",
    Dependent: "Steady Supporter",
    Avoidant: "Option Reducer",
    Spontaneous: "Calm Decider",
  },
};

export function getEmotionDecisionRole(emotionTag: string | null, decisionBlock: DecisionBlock): string {
  const key = (emotionTag || "neutral").toLowerCase();
  const row = EMOTION_DECISION_ROLES[key];
  if (!row) return EMOTION_DECISION_ROLES.neutral[decisionBlock];
  return row[decisionBlock] ?? EMOTION_DECISION_ROLES.neutral[decisionBlock];
}

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
  suggestedPrompts?: string[];
}

/** Scenes that use the Agora-2 profile + intake pipeline before /api/start. */
export const AGORA2_SCENE_IDS = ["employment", "parent_child"] as const;
export type Agora2SceneId = (typeof AGORA2_SCENE_IDS)[number];

export function isAgora2SceneId(id: string | null | undefined): id is Agora2SceneId {
  return !!id && (AGORA2_SCENE_IDS as readonly string[]).includes(id);
}
