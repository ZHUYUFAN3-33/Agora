#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask Web API for Multi-Agent Chatbot System
"""

import io
import json
import os
import random
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from openai import OpenAI, AuthenticationError, APIError
from dotenv import load_dotenv

# Import from agentwake_new (agent-module - phase-based deliberation)
import sys
import importlib.util

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Load emotion module (optional) ───────────────────────────────────────────
EMOTION_MODULE_LOADED = False
_emotion_probs_from_text = None
_emotion_probs_from_sliders = None
_emotion_fuse = None

_emotion_module_path = os.path.join(BASE_DIR, "emotion block", "emotion.py")
if os.path.exists(_emotion_module_path):
    try:
        _spec_e = importlib.util.spec_from_file_location("emotion", _emotion_module_path)
        _emotion_mod = importlib.util.module_from_spec(_spec_e)
        _spec_e.loader.exec_module(_emotion_mod)
        _emotion_probs_from_text = _emotion_mod.emotion_probs_from_text
        _emotion_probs_from_sliders = _emotion_mod.emotion_probs_from_sliders
        _emotion_fuse = _emotion_mod.fuse
        EMOTION_MODULE_LOADED = True
        print("✓ Emotion module loaded")
    except Exception as _e:
        print(f"⚠ Emotion module failed to load: {_e}")

# ─── Load agentwake_new ───────────────────────────────────────────────────────
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
import agentwake_new as agent_module

# Agora-2 adapter (profile/intake/stance/assembly)
try:
    import agora2_http
    HAVE_AGORA2 = True
    print("✓ Agora-2 adapter loaded")
except Exception as _agora2_err:
    agora2_http = None  # type: ignore
    HAVE_AGORA2 = False
    print(f"⚠ Agora-2 adapter not loaded: {_agora2_err}")

try:
    from user_store import get_user_store, profile_complete as user_profile_complete
    HAVE_USER_STORE = True
except Exception as _user_store_err:
    get_user_store = None  # type: ignore
    user_profile_complete = None  # type: ignore
    HAVE_USER_STORE = False
    print(f"⚠ User store not loaded: {_user_store_err}")

now_local_iso = agent_module.now_local_iso
read_text = agent_module.read_text
ensure_dir = agent_module.ensure_dir
make_room_id_6 = agent_module.make_room_id_6
update_user_facts = agent_module.update_user_facts
facts_to_bullets = agent_module.facts_to_bullets
ChatAgent = agent_module.ChatAgent
load_agent_configs = agent_module.load_agent_configs
create_response_with_client = agent_module.create_response_with_client
get_phase_prompt = agent_module.get_phase_prompt
parse_moderator_plan = agent_module.parse_moderator_plan
build_roles_summary = agent_module.build_roles_summary
history_to_transcript_lines = agent_module.history_to_transcript_lines
build_transcript = agent_module.build_transcript
clamp_history = agent_module.clamp_history
last_user_index = agent_module.last_user_index
sanitize_single_message = agent_module.sanitize_single_message
ADMIN1_SYSTEM = agent_module.ADMIN1_SYSTEM
ADMIN2_SYSTEM = agent_module.ADMIN2_SYSTEM
ADMIN3_SYSTEM = agent_module.ADMIN3_SYSTEM
MODERATOR_INTERVAL = agent_module.MODERATOR_INTERVAL
MODERATOR_STALL_TURNS = agent_module.MODERATOR_STALL_TURNS
extract_text = agent_module.extract_text

# API-only Flask app (React frontend lives in ../frontend)
app = Flask(__name__)
CORS(app)

# Configuration
TZ = ZoneInfo("Asia/Tokyo")
Speaker = Literal["A", "B", "C", "U"]
# Load API key from environment (.env supported). No hardcoded fallback key.
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(os.path.dirname(BASE_DIR), ".env"))
API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
# Faithful CLI default (Agora-2 backend-dev): prefer_agents=0.85
PREFER_AGENTS = float(os.getenv("AGORA_PREFER_AGENTS") or "0.85")

# Global state for chat sessions
chat_sessions: Dict[str, dict] = {}

# Load scene and agent profiles (from new_module, synced with agent-module)
SCENE_FILE = os.path.join(BASE_DIR, "scene.txt")
SCENE_DIR = os.path.join(BASE_DIR, "new_module", "new")
SCENES: Dict[str, str] = {}
if os.path.isdir(SCENE_DIR):
    for fname in sorted(os.listdir(SCENE_DIR), key=lambda n: (int(re.match(r"scene(\d+)\.txt$", n).group(1)) if re.match(r"scene(\d+)\.txt$", n) else 10**9, n)):
        m = re.match(r"scene(\d+)\.txt$", fname)
        if not m:
            continue
        scene_key = f"scene{int(m.group(1))}"
        p = os.path.join(SCENE_DIR, fname)
        if os.path.exists(p):
            SCENES[scene_key] = read_text(p)
BOT1_FILE = os.path.join(BASE_DIR, "chatbot1.txt")
BOT2_FILE = os.path.join(BASE_DIR, "chatbot2.txt")
BOT3_FILE = os.path.join(BASE_DIR, "chatbot3.txt")
INFO_JSONL = os.path.join(BASE_DIR, "info.jsonl")
INFO_EXAMPLE_JSONL = os.path.join(BASE_DIR, "info_example.jsonl")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DECISION_BLOCK_DIR = os.path.join(SCENE_DIR, "decision block")
EMOTION_BLOCK_DIR = os.path.join(SCENE_DIR, "emotion block")  # Newst: new/emotion block/
EMOTION_PROMPTS_LEGACY = os.path.join(BASE_DIR, "emotion block", "prompts")  # fallback

ensure_dir(LOG_DIR)

# Load agent configs from info.jsonl (default decision/emotion per agent)
_info_path = INFO_JSONL if os.path.exists(INFO_JSONL) else INFO_EXAMPLE_JSONL
AGENT_CONFIGS = load_agent_configs(_info_path)

# Initialize OpenAI clients (will be initialized on first use)
client_chat = None
client_admin = None

def get_openai_clients():
    """Lazy initialization of OpenAI clients"""
    global client_chat, client_admin
    if not API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Create backend/.env with OPENAI_API_KEY=sk-... and restart the API."
        )
    if client_chat is None:
        client_chat = OpenAI(api_key=API_KEY)
    if client_admin is None:
        client_admin = OpenAI(api_key=API_KEY)
    return client_chat, client_admin

# Load scene and agent profiles
def _sanitize_runtime_controlled_role_text(agent_name: str, raw_text: str) -> str:
    """Remove baked-in emotion/decision defaults so runtime config is the only source of tone."""
    txt = (raw_text or "").strip()
    markers = (
        "[Selected Decision Block]",
        "[Selected Emotion Block]",
        "[Decision Block:",
        "[Emotion Block:",
    )
    if txt and not any(marker in txt for marker in markers):
        return txt
    return (
        f"You are {agent_name}, a collaborative discussion agent in a multi-agent conversation.\n"
        "- Your emotional tone and decision style are controlled by the runtime configuration later in the prompt.\n"
        "- Do not assume any fixed default emotion or decision style from prior sessions.\n"
        "- After any required first-message greeting, make the runtime emotion visible in your wording, reactions, and emphasis.\n"
        "- Do not fall back to generic cheerful or optimistic phrasing unless the runtime emotion explicitly supports it.\n"
        "- Stay conversational, react to other agents naturally, and keep helping the user move the discussion forward."
    )


scene = read_text(SCENE_FILE) if os.path.exists(SCENE_FILE) else ""
bot1 = _sanitize_runtime_controlled_role_text("ChatbotA", read_text(BOT1_FILE) if os.path.exists(BOT1_FILE) else "")
bot2 = _sanitize_runtime_controlled_role_text("ChatbotB", read_text(BOT2_FILE) if os.path.exists(BOT2_FILE) else "")
bot3 = _sanitize_runtime_controlled_role_text("ChatbotC", read_text(BOT3_FILE) if os.path.exists(BOT3_FILE) else "")
SLOT_KEYS: List[str] = ["A", "B", "C"]  # default roster; sessions use session["slot_keys"]
POOL_KEYS: List[str] = ["A", "B", "C", "D", "E", "F"]
VALID_SLOT_KEYS: List[str] = list(POOL_KEYS)
MIN_ROSTER_AGENTS = 2
MAX_ROSTER_AGENTS = 6
PROFILE_FIXED_CONFIG: Dict[str, dict] = {
    "A": {"decision": "Spontaneous", "emotion": "joy"},
    "B": {"decision": "Rational", "emotion": "fear"},
    "C": {"decision": "Avoidant", "emotion": "disgust"},
    "D": {"decision": "Dependent", "emotion": "surprise"},
    "E": {"decision": "Intuitive", "emotion": "anger"},
    "F": {"decision": "Rational", "emotion": "sadness"},
}


def _session_slot_keys(session: dict) -> List[str]:
    keys = session.get("slot_keys") or SLOT_KEYS
    out: List[str] = []
    for k in keys:
        ku = str(k).upper()
        if ku in VALID_SLOT_KEYS and ku not in out:
            out.append(ku)
    return out or list(SLOT_KEYS)


def _normalize_emotion_label(emotion: str) -> str:
    e = (emotion or "Joy").strip()
    if not e:
        return "Joy"
    return e[:1].upper() + e[1:].lower()


def _normalize_decision_label(decision: str) -> str:
    d = (decision or "Rational").strip()
    return d or "Rational"


def _valid_stances_for_scenario(scenario_type: Optional[str]) -> List[str]:
    if not scenario_type:
        return []
    try:
        from stance import STANCE_CYCLE_ORDER
        return list(STANCE_CYCLE_ORDER.get(scenario_type) or [])
    except Exception:
        return []


def _parse_agent_entry(item: dict, *, require_behavior: bool = True) -> Tuple[str, str, dict]:
    """Returns (key, display_name, runtime_conf)."""
    if not isinstance(item, dict):
        raise ValueError("each agents[] entry must be an object")
    key = str(item.get("key") or "").upper()
    if key not in VALID_SLOT_KEYS:
        raise ValueError(f"invalid agent key '{key}' (allowed: {VALID_SLOT_KEYS})")
    decision_raw = item.get("decision")
    emotion_raw = item.get("emotion")
    if require_behavior and (not decision_raw or not emotion_raw):
        raise ValueError(f"agent {key} requires decision and emotion")
    name = (item.get("name") or f"Chatbot{key}").strip() or f"Chatbot{key}"
    conf: Dict[str, Any] = {
        "decision": _normalize_decision_label(str(decision_raw or "Rational")),
        "emotion": _normalize_emotion_label(str(emotion_raw or "Joy")),
    }
    hint = (item.get("hint") or "").strip() if isinstance(item.get("hint"), str) else ""
    if hint:
        conf["hint"] = hint
    stance = (item.get("stance") or "").strip() if isinstance(item.get("stance"), str) else ""
    if stance:
        conf["stance"] = stance
    return key, name, conf


def _parse_start_agents_payload(data: dict, mode: str, scenario_type: Optional[str] = None):
    """
    Parse optional agents[] from /api/start or /api/roster.
    Returns (slot_keys, display_names, runtime_config) or (None, None, None) to use defaults.
    Raises ValueError with a user-facing message on invalid input.
    """
    raw = data.get("agents")
    if raw is None:
        return None, None, None
    if not isinstance(raw, list):
        raise ValueError("agents must be a list")

    allowed_stances = set(_valid_stances_for_scenario(scenario_type))

    def _check_stance(key: str, conf: dict) -> None:
        stance = conf.get("stance")
        if stance and allowed_stances and stance not in allowed_stances:
            raise ValueError(
                f"agent {key}: invalid stance '{stance}' (allowed: {sorted(allowed_stances)})"
            )

    if mode == "single":
        if len(raw) == 0:
            return ["A"], {"A": "ChatbotA"}, {
                "A": {"decision": "Rational", "emotion": "Joy"}
            }
        entry = raw[0] if isinstance(raw[0], dict) else {}
        key, name, conf = _parse_agent_entry(entry, require_behavior=False)
        key = "A"
        _check_stance(key, conf)
        return [key], {key: name if name else "ChatbotA"}, {key: conf}

    if mode == "limited":
        # Limited keeps fixed 3 slots from pool selection; ignore custom agents length.
        return None, None, None

    if len(raw) < MIN_ROSTER_AGENTS or len(raw) > MAX_ROSTER_AGENTS:
        raise ValueError(
            f"agents length must be {MIN_ROSTER_AGENTS}–{MAX_ROSTER_AGENTS} (got {len(raw)})"
        )

    slot_keys: List[str] = []
    display_names: Dict[str, str] = {}
    runtime: Dict[str, dict] = {}
    for item in raw:
        key, name, conf = _parse_agent_entry(item, require_behavior=True)
        if key in slot_keys:
            raise ValueError(f"duplicate agent key '{key}'")
        _check_stance(key, conf)
        slot_keys.append(key)
        display_names[key] = name
        runtime[key] = conf
    return slot_keys, display_names, runtime


def _apply_slot_keys_to_session(session: dict, slot_keys: List[str]) -> None:
    session["slot_keys"] = list(slot_keys)
    session["has_spoken"] = {k: False for k in slot_keys}
    session["memory_snippets"] = {k: [] for k in slot_keys}
    session["turns_since_distill"] = {k: 0 for k in slot_keys}
    session["latest_rationale"] = {k: "" for k in slot_keys}
    session["latest_snippet_id"] = {k: None for k in slot_keys}
    session["snippet_counters"] = {k: 0 for k in slot_keys}


def _merge_slot_keys_to_session(session: dict, slot_keys: List[str]) -> None:
    """Update roster while preserving per-agent memory for keys that remain."""
    prev_spoken = session.get("has_spoken") or {}
    prev_snippets = session.get("memory_snippets") or {}
    prev_turns = session.get("turns_since_distill") or {}
    prev_rationale = session.get("latest_rationale") or {}
    prev_snippet_id = session.get("latest_snippet_id") or {}
    prev_counters = session.get("snippet_counters") or {}
    session["slot_keys"] = list(slot_keys)
    session["has_spoken"] = {k: bool(prev_spoken.get(k, False)) for k in slot_keys}
    session["memory_snippets"] = {k: list(prev_snippets.get(k) or []) for k in slot_keys}
    session["turns_since_distill"] = {k: int(prev_turns.get(k) or 0) for k in slot_keys}
    session["latest_rationale"] = {k: str(prev_rationale.get(k) or "") for k in slot_keys}
    session["latest_snippet_id"] = {k: prev_snippet_id.get(k) for k in slot_keys}
    session["snippet_counters"] = {k: int(prev_counters.get(k) or 0) for k in slot_keys}


def _assemble_cfg_from_runtime(session: dict) -> Dict[str, dict]:
    assemble_cfg: Dict[str, dict] = {}
    for slot in _session_slot_keys(session):
        conf = session.get("agent_runtime_config", {}).get(slot, {}) or {}
        entry: Dict[str, Any] = {
            "decision": conf.get("decision", "Rational"),
            "emotion": _normalize_emotion_label(str(conf.get("emotion", "Joy"))),
        }
        hint = (conf.get("hint") or "").strip()
        if hint:
            entry["hint"] = hint
        stance = (conf.get("stance") or "").strip()
        if stance:
            entry["stance"] = stance
        assemble_cfg[slot] = entry
    return assemble_cfg


def _agents_payload_for_session(session: dict, session_agents: Dict[str, ChatAgent]) -> List[dict]:
    agents_payload = []
    for slot in _session_slot_keys(session):
        runtime = session.get("agent_runtime_config", {}).get(slot, {}) or {}
        agents_payload.append({
            "key": slot,
            "pool_key": (session.get("slot_to_profile") or {}).get(slot, slot),
            "name": session_agents[slot].name,
            "role": session_agents[slot].role_text.splitlines()[0] if session_agents[slot].role_text else "",
            "decision": runtime.get("decision", "Rational"),
            "emotion": runtime.get("emotion", "Joy"),
            "stance": runtime.get("stance"),
            "hint": runtime.get("hint") or "",
        })
    return agents_payload

AGENT_POOL: Dict[str, dict] = {
    "A": {"name": "ChatbotA", "role_text": bot1},
    "B": {"name": "ChatbotB", "role_text": bot2},
    "C": {"name": "ChatbotC", "role_text": bot3},
    "D": {
        "name": "ProjectLead",
        "role_text": (
            "You are a deadline-driven product manager in a fast-moving company.\n"
            "- Prioritize delivery impact, user value, and milestone risk.\n"
            "- Push for concrete plans, owners, and timelines.\n"
            "- Keep scope realistic and call out over-engineering."
        ),
    },
    "E": {
        "name": "OpsGuardian",
        "role_text": (
            "You are an operations lead focused on cost, process stability, and compliance.\n"
            "- Highlight budget implications, policy constraints, and operational burden.\n"
            "- Prefer repeatable processes over ad-hoc decisions.\n"
            "- Challenge ideas that create hidden maintenance or governance risk."
        ),
    },
    "F": {
        "name": "ArchKeeper",
        "role_text": (
            "You are a reliability-first engineering lead.\n"
            "- Focus on long-term maintainability, system reliability, and technical debt.\n"
            "- Ask for fallback plans, observability, and failure-mode handling.\n"
            "- Prefer robust architecture over short-lived hacks."
        ),
    },
}


def _normalize_limited_keys(keys: List[str]) -> List[str]:
    unique = []
    for k in keys:
        if k in POOL_KEYS and k not in unique:
            unique.append(k)
    if len(unique) >= 3:
        return unique[:3]
    for k in POOL_KEYS:
        if k not in unique:
            unique.append(k)
        if len(unique) == 3:
            break
    return unique


def _make_session_agents(session: dict) -> Tuple[Dict[str, ChatAgent], List[ChatAgent], List[str]]:
    agents_map: Dict[str, ChatAgent] = {}
    specs = session.get("agora2_specs") or {}
    slot_keys = _session_slot_keys(session)
    display_names = session.get("agent_display_names") or {}
    slot_to_profile = session.get("slot_to_profile") or {}
    for slot in slot_keys:
        profile_key = slot_to_profile.get(slot, slot)
        prof = AGENT_POOL.get(profile_key) or AGENT_POOL.get(slot) or {
            "name": f"Chatbot{slot}",
            "role_text": "",
        }
        role_text = prof.get("role_text") or ""
        if slot in specs and specs[slot].get("role_text"):
            role_text = specs[slot]["role_text"]
        name = display_names.get(slot) or prof.get("name") or f"Chatbot{slot}"
        agents_map[slot] = ChatAgent(slot, name, role_text)
    agent_list = [agents_map[s] for s in slot_keys]
    all_names = [a.name for a in agent_list]
    return agents_map, agent_list, all_names


def _runtime_config_from_slot_profiles(slot_to_profile: Dict[str, str], slot_keys: Optional[List[str]] = None) -> Dict[str, dict]:
    keys = slot_keys or SLOT_KEYS
    conf: Dict[str, dict] = {}
    for slot in keys:
        profile_key = slot_to_profile.get(slot, slot)
        fixed = PROFILE_FIXED_CONFIG.get(profile_key, PROFILE_FIXED_CONFIG.get(slot, {"decision": "Rational", "emotion": "joy"}))
        conf[slot] = {"decision": fixed["decision"], "emotion": fixed["emotion"]}
    return conf


def init_session(room_id: str) -> dict:
    """Initialize a new chat session"""
    chat_log_path = os.path.join(LOG_DIR, f"{room_id}.jsonl")
    thinking_log_path = os.path.join(LOG_DIR, f"{room_id}_thinkinglog.jsonl")
    moderator_log_path = os.path.join(LOG_DIR, f"{room_id}_moderator.jsonl")
    rationale_log_path = os.path.join(LOG_DIR, f"{room_id}_rationale.jsonl")
    memory_log_path = os.path.join(LOG_DIR, f"{room_id}_memory.jsonl")

    chat_fp = open(chat_log_path, "a", encoding="utf-8")
    think_fp = open(thinking_log_path, "a", encoding="utf-8")
    moderator_fp = open(moderator_log_path, "a", encoding="utf-8")
    rationale_fp = open(rationale_log_path, "a", encoding="utf-8")
    memory_fp = open(memory_log_path, "a", encoding="utf-8")

    default_slots = list(SLOT_KEYS)
    session = {
        "room_id": room_id,
        "scene_id": "scene1",
        "mode": "full",
        "slot_keys": default_slots,
        "agent_display_names": {k: f"Chatbot{k}" for k in default_slots},
        "slot_to_profile": {k: k for k in default_slots},
        "agent_runtime_config": {
            k: {
                "decision": AGENT_CONFIGS.get(k, {}).get("decision", "Rational"),
                "emotion": AGENT_CONFIGS.get(k, {}).get("emotion", "Joy"),
            }
            for k in default_slots
        },
        "history": [],
        "known_user_facts": {},
        "bots_since_user": 0,
        "turn_idx": 0,
        "fallback_queue": [],
        "last_speaker_label": "",
        "last_speaker_key": None,
        "mention_queue": [],
        "consecutive_count": 0,
        "has_spoken": {k: False for k in default_slots},
        "chat_log_path": chat_log_path,
        "thinking_log_path": thinking_log_path,
        "moderator_log_path": moderator_log_path,
        "rationale_log_path": rationale_log_path,
        "memory_log_path": memory_log_path,
        "chat_fp": chat_fp,
        "think_fp": think_fp,
        "moderator_fp": moderator_fp,
        "rationale_fp": rationale_fp,
        "memory_fp": memory_fp,
        # In-session per-agent position snapshots (CLI maybe_distill_snippet)
        "memory_snippets": {k: [] for k in default_slots},
        "turns_since_distill": {k: 0 for k in default_slots},
        "latest_rationale": {k: "" for k in default_slots},
        "latest_snippet_id": {k: None for k in default_slots},
        "snippet_counters": {k: 0 for k in default_slots},
        # Phase-based moderator state (CLI-faithful)
        "moderator_state": {"mode": None, "state": "Exploration", "stall": False, "goal": ""},
        "user_turn_count": 0,
        "turns_in_current_state": 0,
        "turns_since_moderator": 0,
        "user_turns_since_moderator": 0,
        "user_spoke_since_moderator": False,
    }
    return session


def append_jsonl(fp, obj: dict):
    fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
    fp.flush()


def _room_title_for_session(session: Optional[dict], room_id: str = "") -> str:
    s = session or {}
    scenario = (s.get("scenario_type") or s.get("scene_id") or "").strip()
    if scenario == "employment":
        return "Employment Decision"
    if scenario == "parent_child":
        return "Parent-Child Decision"
    if scenario:
        return scenario.replace("_", " ").title()
    return (room_id or "Chat").strip() or "Chat"


def _persist_chat_message_db(
    room_id: str,
    msg: dict,
    session: Optional[dict] = None,
) -> None:
    """Dual-write one chat line into SQLite (best-effort). Ensures room row exists."""
    if not HAVE_USER_STORE or not room_id or not isinstance(msg, dict):
        return
    try:
        store = get_user_store()
        if not store.get_chat_room(room_id):
            uid = ""
            scenario = ""
            if isinstance(session, dict):
                uid = str(session.get("user_id") or "")
                scenario = str(session.get("scenario_type") or session.get("scene_id") or "")
            if not uid:
                try:
                    auth_user = store.resolve_token(_bearer_token())
                    if auth_user:
                        uid = auth_user["user_id"]
                except Exception:
                    pass
            if uid:
                store.create_chat_room(
                    room_id,
                    uid,
                    scenario_type=scenario,
                    title=_room_title_for_session(session, room_id),
                    phase=((session or {}).get("moderator_state") or {}).get("state") or "Exploration",
                )
        store.append_chat_message(
            room_id,
            character=str(msg.get("character") or ""),
            txt=str(msg.get("txt") or ""),
            clarifying_question=None,
            created_at=str(msg.get("time") or "") or None,
        )
    except Exception as e:
        print(f"⚠ chat_messages persist: {e}")


def _sync_room_meta(session: dict, room_id: str, *, title: Optional[str] = None) -> None:
    if not HAVE_USER_STORE or not room_id:
        return
    try:
        phase = (session.get("moderator_state") or {}).get("state") or "Exploration"
        concluded = phase == "Concluded"
        if not title:
            existing = get_user_store().get_chat_room(room_id)
            if not existing or not (existing.get("title") or "").strip():
                title = _room_title_for_session(session, room_id)
        get_user_store().update_chat_room(
            room_id, title=title, phase=phase, concluded=concluded
        )
    except Exception as e:
        print(f"⚠ room meta persist: {e}")




@app.route('/')
def index():
    """API root — product UI is the React app on :5173"""
    return jsonify({
        "service": "agora-api",
        "health": "/api/health",
        "frontend": "http://localhost:5173",
    })


@app.route('/api/start', methods=['POST'])
def start_chat():
    """Start a new chat session"""
    data = request.json or {}
    scene_id = (data.get("scene_id") or "").strip()
    mode = (data.get("mode") or "full").strip().lower()
    if mode not in {"full", "limited", "single"}:
        mode = "full"
    requested_limited_keys = data.get("limited_selected_agent_keys") or []

    scenario_type = (data.get("scenario_type") or "").strip()
    if not scenario_type and HAVE_AGORA2 and agora2_http.is_agora2_scenario(scene_id):
        scenario_type = scene_id

    use_agora2 = bool(
        HAVE_AGORA2
        and scenario_type
        and agora2_http.is_agora2_scenario(scenario_type)
    )

    if not scene_id:
        return jsonify({"error": "scene_id is required. Select a scenario before starting."}), 400

    if not use_agora2:
        if scene_id not in SCENES:
            return jsonify({
                "error": f"Unknown scene_id '{scene_id}'. Available: {sorted(SCENES.keys())}",
            }), 400

    room_id = make_room_id_6()
    session = init_session(room_id)
    session["scene_id"] = scenario_type if use_agora2 else scene_id
    session["mode"] = mode
    session["pipeline"] = "agora2" if use_agora2 else "legacy"

    try:
        parsed_keys, parsed_names, parsed_runtime = _parse_start_agents_payload(
            data, mode, scenario_type=scenario_type or None
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if mode == "limited":
        chosen_profiles = _normalize_limited_keys([str(k).upper() for k in requested_limited_keys if isinstance(k, str)])
        slot_keys = list(SLOT_KEYS)
        _apply_slot_keys_to_session(session, slot_keys)
        session["slot_to_profile"] = {slot: chosen_profiles[i] for i, slot in enumerate(slot_keys)}
        session["agent_runtime_config"] = _runtime_config_from_slot_profiles(session["slot_to_profile"], slot_keys)
        session["agent_display_names"] = {
            slot: AGENT_POOL.get(chosen_profiles[i], {}).get("name", f"Chatbot{slot}")
            for i, slot in enumerate(slot_keys)
        }
    elif mode == "single":
        slot_keys = parsed_keys or ["A"]
        _apply_slot_keys_to_session(session, slot_keys)
        session["slot_to_profile"] = {k: k for k in slot_keys}
        if parsed_runtime:
            session["agent_runtime_config"] = parsed_runtime
        else:
            session["agent_runtime_config"] = {
                "A": {
                    "decision": AGENT_CONFIGS.get("A", {}).get("decision", "Rational"),
                    "emotion": AGENT_CONFIGS.get("A", {}).get("emotion", "Joy"),
                }
            }
        session["agent_display_names"] = parsed_names or {"A": "ChatbotA"}
    else:
        slot_keys = parsed_keys or list(SLOT_KEYS)
        _apply_slot_keys_to_session(session, slot_keys)
        session["slot_to_profile"] = {k: k for k in slot_keys}
        if parsed_runtime:
            session["agent_runtime_config"] = parsed_runtime
            session["agent_display_names"] = parsed_names or {k: f"Chatbot{k}" for k in slot_keys}
        else:
            session["agent_runtime_config"] = {
                k: {
                    "decision": AGENT_CONFIGS.get(k, {}).get("decision", "Rational"),
                    "emotion": AGENT_CONFIGS.get(k, {}).get("emotion", "Joy"),
                }
                for k in slot_keys
            }
            session["agent_display_names"] = {k: f"Chatbot{k}" for k in slot_keys}

    if use_agora2:
        lang = (data.get("lang") or "en").strip() or "en"
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        intake = data.get("intake") if isinstance(data.get("intake"), dict) else {}
        session_update = (data.get("session_update") or "").strip()
        # Prefer authenticated user when Bearer present
        user_id = (data.get("user_id") or f"web_{room_id}").strip()
        if HAVE_USER_STORE:
            auth_user = get_user_store().resolve_token(_bearer_token())
            if auth_user:
                user_id = auth_user["user_id"]
        use_demo = bool(data.get("use_demo_intake"))

        # Demo fallback only when explicitly requested (UI normally sends real intake)
        if use_demo and not intake:
            demo_path = os.path.join(
                agora2_http.INTAKE_EXAMPLES_DIR, f"{scenario_type}_{normalize_lang_safe(lang)}.json"
            )
            if os.path.exists(demo_path):
                with open(demo_path, "r", encoding="utf-8-sig") as f:
                    intake = json.load(f)

        if use_demo and not profile:
            for demo_name in (f"demo_{scenario_type}_{normalize_lang_safe(lang)}.json", f"demo_{scenario_type}.json"):
                demo_prof = os.path.join(agora2_http.PROFILES_DIR, demo_name)
                if os.path.exists(demo_prof):
                    with open(demo_prof, "r", encoding="utf-8-sig") as f:
                        raw = json.load(f)
                    profile = raw.get("profile", raw) if isinstance(raw, dict) else {}
                    break

        # Legacy session-level hint is no longer used for knowledge preload;
        # per-agent hints live on agent_runtime_config.

        ctx = agora2_http.prepare_http_context(
            scenario_type=scenario_type,
            lang=lang,
            profile=profile,
            intake=intake,
            user_id=user_id,
            persist=True,
            session_update=session_update,
            session_id=room_id,
        )
        session["agora2"] = ctx
        session["scenario_type"] = scenario_type
        session["lang"] = ctx["lang"]
        session["user_id"] = user_id
        session["hint"] = ""  # deprecated: use per-agent hint on runtime config
        session["memory_saved"] = False

        assemble_cfg = _assemble_cfg_from_runtime(session)
        session["agora2_specs"] = agora2_http.assemble_session_agents(
            assemble_cfg,
            scenario_type=scenario_type,
            lang=ctx["lang"],
            hint="",
        )
        # Sync runtime emotion/decision/stance from assembled specs; keep hint
        for slot, spec in session["agora2_specs"].items():
            prev = session["agent_runtime_config"].get(slot) or {"decision": "Rational", "emotion": "Joy"}
            session["agent_runtime_config"][slot] = {
                "decision": spec.get("decision") or prev["decision"],
                "emotion": spec.get("emotion") or prev["emotion"],
                "stance": spec.get("stance") or prev.get("stance"),
                "hint": prev.get("hint") or "",
            }
    else:
        # Legacy: assemble role_text from decision/emotion presets when available
        try:
            from agent_assembly import build_all_agent_specs
            session["agora2_specs"] = build_all_agent_specs(
                _assemble_cfg_from_runtime(session), scenario_type=None, lang="en"
            )
        except Exception as assemble_err:
            print(f"⚠ legacy assemble: {assemble_err}")

    session_agents, _, _ = _make_session_agents(session)
    chat_sessions[room_id] = session

    # Persist room row for re-login / admin (even for legacy pipeline)
    if HAVE_USER_STORE:
        try:
            uid = session.get("user_id") or ""
            if not uid and HAVE_USER_STORE:
                auth_user = get_user_store().resolve_token(_bearer_token())
                if auth_user:
                    uid = auth_user["user_id"]
                    session["user_id"] = uid
            if uid:
                get_user_store().create_chat_room(
                    room_id,
                    uid,
                    scenario_type=session.get("scenario_type") or session.get("scene_id") or "",
                    title=_room_title_for_session(session, room_id),
                    phase=(session.get("moderator_state") or {}).get("state") or "Exploration",
                )
                if session.get("pipeline") == "agora2":
                    agora2 = session.get("agora2") or {}
                    get_user_store().upsert_session_intake(
                        room_id,
                        uid,
                        session.get("scenario_type") or "",
                        agora2.get("intake") or {},
                    )
        except Exception as room_err:
            print(f"⚠ chat_rooms create: {room_err}")

    agents_payload = _agents_payload_for_session(session, session_agents)

    payload = {
        "room_id": room_id,
        "message": "Chat session started",
        "mode": mode,
        "pipeline": session["pipeline"],
        "scene_id": session["scene_id"],
        "scenario_type": session.get("scenario_type"),
        "lang": session.get("lang"),
        "agents": agents_payload,
    }
    if use_agora2:
        payload["user_id"] = session.get("user_id")
        payload["session_index"] = (session.get("agora2") or {}).get("session_index", 1)
        payload["session_count_before"] = (session.get("agora2") or {}).get("session_count", 0)
        payload["hint"] = session.get("hint") or ""
    return jsonify(payload)


def normalize_lang_safe(lang: str) -> str:
    lang = (lang or "zh").lower()
    return "zh" if lang.startswith("zh") else "en"


@app.route('/api/roster', methods=['POST'])
def update_roster():
    """Update active agent roster mid-session (full mode: 2–6; single: A only)."""
    data = request.json or {}
    room_id = (data.get("room_id") or "").strip()
    if not room_id or room_id not in chat_sessions:
        return jsonify({"error": "Invalid room_id"}), 400

    session = chat_sessions[room_id]
    mode = (session.get("mode") or data.get("mode") or "full").strip().lower()
    if mode == "limited":
        return jsonify({"error": "Roster updates are not supported in limited mode"}), 400

    scenario_type = session.get("scenario_type") or ""
    try:
        slot_keys, display_names, runtime = _parse_start_agents_payload(
            data, mode, scenario_type=scenario_type or None
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not slot_keys or not runtime:
        return jsonify({"error": "agents[] is required"}), 400

    _merge_slot_keys_to_session(session, slot_keys)
    session["slot_to_profile"] = {k: k for k in slot_keys}
    session["agent_display_names"] = display_names or {k: f"Chatbot{k}" for k in slot_keys}
    session["agent_runtime_config"] = runtime

    if session.get("pipeline") == "agora2" and scenario_type and HAVE_AGORA2:
        lang = session.get("lang") or "en"
        assemble_cfg = _assemble_cfg_from_runtime(session)
        session["agora2_specs"] = agora2_http.assemble_session_agents(
            assemble_cfg,
            scenario_type=scenario_type,
            lang=lang,
            hint="",
        )
        for slot, spec in (session.get("agora2_specs") or {}).items():
            prev = session["agent_runtime_config"].get(slot) or {}
            session["agent_runtime_config"][slot] = {
                "decision": spec.get("decision") or prev.get("decision", "Rational"),
                "emotion": spec.get("emotion") or prev.get("emotion", "Joy"),
                "stance": spec.get("stance") or prev.get("stance"),
                "hint": prev.get("hint") or "",
            }
    else:
        try:
            from agent_assembly import build_all_agent_specs
            session["agora2_specs"] = build_all_agent_specs(
                _assemble_cfg_from_runtime(session),
                scenario_type=scenario_type or None,
                lang=session.get("lang") or "en",
            )
            for slot, spec in (session.get("agora2_specs") or {}).items():
                prev = session["agent_runtime_config"].get(slot) or {}
                if spec.get("stance"):
                    session["agent_runtime_config"][slot] = {
                        **prev,
                        "stance": spec.get("stance"),
                    }
        except Exception as assemble_err:
            print(f"⚠ roster assemble: {assemble_err}")

    session_agents, _, _ = _make_session_agents(session)
    return jsonify({
        "room_id": room_id,
        "mode": mode,
        "agents": _agents_payload_for_session(session, session_agents),
    })


@app.route('/api/knowledge-preview', methods=['POST'])
def knowledge_preview():
    """Preview topic-card tags matched by per-agent hint + stance."""
    data = request.json or {}
    scenario_type = (data.get("scenario_type") or "").strip()
    stance = (data.get("stance") or "").strip()
    hint = (data.get("hint") or "").strip()
    lang = normalize_lang_safe(data.get("lang") or "en")
    if not scenario_type or not stance:
        return jsonify({"matched": False, "fallback": False, "tags": [], "card": None})
    try:
        from stance_knowledge import preview_matched_card
        result = preview_matched_card(scenario_type, stance, hint, lang=lang)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "matched": False, "tags": []}), 500


@app.route('/api/message', methods=['POST'])
def send_message():
    """Send a user message and get agent responses (Agora-2 loop, prose only)."""
    data = request.json or {}
    room_id = data.get("room_id")
    user_message = (data.get("message") or "").strip()

    if not room_id or room_id not in chat_sessions:
        return jsonify({"error": "Invalid room_id"}), 400
    if not user_message:
        return jsonify({"error": "Message cannot be empty"}), 400

    session = chat_sessions[room_id]
    agents, agent_list, all_agent_names = _make_session_agents(session)

    emotion_tag = data.get("emotion_tag")
    emotion_target = data.get("emotion_target")
    max_agent_turns_before_user = int(data.get("max_agent_turns_before_user") or 5)
    max_user_gap = int(data.get("max_user_gap") or 12)
    single_mode = data.get("single_mode") is True

    if session.get("pipeline") == "agora2":
        base_scene = (session.get("agora2") or {}).get("scene_text") or ""
    else:
        req_scene_id = (data.get("scene_id") or "").strip()
        if req_scene_id and req_scene_id in SCENES:
            session["scene_id"] = req_scene_id
        base_scene = SCENES.get(session.get("scene_id", "scene1"), scene)

    # Persist user message
    session["known_user_facts"] = update_user_facts(session.get("known_user_facts") or {}, user_message)
    user_msg = {
        "chat_room_id": room_id,
        "time": now_local_iso(),
        "character": "user",
        "txt": user_message,
    }
    append_jsonl(session["chat_fp"], user_msg)
    session["history"].append(user_msg)
    _persist_chat_message_db(room_id, user_msg, session)

    try:
        client_chat, client_admin = get_openai_clients()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    if single_mode:
        transcript = build_transcript(session["history"], max_turns=12)
        scene_context = ""
        if base_scene and base_scene.strip():
            scene_context = (
                "\n\n[Scene context — use to inform answers when relevant]\n"
                + base_scene.strip()
                + "\n"
            )
        try:
            sys_content = (
                "You are a helpful AI assistant. Reply concisely and neutrally. "
                "Do not adopt any persona, emotion, or role." + scene_context
            )
            msgs = [
                {"role": "system", "content": sys_content},
                {
                    "role": "user",
                    "content": "Conversation:\n" + transcript + "\n\nRespond to the user:",
                },
            ]
            txt = create_response_with_client(client_chat, "gpt-4o", msgs, 0.5, 500).strip() or "..."
        except Exception as e:
            print(f"[single_mode] Error: {e}")
            txt = "Sorry, something went wrong."
        agent_msg = {
            "chat_room_id": room_id,
            "time": now_local_iso(),
            "character": "ChatbotA",
            "txt": txt,
        }
        append_jsonl(session["chat_fp"], agent_msg)
        session["history"].append(agent_msg)
        _persist_chat_message_db(room_id, agent_msg, session)
        session["has_spoken"]["A"] = True
        return jsonify({"responses": [{"agent_key": "A", "agent": "ChatbotA", "message": txt}], "phase": None, "stall": False})

    agora2 = session.get("agora2") or {}
    known_context = agora2.get("known_context") or ""
    domain_background = agora2.get("domain_background") or ""
    session_memory_text = agora2.get("session_memory_text") or ""
    # Hint / stance-knowledge preload lives on assembled agent specs
    preloaded_knowledge_text = agora2.get("preloaded_knowledge_text") or ""
    if not preloaded_knowledge_text:
        specs = session.get("agora2_specs") or {}
        for slot in _session_slot_keys(session):
            pk = (specs.get(slot) or {}).get("preloaded_knowledge") or ""
            if pk:
                preloaded_knowledge_text = pk
                break
    intake_data = agora2.get("intake") or {}
    lang = session.get("lang") or "en"
    scenario_type = session.get("scenario_type")

    # Apply runtime emotion/decision overrides from customizer (optional)
    agent_emotion_overrides = data.get("agent_emotion_overrides") or {}
    agent_decision_block = data.get("agent_decision_block") or {}
    additional_rules = data.get("additional_rules") or {}
    for slot in _session_slot_keys(session):
        conf = session.setdefault("agent_runtime_config", {}).setdefault(slot, {})
        if slot in agent_decision_block and agent_decision_block[slot]:
            conf["decision"] = agent_decision_block[slot]
        if slot in agent_emotion_overrides and agent_emotion_overrides[slot]:
            conf["emotion"] = agent_emotion_overrides[slot]
        # Rebuild role if additional rules (append once per turn into role via agora2_specs is heavy;
        # skip — Agora-2 path uses assembled role_text)

    try:
        from agentwake_new import run_user_turn
        result = run_user_turn(
            session=session,
            user_message=user_message,
            agents=agents,
            agent_list=agent_list,
            all_agent_names=all_agent_names,
            client_chat=client_chat,
            client_admin=client_admin,
            scene=base_scene,
            known_context=known_context,
            domain_background=domain_background,
            session_memory_text=session_memory_text,
            preloaded_knowledge_text=preloaded_knowledge_text,
            intake_data=intake_data,
            scenario_type=scenario_type,
            lang=lang,
            max_user_gap=max_user_gap,
            max_agent_turns_before_user=max_agent_turns_before_user,
            prefer_agents=PREFER_AGENTS,
            persist_chat=lambda msg: _persist_chat_message_db(room_id, msg, session),
            create_response_with_client=create_response_with_client,
        )
    except AuthenticationError:
        return jsonify({
            "error": "OpenAI API key is invalid. Set OPENAI_API_KEY in backend/.env and restart the API."
        }), 401
    except APIError as e:
        return jsonify({"error": f"OpenAI API error: {getattr(e, 'message', str(e))}"}), 502
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    title_guess = None
    for h in session.get("history") or []:
        if str(h.get("character") or "").lower() == "user" and (h.get("txt") or "").strip():
            t = str(h["txt"]).strip()
            title_guess = (t[:48] + "…") if len(t) > 48 else t
            break
    _sync_room_meta(session, room_id, title=title_guess)

    return jsonify({
        "room_id": room_id,
        "user_message": user_message,
        "responses": result.get("responses") or [],
        "known_facts": list(session.get("known_user_facts", {}).values()),
        "emotion_tag": emotion_tag,
        "emotion_target": emotion_target,
        "phase": result.get("phase"),
        "stall": result.get("stall", False),
        "concluded": bool(result.get("concluded")),
    })



@app.route('/api/history/<room_id>', methods=['GET'])
def get_history(room_id):
    """Get chat history for a session (memory or SQLite replay)."""
    room_id = _safe_room_id(room_id) or room_id
    
    # Live in-memory session
    if room_id in chat_sessions:
        session = chat_sessions[room_id]
        # Auth: owner or admin when room has user_id
        owner = session.get("user_id")
        if owner and HAVE_USER_STORE:
            auth = get_user_store().resolve_token(_bearer_token())
            if not auth or (auth["user_id"] != owner and not auth.get("is_admin")):
                return jsonify({"error": "Forbidden"}), 403
        session_agents, _, _ = _make_session_agents(session)
        return jsonify({
            "room_id": room_id,
            "mode": session.get("mode", "full"),
            "active_agents": [
                {"key": slot, "pool_key": session.get("slot_to_profile", {}).get(slot, slot), "name": session_agents[slot].name}
                for slot in _session_slot_keys(session)
            ],
            "history": session["history"],
            "known_facts": list(session["known_user_facts"].values()),
            "phase": (session.get("moderator_state") or {}).get("state"),
            "source": "memory",
        })

    # SQLite replay after restart
    if not HAVE_USER_STORE:
        return jsonify({"error": "Session not found"}), 404
    store = get_user_store()
    room = store.get_chat_room(room_id)
    if not room:
        return jsonify({"error": "Session not found"}), 404
    auth = store.resolve_token(_bearer_token())
    if not auth or (auth["user_id"] != room["user_id"] and not auth.get("is_admin")):
        return jsonify({"error": "Forbidden"}), 403
    msgs = store.list_chat_messages(room_id)
    history = []
    for m in msgs:
        history.append({
            "character": m["character"],
            "txt": m["txt"],
            "time": m.get("created_at"),
            "chat_room_id": room_id,
        })
    return jsonify({
        "room_id": room_id,
        "mode": "full",
        "active_agents": [],
        "history": history,
        "known_facts": [],
        "phase": room.get("phase"),
        "scenario_type": room.get("scenario_type"),
        "title": room.get("title"),
        "concluded": room.get("concluded"),
        "source": "db",
    })


@app.route('/api/log-param-change', methods=['POST'])
def log_param_change():
    """Log user parameter modifications (Full mode only). Records timestamp, change type, agent (full name), before/after values."""
    data = request.json or {}
    room_id = (data.get("room_id") or "").strip()
    mode = data.get("mode") or "full"
    changes = data.get("changes") or []

    if mode != "full":
        return jsonify({"ok": True, "skipped": "mode is not full"}), 200

    if not room_id or not changes:
        return jsonify({"ok": True, "skipped": "no room_id or changes"}), 200

    params_log_path = os.path.join(LOG_DIR, f"{room_id}_params.jsonl")
    change_count = 0
    if os.path.exists(params_log_path):
        with open(params_log_path, "r", encoding="utf-8") as f:
            change_count = sum(1 for _ in f)
    change_count += 1

    entry = {
        "room_id": room_id,
        "time": now_local_iso(),
        "changes": changes,
        "change_count": change_count,
    }
    with open(params_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()

    return jsonify({"ok": True, "change_count": change_count}), 200


def _safe_room_id(room_id: str) -> Optional[str]:
    """Reject path traversal; room ids are alphanumeric (see session create)."""
    if not room_id or not re.fullmatch(r"[A-Za-z0-9_-]+", room_id):
        return None
    return room_id


@app.route('/api/export-logs/<room_id>', methods=['GET'])
def export_logs(room_id):
    """Export this session's logs as a zip (disk jsonl + SQLite transcript when available)."""
    room_id = _safe_room_id(room_id)
    if not room_id:
        return jsonify({"error": "Invalid room id"}), 400

    chat_path = os.path.join(LOG_DIR, f"{room_id}.jsonl")
    db_room = None
    if HAVE_USER_STORE:
        try:
            db_room = get_user_store().get_chat_room(room_id)
        except Exception:
            db_room = None
    if room_id not in chat_sessions and not os.path.exists(chat_path) and not db_room:
        return jsonify({"error": "Session not found"}), 404

    # Ownership check when DB room exists
    if db_room and HAVE_USER_STORE:
        auth = get_user_store().resolve_token(_bearer_token())
        if auth and auth["user_id"] != db_room["user_id"] and not auth.get("is_admin"):
            return jsonify({"error": "Forbidden"}), 403

    buf = io.BytesIO()
    wrote = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, filename in [
            (f"{room_id}.jsonl", f"{room_id}.jsonl"),
            (f"{room_id}_thinkinglog.jsonl", f"{room_id}_thinkinglog.jsonl"),
            (f"{room_id}_moderator.jsonl", f"{room_id}_moderator.jsonl"),
            (f"{room_id}_params.jsonl", f"{room_id}_params.jsonl"),
        ]:
            path = os.path.join(LOG_DIR, filename)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    zf.writestr(name, f.read())
                wrote += 1
        if HAVE_USER_STORE and db_room:
            store = get_user_store()
            payload = {
                "room": db_room,
                "messages": store.list_chat_messages(room_id),
                "intake": store.get_session_intake(room_id),
                "board_snapshot": store.get_board_snapshot(room_id),
            }
            zf.writestr(f"{room_id}_db.json", json.dumps(payload, ensure_ascii=False, indent=2))
            wrote += 1

    if wrote == 0:
        return jsonify({"error": "No log files for this session"}), 404

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"agora_logs_{room_id}.zip",
    )


