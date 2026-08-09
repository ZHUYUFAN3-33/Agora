# -*- coding: utf-8 -*-
"""
build_stance_knowledge.py
Generates background_templates/stance_knowledge.json from the structured
data below. Run once (or whenever content is edited) to regenerate the
JSON file that stance_knowledge.py actually reads at runtime.
"""
import json

Q = "\u201c"  # left curly quote, used inside zh text to avoid JSON escaping issues
QQ = "\u201d"  # right curly quote


def card(id_, keywords, zh, en, source, source_type, related=None):
    return {
        "id": id_,
        "keywords": keywords,
        "text": {"zh": zh, "en": en},
        "source": source,
        "source_type": source_type,
        "related_cards": related or [],
    }


def fallback(zh, en, source, source_type):
    return {"zh": zh, "en": en, "source": source, "source_type": source_type}


# =========================================================================
# PARENT_CHILD SCENARIO
# =========================================================================

pc_child_centered = [
    card(
        "child_emotional_outburst",
        ["发脾气", "情绪失控", "崩溃", "tantrum", "meltdown", "emotional outburst"],
        f"儿童的情绪失控，很多时候不是{Q}故意不听话{QQ}，而是情绪调节能力还没发展成熟、又缺乏语言表达内心需求的能力时的一种外显方式。年龄越小，这种关联越明显。以上是一般性框架，不是对具体某个孩子的判断。",
        "A child's emotional outbursts are often not willful defiance, but an outward expression of still-developing emotional regulation combined with limited language to express underlying needs. This association is stronger at younger ages. This is a general framework, not a judgment about any specific child.",
        "General developmental psychology framing consistent with emotion-coaching research (cf. Gottman, Katz, & Hooven, 1997, on parental meta-emotion philosophy); for illustrative/educational use only, not a substitute for professional guidance.",
        "academic",
        related=["child_defiance", "relationship_communication_breakdown"],
    ),
    card(
        "child_defiance",
        ["不听话", "叛逆", "对抗", "defiant", "rebellious"],
        f"儿童和青少年阶段性的{Q}不听话{QQ}，常常和发展自主性的心理需求有关，尤其在青春期前后更明显。这不必然代表亲子关系出了问题，也是成长过程的常见部分。以上是一般性框架，不是对具体某个孩子的判断。",
        "Stage-related \u201cdefiance\u201d in children and adolescents is often linked to the developmental need for autonomy, especially around early adolescence. It does not necessarily indicate a problem in the parent-child relationship, and is a common part of development. This is a general framework, not a judgment about any specific child.",
        "General developmental framing consistent with autonomy-support parenting research (cf. Grolnick & Pomerantz, 2009); for illustrative/educational use only, not a substitute for professional guidance.",
        "academic",
        related=["relationship_adolescent_distancing", "parent_power_struggle"],
    ),
    card(
        "child_social_withdrawal",
        ["不合群", "交友困难", "社交退缩", "没朋友", "social withdrawal", "friendship difficulty"],
        "孩子在社交上表现退缩或交友困难，原因可能是气质上偏内向、社交技能仍在发展中，或是在某段关系里经历过挫折后的自我保护反应，三者需要的回应方式并不相同。以上是一般性框架，不是对具体某个孩子的判断。",
        "A child's social withdrawal or difficulty making friends may stem from an introverted temperament, still-developing social skills, or a self-protective reaction following a difficult relational experience \u2014 these three causes call for different kinds of support. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with research on childhood shyness and peer relations (cf. Rubin, Coplan, & Bowker, 2009, on social withdrawal in childhood); for illustrative/educational use only.",
        "academic",
        related=["child_learning_motivation"],
    ),
    card(
        "child_learning_motivation",
        ["不想学习", "学习动力不足", "厌学", "不爱学习", "lack of motivation", "unmotivated to study"],
        "孩子对学习缺乏动力，常见的一个区分是：动力来自外部奖惩（怕被骂、想要奖励）还是内在兴趣（觉得这件事本身有意思）。长期只靠外部奖惩维持的学习行为，动力更容易随着奖惩撤销而消失。以上是一般性框架，不是对具体某个孩子的判断。",
        "A child's lack of motivation to study is often usefully separated into two sources: motivation driven by external reward/punishment versus motivation driven by genuine interest in the activity itself. Learning behavior sustained mainly by external reward tends to fade once that reward is removed. This is a general framework, not a judgment about any specific child.",
        "General framing based on Self-Determination Theory (Ryan & Deci, 2000) on intrinsic versus extrinsic motivation; for illustrative/educational use only.",
        "academic",
        related=["child_device_dependency"],
    ),
    card(
        "child_device_dependency",
        ["离不开手机", "沉迷游戏", "电子设备依赖", "screen addiction", "device dependency"],
        "从孩子的角度看，电子设备/游戏有时承担着社交连接或情绪调节的功能，而不只是娱乐——尤其当现实中的社交或成就感来源有限时，这种依赖可能更多是一种替代满足，而不是单纯的自控力问题。以上是一般性框架，不是对具体某个孩子的判断。",
        "From a child's perspective, devices or games can sometimes serve a social-connection or emotion-regulation function rather than pure entertainment \u2014 especially when other sources of social connection or achievement are limited, making the dependency more of a substitute satisfaction than simply a self-control issue. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with research on adolescent media use and psychosocial needs (cf. Przybylski, Rigby, & Ryan, 2010, on motivational models of video game engagement); for illustrative/educational use only.",
        "academic",
        related=["parent_screen_time", "child_social_withdrawal"],
    ),
]

