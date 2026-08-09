/** Lightweight UI i18n for Agora (en | zh). No external i18n library. */

export type UiLang = "en" | "zh";

export const UI_LANG_STORAGE_KEY = "agora.uiLang";

export function normalizeUiLang(v: unknown): UiLang {
  return v === "zh" ? "zh" : "en";
}

export function loadUiLang(): UiLang {
  try {
    return normalizeUiLang(localStorage.getItem(UI_LANG_STORAGE_KEY));
  } catch {
    return "en";
  }
}

export function saveUiLang(lang: UiLang): void {
  try {
    localStorage.setItem(UI_LANG_STORAGE_KEY, lang);
  } catch {
    /* ignore */
  }
  if (typeof document !== "undefined") {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }
}

export function applyDocumentLang(lang: UiLang): void {
  if (typeof document !== "undefined") {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }
}

const LATIN_UI_FONT = "'Share Tech Mono', monospace";
const LATIN_CONDENSED_FONT = "'Barlow Condensed', sans-serif";
const CJK_UI_FONT =
  "'Noto Sans SC', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif";

export function getUiFont(lang: UiLang): { fontFamily: string } {
  return { fontFamily: lang === "zh" ? CJK_UI_FONT : LATIN_UI_FONT };
}

export function getCondensedFont(lang: UiLang): { fontFamily: string } {
  return { fontFamily: lang === "zh" ? CJK_UI_FONT : LATIN_CONDENSED_FONT };
}

/** Label class tweaks for zh: avoid uppercase + wide tracking on CJK. */
export function labelCaseClass(lang: UiLang): string {
  return lang === "zh" ? "tracking-normal normal-case" : "uppercase tracking-widest";
}

type Dict = Record<string, string>;