@app.route('/api/summary/<room_id>', methods=['POST', 'GET'])
def session_summary(room_id):
    """
    Decision-direction summary for one chat session (transcript_summary.py).
    Scoped to room_id; reads logs/{room_id}.jsonl (+ moderator phases when present).
    Default language: en (UI is English).
    """
    room_id = _safe_room_id(room_id)
    if not room_id:
        return jsonify({"error": "Invalid room id"}), 400

    chat_path = os.path.join(LOG_DIR, f"{room_id}.jsonl")
    if not os.path.exists(chat_path):
        return jsonify({"error": "No chat log for this session yet"}), 404

    lang = "en"
    if request.method == "GET":
        lang = (request.args.get("lang") or "en").strip().lower()
    else:
        body = request.get_json(silent=True) or {}
        lang = (body.get("lang") or request.args.get("lang") or "en").strip().lower()
    if lang not in ("en", "zh"):
        lang = "en"

    try:
        from transcript_summary import build as build_summary
        text = build_summary(chat_path, lang)
    except Exception as e:
        return jsonify({"error": f"Summary failed: {e}"}), 502

    memory_record = None
    session = chat_sessions.get(room_id) or {}
    if (
        HAVE_AGORA2
        and session.get("pipeline") == "agora2"
        and not session.get("memory_saved")
        and session.get("user_id")
        and session.get("scenario_type")
    ):
        try:
            # Build plain transcript for archival memory (separate from user-facing summary)
            lines = []
            with open(chat_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    speaker = row.get("character") or row.get("speaker") or row.get("role") or ""
                    content = (row.get("txt") or row.get("content") or row.get("message") or "").strip()
                    if content:
                        lines.append(f"{speaker}: {content}" if speaker else content)
            transcript_text = "\n".join(lines)
            mem_lang = session.get("lang") or lang
            memory_record = agora2_http.persist_session_memory(
                user_id=session["user_id"],
                scenario_type=session["scenario_type"],
                session_id=room_id,
                date=datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d"),
                transcript_text=transcript_text,
                lang=mem_lang,
                create_response=agent_module.create_response,
            )
            if memory_record:
                # Merge board open_threads (parked digressions) into archival memory
                seeded = [str(t).strip() for t in (session.get("pending_open_threads") or []) if str(t).strip()]
                if seeded:
                    existing = [str(t).strip() for t in (memory_record.get("open_threads") or []) if str(t).strip()]
                    merged = existing[:]
                    for t in seeded:
                        if t not in merged:
                            merged.append(t)
                    memory_record["open_threads"] = merged[:12]
                    # Re-persist merged threads to JSONL+SQLite
                    if HAVE_USER_STORE:
                        get_user_store().upsert_session_memory(
                            user_id=session["user_id"],
                            scenario_type=session["scenario_type"],
                            session_id=room_id,
                            date=datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d"),
                            summary=memory_record.get("summary") or "",
                            open_threads=memory_record["open_threads"],
                        )
                session["memory_saved"] = True
                _sync_room_meta(session, room_id)
        except Exception as mem_err:
            print(f"⚠ session memory save failed: {mem_err}")

    return jsonify({
        "room_id": room_id,
        "lang": lang,
        "markdown": text,
        "memory_saved": bool(memory_record),
        "memory": memory_record,
    })


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "sessions": len(chat_sessions),
        "emotion_module": EMOTION_MODULE_LOADED,
        "agora2": HAVE_AGORA2,
        "agora2_scenarios": list(agora2_http.SCENARIO_TYPES) if HAVE_AGORA2 else [],
    })