pc_parent_centered = [
    card(
        "parent_power_struggle",
        ["总是吵架", "亲子矛盾", "冲突", "对抗", "conflict", "argue", "fight"],
        f"家长与孩子反复出现的冲突，常见的诱因之一是双方对{Q}谁来做决定{QQ}这件事本身的争夺感，而不一定是具体事项本身的分歧。识别{Q}这是关于决定权的冲突，还是关于这件事本身的冲突{QQ}，有时比争论对错更有帮助。以上是一般性框架，不是对具体情况的判断。",
        "Recurring parent-child conflict is often driven partly by a struggle over who gets to decide, not only by disagreement on the specific issue itself. Distinguishing \u201ca conflict about decision-making authority\u201d from \u201ca conflict about the issue itself\u201d can sometimes be more useful than arguing over who is right. This is a general framework, not a judgment about a specific situation.",
        "General framing drawn from parenting-style and family-communication literature (cf. Baumrind, 1991, on authoritative vs. authoritarian vs. permissive parenting); for illustrative/educational use only, not a substitute for professional guidance.",
        "academic",
        related=["child_defiance", "relationship_inconsistent_styles"],
    ),
    card(
        "parent_screen_time",
        ["手机", "屏幕时间", "screen time", "phone", "游戏时间"],
        f"关于屏幕使用时间的家庭分歧，通常在{Q}设定清晰、一致的规则{QQ}并{Q}让孩子理解规则背后的原因{QQ}时，比单纯限制时长更容易被孩子接受。以上是一般性框架，不是具体的操作建议。",
        "Family disagreements over screen time are often easier for children to accept when rules are clear and consistent, and when the reasoning behind the rule is explained, rather than relying on limits alone. This is a general framework, not a specific action plan.",
        "General framing consistent with published guidance on screen-time management from pediatric and family-communication research (cf. AAP Council on Communications and Media, 2016); for illustrative/educational use only.",
        "government",
        related=["child_device_dependency"],
    ),
    card(
        "parent_academic_pressure",
        ["学习压力", "成绩压力", "补习", "academic pressure", "study pressure"],
        "家长在管理孩子的学业压力时，一个常见的张力是：家长自身对结果的焦虑，可能会在无意中传递给孩子，让孩子把学业表现和自我价值感过度绑定。区分{Q}家长自己的焦虑{QQ}和{Q}孩子实际的能力/兴趣状况{QQ}，有助于更精准地判断需要调整的是压力管理还是学习方法本身。以上是一般性框架，不是对具体情况的判断。",
        "A common tension in managing a child's academic pressure is that a parent's own anxiety about outcomes can be unintentionally transmitted, leading the child to over-tie academic performance to self-worth. Separating \u201cthe parent's own anxiety\u201d from \u201cthe child's actual ability or interest\u201d can help clarify whether what needs adjusting is pressure management or the learning approach itself. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on parental academic pressure and child anxiety (cf. Pomerantz, Grolnick, & Price, 2005); for illustrative/educational use only.",
        "academic",
        related=["child_learning_motivation"],
    ),
    card(
        "parent_sibling_comparison",
        ["偏心", "多子女", "比较", "手足", "sibling comparison", "favoritism"],
        "多子女家庭中，孩子对{Q}公平{QQ}的感知，往往不完全取决于家长是否真的做到了资源对等分配，也取决于每个孩子是否感到自己作为独立个体被理解，而不是被拿来跟兄弟姐妹比较。以上是一般性框架，不是对具体情况的判断。",
        "In families with multiple children, a child's perception of \u201cfairness\u201d often depends not only on whether resources are literally divided equally, but on whether each child feels understood as an individual rather than being compared to a sibling. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on sibling relationships and parental differential treatment (cf. Suitor et al., 2008); for illustrative/educational use only.",
        "academic",
        related=["parent_power_struggle"],
    ),
    card(
        "parent_financial_stress",
        ["经济压力", "钱不够", "financial stress", "money worries"],
        "经济压力对教养行为的影响，文献里常见的一条路径是：财务压力增加家长的心理负荷和情绪疲惫，进而间接影响教养中的耐心和一致性，而不是经济状况本身直接决定教养质量。理解这条中介路径，有助于把注意力放在压力管理而不只是自责。以上是一般性框架，不是对具体情况的判断。",
        "A commonly documented pathway in the literature is that financial stress increases a parent's psychological load and emotional fatigue, which in turn indirectly affects patience and consistency in parenting \u2014 rather than financial status directly determining parenting quality on its own. Understanding this mediating pathway can help focus attention on stress management rather than self-blame. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with the Family Stress Model (Conger & Conger, 2002); for illustrative/educational use only.",
        "academic",
        related=["parent_academic_pressure"],
    ),
]

