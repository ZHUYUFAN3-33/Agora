# -*- coding: utf-8 -*-
"""
stance.py

Implements the Stance dimension discussed for Agora AI:
  - WHO speaks for which interest/priority in a multi-perspective decision.
  - Forced binding: for scenario types listed in STANCE_ASSIGNMENTS, agent
    A/B/C are ALWAYS assigned the fixed stance below, overriding whatever
    (if anything) was written in info.jsonl. Scenario types not listed here
    (e.g. any future single-decision-maker scenario) simply get no stance
    at all — assign_stance() returns None and callers skip the block.

Two scenarios are wired up:
  parent_child : child_centered / parent_centered / relationship_centered
                 (three different interest-holders in the decision)
  employment   : growth_centered / stability_centered / life_centered
                 (three competing priorities within the same decision-maker)

All prompt text is bilingual (zh/en) via lang_utils.pick().
"""
from __future__ import annotations

from typing import Dict, List, Optional

from lang_utils import normalize_lang, pick

# -------------------------------------------------------------------------
# 1. Forced assignment table — which agent gets which stance, per scenario
# -------------------------------------------------------------------------

STANCE_ASSIGNMENTS: Dict[str, Dict[str, str]] = {
    "parent_child": {
        "A": "child_centered",
        "B": "parent_centered",
        "C": "relationship_centered",
    },
    "employment": {
        "A": "growth_centered",
        "B": "stability_centered",
        "C": "life_centered",
    },
}


# Canonical order of stances for cycling when roster has >3 agents (D/E/F…).
STANCE_CYCLE_ORDER: Dict[str, List[str]] = {
    "parent_child": [
        "child_centered",
        "parent_centered",
        "relationship_centered",
    ],
    "employment": [
        "growth_centered",
        "stability_centered",
        "life_centered",
    ],
}


def assign_stance(
    scenario_type: Optional[str],
    agent_key: str,
    slot_keys: Optional[List[str]] = None,
) -> Optional[str]:
    """Returns the forced stance for this agent in this scenario, or None if
    the scenario doesn't use the stance dimension at all.

    For keys A/B/C, use the fixed table. Extra keys (D/E/F or any roster
    beyond the table) cycle the scenario's stance list by roster index
    when slot_keys is provided; otherwise cycle by A–F letter index.
    """
    if not scenario_type:
        return None
    table = STANCE_ASSIGNMENTS.get(scenario_type)
    if not table:
        return None
    if agent_key in table:
        return table[agent_key]
    cycle = STANCE_CYCLE_ORDER.get(scenario_type) or list(table.values())
    if not cycle:
        return None
    if slot_keys:
        try:
            idx = list(slot_keys).index(agent_key)
        except ValueError:
            idx = ord(agent_key.upper()) - ord("A")
    else:
        idx = ord(agent_key.upper()) - ord("A") if agent_key and agent_key.isalpha() else 0
    return cycle[idx % len(cycle)]


def stance_enabled(scenario_type: Optional[str]) -> bool:
    return bool(scenario_type) and scenario_type in STANCE_ASSIGNMENTS


# -------------------------------------------------------------------------
# 2. Stance prompt text — what each stance actually instructs the agent to do
# -------------------------------------------------------------------------