const en: Dict = {
  // Landing
  "landing.login": "Login",
  "landing.register": "Register",
  "landing.enterCreds": "Enter user ID and password",
  "landing.userIdPh": "User ID (3–32: a-z, 0-9, _ -)",
  "landing.passwordPh": "Password",
  "landing.createAccount": "Create account",
  "landing.pleaseWait": "Please wait…",
  "landing.forgot": "Forgot password? Contact admin.",
  "landing.back": "← back",
  "landing.google": "Continue with Google",
  "landing.apple": "Continue with Apple",
  "landing.or": "OR",
  "landing.continueUserId": "Continue with User ID",
  "landing.authFailed": "Auth failed",

  // Welcome
  "welcome.scene": "SCENE",
  "welcome.agents": "AGENTS",
  "welcome.prompts": "SUGGESTED PROMPTS",
  "welcome.selectScene": "Select a scene",
  "welcome.chooseSceneHint":
    "Choose employment, parent-child, or another scenario before chatting. Nothing starts until you pick one.",
  "welcome.clickChoose": "click to choose scenario →",
  "welcome.clickChange": "click to change scenario →",
  "welcome.intakeReady": "intake ready · click to change →",
  "welcome.sessionN": "· Session {n}",
  "welcome.clickCustomize": "click to customize →",
  "welcome.addAgent": "add agent",
  "welcome.selectedN": "Selected {n}/3",
  "welcome.backendOffline": "Backend offline — start with: python app.py",
  "welcome.intakeRequired": "intake required",
  "welcome.customize": "customize",
  "welcome.clearSelection": "Clear selection",
  "welcome.chooseScenario": "Choose scenario",
  "welcome.scenarioSubtitle": "Employment / Parent-Child",
  "settings.language": "Language",

  // Tutorial
  "tutorial.skip": "skip",
  "tutorial.back": "back",
  "tutorial.next": "next",
  "tutorial.open": "open",
  "tutorial.done": "done",
  "tutorial.continue": "continue",
  "tutorial.scene.title": "Scene",
  "tutorial.scene.body":
    "The scene changes the decision context and swaps the suggested prompts to match that situation.",
  "tutorial.agents.title": "Agents",
  "tutorial.agents.body":
    "These cards define who joins the discussion. Open one agent card first, then I will walk through each setup page before we move on.",
  "tutorial.basic.title": "Basic",
  "tutorial.basic.body":
    "This page sets the display name and accent color. It controls how that agent appears in the workspace and chat header.",
  "tutorial.tone.title": "Tone",
  "tutorial.tone.body":
    "Pick how this agent sounds from the tone list. Example replies update to match your choice.",
  "tutorial.behavior.title": "Behavior",
  "tutorial.behavior.body":
    "This page controls how the agent reasons. Decision style changes response structure.",
  "tutorial.prompts.title": "Suggested Prompts",
  "tutorial.prompts.body":
    "Use one of these to start quickly, or ignore them and write your own question.",
  "tutorial.input.title": "Input",
  "tutorial.input.body":
    "Type here to start. Enter adds a new line; ⌘+Enter / Alt+Enter sends. The settings button opens advanced controls.",

  // Customizer
  "custom.title": "Customize Agent",
  "custom.subtitleSimple": "Configure name and color",
  "custom.cardBasic": "Basic",
  "custom.cardTone": "Tone",
  "custom.cardBehavior": "Behavior",
  "custom.cardsSuffix": "· {n} cards",
  "custom.selectAgent": "Select Agent",
  "custom.cancel": "Cancel",
  "custom.save": "Save",
  "custom.saving": "Saving...",
  "custom.displayName": "Display Name",
  "custom.accentColor": "Accent Color",
  "custom.stanceHintUnbound":
    "Select an Employment or Parent-Child scene for live knowledge matching. Showing Employment stance options for now.",
  "custom.basicStance": "Basic Stance",
  "custom.knowledgeHint": "Knowledge Hint",
  "custom.knowledgeHelp":
    'Topic keywords for this agent (optional). Partial phrases work — e.g. "job change".',
  "custom.knowledgePh": "e.g. job change, burnout, commute",
  "custom.noKnowledge": "no knowledge matched",
  "custom.matchedTopic": "matched topic",
  "custom.tone": "Tone",
  "custom.toneHelp": "Choose how this agent sounds",
  "custom.examples": "Example responses",
  "custom.decisionStyle": "Decision making style",
  "custom.decisionHelp": "Reasoning style for this agent",

  // Chat chrome
  "chat.newChat": "new chat",
  "chat.mode": "MODE",
  "chat.multi": "Multi agent",
  "chat.multi2": "Multi-2",
  "chat.single": "Single agent",
  "chat.noConversations": "no conversations yet",
  "chat.offline": "offline",
  "chat.newConversation": "new conversation_",
  "chat.turnN": "Turn {n}",
  "chat.phase": "· Phase: {phase}",
  "chat.you": "You",
  "chat.agents": "Agents",
  "chat.addAgent": "Add agent",
  "chat.removeAgent": "Remove {name}",
  "chat.inputPh": "Enter a question or topic to explore...",
  "chat.inputHint": "Enter for new line · ⌘+Enter / Alt+Enter to send",
  "chat.addFiles": "Add photos and files",
  "chat.justNow": "just now",
  "chat.pastSession": "Past session",
  "chat.phasePrefix": "Phase: {phase}",
  "chat.knowledgeUsed": "Background used",

  // Settings
  "settings.customizeAgent": "Customize Agent",
  "settings.customizeScene": "Customize Scene",
  "settings.reloadHistory": "Reload history",
  "settings.decisionSummary": "Decision summary",
  "settings.exportLog": "Export log",
  "settings.pastMemory": "Past session memory",
  "settings.account": "Account",
  "settings.admin": "Admin",
  "settings.help": "Help",
  "settings.logout": "Logout",
  "settings.fontColor": "Font color",

  // Summary
  "summary.title": "Decision summary",
  "summary.session": "Session {id}",
  "summary.generating": "Generating…",
  "summary.regenerate": "Regenerate",
  "summary.tryAgain": "Try again",
  "summary.generate": "Generate",
  "summary.reading": "Reading this session's log and drafting the direction summary…",
  "summary.idle":
    "Generate a short decision-direction summary for this session. Nothing is requested until you press Generate.",
  "summary.close": "Close summary",

  // Layers / hover
  "layer.decision": "Decision Layer",
  "layer.emotion": "Emotion Layer",
  "layer.scene": "Scene Layer",
  "layer.hint":
    "Layer annotation: select text, then choose Decision, Emotion, or Scene. Press x to exit.",
  "layer.clearAll": "Clear all",
  "hover.emotion": "Tone",
  "hover.decision": "Decision",
  "hover.resetTag": "reset tone",
  "hover.advanced": "advance setting",
  "hover.prevDecision": "Previous decision style",
  "hover.nextDecision": "Next decision style",

  // Appearance
  "appearance.title": "Font color",
  "appearance.subtitle": "Adjust secondary text color for readability on different screens",
  "appearance.secondary": "Secondary text color",
  "appearance.reset": "Reset",
  "appearance.done": "Done",
  "appearance.presetDeep": "Deeper",
  "appearance.presetDark": "Dark gray",
  "appearance.presetMid": "Mid gray",
  "appearance.presetLight": "Light gray",

  // Errors
  "err.selectScene": "Select a scene first — do not start without choosing your scenario.",
  "err.limited3": "Limited mode requires selecting exactly 3 agents.",
  "err.profile": "Complete your profile before chatting.",
  "err.intake": "Complete session intake for this scene before chatting.",
  "err.createSession": "Failed to create session. Please try again.",
  "err.noRoom": "No room_id from server. Please try again.",
  "err.backendDown": "Backend is not running. Start with: python app.py",
  "err.sessionExpired": "Session expired after server restart. Please start a new conversation.",
  "err.generic": "Something went wrong. Please try again.",
  "err.export": "Export failed",
  "err.exportBackend": "Export failed — is the backend running?",
  "err.summary": "Could not generate summary",
  "err.summaryBackend": "Summary failed — is the backend running?",

  // Stance
  "stance.growth_centered": "Growth",
  "stance.stability_centered": "Stability",
  "stance.life_centered": "Work–life",
  "stance.child_centered": "Child",
  "stance.parent_centered": "Parent",
  "stance.relationship_centered": "Relationship",

  // Tone
  "tone.joy": "Joy",
  "tone.anger": "Anger",
  "tone.fear": "Fear",
  "tone.sadness": "Sadness",
  "tone.surprise": "Surprise",
  "tone.disgust": "Disgust",
  "tone.neutral": "Neutral",

  // Decision
  "decision.Rational": "Rational",
  "decision.Intuitive": "Intuitive",
  "decision.Dependent": "Dependent",
  "decision.Avoidant": "Avoidant",
  "decision.Spontaneous": "Spontaneous",
  "decision.desc.Rational": "Structured comparison: objective → criteria → trade-offs → conclusion",
  "decision.desc.Intuitive": "Fit-driven: anchor to context → pick aligned → light justification",
  "decision.desc.Dependent": "Guided support: validate uncertainty → narrow paths → recommend",
  "decision.desc.Avoidant": "Simplify: at most two paths → emphasize reversibility",
  "decision.desc.Spontaneous": "Fast action: choose quickly → minimal deliberation",

  // Phase
  "phase.Exploration": "Exploration",
  "phase.Structuring": "Structuring",
  "phase.Narrowing": "Narrowing",
  "phase.Convergence": "Convergence",
  "phase.Concluded": "Concluded",
  "phase.Integration": "Integration",
  "phase.Evaluation": "Evaluation",

  // Decision navi
  "navi.title": "Decision path",
  "navi.subtitle": "Key turns in this discussion",
  "navi.collapse": "Collapse decision path",
  "navi.start": "Started",
  "navi.topic": "Topic shift",
  "navi.userCall": "Your call",
  "navi.currentPhase": "Current phase",
  "navi.phaseFrom": "from {from}",

  // Decision map
  "map.title": "Decision map",
  "map.subtitle": "Topics, stances, and conclusions",
  "map.close": "Close decision map",
  "map.refresh": "Refresh",
  "map.loading": "Loading…",
  "map.extract": "Deepen",
  "map.extracting": "Extracting…",
  "map.extractHint": "Run LLM extract to refine branches and relations",
  "map.phases": "Phases",
  "map.topics": "Topics",
  "map.stances": "Stances",
  "map.conclusion": "Conclusion",
  "map.annotations": "Notes",
  "map.empty": "Send a message to start the map.",
  "map.noStances": "No stance nodes for this topic yet.",
  "map.noConclusion": "No conclusion yet — generate a summary to fill this in.",
  "map.noAnnotations": "No notes yet.",
  "map.annotationPh": "Add a note…",
  "map.addAnnotation": "Add",
  "map.deleteAnnotation": "Delete note",
  "map.promoteLayers": "Import decision highlights",
  "map.edge.supports": "supports",
  "map.edge.challenges": "challenges",
  "map.edge.extends": "extends",
  "map.edge.emerged_from": "emerged from",
  "map.edge.parallel_with": "parallel with",
  "map.edge.merged_into": "merged into",
  "map.status.open": "open",
  "map.status.active": "active",
  "map.status.concluded": "done",
  "map.status.parked": "parked",
  "map.zoomIn": "Zoom in",
  "map.zoomOut": "Zoom out",
  "map.fit": "Fit",
  "map.selectHint": "Select a node to inspect · drag empty space to pan · ⌘/Ctrl+scroll to zoom",
  "map.jumpEvidence": "Jump to evidence",
  "map.issues": "Issues",
  "map.claims": "Claims",
  "map.subtitleSmart": "Issues, claims, support & oppose",
  "map.insufficient": "Not enough discussion yet — chat a bit more, then open the map again.",
  "map.emptySmart": "Building the map…",
  "map.status.leaning": "leaning",
  "map.status.settled": "settled",
  "map.resizeFrame": "Drag to resize issue frame",
  "map.params": "Parameters",
  "map.param.type": "Type",
  "map.param.label": "Label",
  "map.param.status": "Status",
  "map.param.summary": "Summary",
  "map.param.phase": "Phase",
  "map.param.claims": "Claims",
  "map.param.winning": "Winning claim",
  "map.param.speaker": "Speaker",
  "map.param.text": "Text",
  "map.param.badge": "Badge",
  "map.param.issue": "Parent issue",
  "map.param.supports": "Supports",
  "map.param.opposes": "Opposes",
  "map.param.supportedBy": "Supported by",
  "map.param.opposedBy": "Opposed by",
  "map.param.evidence": "Evidence msgs",
  "map.param.none": "—",
  "map.jumpClaim": "Jump to claim",
  "map.closeParams": "Close parameters",
  "map.errorLoad": "Failed to load decision map",
  "map.errorExtract": "Extract failed",
  "map.edge.opposes": "opposes",
  "map.options": "Options",
  "map.status.chosen": "chosen",
  "map.status.rejected": "not chosen",
  "map.param.proposedBy": "Proposed by",
  "map.param.optionStatus": "Option status",
  "map.legend.chosen": "chosen",
  "map.legend.supports": "supports",
  "map.legend.opposes": "opposes",
  "chat.choseOption": "Chose: {label}",
  "chat.optionsPickHint": "Tap an option",
  "chat.optionLocked": "Already chosen",
};

