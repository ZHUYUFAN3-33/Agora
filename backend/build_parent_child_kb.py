# -*- coding: utf-8 -*-
"""
build_parent_child_kb.py

Regenerates background_templates/stance_knowledge/parent_child.json.

Changes in this revision:
  - Expanded from 15 -> 28 topic cards (9/10/9 per stance)
  - Added `tag` field (bilingual short label) for frontend capture
  - English keywords brought up to parity with Chinese, incl. colloquial forms
  - related_cards raised to >= 2 edges per card, cross-stance edges prioritized
  - Low-age coverage added (sleep, eating) to align with the four age bands
    used by the Domain Background layer
"""
import json
import os

Q = "\u201c"
QQ = "\u201d"


def card(id_, tag_zh, tag_en, keywords, zh, en, source, related):
    return {
        "id": id_,
        "tag": {"zh": tag_zh, "en": tag_en},
        "keywords": keywords,
        "text": {"zh": zh, "en": en},
        "source": source,
        "source_type": "academic",
        "related_cards": related,
    }


# =========================================================================
# CHILD-CENTERED (9 cards)
# Written from the parent's vantage point: "how your child may be seeing this"
# =========================================================================

child_centered = [
    card(
        "child_emotional_outburst",
        "情绪失控", "Emotional outburst",
        ["发脾气", "情绪失控", "崩溃", "闹脾气", "哭闹",
         "tantrum", "meltdown", "emotional outburst", "blows up", "loses it", "screaming fit"],
        f"儿童的情绪失控，很多时候不是{Q}故意不听话{QQ}，而是情绪调节能力还没发展成熟、又缺乏语言表达内心需求时的一种外显方式。年龄越小，这种关联越明显。以上是一般性框架，不是对具体某个孩子的判断。",
        "A child's emotional outbursts are often not willful defiance, but an outward expression of still-developing emotional regulation combined with limited language to express underlying needs. This association is stronger at younger ages. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with emotion socialization research (cf. Gottman, Katz, & Hooven, 1997, on parental meta-emotion philosophy); for illustrative/educational use only.",
        ["child_sleep", "relationship_communication_breakdown"],
    ),
    card(
        "child_defiance",
        "对抗与自主", "Defiance and autonomy",
        ["不听话", "叛逆", "对抗", "顶嘴", "唱反调",
         "defiant", "rebellious", "won't listen", "talks back", "pushes back", "refuses to listen"],
        f"儿童和青少年阶段性的{Q}不听话{QQ}，常常和发展自主性的心理需求有关，尤其在青春期前后更明显。这不必然代表亲子关系出了问题，也是成长过程的常见部分。以上是一般性框架，不是对具体某个孩子的判断。",
        "Stage-related \u201cdefiance\u201d in children and adolescents is often linked to the developmental need for autonomy, especially around early adolescence. It does not necessarily indicate a problem in the parent-child relationship, and is a common part of development. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with autonomy-support research (cf. Grolnick & Pomerantz, 2009, on parental control and autonomy support); for illustrative/educational use only.",
        ["child_personal_jurisdiction", "relationship_conflict_normativity", "parent_power_struggle"],
    ),
    card(
        "child_personal_jurisdiction",
        "私人领域归类", "Personal jurisdiction",
        ["我的事", "关你什么事", "私人空间", "凭什么管", "自己决定", "隐私",
         "my business", "personal choice", "none of your business", "my own decision",
         "let me decide", "privacy", "stay out of it"],
        f"家长和孩子有时会把同一件事归到不同类别：孩子视之为{Q}属于自己的私人领域{QQ}（穿什么、房间怎么摆、跟谁来往），而家长视之为需要管理的范围。此类冲突的核心常常是归类分歧，而非孩子不服管教本身。以上是一般性框架，不是对具体某个孩子的判断。",
        f"Parents and children sometimes sort the same issue into different categories: the child treats it as belonging to their own personal domain (clothing, their room, who they spend time with), while the parent treats it as within the range of legitimate parental regulation. Such conflicts often turn on this categorical disagreement rather than on defiance as such. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with social domain theory research (cf. Smetana, 2011, on adolescent-parent conflict and domains of social reasoning); for illustrative/educational use only.",
        ["child_defiance", "parent_intensive_norms", "relationship_psychological_control"],
    ),
    card(
        "child_participation_voice",
        "参与和被听见", "Participation and voice",
        ["没人问我", "不听我的", "我说了不算", "为什么不问我", "被决定",
         "no one asked me", "nobody listens to me", "I have no say", "left out of the decision",
         "decided for me"],
        "孩子在多大程度上参与了关于自己的决定，与其对最终结果的接受程度相关：即便结论未变，被征询过意见的孩子通常更容易接受该结论。以上是一般性框架，不是对具体某个孩子的判断。",
        "The degree to which a child participates in decisions about their own life is associated with how readily they accept the outcome: even when the conclusion is unchanged, a child who was consulted tends to accept it more readily. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with child participation research (cf. Lansdown, 2005, on children's participation in decision-making); for illustrative/educational use only.",
        ["relationship_trust_disclosure", "parent_power_struggle", "child_personal_jurisdiction"],
    ),
    card(
        "child_social_withdrawal",
        "社交退缩", "Social withdrawal",
        ["不合群", "交友困难", "社交退缩", "没朋友", "内向", "不爱出门",
         "social withdrawal", "friendship difficulty", "no friends", "shy", "keeps to themselves",
         "won't go out"],
        "孩子在社交上表现退缩或交友困难，可能源于气质上偏内向、社交技能仍在发展中，或是在某段关系里经历挫折后的自我保护反应，三者需要的回应方式并不相同。以上是一般性框架，不是对具体某个孩子的判断。",
        "A child's social withdrawal or difficulty making friends may stem from an introverted temperament, still-developing social skills, or a self-protective reaction following a difficult relational experience \u2014 these call for different kinds of support. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with research on shyness and peer relations in childhood (cf. Rubin, Coplan, & Bowker, 2009, on social withdrawal); for illustrative/educational use only.",
        ["child_learning_motivation", "relationship_shared_time"],
    ),
    card(
        "child_learning_motivation",
        "学习动力", "Learning motivation",
        ["不想学习", "学习动力不足", "厌学", "不爱学习", "推一下动一下", "没兴趣",
         "lack of motivation", "unmotivated to study", "hates school", "only does it when pushed",
         "no interest in learning", "doesn't care about school"],
        "孩子对学习缺乏动力，常见的一个区分是：动力来自外部奖惩，还是来自内在兴趣。长期只靠外部奖惩维持的学习行为，动力更容易随着奖惩撤销而消失。以上是一般性框架，不是对具体某个孩子的判断。",
        "A child's lack of motivation to study is often usefully separated into motivation driven by external reward or punishment versus motivation driven by genuine interest. Learning behavior sustained mainly by external reward tends to fade once that reward is removed. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with self-determination theory research (cf. Ryan & Deci, 2000, on intrinsic and extrinsic motivation); for illustrative/educational use only.",
        ["child_device_dependency", "parent_academic_pressure"],
    ),
    card(
        "child_device_dependency",
        "电子设备依赖", "Device dependency",
        ["离不开手机", "沉迷游戏", "电子设备依赖", "刷个不停", "抱着手机",
         "screen addiction", "device dependency", "glued to the screen", "always on their phone",
         "can't put it down", "gaming all the time"],
        "从孩子的角度看，电子设备与游戏有时承担着社交连接或情绪调节的功能，而不只是娱乐——尤其当现实中的社交或成就感来源有限时，这种依赖可能更多是一种替代满足，而不是单纯的自控力问题。以上是一般性框架，不是对具体某个孩子的判断。",
        "From a child's perspective, devices and games can serve social-connection or emotion-regulation functions rather than pure entertainment \u2014 especially when other sources of connection or achievement are limited, making the dependency more of a substitute satisfaction than simply a self-control issue. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with research on adolescent media engagement and psychosocial needs (cf. Przybylski, Rigby, & Ryan, 2010); for illustrative/educational use only.",
        ["parent_screen_time", "child_social_withdrawal"],
    ),
    card(
        "child_sleep",
        "睡眠与情绪", "Sleep and mood",
        ["睡不好", "熬夜", "赖床", "起不来", "睡眠不足", "白天没精神",
         "sleep", "won't go to bed", "stays up late", "can't wake up", "tired all the time",
         "sleep deprived", "bedtime battles"],
        "睡眠与白天的情绪调节、注意力和行为表现之间是双向关系：睡眠不足会放大情绪反应，而白天的压力与情绪状态也会反过来影响入睡。因此单看行为表现，不容易判断因果方向。以上是一般性框架，不是对具体某个孩子的判断。",
        "Sleep and daytime emotional regulation, attention, and behavior are bidirectionally related: insufficient sleep amplifies emotional reactivity, while daytime stress and mood in turn affect falling asleep. Looking at behavior alone therefore rarely settles the direction of causation. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with pediatric sleep research (cf. Mindell et al., 2006, on behavioral sleep problems in children); for illustrative/educational use only.",
        ["child_emotional_outburst", "parent_burnout"],
    ),
    card(
        "child_eating",
        "进食与压力", "Eating and pressure",
        ["挑食", "不好好吃饭", "喂饭", "追着喂", "吃得少", "偏食",
         "picky eater", "won't eat", "fussy about food", "mealtime struggle",
         "refuses vegetables", "eating battles"],
        "在进食上施加压力（催促、条件交换、强制吃完）往往降低而非提高孩子对该食物的长期接受度。进食冲突有时更多反映的是餐桌上的互动模式，而不是孩子的食物偏好本身。以上是一般性框架，不是对具体某个孩子的判断。",
        "Applying pressure around eating (urging, bargaining, requiring a clean plate) tends to reduce rather than increase a child's long-term acceptance of that food. Mealtime conflict sometimes reflects the interaction pattern at the table more than the child's underlying food preferences. This is a general framework, not a judgment about any specific child.",
        "General framing consistent with child feeding research (cf. Birch, 1999, on the development of food acceptance patterns); for illustrative/educational use only.",
        ["child_emotional_outburst", "parent_burnout"],
    ),
]