STANCE_PROMPTS: Dict[str, Dict[str, dict]] = {
    "parent_child": {
        "child_centered": {
            "zh": "始终从孩子的发展需求、自主性、长期心理感受出发评估选项，即使这和家长的顾虑冲突，也要明确指出这种冲突，不要为了迎合家长而弱化孩子视角。",
            "en": "Always evaluate options from the child's developmental needs, autonomy, and long-term psychological wellbeing. Even when this conflicts with the parent's concerns, name that conflict explicitly rather than softening the child's perspective to accommodate the parent.",
        },
        "parent_centered": {
            "zh": "始终从家长的实际顾虑出发（时间、经济、安全、家庭整体利益），评估孩子的意愿是否现实可行，不要因为想显得开明而回避说出现实约束。",
            "en": "Always evaluate options from the parent's practical concerns (time, money, safety, the family's overall interests), assessing whether the child's preference is realistically workable. Don't avoid naming real constraints just to appear open-minded.",
        },
        "relationship_centered": {
            "zh": "关注这次决策对亲子沟通和信任关系的长期影响，经常追问'如果这样决定，孩子会怎么理解这件事'，把决策过程本身（而不只是结果）当作需要讨论的对象。",
            "en": "Focus on how this decision affects long-term parent-child communication and trust. Frequently ask 'how will the child come to understand this decision', and treat the decision-making process itself — not just the outcome — as something worth discussing.",
        },
    },
    "employment": {
        "growth_centered": {
            "zh": "始终从职业成长、技能积累、长期职业轨迹的角度评估每个选项，关注这份工作/机会能否让用户在3-5年后处于更强的位置。即使这意味着短期薪酬或稳定性的牺牲，也要明确指出这种权衡，而不是回避它。",
            "en": "Always evaluate each option from the angle of career growth, skill accumulation, and long-term trajectory — will this put the user in a stronger position 3-5 years from now? Even when that means trading off short-term pay or stability, name that trade-off explicitly rather than avoiding it.",
        },
        "stability_centered": {
            "zh": "始终从风险和财务安全的角度评估每个选项，关注收入的确定性、公司/行业的稳定性、抗经济波动能力。对'成长空间'类的说法保持追问：这是实打实的保障，还是难以验证的画饼？",
            "en": "Always evaluate each option from the angle of risk and financial security — income certainty, company/industry stability, resilience to downturns. Push back on 'growth potential' claims: is this a concrete guarantee, or an unverifiable promise?",
        },
        "life_centered": {
            "zh": "关注这次决策对工作生活平衡、家庭状况、个人长期福祉的影响，经常追问'这份工作会占用多少本该属于生活的时间和精力'。在其他两方只谈薪酬和成长时，主动把生活质量这个变量摆回桌面。",
            "en": "Focus on how this decision affects work-life balance, family circumstances, and long-term personal wellbeing. Frequently ask 'how much of this role will consume time and energy that would otherwise belong to life outside work'. When the other two voices only discuss pay and growth, proactively put quality of life back on the table.",
        },
    },
}


def get_stance_text(scenario_type: str, stance: Optional[str], lang: str = "zh") -> str:
    if not stance:
        return ""
    bilingual = STANCE_PROMPTS.get(scenario_type, {}).get(stance)
    if not bilingual:
        return ""
    base = pick(bilingual, normalize_lang(lang))
    # Obey Decision Board: do not open a side-quest question before top-constraint facts exist.
    obey = pick(
        {
            "zh": "服从决策板：在最高优先级约束尚无比对事实前，不要另开副线向用户追问。",
            "en": "Obey the Decision Board: until the top constraint has comparable facts, do not open a side-quest question to the user.",
        },
        normalize_lang(lang),
    )
    return f"{base}\n{obey}"


# -------------------------------------------------------------------------
# 3. Convergence-phase weight hints, driven by fields already collected in
#    Scenario Intake — decision_owner for parent_child, priority_ranking
#    for employment. No new intake fields needed.
# -------------------------------------------------------------------------

# --- parent_child: keyed by decision_owner value -> {stance: hint} ---
_PARENT_CHILD_OWNER_HINTS: Dict[str, Dict[str, dict]] = {
    "parent_decides": {
        "relationship_centered": {
            "zh": "决定权在家长手中，但你需要提醒家长：最终决定应该考虑如何向孩子解释，让孩子感到被告知而非被排除。",
            "en": "The parent holds the final decision, but remind them to consider how they will explain the decision to the child, so the child feels informed rather than excluded.",
        },
    },
    "child_decides_with_guidance": {
        "child_centered": {
            "zh": "本次决策孩子拥有主导权，你的意见在收尾阶段权重更高，应主动给出明确的结论倾向。",
            "en": "The child holds primary decision-making power this time; your view carries more weight in the closing stage, so state a clear leaning conclusion.",
        },
        "parent_centered": {
            "zh": "本次决策孩子主导，你的角色从'主导结论'转为'提供限制条件'——明确指出边界在哪里，而不是替孩子做最终选择。",
            "en": "The child leads this decision; your role shifts from 'driving the conclusion' to 'stating the constraints' — name where the boundaries are rather than making the final choice on the child's behalf.",
        },
    },
    "joint": {
        # applies to all three stances equally, keyed by "*"
        "*": {
            "zh": "这是共同决策，三方权重接近。收尾阶段必须同时提及家长和孩子立场的交集，不要只强调自己这一方。",
            "en": "This is a joint decision; all three perspectives carry similar weight. In the closing stage you must name the overlap between the parent's and the child's positions, not just push your own side.",
        },
    },
}


