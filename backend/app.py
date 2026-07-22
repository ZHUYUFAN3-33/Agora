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
from typing import Dict, List, Literal, Optional, Tuple
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from openai import OpenAI

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
PREFER_AGENTS = 0.85  # When admin chooses U, override to random agent with this probability

# Load API key from environment or use default (should be set in .env)
API_KEY = os.getenv("OPENAI_API_KEY", "sk-tnIxDvUFzbMtFbnGpiLC5FXqep9dRMRdsdvUWs2g9hT3BlbkFJmfl6UE3khKvUqT_xeZpq66twaUika-kvxbrc-srSQA")

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
LOG_DIR = os.path.join(BASE_DIR, "logs")
DECISION_BLOCK_DIR = os.path.join(SCENE_DIR, "decision block")
EMOTION_BLOCK_DIR = os.path.join(SCENE_DIR, "emotion block")  # Newst: new/emotion block/
EMOTION_PROMPTS_LEGACY = os.path.join(BASE_DIR, "emotion block", "prompts")  # fallback

ensure_dir(LOG_DIR)

# Load agent configs from info.jsonl (default decision/emotion per agent)
AGENT_CONFIGS = load_agent_configs(INFO_JSONL)

# Initialize OpenAI clients (will be initialized on first use)
client_chat = None
client_admin = None

def get_openai_clients():
    """Lazy initialization of OpenAI clients"""
    global client_chat, client_admin
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
SLOT_KEYS: List[str] = ["A", "B", "C"]
POOL_KEYS: List[str] = ["A", "B", "C", "D", "E", "F"]
PROFILE_FIXED_CONFIG: Dict[str, dict] = {
    "A": {"decision": "Spontaneous", "emotion": "joy"},
    "B": {"decision": "Rational", "emotion": "fear"},
    "C": {"decision": "Avoidant", "emotion": "disgust"},
    "D": {"decision": "Dependent", "emotion": "surprise"},
    "E": {"decision": "Intuitive", "emotion": "anger"},
    "F": {"decision": "Rational", "emotion": "sadness"},
}

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
    for slot in SLOT_KEYS:
        profile_key = session["slot_to_profile"].get(slot, slot)
        prof = AGENT_POOL.get(profile_key, AGENT_POOL[slot])
        agents_map[slot] = ChatAgent(slot, prof["name"], prof["role_text"])
    agent_list = [agents_map[s] for s in SLOT_KEYS]
    all_names = [a.name for a in agent_list]
    return agents_map, agent_list, all_names


def _runtime_config_from_slot_profiles(slot_to_profile: Dict[str, str]) -> Dict[str, dict]:
    conf: Dict[str, dict] = {}
    for slot in SLOT_KEYS:
        profile_key = slot_to_profile.get(slot, slot)
        fixed = PROFILE_FIXED_CONFIG.get(profile_key, PROFILE_FIXED_CONFIG.get(slot, {"decision": "Rational", "emotion": "joy"}))
        conf[slot] = {"decision": fixed["decision"], "emotion": fixed["emotion"]}
    return conf