@app.route('/api/agora2/scenarios', methods=['GET'])
def agora2_scenarios():
    if not HAVE_AGORA2:
        return jsonify({"error": "Agora-2 adapter not available"}), 503
    lang = (request.args.get("lang") or "en").strip()
    return jsonify({"scenes": agora2_http.list_scenarios(lang)})


@app.route('/api/agora2/profile-template', methods=['GET'])
def agora2_profile_template():
    """Per-scenario profile fields when ?scenario_type= is set; else shared legacy."""
    if not HAVE_AGORA2:
        return jsonify({"error": "Agora-2 adapter not available"}), 503
    scenario_type = (request.args.get("scenario_type") or "").strip()
    if scenario_type and agora2_http.is_agora2_scenario(scenario_type):
        return jsonify(agora2_http.load_scenario_profile_template(scenario_type))
    return jsonify(agora2_http.load_shared_profile_template())


@app.route('/api/agora2/memory', methods=['GET'])
def agora2_memory():
    """Cross-session memory status for user_id + scenario_type (Session N / history)."""
    if not HAVE_AGORA2:
        return jsonify({"error": "Agora-2 adapter not available"}), 503
    scenario_type = (request.args.get("scenario_type") or "").strip()
    if not agora2_http.is_agora2_scenario(scenario_type):
        return jsonify({"error": "Invalid scenario_type"}), 400
    user_id = (request.args.get("user_id") or "").strip()
    if HAVE_USER_STORE:
        auth_user = get_user_store().resolve_token(_bearer_token())
        if auth_user:
            user_id = auth_user["user_id"]
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    try:
        limit = int(request.args.get("limit") or "10")
    except ValueError:
        limit = 10
    return jsonify(agora2_http.get_memory_status(user_id, scenario_type, limit=limit))


