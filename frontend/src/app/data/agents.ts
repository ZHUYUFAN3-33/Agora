export type AgentKey = "A" | "B" | "C" | "D" | "E" | "F";
export type AgentPoolKey = AgentKey;

/** Experiment mode: full = all options, limited = color/name only, single = Agent A only, neutral */
export type ExperimentMode = "full" | "limited" | "single";

/** All possible roster slots (max 6). */
export const ALL_AGENT_KEYS: AgentKey[] = ["A", "B", "C", "D", "E", "F"];
/** Default welcome roster (3 agents). Prefer activeAgentKeys in UI. */
export const AGENT_KEYS: AgentKey[] = ["A", "B", "C"];
export const DEFAULT_ACTIVE_AGENT_KEYS: AgentKey[] = ["A", "B", "C"];
export const MIN_ROSTER_AGENTS = 2;
export const MAX_ROSTER_AGENTS = 6;
export const LIMITED_DEFAULT_SELECTED: AgentPoolKey[] = ["A", "D", "E"];

export function nextFreeAgentKey(active: AgentKey[]): AgentKey | null {
  for (const k of ALL_AGENT_KEYS) {
    if (!active.includes(k)) return k;
  }
  return null;
}

export function backendLabelForKey(key: AgentKey): string {
  return `Chatbot${key}`;
}

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
  D: "ChatbotD",
  E: "ChatbotE",
  F: "ChatbotF",
};

export const DEFAULT_AGENT_ROLES: Record<AgentKey, string> = {
  A: "+ + + + +",
  B: "+ + + + +",
  C: "+ + + + +",
  D: "+ + + + +",
  E: "+ + + + +",
  F: "+ + + + +",
};

export const DEFAULT_AGENT_COLORS: Record<AgentKey, string> = {
  A: "#000000",
  B: "#000000",
  C: "#000000",
  D: "#000000",
  E: "#000000",
  F: "#000000",
};

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "/api";

export const BACKEND_NAME_TO_KEY: Record<string, AgentKey> = {
  ChatbotA: "A",
  ChatbotB: "B",
  ChatbotC: "C",
  ChatbotD: "D",
  ChatbotE: "E",
  ChatbotF: "F",
};

/**
 * Opener chips.
 *
 * These are the app's own words, so they decide what the very first agent turn
 * has to work with. The previous set asked the agents to rank criteria or to
 * compare the options in general — reasonable questions, but ones no topic card
 * is about: measured against the stance knowledge base, the 16 chips below
 * retrieved a card on 1 of 48 (scenario x stance) lookups, and 5 of the 14
 * retrieved turns in real study sessions were a chip pasted verbatim. So every
 * chip here names a concrete concern that some card actually covers, and the
 * four span the three stances rather than asking for all three at once.
 * tests_offline/test_retrieval_eval.py reads this list and reports what it hits.
 */