def init_session(room_id: str) -> dict:
    """Initialize a new chat session"""
    chat_log_path = os.path.join(LOG_DIR, f"{room_id}.jsonl")
    thinking_log_path = os.path.join(LOG_DIR, f"{room_id}_thinkinglog.jsonl")
    moderator_log_path = os.path.join(LOG_DIR, f"{room_id}_moderator.jsonl")

    chat_fp = open(chat_log_path, "a", encoding="utf-8")
    think_fp = open(thinking_log_path, "a", encoding="utf-8")
    moderator_fp = open(moderator_log_path, "a", encoding="utf-8")

    session = {
        "room_id": room_id,
        "scene_id": "scene1",
        "mode": "full",
        "slot_to_profile": {"A": "A", "B": "B", "C": "C"},
        "agent_runtime_config": {
            "A": {"decision": AGENT_CONFIGS.get("A", {}).get("decision", "Rational"), "emotion": AGENT_CONFIGS.get("A", {}).get("emotion", "Joy")},
            "B": {"decision": AGENT_CONFIGS.get("B", {}).get("decision", "Rational"), "emotion": AGENT_CONFIGS.get("B", {}).get("emotion", "Joy")},
            "C": {"decision": AGENT_CONFIGS.get("C", {}).get("decision", "Rational"), "emotion": AGENT_CONFIGS.get("C", {}).get("emotion", "Joy")},
        },
        "history": [],
        "known_user_facts": {},
        "bots_since_user": 0,
        "turn_idx": 0,
        "fallback_queue": [],
        "last_speaker_label": "",
        "consecutive_count": 0,
        "has_spoken": {"A": False, "B": False, "C": False},
        "chat_log_path": chat_log_path,
        "thinking_log_path": thinking_log_path,
        "moderator_log_path": moderator_log_path,
        "chat_fp": chat_fp,
        "think_fp": think_fp,
        "moderator_fp": moderator_fp,
        # Newst: phase-based moderator state
        "moderator_state": {"mode": None, "state": "Exploration", "stall": False, "goal": ""},
        "user_turn_count": 0,
        "turns_in_current_state": 0,
    }
    return session


def append_jsonl(fp, obj: dict):
    fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
    fp.flush()


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
    scene_id = (data.get("scene_id") or "scene1").strip()
    mode = (data.get("mode") or "full").strip().lower()
    if mode not in {"full", "limited", "single"}:
        mode = "full"
    requested_limited_keys = data.get("limited_selected_agent_keys") or []
    if scene_id not in SCENES:
        scene_id = "scene1" if SCENES else ""
    room_id = make_room_id_6()
    session = init_session(room_id)
    session["scene_id"] = scene_id
    session["mode"] = mode

    if mode == "limited":
        chosen_profiles = _normalize_limited_keys([str(k).upper() for k in requested_limited_keys if isinstance(k, str)])
        session["slot_to_profile"] = {slot: chosen_profiles[i] for i, slot in enumerate(SLOT_KEYS)}
        session["agent_runtime_config"] = _runtime_config_from_slot_profiles(session["slot_to_profile"])
    else:
        session["slot_to_profile"] = {"A": "A", "B": "B", "C": "C"}
        session["agent_runtime_config"] = {
            "A": {"decision": AGENT_CONFIGS.get("A", {}).get("decision", "Rational"), "emotion": AGENT_CONFIGS.get("A", {}).get("emotion", "Joy")},
            "B": {"decision": AGENT_CONFIGS.get("B", {}).get("decision", "Rational"), "emotion": AGENT_CONFIGS.get("B", {}).get("emotion", "Joy")},
            "C": {"decision": AGENT_CONFIGS.get("C", {}).get("decision", "Rational"), "emotion": AGENT_CONFIGS.get("C", {}).get("emotion", "Joy")},
        }

    session_agents, _, _ = _make_session_agents(session)
    chat_sessions[room_id] = session

    return jsonify({
        "room_id": room_id,
        "message": "Chat session started",
        "mode": mode,
        "agents": [
            {
                "key": slot,
                "pool_key": session["slot_to_profile"].get(slot, slot),
                "name": session_agents[slot].name,
                "role": session_agents[slot].role_text.splitlines()[0] if session_agents[slot].role_text else "",
                "decision": session["agent_runtime_config"].get(slot, {}).get("decision", "Rational"),
                "emotion": session["agent_runtime_config"].get(slot, {}).get("emotion", "Joy"),
            }
            for slot in SLOT_KEYS
        ]
    })