def _bearer_token() -> Optional[str]:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def _require_user():
    if not HAVE_USER_STORE:
        return None, (jsonify({"error": "User store not available"}), 503)
    store = get_user_store()
    user = store.resolve_token(_bearer_token())
    if not user:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return user, None


def _require_admin():
    user, err = _require_user()
    if err:
        return None, err
    if not user.get("is_admin"):
        return None, (jsonify({"error": "Admin only"}), 403)
    return user, None


@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    if not HAVE_USER_STORE:
        return jsonify({"error": "User store not available"}), 503
    body = request.get_json(silent=True) or {}
    data, err = get_user_store().register(body.get("user_id") or "", body.get("password") or "")
    if err:
        return jsonify({"error": err}), 400
    return jsonify(data)


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    if not HAVE_USER_STORE:
        return jsonify({"error": "User store not available"}), 503
    body = request.get_json(silent=True) or {}
    data, err = get_user_store().login(body.get("user_id") or "", body.get("password") or "")
    if err:
        return jsonify({"error": err}), 401
    return jsonify(data)


@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    if HAVE_USER_STORE:
        get_user_store().logout(_bearer_token())
    return jsonify({"ok": True})


@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    user, err = _require_user()
    if err:
        return err
    return jsonify(user)


@app.route('/api/me/profile', methods=['GET', 'POST'])
def me_profile():
    user, err = _require_user()
    if err:
        return err
    store = get_user_store()
    scenario_type = (request.args.get("scenario_type") or "").strip()
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if not scenario_type:
            scenario_type = (body.get("scenario_type") or "").strip()

    def _fields_for_complete():
        if HAVE_AGORA2 and scenario_type and agora2_http.is_agora2_scenario(scenario_type):
            return agora2_http.load_scenario_profile_template(scenario_type).get("profile_fields") or []
        if HAVE_AGORA2:
            return agora2_http.load_shared_profile_template().get("profile_fields") or []
        return []

    if request.method == "GET":
        data = store.get_profile(user["user_id"])
        # Merge JSON agora2 profile so CLI/HTTP stay aligned
        if HAVE_AGORA2:
            from profile_store import load_profile
            disk = load_profile(user["user_id"], agora2_http.PROFILES_DIR)
            merged = {**(disk.get("profile") or {}), **(data.get("profile") or {})}
        else:
            merged = data.get("profile") or {}
        complete = False
        if HAVE_AGORA2 and user_profile_complete:
            complete = user_profile_complete(merged, _fields_for_complete())
        return jsonify({
            "user_id": user["user_id"],
            "profile": merged,
            "updated_at": data.get("updated_at"),
            "complete": complete,
            "scenario_type": scenario_type or None,
        })
    body = request.get_json(silent=True) or {}
    profile = body.get("profile") if isinstance(body.get("profile"), dict) else {}
    data = store.save_profile(user["user_id"], profile)
    if HAVE_AGORA2:
        from profile_store import load_profile, save_profile
        disk = load_profile(user["user_id"], agora2_http.PROFILES_DIR)
        disk["profile"] = {**(disk.get("profile") or {}), **profile}
        save_profile(user["user_id"], disk, agora2_http.PROFILES_DIR)
    complete = False
    if HAVE_AGORA2 and user_profile_complete:
        complete = user_profile_complete(data.get("profile") or {}, _fields_for_complete())
    return jsonify({
        "user_id": user["user_id"],
        "profile": data.get("profile") or {},
        "updated_at": data.get("updated_at"),
        "complete": complete,
        "scenario_type": scenario_type or None,
    })