# =========================================================================
# PARENT-CENTERED (10 cards)
# Note: five new cards deliberately speak to the parent's own situation,
# not to how the parent should manage the child.
# =========================================================================

parent_centered = [
    card(
        "parent_interparental_conflict",
        "父母间冲突", "Interparental conflict",
        ["夫妻吵架", "两个人意见不合", "当着孩子面吵", "离婚", "分居",
         "we argue", "disagree with my partner", "fighting in front of the kids", "divorce",
         "separated", "co-parenting conflict"],
        "对孩子影响较大的，通常是父母间冲突的暴露程度与解决方式，而非家庭结构本身（如是否离异）。这意味着评估的重点更多在于冲突如何呈现和收尾，而不只是家庭形式。以上是一般性框架，不是对具体情况的判断。",
        "What tends to matter more for children is the degree of exposure to interparental conflict and how that conflict is resolved, rather than family structure itself (such as whether parents are divorced). The focus of assessment is therefore how conflict is expressed and concluded, not only the form the family takes. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on interparental conflict and child adjustment (cf. Amato, 2000, on the consequences of divorce for adults and children); for illustrative/educational use only.",
        ["relationship_inconsistent_styles", "relationship_repair_timing"],
    ),
    card(
        "parent_power_struggle",
        "决定权争夺", "Struggle over authority",
        ["总是吵架", "亲子矛盾", "冲突", "对着干", "较劲", "谁说了算",
         "conflict", "argue", "fight", "power struggle", "butting heads", "who decides",
         "constant battles"],
        f"家长与孩子反复出现的冲突，常见诱因之一是双方对{Q}谁来做决定{QQ}这件事本身的争夺感，而不一定是具体事项本身的分歧。区分{Q}这是关于决定权的冲突，还是关于这件事本身的冲突{QQ}，有时比争论对错更有帮助。以上是一般性框架，不是对具体情况的判断。",
        "Recurring parent-child conflict is often driven partly by a struggle over who gets to decide, not only by disagreement on the specific issue. Distinguishing \u201ca conflict about decision-making authority\u201d from \u201ca conflict about the issue itself\u201d can be more useful than arguing over who is right. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with parenting-style research (cf. Baumrind, 1991, on authoritative, authoritarian, and permissive parenting); for illustrative/educational use only.",
        ["child_personal_jurisdiction", "relationship_inconsistent_styles", "child_participation_voice"],
    ),
    card(
        "parent_screen_time",
        "屏幕时间管理", "Screen time rules",
        ["手机", "屏幕时间", "游戏时间", "限制使用", "收手机", "定规矩",
         "screen time", "phone rules", "gaming limits", "taking the phone away",
         "setting limits", "device rules"],
        f"关于屏幕使用时间的家庭分歧，通常在{Q}规则清晰且前后一致{QQ}并{Q}让孩子理解规则背后的原因{QQ}时，比单纯限制时长更容易被接受。以上是一般性框架，不是具体的操作建议。",
        "Family disagreements over screen time are generally easier to sustain when rules are clear and consistent and the reasoning behind them is explained, rather than relying on time limits alone. This is a general framework, not a specific action plan.",
        "General framing consistent with published guidance on family media use (cf. AAP Council on Communications and Media, 2016); for illustrative/educational use only.",
        ["child_device_dependency", "relationship_warmth_structure"],
    ),
    card(
        "parent_academic_pressure",
        "学业压力传导", "Academic pressure",
        ["学习压力", "成绩压力", "补习", "分数", "排名", "考不好",
         "academic pressure", "study pressure", "grades", "test scores", "tutoring",
         "falling behind", "school performance"],
        f"家长在管理孩子学业压力时，一个常见的张力是：家长自身对结果的焦虑可能在无意中传递给孩子，使孩子把学业表现与自我价值过度绑定。区分{Q}家长自己的焦虑{QQ}与{Q}孩子实际的能力与兴趣状况{QQ}，有助于判断需要调整的是压力管理还是学习方式本身。以上是一般性框架，不是对具体情况的判断。",
        "A common tension in managing a child's academic pressure is that a parent's own anxiety about outcomes can be unintentionally transmitted, leading the child to over-tie performance to self-worth. Separating the parent's own anxiety from the child's actual ability and interest helps clarify whether what needs adjusting is pressure management or the approach to learning. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on parental involvement and child anxiety (cf. Pomerantz, Grolnick, & Price, 2005); for illustrative/educational use only.",
        ["child_learning_motivation", "parent_intensive_norms"],
    ),
    card(
        "parent_sibling_comparison",
        "多子女公平感", "Sibling fairness",
        ["偏心", "多子女", "比较", "手足", "老大老二", "不公平",
         "sibling comparison", "favoritism", "unfair", "playing favorites",
         "comparing siblings", "second child"],
        f"多子女家庭中，孩子对{Q}公平{QQ}的感知，往往不完全取决于资源是否对等分配，也取决于每个孩子是否感到自己作为独立个体被理解，而不是被拿来与兄弟姐妹比较。以上是一般性框架，不是对具体情况的判断。",
        "In families with multiple children, a child's sense of fairness often depends less on whether resources are literally divided equally than on whether each child feels understood as an individual rather than compared to a sibling. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on parental differential treatment (cf. Suitor et al., 2008); for illustrative/educational use only.",
        ["parent_work_family", "relationship_warmth_structure"],
    ),
    card(
        "parent_financial_stress",
        "经济压力", "Financial stress",
        ["经济压力", "钱不够", "负担不起", "开销", "学费",
         "financial stress", "money worries", "can't afford", "tuition costs",
         "tight budget", "expenses"],
        "经济压力对教养行为的影响，文献中常见的一条路径是：财务压力增加家长的心理负荷与情绪疲惫，进而间接影响教养中的耐心与一致性，而非经济状况直接决定教养质量。理解这条中介路径，有助于把注意力放在压力管理而不只是自责。以上是一般性框架，不是对具体情况的判断。",
        "A commonly documented pathway is that financial stress increases a parent's psychological load and emotional fatigue, which in turn indirectly affects patience and consistency in parenting \u2014 rather than financial circumstances directly determining parenting quality. Recognizing this mediating pathway helps direct attention to stress management rather than self-blame. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with the family stress model (cf. Conger & Conger, 2002); for illustrative/educational use only.",
        ["parent_burnout", "parent_work_family"],
    ),
    card(
        "parent_burnout",
        "育儿倦怠", "Parental burnout",
        ["太累了", "撑不住", "精疲力尽", "喘不过气", "育儿倦怠", "没精力",
         "exhausted", "burned out", "can't keep this up", "running on empty",
         "parental burnout", "overwhelmed", "no energy left"],
        "育儿倦怠被描述为一种有别于一般工作倦怠的状态，其风险因素包括长期高投入且缺少恢复时间，而非单纯的育儿时长。识别这一点有助于把{Q}我是不是不够好{QQ}的自我评价，转为对恢复资源是否充足的评估。以上是一般性框架，不是对具体情况的判断。".replace("{Q}", Q).replace("{QQ}", QQ),
        "Parental burnout has been described as a state distinct from general work burnout, with risk factors including sustained high investment combined with insufficient recovery time, rather than caregiving hours alone. Recognizing this can shift the question from \u201cam I not good enough\u201d to whether recovery resources are adequate. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with parental burnout research (cf. Roskam & Mikolajczak, 2017, on the structure of parental burnout); for illustrative/educational use only.",
        ["parent_financial_stress", "parent_work_family", "child_sleep"],
    ),
    card(
        "parent_own_upbringing",
        "自身成长经验", "Own upbringing",
        ["我小时候", "我爸妈就是这样", "不想像我父母", "从小被这样",
         "when I was a kid", "my parents did this", "don't want to repeat", "how I was raised",
         "grew up with this"],
        "养育方式部分承接自家长自身被养育的经验，有时以延续的形式出现，有时以刻意的反向操作出现（例如因自身经历过严格管束而选择放手）。意识到当前做法与自身经历的关联，有助于区分这是对孩子情况的判断，还是对自己经历的回应。以上是一般性框架，不是对具体情况的判断。",
        "Parenting approaches partly carry over from a parent's own upbringing, sometimes as continuity and sometimes as deliberate reversal (for example, choosing to step back because of one's own experience of strict control). Noticing this connection helps distinguish a judgment about the child's situation from a response to one's own history. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with intergenerational transmission of parenting research (cf. Belsky, Conger, & Capaldi, 2009); for illustrative/educational use only.",
        ["parent_intensive_norms", "relationship_inconsistent_styles"],
    ),
    card(
        "parent_intensive_norms",
        "社会规范压力", "Social expectations",
        ["别人家的孩子", "别的家长都", "好家长", "应该做到", "怕被说",
         "other parents", "supposed to", "good parent", "everyone else does",
         "what people will think", "keeping up"],
        f"关于{Q}好家长应该做什么{QQ}的社会规范，会抬高自我要求，使某些本来可行的选项显得不可接受（例如把{Q}少投入一些{QQ}等同于失职）。把规范压力与实际约束分开评估，有助于看清哪些限制来自处境，哪些来自期待。以上是一般性框架，不是对具体情况的判断。",
        "Social norms about what a \u201cgood parent\u201d ought to do can raise self-imposed standards, making otherwise workable options appear unacceptable (for instance, equating investing less with failing the child). Evaluating normative pressure separately from actual constraints helps clarify which limits come from circumstances and which from expectations. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on intensive mothering norms (cf. Hays, 1996, on cultural contradictions of motherhood); for illustrative/educational use only.",
        ["parent_own_upbringing", "parent_academic_pressure", "child_personal_jurisdiction"],
    ),
    card(
        "parent_work_family",
        "工作与家庭分配", "Work-family conflict",
        ["没时间", "加班", "工作忙", "陪不了", "时间不够", "分身乏术",
         "no time", "working late", "too busy", "can't be there", "juggling work and family",
         "time pressure"],
        "时间与精力在工作和家庭之间的分配冲突，通常不是单纯的时间总量问题，也涉及两个领域之间的相互溢出（工作中的疲惫影响在家的耐心，反之亦然）。因此某些教养决定的可行性，取决于当前的溢出状况而不只是日程安排。以上是一般性框架，不是对具体情况的判断。",
        "Conflict over allocating time and energy between work and family is typically not just a matter of total hours, but also of spillover between the two domains (fatigue at work affecting patience at home, and vice versa). The feasibility of certain parenting decisions therefore depends on current spillover conditions, not only on scheduling. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with work-family research (cf. Bianchi & Milkie, 2010, on work and family research in the twenty-first century); for illustrative/educational use only.",
        ["parent_burnout", "relationship_shared_time"],
    ),
]