export const SCENE_SUGGESTED_PROMPTS: Record<string, string[]> = {
  employment: [
    "Five years from now, will I regret whichever one I turn down?",
    "If it does not work out, can I go back? Or is one of these a one-way door?",
    "One option means moving cities, away from my partner. How much should that weigh?",
    "What should I check in the contract and probation period before I decide?",
  ],
  parent_child: [
    "My child keeps saying 'let me decide'. How much of this is actually theirs to decide?",
    "We need phone rules that hold. Where should the screen time limits actually sit?",
    "On this one, am I being too strict or too lenient?",
    "My child says nobody listens to me when we decide things like this. How do I bring them in?",
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

export const SUGGESTED_PROMPTS = SCENE_SUGGESTED_PROMPTS.employment;

/** Chinese suggested prompts (semantic alignment, not literal machine translation). */
export const SCENE_SUGGESTED_PROMPTS_ZH: Record<string, string[]> = {
  employment: [
    "五年后回头看，我会不会后悔现在放弃的那个？",
    "如果去了发现不合适，还能回来吗？还是一条路走到黑？",
    "有个选择要换城市，和伴侣两地分居，这个该怎么权衡？",
    "签之前，合同和试用期条款我该重点看哪些？",
  ],
  parent_child: [
    "孩子总说「自己决定」，这件事到底哪部分该他自己定？",
    "手机和屏幕时间该怎么定规矩，才不会每次都吵起来？",
    "这件事上我是太严还是太松？",
    "孩子说「没人问我」，我该怎么把他的意见放进来？",
  ],
};

export function getSuggestedPrompts(sceneId: string | null | undefined, lang: "en" | "zh" = "en"): string[] {
  const id = sceneId || "employment";
  if (lang === "zh") {
    return SCENE_SUGGESTED_PROMPTS_ZH[id] || SCENE_SUGGESTED_PROMPTS[id] || SUGGESTED_PROMPTS;
  }
  return SCENE_SUGGESTED_PROMPTS[id] || SUGGESTED_PROMPTS;
}

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

/** Chinese one-liners for full-mode agent cards (semantic, not literal MT). */
export const EMOTION_DECISION_SUMMARIES_ZH: Record<string, Record<DecisionBlock, string>> = {
  joy: {
    Rational: "积极且条理清晰；清楚权衡利弊后给出方向。",
    Intuitive: "开朗、凭直觉；很快选中感觉对的选项。",
    Dependent: "温暖支持；细心帮你收窄选项。",
    Avoidant: "轻松正向；尽量简单，最多两个选择。",
    Spontaneous: "积极果断；行动快，少做冗长权衡。",
  },
  anger: {
    Rational: "尖锐直接；用结构化逻辑砍掉干扰。",
    Intuitive: "急躁且凭本能；相信直觉，不做二次猜测。",
    Dependent: "强硬但带引导；推动澄清，选项从简。",
    Avoidant: "直白精简；限制选项，尽快推进。",
    Spontaneous: "紧迫果断；立刻行动，毫不犹豫。",
  },
  fear: {
    Rational: "谨慎分析；先评估风险再决定。",
    Intuitive: "焦虑但仍信直觉；在不确定中仍做选择。",
    Dependent: "不确定；需要确认与引导。",
    Avoidant: "警惕且精简；选项少、可逆。",
    Spontaneous: "紧张但迅速；快决定以降低焦虑。",
  },
  sadness: {
    Rational: "偏沉稳但仍周全；仔细权衡选项。",
    Intuitive: "温和凭感觉；选不那么沉重的方向。",
    Dependent: "柔软支持；寻求共同方向。",
    Avoidant: "安静低负担；保持简单，只有两条路。",
    Spontaneous: "语气克制但行动快；快决定以减轻负担。",
  },
  surprise: {
    Rational: "好奇且有条理；系统探索新角度。",
    Intuitive: "开放凭直觉；抓住意外却契合的选项。",
    Dependent: "兴致高且协作；在新事物上寻求引导。",
    Avoidant: "吃惊但克制；选项少、可逆。",
    Spontaneous: "兴奋且干脆；对转折快速拍板。",
  },
  disgust: {
    Rational: "冷静分析；剔除令人不适的选项。",
    Intuitive: "排斥且凭直觉；拒绝感觉不对的方向。",
    Dependent: "坚定引导；带你远离糟糕选项。",
    Avoidant: "拒绝且精简；选项少而干净。",
    Spontaneous: "干脆果断；快速否决，不纠缠。",
  },
  neutral: {
    Rational: "平衡且有条理；客观权衡选项。",
    Intuitive: "平静凭直觉；选择契合情境的方向。",
    Dependent: "平和支持；在引导下收窄选项。",
    Avoidant: "中性精简；保持简单、可逆。",
    Spontaneous: "平静快速；无偏好地迅速决定。",
  },
};

export function getEmotionDecisionSummary(
  emotionTag: string | null,
  decisionBlock: DecisionBlock,
  lang: "en" | "zh" = "en",
): string {
  const key = (emotionTag || "neutral").toLowerCase();
  const table = lang === "zh" ? EMOTION_DECISION_SUMMARIES_ZH : EMOTION_DECISION_SUMMARIES;
  const row = table[key] || table.neutral;
  return row[decisionBlock] ?? table.neutral[decisionBlock];
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

export const EMOTION_DECISION_ROLES_ZH: Record<string, Record<DecisionBlock, string>> = {
  joy: {
    Rational: "机会发现者",
    Intuitive: "势头追寻者",
    Dependent: "鼓励支持者",
    Avoidant: "轻量简化者",
    Spontaneous: "能量推动者",
  },
  anger: {
    Rational: "低效切除者",
    Intuitive: "直觉执行者",
    Dependent: "压力驱动者",
    Avoidant: "噪音削减者",
    Spontaneous: "行动逼迫者",
  },
  fear: {
    Rational: "风险评估者",
    Intuitive: "谨慎核查者",
    Dependent: "安心寻求者",
    Avoidant: "安全守护者",
    Spontaneous: "张力释放者",
  },
  sadness: {
    Rational: "负担权衡者",
    Intuitive: "温和引导者",
    Dependent: "支持托举者",
    Avoidant: "负荷最小化者",
    Spontaneous: "解脱寻求者",
  },
  surprise: {
    Rational: "角度探索者",
    Intuitive: "新意发现者",
    Dependent: "发现协作者",
    Avoidant: "范围守门者",
    Spontaneous: "转折追逐者",
  },
  disgust: {
    Rational: "质量过滤器",
    Intuitive: "红旗喊停者",
    Dependent: "边界设定者",
    Avoidant: "清晰守护者",
    Spontaneous: "快速否决者",
  },
  neutral: {
    Rational: "证据平衡者",
    Intuitive: "契合匹配者",
    Dependent: "稳健支持者",
    Avoidant: "选项精简者",
    Spontaneous: "冷静决策者",
  },
};

export function getEmotionDecisionRole(
  emotionTag: string | null,
  decisionBlock: DecisionBlock,
  lang: "en" | "zh" = "en",
): string {
  const key = (emotionTag || "neutral").toLowerCase();
  const table = lang === "zh" ? EMOTION_DECISION_ROLES_ZH : EMOTION_DECISION_ROLES;
  const row = table[key] || table.neutral;
  return row[decisionBlock] ?? table.neutral[decisionBlock];
}

export const DECISION_BLOCK_EXAMPLES: Record<DecisionBlock, string[]> = {
  Rational: ["Let's weigh the pros and cons first.", "Here are the main criteria to consider.", "Based on the trade-offs, I'd recommend...", "We need to compare options systematically.", "The objective is clear—now let's evaluate."],
  Intuitive: ["This one just feels right.", "I'd go with that—it fits.", "Trust your gut on this.", "Something about this option clicks.", "It aligns with what you need."],
  Dependent: ["What matters most to you?", "Let me help narrow it down.", "I can suggest a few solid paths.", "Let's focus on what you're comfortable with.", "I'd recommend option A or B."],
  Avoidant: ["Keep it simple—two choices max.", "You can always change later.", "Let's not overcomplicate.", "Either way works—you can reverse.", "Stick to the basics."],
  Spontaneous: ["Just pick one.", "Go for it.", "Don't overthink—decide.", "Quick call: take it.", "Act now."],
};

export const DECISION_BLOCK_EXAMPLES_ZH: Record<DecisionBlock, string[]> = {
  Rational: ["我们先权衡利弊。", "先看这几条主要标准。", "基于这些取舍，我建议…", "需要系统地比较选项。", "目标清楚了——现在来评估。"],
  Intuitive: ["这个就是感觉对。", "我会选那个——更契合。", "这件事可以相信直觉。", "这个选项让人有点击感。", "它和你真正需要的对齐。"],
  Dependent: ["对你来说什么最重要？", "我帮你把选项收窄一点。", "我可以给出几条稳妥路径。", "我们聚焦你更安心的选择。", "我建议 A 或 B。"],
  Avoidant: ["保持简单——最多两个选择。", "以后随时可以改。", "别把事情搞复杂。", "怎么选都行——都可以回头。", "抓住基本面就好。"],
  Spontaneous: ["就选一个。", "冲。", "别想太多——决定。", "快速判断：就它了。", "现在行动。"],
};

export function getDecisionExamples(block: DecisionBlock, lang: "en" | "zh" = "en"): string[] {
  if (lang === "zh") return DECISION_BLOCK_EXAMPLES_ZH[block] || DECISION_BLOCK_EXAMPLES[block] || [];
  return DECISION_BLOCK_EXAMPLES[block] || [];
}

export const EMOTION_EXAMPLES: Record<string, string[]> = {
  joy: ["Nice! I love that direction.", "This could turn out really well.", "Awesome—let's build on that.", "That sounds exciting!", "Yes! That's the energy."],
  anger: ["No. That's not the right move.", "Stop hesitating and act.", "This is inefficient—fix it now.", "You already know what needs to happen.", "Act. Don't overthink it."],
  fear: ["I'm not fully comfortable with that yet.", "What if this goes wrong?", "Maybe we should double-check first.", "There's uncertainty here.", "Can we reduce the risk?"],
  sadness: ["That feels heavy…", "Let's slow down.", "We don't need to rush.", "One small step at a time.", "It's okay to move gently."],
  surprise: ["Wait—really?", "That wasn't expected.", "Wow, that changes things.", "Interesting twist.", "Okay, that's new."],
  disgust: ["That doesn't feel right.", "I wouldn't go near that.", "This feels off.", "Let's not entertain that.", "No. Drop it."],
};

export const EMOTION_EXAMPLES_ZH: Record<string, string[]> = {
  joy: ["太好了，我喜欢这个方向。", "这很可能会顺利展开。", "棒——我们顺着这个往下走。", "听起来很令人振奋！", "对，就是这股劲。"],
  anger: ["不行，这不是正确做法。", "别再犹豫，行动起来。", "这样太低效——现在就改。", "你其实已经知道该做什么。", "做决定，别想太多。"],
  fear: ["我对这个还不太放心。", "万一出问题怎么办？", "也许我们该先再核对一遍。", "这里还有不确定性。", "能不能先把风险降下来？"],
  sadness: ["这感觉有点沉重…", "我们慢一点。", "不必着急。", "一步一步来就好。", "慢慢推进也没关系。"],
  surprise: ["等等——真的吗？", "这有点出乎意料。", "哇，这改变了一些事。", "有意思的转折。", "好吧，这是新情况。"],
  disgust: ["这感觉不对。", "我不会碰那个选项。", "这有点不对劲。", "我们别沿着那条线想。", "不行，放弃它。"],
};

export function getEmotionExamples(tag: string | null | undefined, lang: "en" | "zh" = "en"): string[] {
  const key = (tag || "joy").toLowerCase();
  if (lang === "zh") return EMOTION_EXAMPLES_ZH[key] || EMOTION_EXAMPLES[key] || [];
  return EMOTION_EXAMPLES[key] || [];
}

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
  /** Agora-2 scenario stance override (e.g. growth_centered). */
  stance: string | null;
  /** Per-agent knowledge-base hint (keyword match). */
  hint: string;
}

export const SCENARIO_STANCES: Record<string, { value: string; label: string }[]> = {
  employment: [
    { value: "growth_centered", label: "Growth" },
    { value: "stability_centered", label: "Stability" },
    { value: "life_centered", label: "Work–life" },
  ],
  parent_child: [
    { value: "child_centered", label: "Child" },
    { value: "parent_centered", label: "Parent" },
    { value: "relationship_centered", label: "Relationship" },
  ],
};

export function defaultStanceForKey(scenarioId: string | null | undefined, key: AgentKey, roster: AgentKey[]): string | null {
  const options = scenarioId ? SCENARIO_STANCES[scenarioId] : undefined;
  if (!options?.length) return null;
  const idx = Math.max(0, roster.indexOf(key));
  return options[idx % options.length]?.value ?? options[0].value;
}

export const defaultSetting = (key?: AgentKey): AgentCustomSetting => ({
  emotionOn: true,
  emotionTag: "joy",
  valence: 0.85,
  arousal: 0.65,
  control: 0.6,
  emotionText: "",
  additionalPrompt: "",
  decisionBlock: "Rational",
  roleDescription: key ? DEFAULT_AGENT_ROLES[key] : "",
  accentColor: key ? DEFAULT_AGENT_COLORS[key] : "#000000",
  stance: null,
  hint: "",
});

export interface Scene {
  id: string;
  title: string;
  description: string;
  icon: string;
  color: string;
  suggestedPrompts?: string[];
  /**
   * False when this deployment does not run the scene (AGORA_ALLOWED_SCENARIOS,
   * see backend/study_policy.py). The picker greys it out instead of dropping
   * it, so the roster a participant was briefed on still matches what they see.
   * Undefined from an older backend, which means "no restriction".
   */
  available?: boolean;
}

/** Scenes that use the Agora-2 profile + intake pipeline before /api/start. */
export const AGORA2_SCENE_IDS = ["employment", "parent_child"] as const;
export type Agora2SceneId = (typeof AGORA2_SCENE_IDS)[number];

export function isAgora2SceneId(id: string | null | undefined): id is Agora2SceneId {
  return !!id && (AGORA2_SCENE_IDS as readonly string[]).includes(id);
}