@app.route('/api/me/rooms', methods=['GET'])
def me_rooms():
    """List chat rooms for the logged-in user (survives re-login)."""
    user, err = _require_user()
    if err:
        return err
    limit = request.args.get("limit", 50)
    try:
        limit_n = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        limit_n = 50
    rooms = get_user_store().list_chat_rooms(user["user_id"], limit=limit_n)
    return jsonify({"user_id": user["user_id"], "rooms": rooms})


@app.route('/api/admin/users/<user_id>/rooms', methods=['GET'])
def admin_user_rooms(user_id):
    _, err = _require_admin()
    if err:
        return err
    uid = (user_id or "").strip()
    rooms = get_user_store().list_chat_rooms(uid, limit=200)
    memory = []
    scenarios = sorted({r.get("scenario_type") for r in rooms if r.get("scenario_type")})
    # Always include Agora-2 scenario memories even when rooms were cleared
    for sc in ("employment", "parent_child"):
        if sc not in scenarios:
            scenarios.append(sc)
    seen_mem = set()
    for sc in scenarios:
        for rec in get_user_store().load_session_memory(uid, sc, limit=0):
            key = (sc, rec.get("session_id"))
            if key in seen_mem:
                continue
            seen_mem.add(key)
            memory.append({**rec, "scenario_type": sc})
    return jsonify({"user_id": uid, "rooms": rooms, "session_memory": memory})


