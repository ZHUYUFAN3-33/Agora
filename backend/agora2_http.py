# -*- coding: utf-8 -*-
"""
HTTP adapter for Agora-2 scenario context (profile/intake/stance/assembly).

Wraps profile_store / scenario_background / agent_assembly / stance /
session_memory / stance_knowledge so Flask can build session context
without CLI intake prompts.
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
    most_recent_intake,
)
from scenario_background import load_background_template, get_scenario_background
from agent_assembly import build_all_agent_specs, build_agent_spec
from stance import stance_enabled, assign_stance, get_stance_text

try:
    from session_memory import (
        load_recent_sessions,
        build_session_memory_text,
        summarize_session,
        append_session_record,
        memory_path,
        MEMORY_DIR_DEFAULT,
    )
    HAVE_SESSION_MEMORY = True
except ImportError:
    HAVE_SESSION_MEMORY = False

try:
    from stance_knowledge import (
        load_stance_knowledge,
        get_stance_knowledge_block,
        _match_topic_card as sk_match_topic_card,
    )
    HAVE_STANCE_KNOWLEDGE = True
except ImportError:
    HAVE_STANCE_KNOWLEDGE = False

from data_paths import BASE_DIR, PROFILES_DIR, MEMORY_DIR

SCENARIO_TYPES = ("employment", "parent_child")

TEMPLATES_DIR = os.path.join(BASE_DIR, "scenario_templates")
BACKGROUND_DIR = os.path.join(BASE_DIR, "background_templates")
SCENES_DIR = os.path.join(BASE_DIR, "scenes")
DECISION_DIR = os.path.join(BASE_DIR, "decision")
EMOTION_DIR = os.path.join(BASE_DIR, "emotion")
INTAKE_EXAMPLES_DIR = os.path.join(BASE_DIR, "intake_examples")
# Ensure writable dirs exist (volume mount on Fly, local backend/ otherwise)
os.makedirs(PROFILES_DIR, exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

# Cached knowledge dict (loaded once)
_STANCE_KB: Optional[dict] = None


def get_stance_kb() -> dict:
    global _STANCE_KB
    if not HAVE_STANCE_KNOWLEDGE:
        return {}
    if _STANCE_KB is None:
        kb_dir = os.path.join(BACKGROUND_DIR, "stance_knowledge")
        _STANCE_KB = load_stance_knowledge(kb_dir)
    return _STANCE_KB or {}


def is_agora2_scenario(scenario_type: Optional[str]) -> bool:
    return bool(scenario_type) and scenario_type in SCENARIO_TYPES


def load_scene_text(scenario_type: str, lang: str = "zh") -> str:
    lang = normalize_lang(lang)
    path = os.path.join(SCENES_DIR, f"{scenario_type}_{lang}.txt")
    if not os.path.exists(path):
        alt = "en" if lang == "zh" else "zh"
        path = os.path.join(SCENES_DIR, f"{scenario_type}_{alt}.txt")
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def load_shared_profile_template() -> dict:
    """Legacy shared template (kept for admin completeness checks)."""
    path = os.path.join(TEMPLATES_DIR, "shared_profile.json")
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_scenario_profile_template(scenario_type: str) -> dict:
    """Per-scenario profile fields from employment.json / parent_child.json."""
    tmpl = load_scenario_template(scenario_type, TEMPLATES_DIR)
    return {
        "label": tmpl.get("label", {}),
        "profile_fields": tmpl.get("profile_fields", []),
        "scenario_type": scenario_type,
    }


def context_template_for_prompt(scenario_type: str) -> dict:
    """Scenario-specific profile + intake fields for KNOWN USER CONTEXT."""
    scenario = load_scenario_template(scenario_type, TEMPLATES_DIR)
    return {
        "label": scenario.get("label", {}),
        "profile_fields": scenario.get("profile_fields", []),
        "scenario_fields": scenario.get("scenario_fields", []),
    }


def stance_knowledge_on_hit(
    scenario_type: str,
    stance: Optional[str],
    message: str,
    lang: str,
    include_header: bool = True,
) -> str:
    """Keyword-hit only; empty string when no match (no generic fallback)."""
    if not (HAVE_STANCE_KNOWLEDGE and stance and message):
        return ""
    knowledge = get_stance_kb()
    if not knowledge:
        return ""
    scenario_cfg = knowledge.get(scenario_type, {}) or {}
    stance_cfg = scenario_cfg.get(stance)
    topic_cards = stance_cfg.get("topic_cards", []) if isinstance(stance_cfg, dict) else []
    if not sk_match_topic_card(message, topic_cards, lang):
        return ""
    return get_stance_knowledge_block(
        scenario_type,
        stance,
        message,
        lang,
        knowledge=knowledge,
        include_header=include_header,
    )


def prepare_http_context(
    scenario_type: str,
    lang: str = "zh",
    profile: Optional[dict] = None,
    intake: Optional[dict] = None,
    user_id: str = "web_user",
    persist: bool = True,
    session_update: str = "",
    session_id: str = "",
) -> Dict:
    """
    Non-interactive context build for Flask.
    profile/intake may be partial; missing fields are marked unfilled in the prompt.
    session_update: optional "what's new since last time" text for 2nd+ sessions.
    """
    if not is_agora2_scenario(scenario_type):
        raise ValueError(f"Unknown scenario_type: {scenario_type}")

    lang = normalize_lang(lang)
    profile = dict(profile or {})
    intake = dict(intake or {})
    session_update = (session_update or "").strip()
    if session_update:
        intake = {**intake, "session_update": session_update}

    template = context_template_for_prompt(scenario_type)

    if persist and user_id:
        data = load_profile(user_id, PROFILES_DIR)
        merged = {**data.get("profile", {}), **profile}
        data["profile"] = merged
        save_profile(user_id, data, PROFILES_DIR)
        profile = merged
        if intake:
            append_session_history(
                user_id,
                scenario_type,
                intake,
                PROFILES_DIR,
                session_id=session_id or None,
            )

    known_context = format_known_context(
        scenario_type=scenario_type,
        profile=profile,
        intake=intake,
        template=template,
        lang=lang,
    )
    if session_update:
        if lang == "zh":
            known_context += f"\n距上次以来的新情况：{session_update}\n"
        else:
            known_context += f"\nWhat's new since last session: {session_update}\n"

    bg_cfg = load_background_template(scenario_type, BACKGROUND_DIR)
    match_context = {**profile, **intake}
    domain_background = get_scenario_background(
        scenario_type=scenario_type,
        intake=match_context,
        cfg=bg_cfg,
        lang=lang,
    )

    session_memory_text = ""
    recent_sessions: List[dict] = []
    session_count = 0
    if HAVE_SESSION_MEMORY and user_id:
        all_recent = load_recent_sessions(user_id, scenario_type, limit=0, dir_path=MEMORY_DIR)
        # limit=0 means all in Agora-2: `records[-limit:] if limit and limit > 0 else records`
        # so limit=0 returns all. Good for count.
        session_count = len(all_recent)
        recent_sessions = all_recent[-3:] if all_recent else []
        session_memory_text = build_session_memory_text(recent_sessions, lang)

    return {
        "scenario_type": scenario_type,
        "lang": lang,
        "known_context": known_context,
        "domain_background": domain_background,
        "session_memory_text": session_memory_text,
        "session_count": session_count,
        "session_index": session_count + 1,  # this run is the next one
        "profile": profile,
        "intake": intake,
        "scene_text": load_scene_text(scenario_type, lang),
        "user_id": user_id,
    }


def assemble_session_agents(
    agent_configs: Dict[str, dict],
    scenario_type: str,
    lang: str = "zh",
    hint: str = "",
) -> Dict[str, dict]:
    """
    Returns {slot: AgentSpec including preloaded_knowledge}.

    Prefer per-agent ``hint`` / ``stance`` on each config entry.
    The optional top-level ``hint`` arg is legacy: only applied to slots
    that do not already carry their own hint.
    """
    legacy_hint = (hint or "").strip()
    cfg = {}
    for key, conf in agent_configs.items():
        entry = dict(conf)
        own = (entry.get("hint") or "").strip()
        if own:
            entry["hint"] = own
        elif legacy_hint:
            entry["hint"] = legacy_hint
        else:
            entry.pop("hint", None)
        cfg[key] = entry

    kb = get_stance_kb() if HAVE_STANCE_KNOWLEDGE else None
    specs = build_all_agent_specs(
        cfg,
        scenario_type=scenario_type,
        lang=lang,
        decision_dir=DECISION_DIR,
        emotion_dir=EMOTION_DIR,
        stance_knowledge=kb,
    )
    return specs


def get_memory_status(user_id: str, scenario_type: str, limit: int = 10) -> dict:
    if not HAVE_SESSION_MEMORY or not user_id or not is_agora2_scenario(scenario_type):
        return {"session_count": 0, "recent": [], "last_intake": None}
    recent = load_recent_sessions(user_id, scenario_type, limit=limit, dir_path=MEMORY_DIR)
    last_intake = most_recent_intake(user_id, scenario_type, PROFILES_DIR)
    return {
        "session_count": len(
            load_recent_sessions(user_id, scenario_type, limit=0, dir_path=MEMORY_DIR)
        ),
        "recent": recent,
        "last_intake": last_intake,
        "scenario_type": scenario_type,
        "user_id": user_id,
    }


def persist_session_memory(
    user_id: str,
    scenario_type: str,
    session_id: str,
    date: str,
    transcript_text: str,
    lang: str,
    create_response,
    model: str = "gpt-4o",
) -> Optional[dict]:
    """End-of-session archival summary → memory jsonl."""
    if not HAVE_SESSION_MEMORY or not user_id or not scenario_type:
        return None
    result = summarize_session(
        transcript_text,
        lang,
        create_response,
        model=model,
    )
    return append_session_record(
        user_id=user_id,
        scenario_type=scenario_type,
        session_id=session_id,
        date=date,
        summary=result.get("summary") or "",
        open_threads=result.get("open_threads") or [],
        dir_path=MEMORY_DIR,
    )


def load_suggested_prompts(scenario_type: str, lang: str = "en") -> List[str]:
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
    lang = normalize_lang(lang)
    meta = {
        "employment": {
            "icon": "💼",
            "color": "#000000",
            "blurb_en": "Compare job offers or career moves with agents focused on growth, stability, and work-life balance.",
            "blurb_zh": "在成长、稳定与生活平衡三个视角下比较工作机会或职业变动。",
        },
        "parent_child": {
            "icon": "👨‍👩‍👧",
            "color": "#000000",
            "blurb_en": "Work through a parenting decision with agents representing the child, the parent, and the relationship.",
            "blurb_zh": "在孩子、家长与关系三个视角下讨论亲子相关决策。",
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
        m = meta.get(st, {"icon": "◎", "color": "#000000", "blurb_en": title, "blurb_zh": title})
        blurb = m.get(f"blurb_{lang}") or m.get("blurb_en") or title
        out.append({
            "id": st,
            "scenario_type": st,
            "title": title,
            "description": blurb,
            "icon": m["icon"],
            "color": m["color"],
            "pipeline": "agora2",
            "suggestedPrompts": load_suggested_prompts(st, lang),
        })
    return out