pc_relationship_centered = [
    card(
        "relationship_trust_disclosure",
        ["信任", "trust", "隐瞒", "不愿意说"],
        f"亲子之间的信任感，往往更多受{Q}决策过程是否透明{QQ}影响，而不是{Q}最终结果是否符合孩子期待{QQ}。孩子事后是否愿意主动分享类似的事，通常和这次沟通方式的感受有关。以上是一般性框架，不是对具体情况的判断。",
        "Parent-child trust is often shaped more by whether the decision-making process felt transparent than by whether the final outcome matched the child's expectations. Whether a child later chooses to share similar things again is often related to how this conversation felt, not just its result. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with family-communication literature (cf. Kerr & Stattin, 2000, on parental knowledge, child disclosure, and monitoring); for illustrative/educational use only, not a substitute for professional guidance.",
        "academic",
        related=["relationship_communication_breakdown"],
    ),
    card(
        "relationship_communication_breakdown",
        ["沟通不了", "说不上话", "不理我", "communication breakdown", "won't talk to me"],
        f"沟通中断有时不是{Q}孩子不愿意说话{QQ}，而是过去的沟通经验让孩子预期{Q}说了也没用/会被评判{QQ}，转而选择沉默作为自我保护。修复的第一步通常是重建{Q}说了不会被立刻评判{QQ}的安全感，而不是急于获取信息本身。以上是一般性框架，不是对具体情况的判断。",
        f"Communication breakdown is sometimes not a matter of \u201cthe child refusing to talk,\u201d but of past experience leading the child to expect that speaking up \u201cwon't help / will be judged,\u201d leading them to choose silence as self-protection. The first step toward repair is often rebuilding the sense that \u201cspeaking up won't be immediately judged,\u201d rather than rushing to extract information. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with family-communication and emotion-coaching literature (cf. Gottman, Katz, & Hooven, 1997); for illustrative/educational use only.",
        "academic",
        related=["relationship_trust_disclosure", "child_emotional_outburst"],
    ),
    card(
        "relationship_adolescent_distancing",
        ["疏远", "不亲近", "青春期", "adolescent distancing", "pulling away"],
        "青春期孩子在情感上与家长保持一定距离，是发展独立自我认同过程中的常见现象，本身不一定代表关系变差，但需要区分{Q}健康的独立化{QQ}和{Q}关系确实出现裂痕后的回避{QQ}——前者通常伴随孩子仍愿意在需要时求助，后者则伴随更全面的回避。以上是一般性框架，不是对具体情况的判断。",
        f"Adolescents maintaining some emotional distance from parents is a common part of developing an independent identity, and does not by itself indicate a worsening relationship \u2014 but it is worth distinguishing \u201chealthy individuation\u201d from \u201cavoidance following an actual rupture in the relationship,\u201d the former usually still involving the child seeking help when needed, the latter involving more comprehensive avoidance. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with adolescent development literature (cf. Steinberg, 2001, on parent-adolescent relationships in retrospect and prospect); for illustrative/educational use only.",
        "academic",
        related=["child_defiance"],
    ),
    card(
        "relationship_inconsistent_styles",
        ["教育方式不一样", "父母意见不合", "inconsistent parenting", "parents disagree"],
        "父母双方教养风格不一致，对孩子的影响往往不是{Q}哪种风格更好{QQ}，而是不一致本身带来的不可预测性，会让孩子更难形成稳定的行为预期，进而更容易出现在不同家长面前表现不同的情况。以上是一般性框架，不是对具体情况的判断。",
        f"When two parents have inconsistent parenting styles, the impact on the child is often less about \u201cwhich style is better\u201d and more about the unpredictability that inconsistency itself creates, making it harder for the child to form stable behavioral expectations and more likely to behave differently around each parent. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with parenting-style literature on consistency effects (cf. Baumrind, 1991); for illustrative/educational use only.",
        "academic",
        related=["parent_power_struggle"],
    ),
    card(
        "relationship_repair_timing",
        ["什么时候谈", "修复关系", "道歉时机", "repair timing", "when to talk"],
        "亲子关系出现摩擦后，选择修复对话的时机，通常比修复对话的内容本身更容易被忽视——双方都处于情绪激烈状态时展开的对话，即使内容正确，也更容易被当成新一轮冲突，而不是被当成修复。以上是一般性框架，不是对具体情况的判断。",
        "After friction in a parent-child relationship, the timing of a repair conversation is often overlooked relative to its content \u2014 a conversation started while both sides are still emotionally activated is more likely to be experienced as another round of conflict than as repair, even if the content itself is reasonable. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with conflict-repair literature in close relationships (cf. Gottman & Silver, 1999, on repair attempts); for illustrative/educational use only.",
        "academic",
        related=["relationship_communication_breakdown"],
    ),
]