@app.route('/api/admin/rooms/<room_id>', methods=['GET', 'DELETE'])
def admin_room_detail(room_id):
    admin, err = _require_admin()
    if err:
        return err
    store = get_user_store()
    rid = _safe_room_id(room_id) or (room_id or "").strip()
    if request.method == "DELETE":
        ok, msg, meta = store.delete_chat_room(rid)
        if not ok:
            return jsonify({"error": msg or "Delete failed"}), 404
        # Drop live session + close file handles
        sess = chat_sessions.pop(rid, None)
        if isinstance(sess, dict):
            for fp_key in ("chat_fp", "think_fp", "moderator_fp", "rationale_fp", "memory_fp"):
                fp = sess.get(fp_key)
                try:
                    if fp and not fp.closed:
                        fp.close()
                except Exception:
                    pass
        # Remove jsonl logs for this room
        for suffix in ("", "_thinkinglog", "_thinking", "_moderator", "_params"):
            path = os.path.join(LOG_DIR, f"{rid}{suffix}.jsonl")
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass
        # Strip matching line from memory/{user}__{scenario}.jsonl if present
        try:
            if meta and HAVE_AGORA2:
                from session_memory import memory_path, MEMORY_DIR_DEFAULT
                mem_dir = getattr(agora2_http, "MEMORY_DIR", None) or os.path.join(BASE_DIR, MEMORY_DIR_DEFAULT)
                uid = meta.get("user_id") or ""
                sc = meta.get("scenario_type") or ""
                if uid and sc:
                    mpath = memory_path(uid, sc, mem_dir)
                    if os.path.isfile(mpath):
                        kept = []
                        with open(mpath, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    rec = json.loads(line)
                                except json.JSONDecodeError:
                                    kept.append(line)
                                    continue
                                if str(rec.get("session_id") or "") == rid:
                                    continue
                                kept.append(line)
                        with open(mpath, "w", encoding="utf-8") as f:
                            for line in kept:
                                f.write(line + "\n")
        except Exception as mem_err:
            print(f"⚠ memory jsonl prune: {mem_err}")
        return jsonify({"ok": True, "deleted": meta, "by": admin["user_id"]})

    room = store.get_chat_room(rid)
    if not room:
        return jsonify({"error": "Room not found"}), 404
    return jsonify({
        "room": room,
        "messages": store.list_chat_messages(rid),
        "intake": store.get_session_intake(rid),
        "board_snapshot": store.get_board_snapshot(rid),
        "viewer": admin["user_id"],
    })


@app.route('/api/admin/users/<user_id>/memory/<session_id>', methods=['DELETE'])
def admin_delete_session_memory(user_id, session_id):
    """Delete a standalone memory summary row (user profile untouched)."""
    _, err = _require_admin()
    if err:
        return err
    uid = (user_id or "").strip()
    sid = (session_id or "").strip()
    scenario_type = (request.args.get("scenario_type") or "").strip()
    ok, msg = get_user_store().delete_session_memory(uid, sid, scenario_type)
    if not ok:
        return jsonify({"error": msg or "Delete failed"}), 404
    return jsonify({"ok": True, "user_id": uid, "session_id": sid, "scenario_type": scenario_type or None})


@app.route('/api/admin/export', methods=['GET'])
def admin_export_bundle():
    _, err = _require_admin()
    if err:
        return err
    uid = (request.args.get("user_id") or "").strip()
    if not uid:
        return jsonify({"error": "user_id required"}), 400
    scenario_type = (request.args.get("scenario_type") or "").strip() or None
    bundle = get_user_store().export_user_bundle(uid, scenario_type=scenario_type)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{uid}_export.json",
            json.dumps(bundle, ensure_ascii=False, indent=2),
        )
        # Also flatten chat transcripts per room
        for item in bundle.get("rooms") or []:
            room = item.get("room") or {}
            rid = room.get("room_id") or "room"
            lines = []
            for m in item.get("messages") or []:
                lines.append(f"{m.get('character')}: {m.get('txt')}")
            zf.writestr(f"transcripts/{rid}.txt", "\n".join(lines))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"agora_export_{uid}.zip",
    )