# =========================================================================
# RELATIONSHIP-CENTERED (9 cards)
# =========================================================================

relationship_centered = [
    card(
        "relationship_trust_disclosure",
        "信任与主动告知", "Trust and disclosure",
        ["信任", "隐瞒", "不愿意说", "什么都不告诉我", "藏着",
         "trust", "hiding things", "won't tell me", "keeps secrets", "shuts me out",
         "doesn't open up"],
        f"亲子之间的信任感，往往更多受{Q}决策过程是否透明{QQ}影响，而不是{Q}最终结果是否符合孩子期待{QQ}。孩子日后是否愿意主动分享类似的事，通常与这次沟通方式带来的感受相关。以上是一般性框架，不是对具体情况的判断。",
        "Parent-child trust is often shaped more by whether the decision-making process felt transparent than by whether the outcome matched the child's expectations. Whether a child later chooses to share similar things again tends to relate to how this exchange felt. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on parental knowledge and child disclosure (cf. Kerr & Stattin, 2000); for illustrative/educational use only.",
        ["relationship_communication_breakdown", "child_participation_voice"],
    ),
    card(
        "relationship_communication_breakdown",
        "沟通中断", "Communication breakdown",
        ["沟通不了", "说不上话", "不理我", "一说就炸", "懒得说",
         "communication breakdown", "won't talk to me", "shuts down", "stonewalls",
         "every conversation turns into a fight", "gives up talking"],
        f"沟通中断有时不是{Q}孩子不愿意说话{QQ}，而是过去的沟通经验让孩子预期{Q}说了也没用或会被评判{QQ}，转而以沉默作为自我保护。修复的第一步通常是重建{Q}说了不会被立刻评判{QQ}的安全感，而非急于获取信息本身。以上是一般性框架，不是对具体情况的判断。",
        "Communication breakdown is sometimes less about a child refusing to talk than about prior experience leading them to expect that speaking up won't help or will be judged, so silence becomes self-protective. The first step toward repair is often rebuilding the sense that speaking up won't be met with immediate judgment, rather than pressing for information. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with family communication research (cf. Gottman, Katz, & Hooven, 1997); for illustrative/educational use only.",
        ["relationship_trust_disclosure", "relationship_psychological_control", "child_emotional_outburst"],
    ),
    card(
        "relationship_adolescent_distancing",
        "青春期疏离", "Adolescent distancing",
        ["疏远", "不亲近", "青春期", "关房门", "不愿意一起",
         "distancing", "pulling away", "adolescence", "closes the door",
         "doesn't want to spend time", "growing apart"],
        f"青春期孩子在情感上与家长保持一定距离，是发展独立自我认同过程中的常见现象，本身不必然代表关系变差；但值得区分{Q}健康的独立化{QQ}与{Q}关系出现裂痕后的回避{QQ}——前者通常伴随孩子在需要时仍愿意求助，后者则伴随更全面的回避。以上是一般性框架，不是对具体情况的判断。",
        "Adolescents keeping some emotional distance is a common part of developing an independent identity and does not by itself indicate a deteriorating relationship; it is worth distinguishing healthy individuation from avoidance following a rupture \u2014 the former usually still involves seeking help when needed, the latter a broader withdrawal. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with adolescent development research (cf. Steinberg, 2001, on parent-adolescent relationships); for illustrative/educational use only.",
        ["relationship_conflict_normativity", "child_defiance"],
    ),
    card(
        "relationship_conflict_normativity",
        "冲突的常态性", "Conflict as normative",
        ["经常吵", "越来越多矛盾", "以前不这样", "是不是不正常",
         "arguing more", "constant conflict lately", "didn't used to be like this",
         "is this normal", "more friction"],
        "亲子冲突的频率在青春期早期上升并达到峰值，属于发展过程中的常态现象；相较之下，冲突的强度与是否得到修复，比冲突的次数更值得关注。以上是一般性框架，不是对具体情况的判断。",
        "The frequency of parent-child conflict tends to rise and peak in early adolescence as a normative developmental pattern; the intensity of conflict and whether it gets repaired are generally more informative than how often it occurs. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with meta-analytic work on parent-adolescent conflict (cf. Laursen, Coy, & Collins, 1998; Laursen & Collins, 2009); for illustrative/educational use only.",
        ["relationship_adolescent_distancing", "relationship_repair_timing", "child_defiance"],
    ),
    card(
        "relationship_psychological_control",
        "心理控制与行为管束", "Psychological vs behavioral control",
        ["让他内疚", "不理他", "冷战", "威胁", "失望", "翻旧账",
         "guilt trip", "silent treatment", "withdrawing affection", "making them feel bad",
         "disappointed in you", "emotional pressure"],
        "对行为层面的管束（规则、界限、监督）与心理层面的控制（内疚诱导、撤回关爱、以情感为条件）在文献中被区分开来，两者与孩子后续适应的关联并不相同。这一区分有助于判断一个做法是在设定界限，还是在施加情感代价。以上是一般性框架，不是对具体情况的判断。",
        "Behavioral control (rules, limits, monitoring) and psychological control (guilt induction, withdrawal of affection, conditional regard) are distinguished in the literature and are not associated with the same downstream adjustment patterns. The distinction helps clarify whether a given approach is setting a limit or imposing an emotional cost. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on psychological control (cf. Barber, 1996, on parental psychological control); for illustrative/educational use only.",
        ["relationship_communication_breakdown", "child_personal_jurisdiction", "relationship_warmth_structure"],
    ),
    card(
        "relationship_inconsistent_styles",
        "父母教养不一致", "Inconsistent parenting",
        ["教育方式不一样", "父母意见不合", "一个唱红脸", "老人插手", "标准不统一",
         "inconsistent parenting", "parents disagree", "good cop bad cop",
         "grandparents interfere", "different rules"],
        f"父母双方教养风格不一致，对孩子的影响往往不在于{Q}哪种风格更好{QQ}，而在于不一致本身带来的不可预测性，使孩子更难形成稳定的行为预期，也更容易出现在不同家长面前表现不同的情况。以上是一般性框架，不是对具体情况的判断。",
        "When two parents have inconsistent styles, what matters is often less which style is better than the unpredictability inconsistency creates, making it harder for the child to form stable expectations and more likely that they behave differently with each parent. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with parenting-style research on consistency (cf. Baumrind, 1991); for illustrative/educational use only.",
        ["parent_interparental_conflict", "parent_power_struggle"],
    ),
    card(
        "relationship_repair_timing",
        "修复时机", "Repair timing",
        ["什么时候谈", "修复关系", "道歉", "缓和", "冷静下来再说",
         "when to talk", "repairing things", "apologize", "cool off first",
         "smooth things over", "make up"],
        "亲子关系出现摩擦后，修复对话的时机往往比对话内容更容易被忽视：双方仍处于情绪激烈状态时展开的对话，即便内容合理，也更容易被体验为新一轮冲突而非修复。以上是一般性框架，不是对具体情况的判断。",
        "After friction, the timing of a repair conversation is often overlooked relative to its content: a conversation begun while both sides are still emotionally activated is more likely to be experienced as another round of conflict than as repair, even when its content is reasonable. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on repair processes in close relationships (cf. Gottman & Silver, 1999); for illustrative/educational use only.",
        ["relationship_conflict_normativity", "relationship_communication_breakdown"],
    ),
    card(
        "relationship_shared_time",
        "共处时间的质量", "Quality of shared time",
        ["陪伴时间", "一起做点什么", "没时间陪", "周末", "多陪陪",
         "time together", "quality time", "spending time with them", "weekends",
         "not around enough", "doing things together"],
        "共同活动与关系质量的关联，不完全取决于相处时长；在同样的时间总量下，活动中的投入程度与互动性质，与关系体验的关联更为紧密。以上是一般性框架，不是对具体情况的判断。",
        "The association between shared activities and relationship quality does not rest on duration alone; at a given amount of time, how engaged the interaction is tends to relate more closely to the experienced quality of the relationship. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with research on parental time and child outcomes (cf. Milkie, Nomaguchi, & Denny, 2015); for illustrative/educational use only.",
        ["parent_work_family", "child_social_withdrawal"],
    ),
    card(
        "relationship_warmth_structure",
        "温暖与规则并存", "Warmth and structure",
        ["太严还是太松", "严格", "放任", "该不该管", "宽松",
         "too strict", "too lenient", "how much to control", "firm or easygoing",
         "rules versus closeness", "being the bad guy"],
        "温暖与规则并非此消彼长的两端：在文献中，教养风格被视为一种整体情境，同一具体做法（如设定一条规则）在温暖的关系背景下与在疏离的关系背景下，与孩子的反应关联并不相同。以上是一般性框架，不是对具体情况的判断。",
        "Warmth and structure are not opposite ends of a single dimension: parenting style is treated in the literature as an overall context, such that the same specific practice (setting a rule, say) relates differently to a child's response depending on whether the relational backdrop is warm or distant. This is a general framework, not a judgment about a specific situation.",
        "General framing consistent with the parenting style as context model (cf. Darling & Steinberg, 1993); for illustrative/educational use only.",
        ["relationship_psychological_control", "parent_screen_time", "parent_sibling_comparison"],
    ),
]