pc_fallbacks = {
    "child_centered": fallback(
        "从孩子的视角出发，通常值得留意的是：这个决定是否让孩子感到自己的想法被听见，而不只是被告知结果。这是一般性提醒，不针对具体情况。",
        "From the child's perspective, it is often worth noting whether the decision makes the child feel heard, not just informed of the outcome. This is a general reminder, not specific to any particular situation.",
        "General framing consistent with child-centered developmental guidance; for illustrative/educational use only.",
        "academic",
    ),
    "parent_centered": fallback(
        f"从家长的视角出发，通常值得留意的是：这个决定的执行成本（时间、精力、一致性）是否现实可持续，而不只是这个决定本身是否{Q}正确{QQ}。这是一般性提醒，不针对具体情况。",
        "From the parent's perspective, it is often worth noting whether the practical cost of following through (time, energy, consistency) is realistically sustainable, not only whether the decision itself is \u201ccorrect.\u201d This is a general reminder, not specific to any particular situation.",
        "General framing; for illustrative/educational use only.",
        "academic",
    ),
    "relationship_centered": fallback(
        "从关系的视角出发，通常值得留意的是：这次决策之后，孩子会怎么理解和记住这次沟通本身，而不只是记住最终结果。这是一般性提醒，不针对具体情况。",
        "From a relationship-centered perspective, it is often worth noting how the child will come to understand and remember this conversation itself, not only the final outcome. This is a general reminder, not specific to any particular situation.",
        "General framing; for illustrative/educational use only.",
        "academic",
    ),
}

# =========================================================================
# EMPLOYMENT SCENARIO
# =========================================================================