@app.route('/api/admin/users', methods=['GET', 'POST'])
def admin_list_users():
    admin, err = _require_admin()
    if err:
        return err
    store = get_user_store()
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        detail, msg = store.admin_create_user(
            body.get("user_id") or "",
            body.get("password") or "",
            is_admin=bool(body.get("is_admin")),
        )
        if msg or not detail:
            return jsonify({"error": msg or "Failed"}), 400
        if HAVE_AGORA2:
            fields = (agora2_http.load_shared_profile_template().get("profile_fields") or [])
            detail["profile_complete"] = user_profile_complete(detail.get("profile") or {}, fields)
            detail["profile_field_count"] = len(
                [k for k, v in (detail.get("profile") or {}).items() if v not in (None, "", [])]
            )
        return jsonify(detail), 201

    users = store.list_users()
    if HAVE_AGORA2:
        fields = (agora2_http.load_shared_profile_template().get("profile_fields") or [])
        for u in users:
            u["profile_complete"] = user_profile_complete(u.get("profile") or {}, fields)
    return jsonify({"users": users})


@app.route('/api/admin/users/<user_id>', methods=['GET', 'DELETE'])
def admin_user_detail(user_id):
    admin, err = _require_admin()
    if err:
        return err
    store = get_user_store()
    if request.method == "DELETE":
        ok, msg = store.admin_delete_user(user_id, admin["user_id"])
        if not ok:
            return jsonify({"error": msg or "Failed"}), 400
        return jsonify({"ok": True, "user_id": user_id})

    detail = store.get_user_detail(user_id)
    if not detail:
        return jsonify({"error": "User not found"}), 404
    if HAVE_AGORA2:
        fields = (agora2_http.load_shared_profile_template().get("profile_fields") or [])
        detail["profile_complete"] = user_profile_complete(detail.get("profile") or {}, fields)
    return jsonify(detail)


