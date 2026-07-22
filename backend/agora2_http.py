# -*- coding: utf-8 -*-
"""
HTTP adapter for Agora-2 scenario context (friend backend).

Wraps profile_store / scenario_background / agent_assembly / stance so Flask
can build session context without CLI intake prompts.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from lang_utils import normalize_lang
from profile_store import (
    format_known_context,
    load_scenario_template,
    append_session_history,
    save_profile,
    load_profile,
)
from scenario_background import load_background_template, get_scenario_background
from agent_assembly import build_all_agent_specs, build_agent_spec
from stance import stance_enabled, assign_stance, get_stance_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCENARIO_TYPES = ("employment", "parent_child")

TEMPLATES_DIR = os.path.join(BASE_DIR, "scenario_templates")
BACKGROUND_DIR = os.path.join(BASE_DIR, "background_templates")
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")
SCENES_DIR = os.path.join(BASE_DIR, "scenes")
DECISION_DIR = os.path.join(BASE_DIR, "decision")
EMOTION_DIR = os.path.join(BASE_DIR, "emotion")
INTAKE_EXAMPLES_DIR = os.path.join(BASE_DIR, "intake_examples")


def is_agora2_scenario(scenario_type: Optional[str]) -> bool:
    return bool(scenario_type) and scenario_type in SCENARIO_TYPES


def load_scene_text(scenario_type: str, lang: str = "zh") -> str:
    lang = normalize_lang(lang)
    path = os.path.join(SCENES_DIR, f"{scenario_type}_{lang}.txt")
    if not os.path.exists(path):
        # fallback to the other language
        alt = "en" if lang == "zh" else "zh"
        path = os.path.join(SCENES_DIR, f"{scenario_type}_{alt}.txt")
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def prepare_http_context(
    scenario_type: str,
    lang: str = "zh",
    profile: Optional[dict] = None,
    intake: Optional[dict] = None,
    user_id: str = "web_user",
    persist: bool = True,
) -> Dict:
    """
    Non-interactive context build for Flask.
    profile/intake may be partial; missing fields are marked unfilled in the prompt.
    """
    if not is_agora2_scenario(scenario_type):
        raise ValueError(f"Unknown scenario_type: {scenario_type}")

    lang = normalize_lang(lang)
    profile = dict(profile or {})
    intake = dict(intake or {})
    template = load_scenario_template(scenario_type, TEMPLATES_DIR)

    if persist and user_id:
        data = load_profile(user_id, PROFILES_DIR)
        # merge provided profile over saved
        merged = {**data.get("profile", {}), **profile}
        data["profile"] = merged
        save_profile(user_id, data, PROFILES_DIR)
        profile = merged
        if intake:
            append_session_history(user_id, scenario_type, intake, PROFILES_DIR)

    known_context = format_known_context(
        scenario_type=scenario_type,
        profile=profile,
        intake=intake,
        template=template,
        lang=lang,
    )

    bg_cfg = load_background_template(scenario_type, BACKGROUND_DIR)
    match_context = {**profile, **intake}
    domain_background = get_scenario_background(
        scenario_type=scenario_type,
        intake=match_context,
        cfg=bg_cfg,
        lang=lang,
    )

    return {
        "scenario_type": scenario_type,
        "lang": lang,
        "known_context": known_context,
        "domain_background": domain_background,
        "profile": profile,
        "intake": intake,
        "scene_text": load_scene_text(scenario_type, lang),
    }


def assemble_session_agents(
    agent_configs: Dict[str, dict],
    scenario_type: str,
    lang: str = "zh",
) -> Dict[str, dict]:
    """
    Returns {slot: {role_text, stance, stance_text, decision, emotion}} using
    friend preset folders + stance binding.
    """
    specs = build_all_agent_specs(
        agent_configs,
        scenario_type=scenario_type,
        lang=lang,
        decision_dir=DECISION_DIR,
        emotion_dir=EMOTION_DIR,
    )
    return specs


def load_suggested_prompts(scenario_type: str, lang: str = "en") -> List[str]:
    """Load dummy chat prompts for a scenario; file optional, English default."""
    lang = normalize_lang(lang)
    path = os.path.join(SCENES_DIR, f"{scenario_type}_prompts_{lang}.json")
    if not os.path.exists(path) and lang != "en":
        path = os.path.join(SCENES_DIR, f"{scenario_type}_prompts_en.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        return []
    return []


def list_scenarios(lang: str = "en") -> List[dict]:
    """Return Scene-card payloads for the React UI (English by default)."""
    lang = normalize_lang(lang)
    meta = {
        "employment": {
            "icon": "💼",
            "color": "#000000",
            "blurb": "Compare job offers or career moves with agents focused on growth, stability, and work-life balance.",
        },
        "parent_child": {
            "icon": "👨‍👩‍👧",
            "color": "#000000",
            "blurb": "Work through a parenting decision with agents representing the child, the parent, and the relationship.",
        },
    }
    out = []
    for st in SCENARIO_TYPES:
        try:
            tmpl = load_scenario_template(st, TEMPLATES_DIR)
            label = tmpl.get("label", {})
            title = label.get(lang) or label.get("en") or label.get("zh") or st
        except Exception:
            title = st
        m = meta.get(st, {"icon": "◎", "color": "#000000", "blurb": title})
        out.append({
            "id": st,
            "scenario_type": st,
            "title": title,
            "description": m.get("blurb") or title,
            "icon": m["icon"],
            "color": m["color"],
            "pipeline": "agora2",
            "suggestedPrompts": load_suggested_prompts(st, lang),
        })
    return out