emp_growth_centered = [
    card(
        "growth_job_change_timing",
        ["跳槽时机", "该不该跳槽", "job change timing", "when to switch jobs"],
        "职业成长角度评估跳槽时机，一个常见的参考框架是看当前岗位是否还能提供{Q}可衡量的新增能力{QQ}——如果近一年的工作内容高度重复、没有新技能或新责任范围的增长，即使薪酬尚可，也可能已经进入成长停滞期。以上是一般性框架，不是具体的行动建议。",
        f"Evaluating job-change timing from a growth perspective, a common reference framework is whether the current role still offers \u201cmeasurable new capability growth\u201d \u2014 if the past year's work has been highly repetitive with no growth in new skills or scope of responsibility, the role may have entered a growth plateau even if compensation remains adequate. This is a general framework, not a specific action recommendation.",
        "General framing consistent with career development theory (cf. Super, 1980, on career stages and developmental tasks); for illustrative/educational use only.",
        "academic",
        related=["growth_promotion_plateau", "growth_skill_obsolescence"],
    ),
    card(
        "growth_skill_obsolescence",
        ["技能过时", "跟不上", "skill obsolescence", "skills outdated"],
        "判断自身技能是否面临过时风险，比起单纯看行业新闻，更直接的信号是观察本行业近期招聘要求的变化——如果新增岗位持续要求你没有的技能，而你目前的核心技能在新招聘中出现频率下降，这是比较具体的预警信号。以上是一般性框架，不是具体的行动建议。",
        "Assessing the risk of one's skills becoming obsolete is often better done not just by reading industry news, but by observing recent changes in job requirements within the field \u2014 if new postings increasingly require skills you lack while your current core skills appear less often, that is a relatively concrete warning sign. This is a general framework, not a specific action recommendation.",
        "General framing consistent with human capital and career self-management literature (cf. Bandura, 1997, on self-efficacy in career development); for illustrative/educational use only.",
        "academic",
        related=["growth_industry_outlook"],
    ),
    card(
        "growth_industry_outlook",
        ["行业前景", "夕阳行业", "industry outlook", "declining industry"],
        "评估行业前景时，一个常见的误区是只看行业整体规模是否在增长，而忽略了同一个行业内部不同细分方向的前景可能差异很大——一个整体收缩的行业里，仍可能存在增长的细分领域，反之亦然。以上是一般性框架，不是具体的行动建议。",
        "A common pitfall in assessing industry outlook is looking only at whether the industry's overall size is growing, while overlooking that different sub-segments within the same industry can have very different outlooks \u2014 a growing sub-segment can exist within an overall shrinking industry, and vice versa. This is a general framework, not a specific action recommendation.",
        "General framing consistent with labor economics and career transition literature; for illustrative/educational use only.",
        "academic",
        related=["growth_job_change_timing", "stability_industry_cyclical_risk"],
    ),
    card(
        "growth_promotion_plateau",
        ["晋升瓶颈", "升不上去", "promotion plateau", "career stagnation"],
        "晋升瓶颈的成因，文献里常区分为{Q}结构性瓶颈{QQ}（组织层级有限，位置本身稀缺）和{Q}能力性瓶颈{QQ}（当前能力尚未达到晋升要求）——两者需要完全不同的应对策略，前者可能需要换环境，后者可能需要针对性补足能力。以上是一般性框架，不是具体的行动建议。",
        f"The causes of a promotion plateau are often distinguished in the literature between \u201cstructural plateauing\u201d (limited organizational hierarchy, scarce positions) and \u201ccontent plateauing\u201d (current ability not yet meeting promotion requirements) \u2014 these call for very different responses, the former potentially requiring a change of environment, the latter targeted skill-building. This is a general framework, not a specific action recommendation.",
        "General framing consistent with organizational career plateau research (cf. Ference, Stoner, & Warren, 1977, on career plateauing); for illustrative/educational use only.",
        "academic",
        related=["growth_job_change_timing"],
    ),
    card(
        "growth_startup_vs_corporate",
        ["创业", "大厂", "小公司还是大公司", "startup vs corporate", "big company or startup"],
        "在成长导向下比较创业公司和成熟大公司，一个常被忽视的维度是{Q}成长的可验证性{QQ}——大公司的成长路径通常有更明确的评估标准和外部认可（头衔、履历含金量），创业公司的成长可能更实质但更难被外部证明，这个权衡取决于个人对{Q}可验证的成长{QQ}与{Q}实质但难以证明的成长{QQ}的相对重视程度。以上是一般性框架，不是具体的行动建议。",
        f"Comparing startups and established large companies from a growth-oriented lens, an often-overlooked dimension is the \u201cverifiability of growth\u201d \u2014 growth paths at large companies typically have clearer evaluation standards and external recognition (titles, resume credibility), while growth at a startup may be more substantive but harder to externally verify; this trade-off depends on how much one values \u201cverifiable growth\u201d versus \u201csubstantive but hard-to-prove growth.\u201d This is a general framework, not a specific action recommendation.",
        "General framing consistent with career capital and signaling literature in career development research; for illustrative/educational use only.",
        "academic",
        related=["growth_promotion_plateau"],
    ),
]