@app.route('/api/admin/users/<user_id>/password', methods=['POST'])
def admin_reset_password(user_id):
    _, err = _require_admin()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    ok, msg = get_user_store().admin_set_password(user_id, body.get("password") or "")
    if not ok:
        return jsonify({"error": msg or "Failed"}), 400
    return jsonify({"ok": True, "user_id": user_id})


@app.route('/api/admin/users/<user_id>/admin', methods=['POST'])
def admin_set_admin_flag(user_id):
    admin, err = _require_admin()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    is_admin = bool(body.get("is_admin"))
    ok, msg = get_user_store().admin_set_admin(user_id, is_admin, admin["user_id"])
    if not ok:
        return jsonify({"error": msg or "Failed"}), 400
    detail = get_user_store().get_user_detail(user_id)
    if HAVE_AGORA2 and detail:
        fields = (agora2_http.load_shared_profile_template().get("profile_fields") or [])
        detail["profile_complete"] = user_profile_complete(detail.get("profile") or {}, fields)
    return jsonify({"ok": True, "user": detail})


@app.route('/api/agora2/profile/<user_id>', methods=['GET', 'POST'])
def agora2_user_profile(user_id):
    """Legacy path: prefer /api/me/profile with Bearer token."""
    if HAVE_USER_STORE:
        store = get_user_store()
        auth_user = store.resolve_token(_bearer_token())
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", (user_id or "").strip()) or ""
        if not auth_user:
            return jsonify({"error": "Unauthorized"}), 401
        if auth_user["user_id"] != safe and not auth_user.get("is_admin"):
            return jsonify({"error": "Forbidden"}), 403
        if request.method == "GET":
            data = store.get_profile(safe)
            return jsonify({"user_id": safe, "profile": data.get("profile") or {}})
        body = request.get_json(silent=True) or {}
        profile = body.get("profile") if isinstance(body.get("profile"), dict) else {}
        data = store.save_profile(safe, profile)
        return jsonify({"user_id": safe, "profile": data.get("profile") or {}})
    if not HAVE_AGORA2:
        return jsonify({"error": "Agora-2 adapter not available"}), 503
    from profile_store import load_profile, save_profile
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", (user_id or "web_user").strip()) or "web_user"
    if request.method == "GET":
        data = load_profile(safe, agora2_http.PROFILES_DIR)
        return jsonify({"user_id": safe, "profile": data.get("profile") or {}})
    body = request.get_json(silent=True) or {}
    profile = body.get("profile") if isinstance(body.get("profile"), dict) else {}
    data = load_profile(safe, agora2_http.PROFILES_DIR)
    merged = {**(data.get("profile") or {}), **profile}
    data["profile"] = merged
    save_profile(safe, data, agora2_http.PROFILES_DIR)
    return jsonify({"user_id": safe, "profile": merged})


@app.route('/api/agora2/template/<scenario_type>', methods=['GET'])
def agora2_template(scenario_type):
    if not HAVE_AGORA2:
        return jsonify({"error": "Agora-2 adapter not available"}), 503
    if not agora2_http.is_agora2_scenario(scenario_type):
        return jsonify({"error": "Unknown scenario_type"}), 404
    from profile_store import load_scenario_template
    tmpl = load_scenario_template(scenario_type, agora2_http.TEMPLATES_DIR)
    return jsonify({
        "label": tmpl.get("label"),
        "scenario_fields": tmpl.get("scenario_fields") or [],
        "profile_fields": tmpl.get("profile_fields") or [],
    })


@app.route('/api/emotion/analyze', methods=['POST'])
def analyze_emotion():
    """Analyze text + sliders to determine emotional state"""
    if not EMOTION_MODULE_LOADED:
        return jsonify({"error": "Emotion module not available"}), 503

    data = request.json or {}
    text    = (data.get("text") or "").strip()
    valence = float(data.get("valence", 0.5))
    arousal = float(data.get("arousal", 0.5))
    control = float(data.get("control", 0.5))

    p_slider = _emotion_probs_from_sliders(valence, arousal, control)
    if not text:
        p_final = p_slider
    else:
        p_text = _emotion_probs_from_text(text)
        p_final = _emotion_fuse(p_text, p_slider, 0.25)

    emotion_tag = max(p_final.items(), key=lambda x: x[1])[0]
    confidence  = p_final[emotion_tag]

    return jsonify({
        "emotion_tag":   emotion_tag,
        "confidence":    round(confidence, 4),
        "probabilities": {k: round(v, 4) for k, v in p_final.items()},
    })


@app.route('/api/agent-prompt/<agent_key>', methods=['GET'])
def get_agent_prompt(agent_key):
    """Get default prompt for an agent"""
    agent_key = (agent_key or "").upper()
    if agent_key not in POOL_KEYS:
        return jsonify({"error": "Invalid agent key"}), 400

    try:
        if agent_key in {"A", "B", "C"}:
            bot_file_map = {
                'A': BOT1_FILE,
                'B': BOT2_FILE,
                'C': BOT3_FILE,
            }
            prompt = AGENT_POOL[agent_key]["role_text"]
        else:
            prompt = AGENT_POOL[agent_key]["role_text"]
        return jsonify({"prompt": prompt})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 多智能体聊天机器人系统启动中...")
    print("🚀 Starting Multi-Agent Chatbot System...")
    print("=" * 60)
    print(f"✓ Scenes loaded: {list(SCENES.keys())} ({sum(len(v) for v in SCENES.values())} chars total)")
    print(f"✓ Agent pool: {', '.join([AGENT_POOL[k]['name'] for k in POOL_KEYS])}")
    print(f"✓ Agora-2 adapter: {'on' if HAVE_AGORA2 else 'off'}"
          + (f" ({', '.join(agora2_http.SCENARIO_TYPES)})" if HAVE_AGORA2 else ""))
    if HAVE_USER_STORE:
        get_user_store()  # init DB + bootstrap admin from env
        print("✓ User store: SQLite (register/login + profiles)")
    else:
        print("⚠ User store: off")
    print("✓ Mode: API only (use React frontend on :5173)")
    print("\n" + "=" * 60)
    # Port: use PORT env var, or find first available in 5000-5009
    import socket
    port = 0
    if os.getenv("PORT"):
        try:
            port = int(os.getenv("PORT", "0"))
        except ValueError:
            port = 0
    if port == 0:
        for p in range(5000, 5010):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', p))
            sock.close()
            if result != 0:
                port = p
                break
        if port == 0:
            port = 5000  # fallback

    print(f"🔌 API listening: http://localhost:{port}")
    print(f"💚 Health check:  http://localhost:{port}/api/health")
    print("🖥️  Frontend:      http://localhost:5173  (npm run dev in frontend/)")
    print("=" * 60)
    print("\n按 Ctrl+C 停止服务器 / Press Ctrl+C to stop the server\n")
    app.run(debug=True, host='127.0.0.1', port=port, use_reloader=False)