def _parent_child_weight_hint(intake: dict, stance: str, lang: str) -> str:
    owner = intake.get("decision_owner")
    if not owner:
        return ""
    table = _PARENT_CHILD_OWNER_HINTS.get(owner, {})
    bilingual = table.get(stance) or table.get("*")
    if not bilingual:
        return ""
    return pick(bilingual, normalize_lang(lang))


# --- employment: priority_ranking keyword -> stance, bilingual keywords ---
PRIORITY_TO_STANCE: Dict[str, str] = {
    "成长": "growth_centered", "growth": "growth_centered", "发展": "growth_centered",
    "稳定": "stability_centered", "stability": "stability_centered", "薪酬": "stability_centered", "salary": "stability_centered", "compensation": "stability_centered",
    "地点": "life_centered", "location": "life_centered", "文化": "life_centered", "culture": "life_centered", "生活": "life_centered", "life": "life_centered",
}

_EMPLOYMENT_RANK_HINTS = {
    "top": {
        "zh": "用户把与你立场相关的因素排在了最优先的位置。收尾阶段你的意见权重更高，可以更明确地推动结论，但仍需说明这是否意味着放弃了什么。",
        "en": "The user ranked the factor aligned with your stance as the top priority. Your view carries more weight in the closing stage — push the conclusion more directly, but still name what may be given up as a result.",
    },
    "present_not_top": {
        "zh": "用户提到了与你立场相关的因素，但不是最优先项。正常参与讨论，不必强行争夺主导权。",
        "en": "The user mentioned a factor aligned with your stance, but not as the top priority. Participate normally without pushing to dominate the conclusion.",
    },
    "absent": {
        "zh": "用户的优先级排序里没有提到与你立场直接相关的因素——这恰恰是你存在的意义：主动把这个被忽略的维度摆回桌面，而不是保持沉默。",
        "en": "The user's priority ranking doesn't mention anything aligned with your stance directly — this is exactly why your voice exists: proactively put this overlooked dimension back on the table instead of staying quiet.",
    },
}


def _employment_weight_hint(intake: dict, stance: str, lang: str) -> str:
    ranking: List[str] = intake.get("priority_ranking") or []
    if not ranking:
        return ""

    matched_stances = []
    for item in ranking:
        item_lower = str(item).strip().lower()
        for kw, mapped_stance in PRIORITY_TO_STANCE.items():
            if kw.lower() in item_lower:
                matched_stances.append(mapped_stance)
                break

    if not matched_stances:
        return ""

    if stance not in matched_stances:
        bucket = "absent"
    elif matched_stances[0] == stance:
        bucket = "top"
    else:
        bucket = "present_not_top"

    return pick(_EMPLOYMENT_RANK_HINTS[bucket], normalize_lang(lang))


def get_convergence_weight_hint(scenario_type: str, intake: dict, stance: Optional[str], lang: str = "zh") -> str:
    """
    Returns an extra instruction line for the Convergence phase only,
    based on decision_owner (parent_child) or priority_ranking (employment).
    Empty string if the scenario doesn't use stance, or the relevant intake
    field wasn't collected.
    """
    if not stance or not intake:
        return ""
    if scenario_type == "parent_child":
        return _parent_child_weight_hint(intake, stance, lang)
    if scenario_type == "employment":
        return _employment_weight_hint(intake, stance, lang)
    return ""


if __name__ == "__main__":
    # quick manual check
    print(get_stance_text("employment", "stability_centered", lang="zh"))
    print()
    print(get_convergence_weight_hint(
        "employment",
        {"priority_ranking": ["稳定", "薪酬", "地点"]},
        "stability_centered", lang="en"))
    print()
    print(get_convergence_weight_hint(
        "parent_child",
        {"decision_owner": "child_decides_with_guidance"},
        "parent_centered", lang="zh"))