emp_stability_centered = [
    card(
        "stability_industry_cyclical_risk",
        ["行业周期", "经济波动", "industry cycle", "economic downturn risk"],
        "评估行业的周期性风险，比较直接的方法是看这个行业在过去一到两次经济下行周期中的招聘/裁员波动幅度——波动幅度越大的行业，稳定性权重应该在决策中被更明确地纳入考量，而不只是看当下的招聘热度。以上是一般性框架，不是具体的行动建议。",
        "A relatively direct way to assess an industry's cyclical risk is to look at how much hiring/layoff activity fluctuated in that industry during the past one or two economic downturns \u2014 industries with larger fluctuations should have stability weighted more explicitly in the decision, not just current hiring momentum. This is a general framework, not a specific action recommendation.",
        "General framing consistent with labor economics research on industry cyclicality and employment volatility; for illustrative/educational use only.",
        "academic",
        related=["growth_industry_outlook", "stability_layoff_signals"],
    ),
    card(
        "stability_layoff_signals",
        ["裁员信号", "公司要裁员", "layoff signals", "company downsizing"],
        "识别裁员风险的信号，比起等待正式公告，更早的间接信号通常包括：招聘冻结、非核心项目被叫停、管理层频繁变动、以及绩效考核标准突然收紧。单一信号不足以判断，但多个信号同时出现时值得提高警惕。以上是一般性框架，不是具体的行动建议。",
        "Identifying layoff risk signals earlier than a formal announcement often involves indirect cues such as hiring freezes, non-core projects being halted, frequent management turnover, and a sudden tightening of performance review standards. No single signal is conclusive, but several appearing together warrants increased vigilance. This is a general framework, not a specific action recommendation.",
        "General framing consistent with organizational behavior research on layoff antecedents; for illustrative/educational use only.",
        "academic",
        related=["stability_industry_cyclical_risk"],
    ),
    card(
        "stability_financial_buffer",
        ["财务缓冲", "存款够不够", "financial buffer", "emergency fund"],
        "评估个人在职业变动中的财务缓冲是否充足，常见的参考标准是{Q}至少覆盖3-6个月基本生活支出的可动用储蓄{QQ}，缓冲不足时，冒险决策（如接受不确定性更高的新机会）的实际风险承受能力会明显下降，即使主观上愿意冒险。以上是一般性框架，不是具体的财务建议。",
        f"A common reference standard for assessing whether one's financial buffer is adequate during a career transition is \u201cliquid savings covering at least 3\u20136 months of essential living expenses\u201d \u2014 when the buffer is insufficient, actual risk tolerance for higher-uncertainty decisions (such as accepting a less certain new opportunity) is meaningfully lower even if one is subjectively willing to take the risk. This is a general framework, not specific financial advice.",
        "General framing consistent with personal finance and career-risk literature; for illustrative/educational use only, not a substitute for professional financial advice.",
        "academic",
        related=["stability_layoff_signals"],
    ),
    card(
        "stability_contract_pitfalls",
        ["合同陷阱", "试用期", "contract pitfalls", "probation period"],
        "评估新工作机会时，试用期条款和合同细节里容易被忽略的部分包括：试用期解雇的补偿标准、竞业限制条款的覆盖范围和期限、以及绩效考核标准是否在入职前就已明确书面化。以上是一般性框架，不是具体的法律建议。",
        "When evaluating a new job offer, commonly overlooked details in the contract and probation terms include: compensation standards for termination during probation, the scope and duration of non-compete clauses, and whether performance review criteria are clearly documented in writing before the start date. This is a general framework, not specific legal advice.",
        "General framing consistent with published labor-law guidance from government labor authorities; for illustrative/educational use only, not a substitute for professional legal advice.",
        "government",
        related=["stability_financial_buffer"],
    ),
    card(
        "stability_side_job_balance",
        ["副业", "兼职", "side job", "side hustle balance"],
        "在稳定性考量下评估副业和主业的平衡，一个常见的框架是区分副业的功能：是作为财务缓冲的补充收入来源，还是作为主业不稳定时的{Q}备用选项{QQ}——两种功能对副业投入精力的合理比例要求不同，前者可以适度、后者可能需要更早地投入以确保备用选项真正可行。以上是一般性框架，不是具体的行动建议。",
        f"Evaluating the balance between a side job and main job from a stability perspective, a common framework distinguishes the side job's function: supplementary income as a financial buffer, versus a \u201cbackup option\u201d in case the main job becomes unstable \u2014 these two functions call for different reasonable levels of time investment, the former can be modest, the latter may need earlier investment to ensure the backup option is genuinely viable. This is a general framework, not a specific action recommendation.",
        "General framing consistent with career-risk diversification literature; for illustrative/educational use only.",
        "academic",
        related=["stability_financial_buffer"],
    ),
]