fallbacks = {
    "child_centered": {
        "zh": "从孩子的视角出发，通常值得留意的是：这个决定是否让孩子感到自己的想法被听见，而不只是被告知结果。这是一般性提醒，不针对具体情况。",
        "en": "From the child's perspective, it is often worth noting whether the decision makes the child feel heard rather than simply informed of the outcome. This is a general reminder, not specific to any particular situation.",
        "source": "General framing; for illustrative/educational use only.",
        "source_type": "academic",
        "tag": {"zh": "孩子视角", "en": "Child's perspective"},
    },
    "parent_centered": {
        "zh": f"从家长的视角出发，通常值得留意的是：这个决定的执行成本（时间、精力、一致性）是否现实可持续，而不只是这个决定本身是否{Q}正确{QQ}。这是一般性提醒，不针对具体情况。",
        "en": "From the parent's perspective, it is often worth noting whether the practical cost of following through (time, energy, consistency) is realistically sustainable, not only whether the decision itself is \u201ccorrect.\u201d This is a general reminder, not specific to any particular situation.",
        "source": "General framing; for illustrative/educational use only.",
        "source_type": "academic",
        "tag": {"zh": "家长处境", "en": "Parent's situation"},
    },
    "relationship_centered": {
        "zh": "从关系的视角出发，通常值得留意的是：这次决策之后，孩子会怎么理解和记住这次沟通本身，而不只是记住最终结果。这是一般性提醒，不针对具体情况。",
        "en": "From a relationship-centered perspective, it is often worth noting how the child will come to understand and remember this exchange itself, not only the final outcome. This is a general reminder, not specific to any particular situation.",
        "source": "General framing; for illustrative/educational use only.",
        "source_type": "academic",
        "tag": {"zh": "关系影响", "en": "Relational impact"},
    },
}

data = {
    "child_centered": {"topic_cards": child_centered, "generic_fallback": fallbacks["child_centered"]},
    "parent_centered": {"topic_cards": parent_centered, "generic_fallback": fallbacks["parent_centered"]},
    "relationship_centered": {"topic_cards": relationship_centered, "generic_fallback": fallbacks["relationship_centered"]},
}


def _fix(obj):
    if isinstance(obj, str):
        return obj.replace("{Q}", Q).replace("{QQ}", QQ)
    if isinstance(obj, dict):
        return {k: _fix(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fix(v) for v in obj]
    return obj


data = _fix(data)

out_dir = os.path.join("background_templates", "stance_knowledge")
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "parent_child.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

total = sum(len(v["topic_cards"]) for v in data.values())
print(f"Written {out_path}")
for stance, cfg in data.items():
    print(f"  {stance}: {len(cfg['topic_cards'])} topic cards")
print(f"Total topic cards: {total} (+3 fallbacks)")