const zh: Dict = {
  "landing.login": "登录",
  "landing.register": "注册",
  "landing.enterCreds": "请输入用户 ID 与密码",
  "landing.userIdPh": "用户 ID（3–32：字母数字 _ -）",
  "landing.passwordPh": "密码",
  "landing.createAccount": "创建账号",
  "landing.pleaseWait": "请稍候…",
  "landing.forgot": "忘记密码？请联系管理员。",
  "landing.back": "← 返回",
  "landing.google": "使用 Google 继续",
  "landing.apple": "使用 Apple 继续",
  "landing.or": "或",
  "landing.continueUserId": "使用用户 ID 继续",
  "landing.authFailed": "登录失败",

  "welcome.scene": "场景",
  "welcome.agents": "智能体",
  "welcome.prompts": "推荐提问",
  "welcome.selectScene": "选择场景",
  "welcome.chooseSceneHint": "请先选择就职或亲子等场景；未选场景前不会开始对话。",
  "welcome.clickChoose": "点击选择场景 →",
  "welcome.clickChange": "点击更换场景 →",
  "welcome.intakeReady": "问卷已就绪 · 点击修改 →",
  "welcome.sessionN": "· 第 {n} 次会话",
  "welcome.clickCustomize": "点击自定义 →",
  "welcome.addAgent": "添加智能体",
  "welcome.selectedN": "已选 {n}/3",
  "welcome.backendOffline": "后端未连接 — 请运行：python app.py",
  "welcome.intakeRequired": "需填写问卷",
  "welcome.customize": "自定义",
  "welcome.clearSelection": "清除选择",
  "welcome.chooseScenario": "选择场景",
  "welcome.scenarioSubtitle": "就职 / 亲子",
  "settings.language": "语言",

  "tutorial.skip": "跳过",
  "tutorial.back": "上一步",
  "tutorial.next": "下一步",
  "tutorial.open": "打开",
  "tutorial.done": "完成",
  "tutorial.continue": "继续",
  "tutorial.scene.title": "场景",
  "tutorial.scene.body": "场景会切换决策语境，并替换与之匹配的推荐提问。",
  "tutorial.agents.title": "智能体",
  "tutorial.agents.body":
    "这些卡片决定谁参与讨论。请先打开一张智能体卡片，我会带你过完各设置页。",
  "tutorial.basic.title": "基础",
  "tutorial.basic.body": "本页设置显示名称与强调色，影响工作区与聊天顶栏的展示。",
  "tutorial.tone.title": "语气",
  "tutorial.tone.body": "从列表选择该智能体的说话语气；示例回复会随选择更新。",
  "tutorial.behavior.title": "行为",
  "tutorial.behavior.body": "本页控制推理方式与决策风格，影响回答结构。",
  "tutorial.prompts.title": "推荐提问",
  "tutorial.prompts.body": "可点一条快速开始，也可忽略并自己写问题。",
  "tutorial.input.title": "输入",
  "tutorial.input.body":
    "在此输入以开始。Enter 换行；⌘+Enter / Alt+Enter 发送。设置按钮打开高级选项。",

  "custom.title": "自定义智能体",
  "custom.subtitleSimple": "配置名称与颜色",
  "custom.cardBasic": "基础",
  "custom.cardTone": "语气",
  "custom.cardBehavior": "行为",
  "custom.cardsSuffix": "· {n} 页",
  "custom.selectAgent": "选择智能体",
  "custom.cancel": "取消",
  "custom.save": "保存",
  "custom.saving": "保存中…",
  "custom.displayName": "显示名称",
  "custom.accentColor": "强调色",
  "custom.stanceHintUnbound":
    "请先选择就职或亲子场景以启用实时知识匹配。暂以就职立场选项预览。",
  "custom.basicStance": "基本立场",
  "custom.knowledgeHint": "知识提示",
  "custom.knowledgeHelp": "为本智能体填写主题关键词（可选）。支持短语片段，例如「跳槽」「加班」。",
  "custom.knowledgePh": "例如：跳槽时机、加班",
  "custom.noKnowledge": "未匹配到知识",
  "custom.matchedTopic": "已匹配主题",
  "custom.tone": "语气",
  "custom.toneHelp": "选择该智能体的说话语气",
  "custom.examples": "示例回复",
  "custom.decisionStyle": "决策风格",
  "custom.decisionHelp": "该智能体的推理风格",

  "chat.newChat": "新对话",
  "chat.mode": "模式",
  "chat.multi": "多智能体",
  "chat.multi2": "多智能体-2",
  "chat.single": "单智能体",
  "chat.noConversations": "暂无对话",
  "chat.offline": "离线",
  "chat.newConversation": "新对话_",
  "chat.turnN": "第 {n} 轮",
  "chat.phase": "· 阶段：{phase}",
  "chat.you": "你",
  "chat.agents": "智能体",
  "chat.addAgent": "添加智能体",
  "chat.removeAgent": "移除 {name}",
  "chat.inputPh": "输入要探讨的问题或主题…",
  "chat.inputHint": "Enter 换行 · ⌘+Enter / Alt+Enter 发送",
  "chat.addFiles": "添加图片和文件",
  "chat.justNow": "刚刚",
  "chat.pastSession": "历史会话",
  "chat.phasePrefix": "阶段：{phase}",
  "chat.knowledgeUsed": "使用的参考知识",

  "settings.customizeAgent": "自定义智能体",
  "settings.customizeScene": "自定义场景",
  "settings.reloadHistory": "重新加载历史",
  "settings.decisionSummary": "决策摘要",
  "settings.exportLog": "导出日志",
  "settings.pastMemory": "历史会话记忆",
  "settings.account": "账户",
  "settings.admin": "管理",
  "settings.help": "帮助",
  "settings.logout": "退出登录",
  "settings.fontColor": "字体颜色",

  "summary.title": "决策摘要",
  "summary.session": "会话 {id}",
  "summary.generating": "生成中…",
  "summary.regenerate": "重新生成",
  "summary.tryAgain": "重试",
  "summary.generate": "生成",
  "summary.reading": "正在阅读本会话日志并起草方向摘要…",
  "summary.idle": "生成本次决策方向的简短摘要… 点击「生成」后才会请求。",
  "summary.close": "关闭摘要",

  "layer.decision": "决策层",
  "layer.emotion": "情绪层",
  "layer.scene": "场景层",
  "layer.hint": "层标注：选中文本后选择决策、情绪或场景。按 x 退出。",
  "layer.clearAll": "全部清除",
  "hover.emotion": "语气",
  "hover.decision": "决策",
  "hover.resetTag": "重置语气",
  "hover.advanced": "高级设置",
  "hover.prevDecision": "上一个决策风格",
  "hover.nextDecision": "下一个决策风格",

  "appearance.title": "字体颜色",
  "appearance.subtitle": "调整次要文字颜色，改善不同屏幕下的可读性",
  "appearance.secondary": "次要文字颜色",
  "appearance.reset": "重置",
  "appearance.done": "完成",
  "appearance.presetDeep": "较深",
  "appearance.presetDark": "深灰",
  "appearance.presetMid": "中灰",
  "appearance.presetLight": "浅灰",

  "err.selectScene": "请先选择场景，未选场景无法开始。",
  "err.limited3": "限定模式需恰好选择 3 个智能体。",
  "err.profile": "请先完成用户档案再开始聊天。",
  "err.intake": "请先完成本场景的会话问卷再开始聊天。",
  "err.createSession": "创建会话失败，请重试。",
  "err.noRoom": "服务器未返回会话 ID，请重试。",
  "err.backendDown": "后端未运行。请执行：python app.py",
  "err.sessionExpired": "服务器重启后会话已失效，请新建对话。",
  "err.generic": "出了点问题，请重试。",
  "err.export": "导出失败",
  "err.exportBackend": "导出失败 — 后端是否在运行？",
  "err.summary": "无法生成摘要",
  "err.summaryBackend": "摘要失败 — 后端是否在运行？",

  "stance.growth_centered": "成长",
  "stance.stability_centered": "稳定",
  "stance.life_centered": "生活平衡",
  "stance.child_centered": "子女",
  "stance.parent_centered": "父母",
  "stance.relationship_centered": "关系",

  "tone.joy": "愉悦",
  "tone.anger": "愤怒",
  "tone.fear": "担忧",
  "tone.sadness": "低落",
  "tone.surprise": "惊讶",
  "tone.disgust": "反感",
  "tone.neutral": "平静",

  "decision.Rational": "理性",
  "decision.Intuitive": "直觉",
  "decision.Dependent": "依赖",
  "decision.Avoidant": "回避",
  "decision.Spontaneous": "冲动",
  "decision.desc.Rational": "结构化比较：目标 → 标准 → 权衡 → 结论",
  "decision.desc.Intuitive": "情境契合：锚定语境 → 选对齐项 → 轻量说明",
  "decision.desc.Dependent": "引导支持：确认不确定 → 收窄路径 → 给出建议",
  "decision.desc.Avoidant": "简化：最多两条路径 → 强调可逆",
  "decision.desc.Spontaneous": "快速行动：迅速选择 → 少做权衡",

  "phase.Exploration": "探索",
  "phase.Structuring": "梳理",
  "phase.Narrowing": "收窄",
  "phase.Convergence": "收敛",
  "phase.Concluded": "已结束",
  "phase.Integration": "整合",
  "phase.Evaluation": "评估",

  "navi.title": "决策轨迹",
  "navi.subtitle": "这场讨论的关键节点",
  "navi.collapse": "收起决策轨迹",
  "navi.start": "开始",
  "navi.topic": "话题节点",
  "navi.userCall": "你的表态",
  "navi.currentPhase": "当前阶段",
  "navi.phaseFrom": "从 {from}",

  "map.title": "决策地图",
  "map.subtitle": "话题、立场与结论",
  "map.close": "关闭决策地图",
  "map.refresh": "刷新",
  "map.loading": "加载中…",
  "map.extract": "深化",
  "map.extracting": "抽取中…",
  "map.extractHint": "用模型抽取补充分支与关系",
  "map.phases": "阶段",
  "map.topics": "话题",
  "map.stances": "立场",
  "map.conclusion": "结论",
  "map.annotations": "备注",
  "map.empty": "发一条消息后即可生成地图。",
  "map.noStances": "这个话题还没有立场节点。",
  "map.noConclusion": "还没有结论 — 生成摘要后会出现在这里。",
  "map.noAnnotations": "暂无备注。",
  "map.annotationPh": "添加备注…",
  "map.addAnnotation": "添加",
  "map.deleteAnnotation": "删除备注",
  "map.promoteLayers": "导入决策高亮",
  "map.edge.supports": "支持",
  "map.edge.challenges": "挑战",
  "map.edge.extends": "延伸",
  "map.edge.emerged_from": "源自",
  "map.edge.parallel_with": "并行",
  "map.edge.merged_into": "并入",
  "map.status.open": "开放",
  "map.status.active": "进行中",
  "map.status.concluded": "已结",
  "map.status.parked": "搁置",
  "map.zoomIn": "放大",
  "map.zoomOut": "缩小",
  "map.fit": "适应",
  "map.selectHint": "点选节点查看详情 · 拖空白平移 · ⌘/Ctrl+滚轮缩放",
  "map.jumpEvidence": "跳到证据",
  "map.issues": "议题",
  "map.claims": "主张",
  "map.subtitleSmart": "议题、主张、支持与反对",
  "map.insufficient": "讨论还太少 — 再聊几轮后再打开决策地图。",
  "map.emptySmart": "正在生成地图…",
  "map.status.leaning": "倾向",
  "map.status.settled": "已定",
  "map.resizeFrame": "拖动调整议题框大小",
  "map.params": "参数",
  "map.param.type": "类型",
  "map.param.label": "标题",
  "map.param.status": "状态",
  "map.param.summary": "摘要",
  "map.param.phase": "阶段",
  "map.param.claims": "主张数",
  "map.param.winning": "领先主张",
  "map.param.speaker": "发言者",
  "map.param.text": "内容",
  "map.param.badge": "标记",
  "map.param.issue": "所属议题",
  "map.param.supports": "支持",
  "map.param.opposes": "反对",
  "map.param.supportedBy": "被支持",
  "map.param.opposedBy": "被反对",
  "map.param.evidence": "证据消息",
  "map.param.none": "—",
  "map.jumpClaim": "跳到主张",
  "map.closeParams": "关闭参数面板",
  "map.errorLoad": "决策地图加载失败",
  "map.errorExtract": "抽取失败",
  "map.edge.opposes": "反对",
  "map.options": "选项",
  "map.status.chosen": "已选",
  "map.status.rejected": "未选",
  "map.param.proposedBy": "提出者",
  "map.param.optionStatus": "选项状态",
  "map.legend.chosen": "已选",
  "map.legend.supports": "支持",
  "map.legend.opposes": "反对",
  "chat.choseOption": "选择了：{label}",
  "chat.optionsPickHint": "点选一个选项",
  "chat.optionLocked": "已选择",
};