emp_life_centered = [
    card(
        "life_commute_cost",
        ["通勤", "通勤时间", "commute", "commute time"],
        "量化通勤对生活质量的实际影响，一个常用的换算方式是把每日通勤时间乘以一年的工作日数，折算成{Q}一年损失的可支配时间{QQ}——这个数字往往比直觉感受到的更大，值得在比较工作机会时明确纳入计算，而不只是当作背景因素。以上是一般性框架，不是具体的行动建议。",
        f"A common way to quantify the real impact of commuting on quality of life is to multiply daily commute time by the number of working days in a year, converting it into \u201cdisposable time lost per year\u201d \u2014 this figure is often larger than intuitively felt, and is worth explicitly factoring into job comparisons rather than treating as a background consideration. This is a general framework, not a specific action recommendation.",
        "General framing consistent with research on commuting and subjective well-being (cf. Stutzer & Frey, 2008, on the commuting paradox); for illustrative/educational use only.",
        "academic",
        related=["life_relocation_family_impact"],
    ),
    card(
        "life_relocation_family_impact",
        ["异地", "搬家", "relocation", "moving for work"],
        "异地工作对家庭的影响，常见的评估维度不只是地理距离本身，还包括：原有社会支持网络（朋友、亲属照顾资源）的中断程度，以及伴侣/子女适应新环境所需的时间成本，这些成本通常在决策初期容易被低估。以上是一般性框架，不是具体的行动建议。",
        "The family impact of relocating for work is often evaluated not only by physical distance itself, but also by the degree of disruption to an existing social support network (friends, extended-family caregiving resources), and the time cost for a partner or children to adapt to a new environment \u2014 these costs are commonly underestimated early in the decision process. This is a general framework, not a specific action recommendation.",
        "General framing consistent with work-family conflict literature (cf. Greenhaus & Beutell, 1985); for illustrative/educational use only.",
        "academic",
        related=["life_commute_cost"],
    ),
    card(
        "life_burnout_signals",
        ["职业倦怠", "burnout", "工作疲惫", "exhausted from work"],
        "职业倦怠的早期信号，常见的三个维度是：情绪耗竭（长期感觉精力被榨干）、去人格化（对工作和同事产生疏离甚至冷漠）、以及个人成就感降低（觉得自己的工作没有价值）。三者同时出现比单一信号更值得重视。以上是一般性框架，不是具体的行动建议。",
        "Early signs of burnout are commonly described along three dimensions: emotional exhaustion (persistent feeling of being drained), depersonalization (a sense of detachment or even cynicism toward work and colleagues), and reduced personal accomplishment (feeling one's work lacks value). The co-occurrence of all three is more significant than any single signal alone. This is a general framework, not a specific action recommendation.",
        "General framing consistent with the Maslach Burnout Inventory framework (Maslach & Leiter, 2016); for illustrative/educational use only, not a substitute for professional guidance.",
        "academic",
        related=["life_work_intensity_health"],
    ),
    card(
        "life_work_intensity_health",
        ["工作强度", "加班", "身体吃不消", "work intensity", "overtime health impact"],
        "评估工作强度对健康的长期影响，一个常见的参考指标是{Q}工作后是否还有足够的恢复时间{QQ}（睡眠、休息、非工作活动），而不只是每周工时总数本身——同样的工时总数下，缺乏有效恢复时间的工作模式，长期健康风险更高。以上是一般性框架，不是具体的医疗建议。",
        f"A common reference indicator for assessing the long-term health impact of work intensity is whether there is sufficient recovery time after work (sleep, rest, non-work activities), rather than total weekly hours alone \u2014 at the same total hours, a work pattern lacking effective recovery time carries higher long-term health risk. This is a general framework, not specific medical advice.",
        "General framing consistent with occupational health research on work recovery (cf. Sonnentag & Fritz, 2007, on the Recovery Experience Questionnaire); for illustrative/educational use only, not a substitute for professional medical guidance.",
        "academic",
        related=["life_burnout_signals"],
    ),
    card(
        "life_remote_hybrid_tradeoffs",
        ["远程办公", "混合办公", "remote work", "hybrid work tradeoffs"],
        "比较远程、混合、全现场办公模式对生活质量的影响，常被低估的一个维度是{Q}非正式沟通和职业能见度{QQ}的差异——完全远程通常带来更多时间灵活性，但可能减少偶然的、非正式的职业发展机会（比如被更资深的人注意到），这个权衡因人和公司文化而异。以上是一般性框架，不是具体的行动建议。",
        f"Comparing remote, hybrid, and fully on-site work arrangements, an often-underweighted dimension is the difference in \u201cinformal communication and career visibility\u201d \u2014 fully remote work typically offers more time flexibility but may reduce incidental, informal career-development opportunities (such as being noticed by more senior colleagues); this trade-off varies by individual and company culture. This is a general framework, not a specific action recommendation.",
        "General framing consistent with research on remote work and career outcomes; for illustrative/educational use only.",
        "academic",
        related=["life_work_intensity_health"],
    ),
]