@app.route('/api/message', methods=['POST'])
def send_message():
    """Send a user message and get agent responses"""
    data = request.json
    room_id = data.get("room_id")
    user_message = data.get("message", "").strip()
    
    if not room_id or room_id not in chat_sessions:
        return jsonify({"error": "Invalid room_id"}), 400
    
    if not user_message:
        return jsonify({"error": "Message cannot be empty"}), 400
    
    session = chat_sessions[room_id]
    session_mode = session.get("mode", "full")
    agents, agent_list, all_agent_names = _make_session_agents(session)

    # Emotion mode: optional emotion_tag + emotion_target from frontend
    emotion_tag    = data.get("emotion_tag")     # e.g. "joy", "anger", None
    emotion_target = data.get("emotion_target")  # "all" | "A" | "B" | "C" | None

    # Per-agent emotion overrides from customizer (key→emotion_tag)
    agent_emotion_overrides = data.get("agent_emotion_overrides") or {}  # {"A": "joy", ...}

    # Per-agent additional rules from customizer
    additional_rules = data.get("additional_rules") or {}  # {"A": "...", ...}

    # Per-agent decision block (Rational, Intuitive, etc.)
    agent_decision_block = data.get("agent_decision_block") or {}  # {"A": "Rational", ...}

    # Global pacing: when to let user speak (NOT per-agent)
    max_agent_turns_before_user = int(data.get("max_agent_turns_before_user") or 5)
    max_user_gap = int(data.get("max_user_gap") or 12)

    # Single mode: plain AI, no persona/scene/emotion/decision
    single_mode = data.get("single_mode") is True

    # Scene: update session if scene_id provided
    req_scene_id = (data.get("scene_id") or "").strip()
    if req_scene_id and req_scene_id in SCENES:
        session["scene_id"] = req_scene_id
    base_scene = SCENES.get(session.get("scene_id", "scene1"), scene)

    def _load_emotion_prompt(tag: str) -> str:
        """Load emotion prompt. Prefer Newst emotion block, fallback to legacy prompts."""
        if not tag:
            return ""
        tag_lower = tag.lower()
        for ep_dir in [EMOTION_BLOCK_DIR, EMOTION_PROMPTS_LEGACY]:
            path = os.path.join(ep_dir, f"{tag_lower}.txt")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as _f:
                    return _f.read()
        return ""

    def _load_decision_block(name: str) -> str:
        """Load decision block prompt (Rational, Intuitive, Dependent, Avoidant, Spontaneous)."""
        if not name or not os.path.isdir(DECISION_BLOCK_DIR):
            return ""
        path = os.path.join(DECISION_BLOCK_DIR, f"{name}.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as _f:
                return _f.read()
        return ""

    def _normalize_style_hint(text: str) -> str:
        """Ensure style hint is plain content so STYLE PREFERENCE wrapper appears exactly once."""
        t = (text or "").strip()
        if not t:
            return ""

        # If user pasted wrapped blocks, keep only inner contents.
        wrapped = re.findall(
            r"\[STYLE PREFERENCE[^\]]*\](.*?)\[END STYLE PREFERENCE\]",
            t,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if wrapped:
            t = "\n".join(s.strip() for s in wrapped if s.strip())

        # Remove stray wrapper marker lines if present.
        t = re.sub(r"(?im)^\s*\[STYLE PREFERENCE[^\]]*\]\s*$", "", t)
        t = re.sub(r"(?im)^\s*\[END STYLE PREFERENCE\]\s*$", "", t)

        return t.strip()[:500]

    # Load sidebar emotion prompt (shared)
    sidebar_emotion_prompt = _load_emotion_prompt(emotion_tag)

    def get_scene_for_agent(agent_key: str) -> str:
        """Return scene string with emotion prompt + decision block + additional rules injected."""
        result = base_scene

        # 1. Per-agent emotion override (from customizer) takes priority
        override_tag = agent_emotion_overrides.get(agent_key)
        if not override_tag and session_mode == "limited":
            override_tag = session.get("agent_runtime_config", {}).get(agent_key, {}).get("emotion")
        if override_tag:
            ep = _load_emotion_prompt(override_tag)
            if ep:
                result += (
                    "\n\n" + "=" * 60
                    + f"\nEMOTIONAL CONTEXT — {override_tag.upper()} (agent-specific):\n"
                    + "=" * 60 + "\n" + ep
                    + "\n\nVISIBLE EXPRESSION RULE:\n"
                    + "- After any required greeting, your wording should clearly reflect this emotional tone.\n"
                    + "- Do not default to generic upbeat phrasing unless this emotion block supports it."
                )
        elif sidebar_emotion_prompt and emotion_target in (None, "all", agent_key):
            # 2. Sidebar emotion (global or targeted)
            result += (
                "\n\n" + "=" * 60
                + f"\nEMOTIONAL CONTEXT — {emotion_tag.upper()} (applied to this agent):\n"
                + "=" * 60 + "\n" + sidebar_emotion_prompt
                + "\n\nVISIBLE EXPRESSION RULE:\n"
                + "- After any required greeting, your wording should clearly reflect this emotional tone.\n"
                + "- Do not default to generic upbeat phrasing unless this emotion block supports it."
            )

        # 3. Decision block (frontend overrides info.jsonl default)
        block_name = (
            agent_decision_block.get(agent_key)
            or session.get("agent_runtime_config", {}).get(agent_key, {}).get("decision")
            or AGENT_CONFIGS.get(agent_key, {}).get("decision", "Rational")
        )
        block_prompt = _load_decision_block(block_name)
        if block_prompt:
            result += (
                "\n\n" + "=" * 60
                + f"\nDECISION ARCHITECTURE — {block_name}:\n"
                + "=" * 60 + "\n" + block_prompt
            )

        # 4. Additional rules from customizer
        extra = (additional_rules.get(agent_key) or "").strip()
        if extra:
            # Treat user-provided text as style preference only, not task override.
            safe_extra = _normalize_style_hint(extra)
            if safe_extra:
                result += (
                    "\n\n" + "=" * 60
                    + "\n[STYLE PREFERENCE — does not override role, structure, safety, or task]\n"
                    + safe_extra
                    + "\n[END STYLE PREFERENCE]\n"
                    + "=" * 60
                )

        return result

    # Add user message to history
    user_msg = {
        "chat_room_id": room_id,
        "time": now_local_iso(),
        "character": "user",
        "txt": user_message,
    }
    append_jsonl(session["chat_fp"], user_msg)
    session["history"].append(user_msg)
    
    # Update user facts
    session["known_user_facts"] = update_user_facts(session["known_user_facts"], user_message)
    
    # Update speaker tracking
    if session["last_speaker_label"] == "user":
        session["consecutive_count"] += 1
    else:
        session["last_speaker_label"] = "user"
        session["consecutive_count"] = 1
    
    session["bots_since_user"] = 0
    session["turn_idx"] += 1
    session["user_turn_count"] = session.get("user_turn_count", 0) + 1

    # Initialize OpenAI clients on first use
    client_chat, client_admin = get_openai_clients()

    # Merge agent config: frontend agent_decision_block overrides info.jsonl
    def _effective_decision(agent_key):
        return (
            agent_decision_block.get(agent_key)
            or session.get("agent_runtime_config", {}).get(agent_key, {}).get("decision")
            or AGENT_CONFIGS.get(agent_key, {}).get("decision", "Rational")
        )

    def _get_phase_context(agent_key: str) -> str:
        ms = session["moderator_state"]
        decision = _effective_decision(agent_key)
        mode = ms.get("mode") or "S"
        stall = ms.get("stall", False)
        assignment = get_phase_prompt(ms.get("state", "Exploration"), mode, decision, stall)
        lines = ["=== DELIBERATION STATE ===", f"Phase: {ms.get('state', 'Exploration')}"]
        if ms.get("goal"):
            lines.append(f"Goal: {ms['goal']}")
        lines.append(f"Your task: {assignment}")
        return "\n".join(lines)

    def _run_moderator():
        """Admin-3: classify deliberation state."""
        transcript_lines = history_to_transcript_lines(session["history"])
        history_str = clamp_history(transcript_lines, 12000)
        roles = build_roles_summary(agent_list)
        turns = session.get("turns_in_current_state", 0)
        stall_eligible = turns > MODERATOR_STALL_TURNS
        stall_hint = f"In '{session['moderator_state'].get('state','Exploration')}' for {turns} agent turns."
        if not stall_eligible:
            stall_hint += " Do NOT set stall: true yet."
        msgs = [
            {"role": "system", "content": ADMIN3_SYSTEM},
            {"role": "user", "content": f"=== SCENE ===\n{base_scene}\n\n=== ROLES ===\n{roles}\n\n{stall_hint}\n\n=== TRANSCRIPT ===\n{history_str}"},
        ]
        raw = create_response_with_client(client_admin, "gpt-4o", msgs, 0.0, 300)
        append_jsonl(session["moderator_fp"], {"time": now_local_iso(), "admin3": raw})
        parsed = parse_moderator_plan(raw)
        if parsed:
            prev = session["moderator_state"]["state"]
            session["moderator_state"].update(parsed)
            if parsed["state"] != prev:
                session["turns_in_current_state"] = 0
            else:
                session["turns_in_current_state"] = session.get("turns_in_current_state", 0) + MODERATOR_INTERVAL

    # Run moderator when appropriate (before agent loop)
    if session["user_turn_count"] % MODERATOR_INTERVAL == 0 or session.get("turns_in_current_state", 0) > MODERATOR_STALL_TURNS:
        _run_moderator()

    # Single mode: plain AI, no persona/emotion/decision; but scene context is used when available
    if single_mode:
        print("[single_mode] Using plain AI (scene context included, no persona/emotion/decision)")
        transcript = build_transcript(session["history"], max_turns=12)
        scene_context = ""
        if base_scene and base_scene.strip():
            scene_context = f"\n\n[Scene context — use to inform answers when relevant]\n{base_scene.strip()}\n"
        try:
            sys_content = "You are a helpful AI assistant. Reply concisely and neutrally. Do not adopt any persona, emotion, or role." + scene_context
            user_content = f"Conversation:\n{transcript}\n\nRespond to the user:"
            msgs = [{"role": "system", "content": sys_content}, {"role": "user", "content": user_content}]
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
        session["has_spoken"]["A"] = True
        return jsonify({"responses": [{"agent_key": "A", "message": txt}], "phase": None, "stall": False})
    
    # Get agent responses (Newst: phase-based, Admin-1/2 for next speaker)
    responses = []
    responded_keys_this_turn: List[str] = []
    transcript_lines = history_to_transcript_lines(session["history"])
    name_map = {a.key: a.name for a in agent_list}
    max_history_chars = 12000

    def _user_gap(hist):
        li = next((i for i in range(len(hist) - 1, -1, -1) if hist[i].get("character") == "user"), None)
        return (len(hist) - 1) - li if li is not None else len(hist)

    def _last_agent_key() -> Optional[str]:
        last_label = session.get("last_speaker_label") or ""
        for key, agent in agents.items():
            if agent.name == last_label:
                return key
        return None

    def _pick_alternative_agent(*exclude_keys: str) -> Optional[str]:
        excluded = {k for k in exclude_keys if k in SLOT_KEYS}
        candidates = [k for k in SLOT_KEYS if k not in excluded]
        if not candidates:
            return None
        candidates.sort(
            key=lambda k: (
                k in responded_keys_this_turn,
                session["has_spoken"].get(k, False),
                k,
            )
        )
        return candidates[0]

    def _normalize_next_speaker(choice: Optional[str]) -> Optional[str]:
        if choice not in {"A", "B", "C", "U"}:
            return _pick_alternative_agent()
        if choice == "U":
            return "U"

        last_key = _last_agent_key()
        if last_key and choice == last_key and int(session.get("consecutive_count", 0) or 0) >= 1:
            alt = _pick_alternative_agent(choice)
            if alt:
                return alt

        # Within one user turn, avoid reusing the same speaker until others have had a chance.
        if choice in responded_keys_this_turn and len(responded_keys_this_turn) < len(SLOT_KEYS):
            alt = _pick_alternative_agent(*responded_keys_this_turn)
            if alt:
                return alt
        return choice

    def _append_agent_response(speaker: str, txt: str) -> None:
        agent = agents[speaker]
        agent_msg = {"chat_room_id": room_id, "time": now_local_iso(), "character": agent.name, "txt": txt}
        append_jsonl(session["chat_fp"], agent_msg)
        session["history"].append(agent_msg)
        transcript_lines.append(f"{agent.name}: {txt}")
        responses.append({"agent": agent.name, "agent_key": speaker, "message": txt, "time": agent_msg["time"]})

        agent.spoke += 1
        session["has_spoken"][speaker] = True
        session["bots_since_user"] += 1
        session["turn_idx"] += 1
        session["turns_in_current_state"] = session.get("turns_in_current_state", 0) + 1
        responded_keys_this_turn.append(speaker)

        if session.get("last_speaker_label") == agent.name:
            session["consecutive_count"] = session.get("consecutive_count", 0) + 1
        else:
            session["last_speaker_label"] = agent.name
            session["consecutive_count"] = 1

    def _admin_choose_next() -> Optional[str]:
        if session["bots_since_user"] >= max_agent_turns_before_user:
            return "U"
        li = last_user_index(transcript_lines)
        gap = (len(transcript_lines) - 1 - li) if li is not None else len(transcript_lines)
        if gap >= max_user_gap:
            return "U"
        history_str = clamp_history(transcript_lines, max_history_chars)
        roles = build_roles_summary(agent_list)
        stats = (
            f"bots_since_user={session['bots_since_user']}, "
            f"moderator_state={session['moderator_state'].get('state','Exploration')}, "
            f"last_speaker={session.get('last_speaker_label') or '(none)'}, "
            f"consecutive_count={session.get('consecutive_count', 0)}, "
            f"responded_this_turn={','.join(responded_keys_this_turn) or '(none)'}"
        )
        admin1_msgs = [
            {"role": "system", "content": ADMIN1_SYSTEM},
            {"role": "user", "content": f"=== SCENE ===\n{base_scene}\n\n=== ROLES ===\n{roles}\n\n=== STATS ===\n{stats}\n\n=== TRANSCRIPT ===\n{history_str}\n\nDecide NEXT."},
        ]
        admin1_out = create_response_with_client(client_admin, "gpt-4o", admin1_msgs, 0.2, 260)
        append_jsonl(session["think_fp"], {
            "chat_room_id": room_id,
            "time": now_local_iso(),
            "turn": session.get("user_turn_count", 0),
            "turn_idx": session.get("turn_idx", 0),
            "phase": session["moderator_state"].get("state", "Exploration"),
            "admin1": admin1_out,
        })
        admin2_msgs = [{"role": "system", "content": ADMIN2_SYSTEM}, {"role": "user", "content": admin1_out}]
        admin2_out = create_response_with_client(client_admin, "gpt-4o", admin2_msgs, 0.0, 16)
        admin2_out = (admin2_out or "").strip().upper()
        append_jsonl(session["think_fp"], {
            "chat_room_id": room_id,
            "time": now_local_iso(),
            "turn": session.get("user_turn_count", 0),
            "turn_idx": session.get("turn_idx", 0),
            "phase": session["moderator_state"].get("state", "Exploration"),
            "admin2": admin2_out,
        })
        if admin2_out not in {"A", "B", "C", "U"}:
            admin2_out = _pick_alternative_agent() or random.choice(["A", "B", "C"])
        if admin2_out == "U" and random.random() < PREFER_AGENTS:
            admin2_out = _pick_alternative_agent(_last_agent_key() or "") or random.choice(["A", "B", "C"])
        return _normalize_next_speaker(admin2_out)

    def _call_chat_agent_new(speaker: str, force_intro: bool = False, stall_mode: bool = False) -> str:
        agent = agents[speaker]
        scene_for_agent = get_scene_for_agent(speaker)
        phase_ctx = _get_phase_context(speaker)
        stall = session["moderator_state"].get("stall", False)
        temp = 0.8 if not (stall or stall_mode) else min(1.05, 1.4)
        extra = (
            f"\n\n(Important) This is your FIRST message. Start with: Hi, I'm {agent.name}."
            " After that opening, the rest of your message must follow the current runtime emotional tone and decision style."
            " Do not default to cheerful language unless the runtime configuration supports it."
        ) if force_intro else ""
        history_str = clamp_history(transcript_lines, max_history_chars)
        if stall_mode:
            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "The moderator has flagged a stall — the group is going in circles.\n"
                "You MUST make a decisive move: propose something new, force a comparison, "
                "ask a direct question that demands an answer, or take a clear position.\n"
                "Never call the human participant 'U'. If you address them, say 'user' or use their nickname.\n"
                "Do NOT repeat what has already been said.\n\n"
                "[TRANSCRIPT START]\n"
                f"{history_str}\n"
                "[TRANSCRIPT END]\n"
            )
        else:
            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "Each line is formatted as: Speaker: message\n"
                f"You are ONLY writing the next message for {agent.name}. Do NOT reproduce or repeat any line from the transcript.\n"
                "Continue the conversation as your character.\n"
                "Try to keep a lively group dynamic by engaging other bots (react, ask them questions, build on their points), "
                "while still keeping the user included.\n"
                "Never call the human participant 'U'. If you address them, say 'user' or use their nickname.\n\n"
                "[TRANSCRIPT START]\n"
                f"{history_str}\n"
                "[TRANSCRIPT END]\n"
                f"{extra}"
            )
        sys_prompt = agent.system_prompt(scene_for_agent, name_map, phase_ctx)
        msgs = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}]
        txt = create_response_with_client(client_chat, "gpt-4o", msgs, temp, 220)
        return sanitize_single_message((txt or "").strip() or "…", agent.name, all_agent_names)

    def _run_stall_burst(skip_key: Optional[str] = None):
        """When stall: force A->B->C burst with stall-specific prompt."""
        for key in ["A", "B", "C"]:
            if key == skip_key:
                continue
            if session["bots_since_user"] >= max_agent_turns_before_user:
                break
            if _user_gap(session["history"]) >= max_user_gap:
                break
            txt = _call_chat_agent_new(key, force_intro=not session["has_spoken"][key], stall_mode=True)
            _append_agent_response(key, txt)

    for _ in range(max_agent_turns_before_user + 2):
        if session["bots_since_user"] >= max_agent_turns_before_user:
            break
        if _user_gap(session["history"]) >= max_user_gap:
            break

        speaker = _admin_choose_next()
        if speaker == "U":
            break

        txt = _call_chat_agent_new(speaker, force_intro=not session["has_spoken"][speaker])
        _append_agent_response(speaker, txt)

        if session["moderator_state"].get("stall"):
            _run_stall_burst(skip_key=speaker)
            break

    current_phase = session["moderator_state"].get("state", "Exploration")
    return jsonify({
        "room_id": room_id,
        "user_message": user_message,
        "responses": responses,
        "known_facts": list(session["known_user_facts"].values()),
        "emotion_tag": emotion_tag,
        "emotion_target": emotion_target,
        "phase": current_phase,
        "stall": session["moderator_state"].get("stall", False),
    })


@app.route('/api/history/<room_id>', methods=['GET'])
def get_history(room_id):
    """Get chat history for a session"""
    if room_id not in chat_sessions:
        return jsonify({"error": "Session not found"}), 404
    
    session = chat_sessions[room_id]
    session_agents, _, _ = _make_session_agents(session)
    return jsonify({
        "room_id": room_id,
        "mode": session.get("mode", "full"),
        "active_agents": [
            {"key": slot, "pool_key": session.get("slot_to_profile", {}).get(slot, slot), "name": session_agents[slot].name}
            for slot in SLOT_KEYS
        ],
        "history": session["history"],
        "known_facts": list(session["known_user_facts"].values()),
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


@app.route('/api/export-logs/<room_id>', methods=['GET'])
def export_logs(room_id):
    """Export current session logs as a zip file (chat, thinking, params)."""
    if room_id not in chat_sessions:
        return jsonify({"error": "Session not found"}), 404

    buf = io.BytesIO()
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

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"agora_logs_{room_id}.zip",
    )


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "sessions": len(chat_sessions),
        "emotion_module": EMOTION_MODULE_LOADED
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
