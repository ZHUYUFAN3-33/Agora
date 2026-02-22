# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

# ===============================
# API KEY (EDIT ME)
# ===============================
# Paste your real key here. Environment variables are intentionally ignored.
API_KEY = "sk-tnIxDvUFzbMtFbnGpiLC5FXqep9dRMRdsdvUWs2g9hT3BlbkFJmfl6UE3khKvUqT_xeZpq66twaUika-kvxbrc-srSQA"

# OpenAI API requires max_output_tokens >= 16
MIN_OUTPUT_TOKENS = 16

# -------------------------------
# OpenAI client (SDK + fallback)
# -------------------------------

def _effective_api_key() -> str:
    """Return API_KEY ONLY. Environment variables are intentionally ignored."""
    return (API_KEY or "").strip()

def _load_openai_client():
    """Try to load the official OpenAI Python SDK (preferred)."""
    try:
        from openai import OpenAI  # type: ignore
        key = _effective_api_key()
        if not key or key == "sk-xxxx":
            raise RuntimeError("No API key. Set API_KEY at top of script.")
        return OpenAI(api_key=key)
    except Exception:
        return None

def _responses_create_http(payload: dict) -> dict:
    """Fallback raw HTTP call to POST /v1/responses (only if SDK missing)."""
    import requests  # type: ignore

    api_key = _effective_api_key()
    if not api_key or api_key == "sk-xxxx":
        raise RuntimeError("No API key. Set API_KEY at top of script.")
    url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    if not r.ok:
        raise RuntimeError(f"OpenAI HTTP error {r.status_code}: {r.text}")
    return r.json()