emp_fallbacks = {
    "growth_centered": fallback(
        "从职业成长的视角出发，通常值得留意的是：这个选择是否能在可预见的时间内积累出可迁移、可被下一次机会验证的具体能力，而不只是感觉上{Q}忙碌/有挑战{QQ}。这是一般性提醒，不针对具体情况。".replace("{Q}", Q).replace("{QQ}", QQ),
        "From a growth perspective, it is often worth noting whether a choice will build concrete, transferable capability that can be validated by the next opportunity within a foreseeable timeframe, rather than simply feeling \u201cbusy or challenging.\u201d This is a general reminder, not specific to any particular situation.",
        "General framing; for illustrative/educational use only.",
        "academic",
    ),
    "stability_centered": fallback(
        "从稳定性的视角出发，通常值得留意的是：如果这个选择的最坏情况真的发生，实际的财务和生活缓冲能不能撑住，而不只是评估最好情况下的收益。这是一般性提醒，不针对具体情况。",
        "From a stability perspective, it is often worth noting whether one's actual financial and life buffer could withstand the worst-case scenario of this choice, rather than evaluating only the best-case upside. This is a general reminder, not specific to any particular situation.",
        "General framing; for illustrative/educational use only.",
        "academic",
    ),
    "life_centered": fallback(
        "从生活质量的视角出发，通常值得留意的是：这个选择会占用多少本该属于生活其他部分（健康、关系、个人时间）的资源，而不只是这个选择在职业维度上是否划算。这是一般性提醒，不针对具体情况。",
        "From a life-quality perspective, it is often worth noting how much of one's resources for other parts of life (health, relationships, personal time) this choice will consume, rather than evaluating only whether it is a good deal on the career dimension. This is a general reminder, not specific to any particular situation.",
        "General framing; for illustrative/educational use only.",
        "academic",
    ),
}

# =========================================================================
# ASSEMBLE
# =========================================================================

data = {
    "parent_child": {
        "child_centered": {"topic_cards": pc_child_centered, "generic_fallback": pc_fallbacks["child_centered"]},
        "parent_centered": {"topic_cards": pc_parent_centered, "generic_fallback": pc_fallbacks["parent_centered"]},
        "relationship_centered": {"topic_cards": pc_relationship_centered, "generic_fallback": pc_fallbacks["relationship_centered"]},
    },
    "employment": {
        "growth_centered": {"topic_cards": emp_growth_centered, "generic_fallback": emp_fallbacks["growth_centered"]},
        "stability_centered": {"topic_cards": emp_stability_centered, "generic_fallback": emp_fallbacks["stability_centered"]},
        "life_centered": {"topic_cards": emp_life_centered, "generic_fallback": emp_fallbacks["life_centered"]},
    },
}


def _fix_placeholders(obj):
    """Some card text was written without the f-string prefix; fix any
    literal '{Q}'/'{QQ}' placeholders left behind, recursively."""
    if isinstance(obj, str):
        return obj.replace("{Q}", Q).replace("{QQ}", QQ)
    if isinstance(obj, dict):
        return {k: _fix_placeholders(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fix_placeholders(v) for v in obj]
    return obj


data = _fix_placeholders(data)

import os

STANCE_KNOWLEDGE_DIR = os.path.join("background_templates", "stance_knowledge")
os.makedirs(STANCE_KNOWLEDGE_DIR, exist_ok=True)

# This script no longer writes anything: both scenarios now have their own
# generator carrying the current content (28 and 29 cards, with the `tag` field
# the frontend reads).
#
#     parent_child.json  ->  build_parent_child_kb.py
#     employment.json    ->  build_employment_kb.py
#
# The card data further up THIS file is the superseded 15-cards-per-scenario
# version with no `tag`. Regenerating from it silently reverted the knowledge
# base — observed for real on both scenarios in turn. The file is kept as the
# historical source rather than deleted, but it must stay inert.
OWNED_ELSEWHERE = {"parent_child", "employment"}

for scenario_type, stances in data.items():
    if scenario_type in OWNED_ELSEWHERE:
        print(f"Skipped {scenario_type}.json — regenerate it with build_{scenario_type}_kb.py")
        continue
    out_path = os.path.join(STANCE_KNOWLEDGE_DIR, f"{scenario_type}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(stances, f, ensure_ascii=False, indent=2)
    print(f"Written {out_path}")

total_cards = sum(
    len(stance_cfg["topic_cards"])
    for scenario in data.values()
    for stance_cfg in scenario.values()
)
print(f"Written. Total topic cards: {total_cards} (+ {sum(len(s) for s in data.values())} fallbacks)")
