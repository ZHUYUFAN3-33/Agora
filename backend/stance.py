# -*- coding: utf-8 -*-
"""
stance.py

Implements the Stance dimension discussed for Agora AI:
  - WHO speaks for which interest/priority in a multi-perspective decision.
  - Forced binding: agents are ALWAYS assigned a stance from the scenario's
    template, overriding whatever (if anything) was written in info.jsonl.
    Scenario types with no template file (e.g. any future single-decision-maker
    scenario) simply get no stance at all — assign_stance() returns None and
    callers skip the block.

DATA LIVES IN JSON, NOT HERE: stance_templates/{scenario_type}.json, one file
per scenario — the same split-file convention already used by
scenario_templates/, background_templates/ and background_templates/
stance_knowledge/. Adding a scenario, a stance, or a fourth interest-holder is
a data edit, no code change. Shape:

    {
      "assignment": ["<stance>", ...],        # index order -> sorted agent keys
      "stances": {
        "<stance>": {
          "label":       {"zh": ..., "en": ...},   # short "represents X" phrase
          "prompt":      {"zh": ..., "en": ...},   # the YOUR STANCE block text
          "phase_focus": {"Exploration": {"zh":..., "en":...}, ...}
        }, ...
      }
    }

WHY ASSIGNMENT IS AN ORDERED LIST RATHER THAN AN {AGENT_KEY: STANCE} MAP: the
agent pool size is configurable (info.jsonl is the single source of truth for
the key set), but the old hardcoded map only covered A/B/C — so a 5-agent pool
left D and E with stance None, i.e. no stance block, no per-stance turn focus,
and no stance knowledge. Sorted agent keys now index into this list and wrap
around, so every agent gets a stance whatever the pool size. With more agents
than stances the extras double up on existing stances, which is reported at
startup rather than happening silently.

All prompt text is bilingual (zh/en) via lang_utils.pick().
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from lang_utils import normalize_lang, pick

# Resolved against THIS FILE, not the process CWD — see the same note in
# stance_knowledge.py. stance_enabled() reads these templates, and when the
# directory is missing it answers False rather than raising, so a wrong CWD
# silently strips every agent of its stance instead of failing loudly.
STANCE_TEMPLATE_DIR_DEFAULT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "stance_templates")

# -------------------------------------------------------------------------
# 1. Template loading + forced assignment
# -------------------------------------------------------------------------

_TEMPLATE_CACHE: Dict[str, dict] = {}


def load_stance_templates(dir_path: str = STANCE_TEMPLATE_DIR_DEFAULT) -> Dict[str, dict]:
    """Read stance_templates/{scenario_type}.json into {scenario_type: cfg}.

    Cached per directory: this is static data read many times per session. A
    missing directory is not an error — it just means no scenario uses stances.
    """
    if dir_path in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[dir_path]
    templates: Dict[str, dict] = {}
    if os.path.isdir(dir_path):
        for fname in sorted(os.listdir(dir_path)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(dir_path, fname), "r", encoding="utf-8-sig") as f:
                templates[fname[:-5]] = json.load(f)
    _TEMPLATE_CACHE[dir_path] = templates
    return templates


def _scenario_cfg(scenario_type: Optional[str]) -> dict:
    if not scenario_type:
        return {}
    return load_stance_templates().get(scenario_type, {}) or {}


def list_stances(scenario_type: Optional[str]) -> List[str]:
    """The scenario's stances in assignment order ([] if it uses no stances)."""
    cfg = _scenario_cfg(scenario_type)
    order = cfg.get("assignment") or []
    return [s for s in order if s in (cfg.get("stances") or {})]


def assign_stance(scenario_type: Optional[str], agent_key: str,
                   agent_keys: Optional[List[str]] = None) -> Optional[str]:
    """The forced stance for this agent, or None if the scenario uses no stances.

    agent_keys: the full pool from info.jsonl. The agent's position in the sorted
    pool indexes into the assignment list (wrapping if the pool is larger). It
    defaults to A/B/C..., which reproduces the original hardcoded mapping exactly
    for the standard three-agent pool.
    """
    order = list_stances(scenario_type)
    if not order:
        return None
    keys = sorted(agent_keys) if agent_keys else [chr(ord("A") + i) for i in range(len(order))]
    if agent_key not in keys:
        return None
    return order[keys.index(agent_key) % len(order)]


def get_stance_label(scenario_type: Optional[str], stance: Optional[str],
                      lang: str = "zh") -> str:
    """Short "represents X" phrase, used to build the cast list in the prompt."""
    if not stance:
        return ""
    cfg = _scenario_cfg(scenario_type).get("stances", {}).get(stance) or {}
    return pick(cfg.get("label", {}), normalize_lang(lang))


def stance_enabled(scenario_type: Optional[str]) -> bool:
    return bool(list_stances(scenario_type))


# -------------------------------------------------------------------------
# 2. Stance prompt text and per-phase focus — both read from the scenario's
#    JSON template (see module docstring for the file shape).
# -------------------------------------------------------------------------


def _stance_field(scenario_type: Optional[str], stance: Optional[str], field: str) -> dict:
    if not stance:
        return {}
    cfg = _scenario_cfg(scenario_type).get("stances", {}).get(stance) or {}
    return cfg.get(field) or {}


def get_stance_text(scenario_type: str, stance: Optional[str], lang: str = "zh") -> str:
    """The YOUR STANCE block text: what this stance instructs the agent to do."""
    return pick(_stance_field(scenario_type, stance, "prompt"), normalize_lang(lang))


def get_stance_phase_focus(scenario_type: Optional[str], stance: Optional[str],
                            phase: str, lang: str = "zh") -> str:
    """What THIS stance should specifically put on the table in THIS phase.

    The generic turn task is keyed on (state, mode, decision_style), so every
    agent receives one of the same shape; with only a two-line stance to tell
    them apart the three voices converge on near-identical content. This is
    keyed on STANCE, so each agent is pushed toward something the others
    structurally cannot produce.

    Returns "" when there is no entry (no stance, or a phase with none defined,
    e.g. the terminal Concluded state), so callers can append blindly.
    """
    if not phase:
        return ""
    focus = _stance_field(scenario_type, stance, "phase_focus").get(phase)
    return pick(focus, normalize_lang(lang)) if focus else ""


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