def create_response(model: str, messages: List[dict], temperature: float, max_output_tokens: int) -> str:
    """Create a text response with the Responses API (enforces max_output_tokens >= 16)."""
    max_output_tokens = max(int(max_output_tokens), MIN_OUTPUT_TOKENS)

    client = _load_openai_client()
    if client is not None:
        resp = client.responses.create(
            model=model,
            input=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        if hasattr(resp, "output_text") and resp.output_text:
            return resp.output_text.strip()

        try:
            chunks = []
            for item in getattr(resp, "output", []) or []:
                for c in getattr(item, "content", []) or []:
                    text = getattr(c, "text", None)
                    if text:
                        chunks.append(text)
            out = "".join(chunks).strip()
            if out:
                return out
        except Exception:
            pass

        return str(resp).strip()

    payload = {
        "model": model,
        "input": messages,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    resp = _responses_create_http(payload)
    out_parts: List[str] = []
    for item in resp.get("output", []) or []:
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text" and "text" in c:
                out_parts.append(c["text"])
    return "".join(out_parts).strip()

# -------------------------------
# Helpers
# -------------------------------

TOKYO = ZoneInfo("Asia/Tokyo")

def now_local_iso() -> str:
    return datetime.now(TOKYO).isoformat(timespec="seconds")

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()

def safe_read_text(path: Optional[str], default: str) -> str:
    if not path:
        return default
    if not os.path.exists(path):
        return default
    return read_text(path)

def clamp_history(transcript_lines: List[str], max_chars: int) -> str:
    """Keep the most recent lines whose total length <= max_chars."""
    if max_chars <= 0:
        return "\n".join(transcript_lines)
    buf: List[str] = []
    total = 0
    for line in reversed(transcript_lines):
        ln = len(line) + 1
        if total + ln > max_chars and buf:
            break
        buf.append(line)
        total += ln
        if total >= max_chars:
            break
    return "\n".join(reversed(buf))

def write_jsonl_line(fp, obj: dict):
    fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
    fp.flush()

# -------------------------------
# Agent definitions
# -------------------------------

@dataclass
class ChatAgent:
    key: str          # "A" / "B" / "C"
    name: str         # "ChatbotA" / ...
    role_text: str    # loaded from chatbotN.txt
    spoke: int = 0    # number of messages spoken so far

    def system_prompt(self, scene: str, name_map: Dict[str, str]) -> str:
        """
        name_map example:
          {"A":"ChatbotA", "B":"ChatbotB", "C":"ChatbotC"}
        """
        roster = "\n".join([f"- {k}: {v}" for k, v in name_map.items()])
        return (
            f"You are {self.name} in a group chat.\n"
            f"Participants (remember their names):\n{roster}\n"
            f"- U: user\n\n"
            f"GROUP DYNAMICS (important):\n"
            f"- This is a FRIEND group chat. You should actively talk WITH the other bots, not only the user.\n"
            f"- Frequently react to what another bot said, build on it, or gently disagree.\n"
            f"- Often ask another bot a direct question (e.g., \"{name_map.get('B','ChatbotB')}, what do you think?\")\n"
            f"- Keep it natural: don't force a question every single time, but aim for more bot-to-bot back-and-forth.\n"
            f"- You may address the user too, but avoid making every message solely about the user.\n"
            f"- Output ONLY what {self.name} says (no speaker label, no quotes).\n\n"
            f"=== SCENE (shared) ===\n{scene}\n\n"
            f"=== ROLE INSTRUCTIONS (for {self.name}) ===\n{self.role_text}\n"
        )

# -------------------------------
# Admin prompts - ENGLISH
# -------------------------------

ADMIN1_SYSTEM = """You are Admin-1: the group-chat pacing analyst.
You will read: the shared scene, the three role settings, and the full transcript.

Your job: infer who SHOULD speak next and give a brief reason.

PACING GOAL (important):
- Promote natural FRIEND group dynamics with more bot-to-bot discussion.
- Encourage back-and-forth between A/B/C (agree/disagree, build on points, ask each other questions),
  while still keeping the user included regularly.
- Always obey the hard rule: after 5 consecutive agent turns, the next speaker must be U.

You MUST end your output with a single clear decision:
NEXT = A or B or C or U (choose exactly one).
This analysis is NOT shown to the user, but is saved to the thinking log."""

ADMIN2_SYSTEM = """You are Admin-2: the strict next-speaker selector.
You will receive Admin-1's analysis text.
Your job: output ONLY ONE character: A or B or C or U.
Do not output anything else (no spaces, punctuation, explanation, or newline)."""

def build_roles_summary(agents: List[ChatAgent]) -> str:
    parts = []
    for a in agents:
        first = a.role_text.splitlines()[0].strip() if a.role_text.strip() else "(empty role file)"
        parts.append(f"{a.key}={a.name}: {first}")
    return "\n".join(parts)

# -------------------------------
# Core loop
# -------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="scene.txt", help="Path to scene.txt")
    ap.add_argument("--bot1", default="chatbot1.txt", help="Path to chatbot1.txt (A)")
    ap.add_argument("--bot2", default="chatbot2.txt", help="Path to chatbot2.txt (B)")
    ap.add_argument("--bot3", default="chatbot3.txt", help="Path to chatbot3.txt (C)")
    ap.add_argument("--start_order", default="ABCU", help="Up to 4 chars from {A,B,C,U}, default ABCU")
    ap.add_argument("--model", default="gpt-4o", help="Model name, default gpt-4o")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--max_output_tokens", type=int, default=220)
    ap.add_argument("--max_history_chars", type=int, default=12000, help="Transcript chars to include per call")
    ap.add_argument("--log_dir", default=".", help="Directory to write jsonl logs")
    args = ap.parse_args()

    args.max_output_tokens = max(int(args.max_output_tokens), MIN_OUTPUT_TOKENS)

    if not _effective_api_key() or _effective_api_key() == "sk-xxxx":
        print("ERROR: No API key. Please set API_KEY at the top of this script (env vars are ignored).", file=sys.stderr)
        sys.exit(2)

    # Load files
    scene = safe_read_text(args.scene, default="(scene file missing)")
    role_a = safe_read_text(args.bot1, default="(chatbot1.txt missing)")
    role_b = safe_read_text(args.bot2, default="(chatbot2.txt missing)")
    role_c = safe_read_text(args.bot3, default="(chatbot3.txt missing)")

    agents: List[ChatAgent] = [
        ChatAgent("A", "ChatbotA", role_a),
        ChatAgent("B", "ChatbotB", role_b),
        ChatAgent("C", "ChatbotC", role_c),
    ]
    key_to_agent = {a.key: a for a in agents}

    # What each agent sees as the roster mapping
    name_map = {a.key: a.name for a in agents}

    chat_room_id = f"{random.randint(0, 999999):06d}"
    os.makedirs(args.log_dir, exist_ok=True)
    chat_path = os.path.join(args.log_dir, f"{chat_room_id}.jsonl")
    thinking_path = os.path.join(args.log_dir, f"{chat_room_id}_thinking.jsonl")

    transcript_lines: List[str] = []

    def log_chat(character: str, txt: str):
        record = {"chat_room_id": chat_room_id, "time": now_local_iso(), "character": character, "txt": txt}
        write_jsonl_line(chat_fp, record)
        transcript_lines.append(f"{character}: {txt}")  # Speaker attribution for models

    def log_thinking(character: str, txt: str):
        record = {"chat_room_id": chat_room_id, "time": now_local_iso(), "character": character, "txt": txt}
        write_jsonl_line(thinking_fp, record)

    print(f"Chat room id: {chat_room_id}")
    print("Commands: /exit to quit\n")

    consecutive_agent_turns = 0  # forces user after 5 agent turns

    with open(chat_path, "a", encoding="utf-8") as chat_fp, open(thinking_path, "a", encoding="utf-8") as thinking_fp:

        def user_turn():
            nonlocal consecutive_agent_turns
            consecutive_agent_turns = 0
            try:
                user_txt = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                user_txt = "/exit"
            if user_txt.lower() in {"/exit", "exit", "quit"}:
                return False
            log_chat("user", user_txt)
            return True

        def agent_turn(agent: ChatAgent, force_intro: bool = False):
            nonlocal consecutive_agent_turns
            consecutive_agent_turns += 1
            agent.spoke += 1

            history = clamp_history(transcript_lines, args.max_history_chars)

            extra = ""
            if force_intro:
                extra = f"\n\n(Important) This is your FIRST message. Start with: Hi, I'm {agent.name}"

            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "Each line is formatted as: Speaker: message\n"
                "The Speaker field is the person who said that line.\n"
                "Continue the conversation as your character.\n"
                "Try to keep a lively group dynamic by engaging other bots (react, ask them questions, build on their points),"
                " while still keeping the user included.\n\n"
                f"{history}\n{extra}"
            )

            messages = [
                {"role": "system", "content": agent.system_prompt(scene, name_map)},
                {"role": "user", "content": user_prompt},
            ]
            txt = create_response(args.model, messages, args.temperature, args.max_output_tokens)
            txt = (txt or "").strip()
            if not txt:
                txt = "…"

            print(f"{agent.name}> {txt}")
            log_chat(agent.name, txt)
            return True

        def admin_choose_next() -> str:
            """Returns 'A'/'B'/'C'/'U'."""
            if consecutive_agent_turns >= 5:
                log_thinking("admin_rule", "Force U because consecutive_agent_turns >= 5")
                return "U"

            history = clamp_history(transcript_lines, args.max_history_chars)
            roles_summary = build_roles_summary(agents)
            stats = (
                f"Spoke counts: A={key_to_agent['A'].spoke}, "
                f"B={key_to_agent['B'].spoke}, C={key_to_agent['C'].spoke}. "
                f"Consecutive agent turns={consecutive_agent_turns}."
            )

            admin1_messages = [
                {"role": "system", "content": ADMIN1_SYSTEM},
                {"role": "user", "content": (
                    f"=== SCENE ===\n{scene}\n\n"
                    f"=== ROLES ===\n{roles_summary}\n\n"
                    f"=== STATS ===\n{stats}\n\n"
                    f"=== TRANSCRIPT (Speaker: message) ===\n{history}\n\n"
                    f"Decide NEXT."
                )},
            ]
            admin1_out = create_response(args.model, admin1_messages, temperature=0.2, max_output_tokens=260)
            log_thinking("admin1", admin1_out)

            admin2_messages = [
                {"role": "system", "content": ADMIN2_SYSTEM},
                {"role": "user", "content": admin1_out},
            ]
            admin2_out = create_response(args.model, admin2_messages, temperature=0.0, max_output_tokens=MIN_OUTPUT_TOKENS)
            admin2_out = (admin2_out or "").strip().upper()
            log_thinking("admin2", admin2_out)

            if admin2_out in {"A", "B", "C", "U"}:
                return admin2_out

            log_thinking("admin_fallback", f"Invalid admin2_out={admin2_out!r}, fallback to U")
            return "U"

        # Apply start order (up to 4 chars)
        start_order = (args.start_order or "").upper()[:4]
        intro_done: Dict[str, bool] = {a.key: False for a in agents}

        for ch in start_order:
            if ch in {"A", "B", "C"}:
                ok = agent_turn(key_to_agent[ch], force_intro=not intro_done[ch])
                intro_done[ch] = True
                if not ok:
                    return
            elif ch == "U":
                ok = user_turn()
                if not ok:
                    return

        while True:
            nxt = admin_choose_next()
            if nxt == "U":
                ok = user_turn()
                if not ok:
                    break
            else:
                a = key_to_agent[nxt]
                ok = agent_turn(a, force_intro=not intro_done[nxt])
                intro_done[nxt] = True
                if not ok:
                    break

    print(f"\nSaved chat log: {chat_path}")
    print(f"Saved thinking log: {thinking_path}")

if __name__ == "__main__":
    main()
