#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask Web API for Multi-Agent Chatbot System
"""

import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI

# Import functions from agent_wakeup_4o_e.py
import sys
import importlib.util

# Get base directory (will be reused)
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
# ──────────────────────────────────────────────────────────────────────────────
AGENT_MODULE_PATH = os.path.join(BASE_DIR, "agent_wakeup_4o_e.py")

spec = importlib.util.spec_from_file_location("agent_wakeup_4o_e", AGENT_MODULE_PATH)
agent_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_module)

# Import functions
now_local_iso = agent_module.now_local_iso
read_text = agent_module.read_text
ensure_dir = agent_module.ensure_dir
make_room_id_6 = agent_module.make_room_id_6
extract_text = agent_module.extract_text
truncate = agent_module.truncate
build_transcript = agent_module.build_transcript
sanitize_single_message = agent_module.sanitize_single_message
parse_next_token = agent_module.parse_next_token
update_user_facts = agent_module.update_user_facts
facts_to_bullets = agent_module.facts_to_bullets
AgentSpec = agent_module.AgentSpec
call_chat_agent = agent_module.call_chat_agent
call_admin_onepass = agent_module.call_admin_onepass
make_fallback_queue_4bots_then_user = agent_module.make_fallback_queue_4bots_then_user

# Get absolute path for static folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')

# Configure Flask - use empty static_url_path so files are served from root
app = Flask(__name__, 
            static_folder=STATIC_FOLDER, 
            static_url_path='')
CORS(app)

# Configuration
TZ = ZoneInfo("Asia/Tokyo")
Speaker = Literal["A", "B", "C", "U"]

# Load API key from environment or use default (should be set in .env)
API_KEY = os.getenv("OPENAI_API_KEY", "sk-tnIxDvUFzbMtFbnGpiLC5FXqep9dRMRdsdvUWs2g9hT3BlbkFJmfl6UE3khKvUqT_xeZpq66twaUika-kvxbrc-srSQA")

# Global state for chat sessions
chat_sessions: Dict[str, dict] = {}

# Load scene and agent profiles
SCENE_FILE = os.path.join(BASE_DIR, "scene.txt")
BOT1_FILE = os.path.join(BASE_DIR, "chatbot1.txt")
BOT2_FILE = os.path.join(BASE_DIR, "chatbot2.txt")
BOT3_FILE = os.path.join(BASE_DIR, "chatbot3.txt")
LOG_DIR = os.path.join(BASE_DIR, "logs")

ensure_dir(LOG_DIR)

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
scene = read_text(SCENE_FILE) if os.path.exists(SCENE_FILE) else ""
bot1 = read_text(BOT1_FILE) if os.path.exists(BOT1_FILE) else ""
bot2 = read_text(BOT2_FILE) if os.path.exists(BOT2_FILE) else ""
bot3 = read_text(BOT3_FILE) if os.path.exists(BOT3_FILE) else ""

agents: Dict[str, AgentSpec] = {
    "A": AgentSpec("A", "ChatbotA", bot1),
    "B": AgentSpec("B", "ChatbotB", bot2),
    "C": AgentSpec("C", "ChatbotC", bot3),
}
agent_list = [agents["A"], agents["B"], agents["C"]]
all_agent_names = [a.name for a in agent_list]


def init_session(room_id: str) -> dict:
    """Initialize a new chat session"""
    chat_log_path = os.path.join(LOG_DIR, f"{room_id}.jsonl")
    thinking_log_path = os.path.join(LOG_DIR, f"{room_id}_thinkinglog.jsonl")
    
    # Open files in append mode (will be closed when session ends or server stops)
    chat_fp = open(chat_log_path, "a", encoding="utf-8")
    think_fp = open(thinking_log_path, "a", encoding="utf-8")
    
    session = {
        "room_id": room_id,
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
        "chat_fp": chat_fp,
        "think_fp": think_fp,
    }
    return session


def append_jsonl(fp, obj: dict):
    fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
    fp.flush()


@app.route('/')
def index():
    """Serve the main HTML page"""
    try:
        return send_from_directory(STATIC_FOLDER, 'index.html')
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/style.css')
def style_css():
    """Serve CSS file"""
    return send_from_directory(STATIC_FOLDER, 'style.css', mimetype='text/css')

@app.route('/script.js')
def script_js():
    """Serve JavaScript file"""
    return send_from_directory(STATIC_FOLDER, 'script.js', mimetype='application/javascript')

@app.route('/Assets/<path:filename>')
def serve_assets(filename):
    """Serve files from Assets folder"""
    assets_folder = os.path.join(BASE_DIR, 'Assets')
    return send_from_directory(assets_folder, filename)

@app.route('/api/start', methods=['POST'])
def start_chat():
    """Start a new chat session"""
    room_id = make_room_id_6()
    session = init_session(room_id)
    chat_sessions[room_id] = session
    
    return jsonify({
        "room_id": room_id,
        "message": "Chat session started",
        "agents": [
            {"key": "A", "name": agents["A"].name},
            {"key": "B", "name": agents["B"].name},
            {"key": "C", "name": agents["C"].name},
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

    # Emotion mode: optional emotion_tag + emotion_target from frontend
    emotion_tag    = data.get("emotion_tag")     # e.g. "joy", "anger", None
    emotion_target = data.get("emotion_target")  # "all" | "A" | "B" | "C" | None

    # Load emotion prompt text (shared)
    emotion_prompt = ""
    if emotion_tag and EMOTION_MODULE_LOADED:
        ep_path = os.path.join(BASE_DIR, "emotion block", "prompts", f"{emotion_tag}.txt")
        if os.path.exists(ep_path):
            with open(ep_path, "r", encoding="utf-8") as _f:
                emotion_prompt = _f.read()

    def get_scene_for_agent(agent_key: str) -> str:
        """Return scene string with emotion prompt injected if this agent is targeted."""
        if not emotion_prompt:
            return scene
        if emotion_target in (None, "all", agent_key):
            return (
                scene
                + "\n\n"
                + "=" * 60
                + f"\nEMOTIONAL CONTEXT — {emotion_tag.upper()} (applied to this agent):\n"
                + "=" * 60
                + "\n"
                + emotion_prompt
            )
        return scene

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
    
    # Initialize OpenAI clients on first use
    get_openai_clients()
    
    # Get agent responses
    responses = []
    
    # Determine next speaker using admin
    for _ in range(5):  # Max 5 agent turns before forcing user
        if session["bots_since_user"] >= 5:
            break
        
        # Check fallback queue first
        if session["fallback_queue"]:
            speaker = session["fallback_queue"].pop(0)
            mode = "fallback"
            thinking = f"Fallback sequence. Next={speaker}."
        else:
            # Use admin to decide next speaker
            nxt, raw, err = call_admin_onepass(
                client=client_admin,
                model="gpt-4o",
                scene=scene,  # admin sees base scene (no emotion bias in speaker selection)
                agents=agent_list,
                history=session["history"],
                known_user_facts=session["known_user_facts"],
                bots_since_user=session["bots_since_user"],
                last_speaker_label=session["last_speaker_label"] or "(none)",
                consecutive_count=session["consecutive_count"],
                debug=False,
            )
            
            if nxt is None:
                session["fallback_queue"] = make_fallback_queue_4bots_then_user()
                speaker = session["fallback_queue"].pop(0)
                mode = "fallback_start"
                thinking = f"Admin failed; starting fallback: {speaker}."
            else:
                speaker = nxt
                mode = "admin"
                thinking = raw.splitlines()[0].strip() if raw.strip() else f"Admin chose Next={speaker}."
        
        # Log thinking
        append_jsonl(session["think_fp"], {
            "chat_room_id": room_id,
            "time": now_local_iso(),
            "mode": mode,
            "bots_since_user": session["bots_since_user"],
            "next": speaker,
            "thinking": thinking,
        })
        
        if speaker == "U":
            break
        
        # Get agent response
        agent = agents[speaker]
        txt = call_chat_agent(
            client=client_chat,
            model="gpt-4o",
            scene=get_scene_for_agent(speaker),
            agent=agent,
            history=session["history"],
            known_user_facts=session["known_user_facts"],
            is_first_utterance=not session["has_spoken"][speaker],
            all_agent_names=all_agent_names,
            debug=False,
        )
        
        # Add agent message to history
        agent_msg = {
            "chat_room_id": room_id,
            "time": now_local_iso(),
            "character": agent.name,
            "txt": txt,
        }
        append_jsonl(session["chat_fp"], agent_msg)
        session["history"].append(agent_msg)
        
        responses.append({
            "agent": agent.name,
            "agent_key": speaker,
            "message": txt,
            "time": agent_msg["time"],
        })
        
        session["has_spoken"][speaker] = True
        session["bots_since_user"] += 1
        session["turn_idx"] += 1
        
        if session["last_speaker_label"] == agent.name:
            session["consecutive_count"] += 1
        else:
            session["last_speaker_label"] = agent.name
            session["consecutive_count"] = 1
    
    return jsonify({
        "room_id": room_id,
        "user_message": user_message,
        "responses": responses,
        "known_facts": list(session["known_user_facts"].values()),
        "emotion_tag":    emotion_tag,
        "emotion_target": emotion_target,
    })


@app.route('/api/history/<room_id>', methods=['GET'])
def get_history(room_id):
    """Get chat history for a session"""
    if room_id not in chat_sessions:
        return jsonify({"error": "Session not found"}), 404
    
    session = chat_sessions[room_id]
    return jsonify({
        "room_id": room_id,
        "history": session["history"],
        "known_facts": list(session["known_user_facts"].values()),
    })


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
    text    = data.get("text", "")
    valence = float(data.get("valence", 0.5))
    arousal = float(data.get("arousal", 0.5))
    control = float(data.get("control", 0.5))

    p_text   = _emotion_probs_from_text(text)
    p_slider = _emotion_probs_from_sliders(valence, arousal, control)
    p_final  = _emotion_fuse(p_text, p_slider)

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
    if agent_key not in ['A', 'B', 'C']:
        return jsonify({"error": "Invalid agent key"}), 400
    
    bot_file_map = {
        'A': BOT1_FILE,
        'B': BOT2_FILE,
        'C': BOT3_FILE,
    }
    
    try:
        prompt = read_text(bot_file_map[agent_key]) if os.path.exists(bot_file_map[agent_key]) else ""
        return jsonify({"prompt": prompt})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 多智能体聊天机器人系统启动中...")
    print("🚀 Starting Multi-Agent Chatbot System...")
    print("=" * 60)
    print(f"✓ Scene loaded: {len(scene)} characters")
    print(f"✓ Agents: {', '.join(all_agent_names)}")
    print(f"✓ Static folder: {STATIC_FOLDER}")
    print(f"✓ Static files exist: {os.path.exists(os.path.join(STATIC_FOLDER, 'index.html'))}")
    print("\n" + "=" * 60)
    # Try to find an available port
    import socket
    port = 5000
    for p in range(5000, 5010):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', p))
        sock.close()
        if result != 0:
            port = p
            break
    
    print(f"🌐 请在浏览器中打开: http://localhost:{port}")
    print(f"🌐 Open in browser: http://localhost:{port}")
    print("=" * 60)
    print("\n按 Ctrl+C 停止服务器 / Press Ctrl+C to stop the server\n")
    app.run(debug=True, host='127.0.0.1', port=port, use_reloader=False)