const TABLES: Record<UiLang, Dict> = { en, zh };

export function t(lang: UiLang, key: string, vars?: Record<string, string | number>): string {
  const table = TABLES[lang] || en;
  let s = table[key] ?? en[key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      s = s.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
    }
  }
  return s;
}

export function phaseLabel(lang: UiLang, phase: string | null | undefined): string {
  if (!phase) return "";
  const key = `phase.${phase}`;
  const localized = t(lang, key);
  return localized === key ? phase : localized;
}

export const TONE_KEYS = ["joy", "anger", "fear", "sadness", "surprise", "disgust"] as const;
export type ToneKey = (typeof TONE_KEYS)[number];

export function toneOptions(lang: UiLang): { value: string; label: string }[] {
  return TONE_KEYS.map((k) => ({ value: k, label: t(lang, `tone.${k}`) }));
}

export function toneLabel(lang: UiLang, tag: string | null | undefined): string {
  const key = (tag || "joy").toLowerCase();
  const k = `tone.${key}`;
  const localized = t(lang, k);
  return localized === k ? key : localized;
}

/** Silent V/A/C centroids so legacy APIs still receive floats. */
export const TONE_DEFAULT_SLIDERS: Record<string, { valence: number; arousal: number; control: number }> = {
  joy: { valence: 0.85, arousal: 0.65, control: 0.6 },
  anger: { valence: 0.2, arousal: 0.85, control: 0.55 },
  fear: { valence: 0.25, arousal: 0.75, control: 0.3 },
  sadness: { valence: 0.2, arousal: 0.35, control: 0.35 },
  surprise: { valence: 0.55, arousal: 0.8, control: 0.4 },
  disgust: { valence: 0.25, arousal: 0.55, control: 0.5 },
  neutral: { valence: 0.5, arousal: 0.5, control: 0.5 },
};

export function defaultsForTone(tag: string | null | undefined) {
  const key = (tag || "joy").toLowerCase();
  return TONE_DEFAULT_SLIDERS[key] || TONE_DEFAULT_SLIDERS.joy;
}

export type TutorialStep = { title: string; body: string };

export function getTutorialSteps(lang: UiLang): TutorialStep[] {
  const ids = ["scene", "agents", "basic", "tone", "behavior", "prompts", "input"] as const;
  return ids.map((id) => ({
    title: t(lang, `tutorial.${id}.title`),
    body: t(lang, `tutorial.${id}.body`),
  }));
}
