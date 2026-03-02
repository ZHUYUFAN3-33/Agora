# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

# ===============================
# API KEY (EDIT ME)
# ===============================
API_KEY = "sk-tnIxDvUFzbMtFbnGpiLC5FXqep9dRMRdsdvUWs2g9hT3BlbkFJmfl6UE3khKvUqT_xeZpq66twaUika-kvxbrc-srSQA"

MIN_OUTPUT_TOKENS = 16

# ===============================
# MODERATOR CONFIG
# ===============================
# How many user input turns between moderator checks
MODERATOR_INTERVAL = 3
# How many consecutive turns in the same state before moderator tries to unstick (strictly greater, first turn excluded)
MODERATOR_STALL_TURNS = 6

# -------------------------------
# OpenAI client (SDK + fallback)
# -------------------------------

def _effective_api_key() -> str:
    return (API_KEY or "").strip()

def _load_openai_client():
    try:
        from openai import OpenAI  # type: ignore
        key = _effective_api_key()
        if not key or key == "sk-xxxx":
            raise RuntimeError("No API key.")
        return OpenAI(api_key=key)
    except Exception:
        return None

def _responses_create_http(payload: dict) -> dict:
    import requests  # type: ignore
    api_key = _effective_api_key()
    if not api_key or api_key == "sk-xxxx":
        raise RuntimeError("No API key. Set API_KEY at top of script.")
    url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/responses"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    if not r.ok:
        raise RuntimeError(f"OpenAI HTTP error {r.status_code}: {r.text}")
    return r.json()

def create_response(model: str, messages: List[dict], temperature: float, max_output_tokens: int) -> str:
    max_output_tokens = max(int(max_output_tokens), MIN_OUTPUT_TOKENS)
    client = _load_openai_client()
    if client is not None:
        resp = client.responses.create(
            model=model, input=messages,
            temperature=temperature, max_output_tokens=max_output_tokens,
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

    payload = {"model": model, "input": messages, "temperature": temperature, "max_output_tokens": max_output_tokens}
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

def last_user_index(transcript_lines: List[str]) -> Optional[int]:
    for i in range(len(transcript_lines) - 1, -1, -1):
        if transcript_lines[i].startswith("user:"):
            return i
    return None

# -------------------------------
# info.jsonl loader
# -------------------------------

def load_agent_configs(info_path: str) -> Dict[str, dict]:
    """
    Read info.jsonl to get emotion/decision type names per agent.
    Expected format: {"agents": {"A": {"decision": "Spontaneous", "emotion": "Joy"}, ...}}
    Returns: {"A": {"decision": "Spontaneous", "emotion": "Joy"}, ...}
    role_text is loaded separately from --bot1/2/3 files.
    """
    with open(info_path, "r", encoding="utf-8-sig") as f:
        raw = f.read().strip()
    if not raw:
        raise RuntimeError(f"info.jsonl is empty: {info_path}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
        for line in raw.splitlines():
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    if data is None:
        raise RuntimeError(f"Could not parse info.jsonl: {info_path}")
    return data.get("agents", {})

# -------------------------------
# Agent definition
# -------------------------------

@dataclass
class ChatAgent:
    key: str
    name: str
    role_text: str
    spoke: int = 0

    def system_prompt(self, scene: str, name_map: Dict[str, str], phase_context: str = "") -> str:
        roster = "\n".join([f"- {k}: {v}" for k, v in name_map.items()])
        prompt = (
            f"You are {self.name} in a group chat.\n"
            f"Participants (remember their names):\n{roster}\n"
            f"- U: user\n\n"
            f"GROUP DYNAMICS (important):\n"
            f"- This is a FRIEND group chat. Actively talk WITH the other bots, not only the user.\n"
            f"- Frequently react to what another bot said, build on it, or gently disagree.\n"
            f"- Often ask another bot a direct question. Vary your phrasing, for example:\n"
            f"  \"{name_map.get('B','ChatbotB')}, what do you think?\"  "
            f"\"{name_map.get('C','ChatbotC')}, do you agree?\"  "
            f"\"What's your take on this, {name_map.get('B','ChatbotB')}?\"  "
            f"\"I'm curious what {name_map.get('C','ChatbotC')} thinks here.\"  "
            f"\"Does that match your read, {name_map.get('A','ChatbotA')}?\"  "
            f"\"Would you push back on that, {name_map.get('B','ChatbotB')}?\"\n"
            f"- Keep it natural: don't force a question every single time, but aim for more bot-to-bot back-and-forth.\n"
            f"- You may address the user too, -when their input is genuinely needed to move the discussion forward, but avoid making every message solely about the user.\n"
            f"- Output ONLY what {self.name} says (no speaker label, no quotes).\n\n"
            f"=== SCENE (shared) ===\n{scene}\n\n"
            f"=== ROLE INSTRUCTIONS (for {self.name}) ===\n{self.role_text}\n"
        )
        if phase_context:
            prompt += f"\n{phase_context}"
        return prompt

# -------------------------------
# Admin prompts
# -------------------------------

ADMIN1_SYSTEM = """You are Admin-1: the group-chat pacing analyst.
You will read: the shared scene, the three role settings, and the full transcript.

Your job: infer who SHOULD speak next and give a brief reason.

PACING GOAL (important):
- Strongly prefer A/B/C speaking over the user, as long as the conversation still feels coherent.
- Promote natural FRIEND group dynamics with more bot-to-bot discussion.
- Still keep the user included regularly, but less frequently than the bots.
- Always obey the hard rule: after 5 consecutive agent turns, the next speaker must be U.

You MUST end your output with a single clear decision:
NEXT = A or B or C or U (choose exactly one).
This analysis is NOT shown to the user, but is saved to the thinking log."""

ADMIN2_SYSTEM = """You are Admin-2: the strict next-speaker selector.
You will receive Admin-1's analysis text.
Your job: output ONLY ONE character: A or B or C or U.
Do not output anything else (no spaces, punctuation, explanation, or newline)."""

# Admin-3 design rationale:
# Admin-3 only classifies the deliberation state and detects stalls.
# Per-agent assignments come from PHASE_PROMPTS — a deterministic lookup table
# keyed on (state, decision_style). This removes LLM variance from the assignment
# layer entirely, while keeping state classification generative (it needs to read
# the transcript). Stall detection uses both a turn counter and the LLM stall flag.

# ── Per-agent assignment table ─────────────────────────────────────────────
# Keys: (state, mode, decision_style)
# mode: "S" = Selection (pick one item), "P" = Package (assemble a plan)
# Values: instruction injected into that agent's system prompt this turn.
#
# Design principles:
# - The stage defines WHAT needs to happen (information goal for this phase).
# - The decision style defines HOW this agent should contribute to that goal.
# - Where S and P require meaningfully different contributions, they are split.
#   Where the task is essentially the same regardless of mode, S and P share a prompt.
#
# Exploration goal : at least 2 concrete options (S) or components (P) on the table
# Structuring goal : each option/component covered by 2+ dimensions; main trade-off named
# Narrowing goal   : eliminate weaker options/components; leave 1-2 with clear rationale
# Convergence goal : one executable recommendation with accepted trade-off and next step

PHASE_PROMPTS: Dict[tuple, str] = {

    # ════════════════════════════════════════════════════════════════════════
    # EXPLORATION — surface the option/component space
    # ════════════════════════════════════════════════════════════════════════
    #
    # S mode: user needs must be understood before options can be meaningful.
    # Each prompt has two steps: if needs are unclear, ask first; only propose
    # options once the transcript contains enough user context to justify them.

    ("Exploration", "S", "Spontaneous"):
        "Check the transcript: if the user's core needs (use case, priorities, constraints) are not yet clear, "
        "ask ONE direct question to uncover the most important missing piece. "
        "Only if needs are already established: name the strongest option that fits and give one reason.",

    ("Exploration", "P", "Spontaneous"):
        "Name one component or policy lever that must be part of any solution. One item, one reason.",

    ("Exploration", "S", "Rational"):
        "Check the transcript: if key requirements (use case, budget range, constraints) have not been stated, "
        "identify the single most critical information gap and ask the user to fill it. "
        "Only if requirements are already clear: define the decision objective and list what is still needed to compare options fairly.",

    ("Exploration", "P", "Rational"):
        "Define the decision objective, then identify the functional components any complete package must address.",

    ("Exploration", "S", "Avoidant"):
        "Check the transcript: if the user's situation is still vague, ask one simple question to clarify "
        "the most basic requirement — keep it low-pressure. "
        "Only if the situation is already clear: name the two most obvious options without evaluating them.",

    ("Exploration", "P", "Avoidant"):
        "Name the two most essential components of a solution — keep it simple, just enough to give the group a starting structure.",

    ("Exploration", "S", "Dependent"):
        "Check the transcript: if the user's needs or preferences have not been expressed, "
        "ask one question that invites the user to share what matters most to them. "
        "Only if needs are already known: ask the group a question that surfaces a concrete option no one has mentioned yet.",

    ("Exploration", "P", "Dependent"):
        "Ask which component or constraint the group considers non-negotiable — get at least one anchor on the table.",

    ("Exploration", "S", "Intuitive"):
        "Check the transcript: if the user's situation and priorities are not yet clear, "
        "ask one question that feels natural given what has been said so far — something that will reveal what the user actually values. "
        "Only if the picture is already clear: state which option direction feels most aligned and briefly say why.",

    ("Exploration", "P", "Intuitive"):
        "State which combination of components feels most naturally fitted to the problem, and say what that fit is based on.",

    # ════════════════════════════════════════════════════════════════════════
    # STRUCTURING — build the comparison framework
    # ════════════════════════════════════════════════════════════════════════

    ("Structuring", "S", "Spontaneous"):
        "Name the single most important trade-off between the options already on the table. One trade-off, stated clearly.",
    ("Structuring", "P", "Spontaneous"):
        "Identify the sharpest tension between two components in the package so far — name what you gain and what you give up.",

    ("Structuring", "S", "Rational"):
        "Introduce one evaluation dimension not yet discussed and apply it explicitly to at least two of the current options.",
    ("Structuring", "P", "Rational"):
        "Introduce one evaluation dimension — such as cost, feasibility, or risk — and assess at least two components against it.",

    ("Structuring", "S", "Avoidant"):
        "Pick the two most similar options and name the single clearest difference between them. Just the difference, nothing more.",
    ("Structuring", "P", "Avoidant"):
        "Identify the two components with the most overlap and state what distinguishes them — keep the framework simple.",

    ("Structuring", "S", "Dependent"):
        "Reflect back what dimensions the group has used so far and ask which one should carry the most weight.",
    ("Structuring", "P", "Dependent"):
        "Reflect on which components have the most consensus so far and ask the group to confirm or challenge that read.",

    ("Structuring", "S", "Intuitive"):
        "State which evaluation dimension feels most relevant given the group's actual priorities, and show how it applies to the options.",
    ("Structuring", "P", "Intuitive"):
        "Say which components feel like they belong together naturally and explain what makes that combination coherent.",

    # ════════════════════════════════════════════════════════════════════════
    # NARROWING — eliminate weaker candidates
    # ════════════════════════════════════════════════════════════════════════

    ("Narrowing", "S", "Spontaneous"):
        "Eliminate one option from the table. State the single reason it loses and do not reopen it.",
    ("Narrowing", "P", "Spontaneous"):
        "Drop one component or approach that is not pulling its weight. Give one reason and move on.",

    ("Narrowing", "S", "Rational"):
        "Summarize the comparative evidence so far and identify which option has the stronger overall case based on the dimensions already established.",
    ("Narrowing", "P", "Rational"):
        "Assess which components have cleared the evidence bar and which have not — recommend dropping the weakest one with justification.",

    ("Narrowing", "S", "Avoidant"):
        "Identify which option carries the least risk given what the group knows, and confirm you can accept it as the leading candidate.",
    ("Narrowing", "P", "Avoidant"):
        "Identify the component combination that minimizes downside exposure and say whether it is enough to move forward.",

    ("Narrowing", "S", "Dependent"):
        "State which option has accumulated the most support in this discussion and commit to backing it as the leading candidate.",
    ("Narrowing", "P", "Dependent"):
        "Identify which components the group seems aligned on and propose locking them in so the remaining debate can narrow.",

    ("Narrowing", "S", "Intuitive"):
        "State which option fits best right now given everything discussed, and name what you would need to change your mind.",
    ("Narrowing", "P", "Intuitive"):
        "Say which component combination feels most coherent as a whole package, and identify the one piece still creating doubt.",

    # ════════════════════════════════════════════════════════════════════════
    # CONVERGENCE — finalize recommendation and next step
    # ════════════════════════════════════════════════════════════════════════

    ("Convergence", "S", "Spontaneous"):
        "State the final recommendation in one sentence. Name the immediate first action to act on it.",
    ("Convergence", "P", "Spontaneous"):
        "State the final package in one sentence. Name the first implementation step.",

    ("Convergence", "S", "Rational"):
        "Confirm the chosen option with a one-line justification that names the key trade-off the group is accepting.",
    ("Convergence", "P", "Rational"):
        "Confirm the final package composition and state the primary trade-off the group has accepted in choosing it.",

    ("Convergence", "S", "Avoidant"):
        "Confirm the chosen option is reversible or low-commitment enough to act on, then give your sign-off.",
    ("Convergence", "P", "Avoidant"):
        "Confirm the package can be adjusted after initial implementation if needed, then give your sign-off.",

    ("Convergence", "S", "Dependent"):
        "Endorse the group's chosen option and propose one concrete next step that moves the decision into action.",
    ("Convergence", "P", "Dependent"):
        "Endorse the final package and propose a concrete first step toward implementation.",

    ("Convergence", "S", "Intuitive"):
        "Confirm the chosen option feels right given the full discussion, and name any remaining watch-out the group should monitor.",
    ("Convergence", "P", "Intuitive"):
        "Confirm the package feels coherent as a whole, and name the one assumption it depends on that should be watched.",
}

STALL_PROMPTS: Dict[str, str] = {
    "Spontaneous": "The discussion is stuck. Pick the strongest option or component and defend it in two sentences — force the group to react.",
    "Rational":    "The discussion is stuck. Stop adding dimensions. Summarize what the evidence already supports and name the leading candidate.",
    "Avoidant":    "The discussion is stuck. Identify the lowest-risk path forward and say you are willing to move on it.",
    "Dependent":   "The discussion is stuck. Stop waiting for consensus — state your own preference clearly, even if you are uncertain.",
    "Intuitive":   "The discussion is stuck. State which direction feels right based on everything so far and push the group to commit.",
}

def get_phase_prompt(state: str, mode: str, decision: str, stall: bool) -> str:
    if stall:
        return STALL_PROMPTS.get(decision, "Break the deadlock: state your position clearly and push for a decision.")
    return PHASE_PROMPTS.get(
        (state, mode, decision),
        PHASE_PROMPTS.get((state, "S", decision), "Contribute to moving the current discussion phase forward.")
    )

ADMIN3_SYSTEM = """You are the deliberation moderator for a group decision chat.
Read the transcript and classify where the conversation actually is right now.

STATES (mutually exclusive, pick exactly one):
- Exploration  : fewer than 2 concrete options/components on the table
- Structuring  : 2+ options exist but key trade-offs are not yet compared
- Narrowing    : trade-offs are clear but the group has not converged yet
- Convergence  : the group is aligned on 1-2 candidates or a final plan

DECISION MODE (infer from topic):
- Selection (S) : choosing one item from a set  (e.g. which product, which restaurant)
- Package  (P)  : assembling a multi-part plan  (e.g. travel itinerary, policy bundle)

STALL flag: set to true only if the conversation has been circling the same points
without making observable progress.

Output ONLY this block, no other text:
[Moderator]
mode: <S|P>
state: <Exploration|Structuring|Narrowing|Convergence>
stall: <true|false>
goal: <one sentence describing what needs to happen this turn>
[/Moderator]"""

def build_roles_summary(agents: List[ChatAgent]) -> str:
    parts = []
    for a in agents:
        first = a.role_text.splitlines()[0].strip() if a.role_text.strip() else "(empty role)"
        parts.append(f"{a.key}={a.name}: {first}")
    return "\n".join(parts)

# -------------------------------
# Moderator plan parser
# -------------------------------

def parse_moderator_plan(text: str) -> Optional[dict]:
    block = re.search(r"\[Moderator\](.*?)\[/Moderator\]", text, re.DOTALL)
    if not block:
        return None
    body = block.group(1)

    def extract(pattern, default=""):
        m = re.search(pattern, body, re.MULTILINE)
        return m.group(1).strip() if m else default

    stall_raw = extract(r"^stall:\s*(.+)", "false")
    return {
        "mode":  extract(r"^mode:\s*([SP])", "S"),
        "state": extract(r"^state:\s*(\w+)", "Exploration"),
        "stall": stall_raw.lower() == "true",
        "goal":  extract(r"^goal:\s*(.+)", ""),
    }

# -------------------------------
# Core loop
# -------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="scene.txt", help="Path to scene.txt")
    ap.add_argument("--info", default="info.jsonl", help="Path to info.jsonl (agent emotion+decision type names)")
    ap.add_argument("--bot1", default="chatbot1.txt", help="Path to chatbot1.txt (A)")
    ap.add_argument("--bot2", default="chatbot2.txt", help="Path to chatbot2.txt (B)")
    ap.add_argument("--bot3", default="chatbot3.txt", help="Path to chatbot3.txt (C)")
    ap.add_argument("--start_order", default="ABCU", help="Up to 4 chars from {A,B,C,U}, default ABCU")
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--max_output_tokens", type=int, default=220)
    ap.add_argument("--max_history_chars", type=int, default=12000)
    ap.add_argument("--log_dir", default="logs", help="Directory to write jsonl logs")
    ap.add_argument("--prefer_agents", type=float, default=0.85,
                    help="Probability to override Admin output to an agent when it picks U (0..1). Default 0.85")
    ap.add_argument("--max_user_gap", type=int, default=12,
                    help="Force U if user hasn't spoken in this many transcript lines. Default 12")

    args = ap.parse_args()
    args.max_output_tokens = max(int(args.max_output_tokens), MIN_OUTPUT_TOKENS)

    if not _effective_api_key() or _effective_api_key() == "sk-xxxx":
        print("ERROR: No API key. Please set API_KEY at the top of this script.", file=sys.stderr)
        sys.exit(2)

    # Load scene
    scene = safe_read_text(args.scene, default="(scene file missing)")

    # Load role text from pre-composed bot files
    role_a = safe_read_text(args.bot1, default="(chatbot1.txt missing)")
    role_b = safe_read_text(args.bot2, default="(chatbot2.txt missing)")
    role_c = safe_read_text(args.bot3, default="(chatbot3.txt missing)")

    # Load emotion/decision type names from info.jsonl (used for phase prompts and Admin-3)
    agent_configs = load_agent_configs(args.info)

    agents: List[ChatAgent] = [
        ChatAgent("A", "ChatbotA", role_a),
        ChatAgent("B", "ChatbotB", role_b),
        ChatAgent("C", "ChatbotC", role_c),
    ]
    key_to_agent = {a.key: a for a in agents}
    name_map = {a.key: a.name for a in agents}

    chat_room_id = f"{random.randint(0, 999999):06d}"
    os.makedirs(args.log_dir, exist_ok=True)
    chat_path = os.path.join(args.log_dir, f"{chat_room_id}.jsonl")
    thinking_path = os.path.join(args.log_dir, f"{chat_room_id}_thinking.jsonl")
    moderator_path = os.path.join(args.log_dir, f"{chat_room_id}_moderator.jsonl")

    transcript_lines: List[str] = []
    consecutive_agent_turns = 0
    user_turn_count = 0         # counts user inputs; moderator triggers on interval
    turns_in_current_state = 0  # stall detection: turns since last state change

    # Moderator state (assignments now come from PHASE_PROMPTS lookup, not LLM)
    moderator_state = {
        "mode":  None,
        "state": "Exploration",
        "stall": False,
        "goal":  "",
    }

    def log_chat(character: str, txt: str):
        record = {"chat_room_id": chat_room_id, "time": now_local_iso(), "character": character, "txt": txt}
        write_jsonl_line(chat_fp, record)
        transcript_lines.append(f"{character}: {txt}")

    def log_thinking(character: str, txt: str):
        record = {"chat_room_id": chat_room_id, "time": now_local_iso(), "character": character, "txt": txt}
        write_jsonl_line(thinking_fp, record)

    def log_moderator(character: str, txt: str):
        record = {"chat_room_id": chat_room_id, "time": now_local_iso(), "character": character, "txt": txt}
        write_jsonl_line(moderator_fp, record)

    def get_phase_context(agent_key: str) -> str:
        s = moderator_state
        decision = agent_configs[agent_key]["decision"]
        mode = s["mode"] or "S"  # default to Selection until mode is determined
        assignment = get_phase_prompt(s["state"], mode, decision, s["stall"])
        lines = ["=== DELIBERATION STATE ==="]
        if s["mode"]:
            lines.append(f"Mode: {'Selection' if mode == 'S' else 'Package'} | Phase: {s['state']}")
        else:
            lines.append(f"Phase: {s['state']}")
        if s["goal"]:
            lines.append(f"Current goal: {s['goal']}")
        lines.append(f"Your task this turn: {assignment}")
        return "\n".join(lines)

    def run_moderator():
        """Classify current deliberation state and issue per-agent moves."""
        nonlocal turns_in_current_state

        history = clamp_history(transcript_lines, args.max_history_chars)
        roles_summary = build_roles_summary(agents)

        # Include stall context so Admin-3 knows how long we've been here
        # Only allow stall detection after MODERATOR_STALL_TURNS (first turn excluded)
        stall_eligible = turns_in_current_state > MODERATOR_STALL_TURNS
        stall_hint = (
            f"The conversation has been in '{moderator_state['state']}' state for "
            f"{turns_in_current_state} agent turns."
            + ("" if stall_eligible else " Do NOT set stall: true — not enough turns yet.")
        )

        admin3_messages = [
            {"role": "system", "content": ADMIN3_SYSTEM},
            {"role": "user", "content": (
                f"=== SCENE ===\n{scene}\n\n"
                f"=== AGENT PERSONALITIES ===\n{roles_summary}\n\n"
                f"=== CURRENT STATE ===\n{moderator_state['state']}\n"
                f"{stall_hint}\n\n"
                f"=== TRANSCRIPT ===\n{history}\n"
            )},
        ]
        raw = create_response(args.model, admin3_messages, temperature=0.0, max_output_tokens=300)
        log_moderator("admin3_moderator", raw)

        parsed = parse_moderator_plan(raw)
        if not parsed:
            return

        prev_state = moderator_state["state"]
        moderator_state.update(parsed)

        if parsed["state"] != prev_state:
            turns_in_current_state = 0
            user_turn_count = 0
            log_moderator("admin3_state_change", f"{prev_state} -> {parsed['state']}  |  {parsed['goal']}")
        else:
            turns_in_current_state += MODERATOR_INTERVAL
            if parsed["stall"] and stall_eligible:
                log_moderator("admin3_stall", f"Stall in state={parsed['state']} after {turns_in_current_state} turns | {parsed['goal']}")

    def stall_burst():
        """
        When stall is active: force all three agents to speak once in sequence,
        bypassing Admin-1/2 turn selection, using elevated temperature.
        Called from agent_turn after a stall is confirmed.
        """
        nonlocal consecutive_agent_turns
        stall_temp = min(args.temperature + 0.25, 1.4)
        log_thinking("stall_burst", f"Forcing A->B->C burst at temp={stall_temp:.2f}")

        for burst_agent in agents:
            consecutive_agent_turns += 1
            burst_agent.spoke += 1

            history = clamp_history(transcript_lines, args.max_history_chars)
            phase_context = get_phase_context(burst_agent.key)

            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "The moderator has flagged a stall — the group is going in circles.\n"
                "You MUST make a decisive move: propose something new, force a comparison, "
                "ask a direct question that demands an answer, or take a clear position.\n"
                "Do NOT repeat what has already been said.\n\n"
                f"{history}"
            )
            messages = [
                {"role": "system", "content": burst_agent.system_prompt(scene, name_map, phase_context)},
                {"role": "user", "content": user_prompt},
            ]
            txt = create_response(args.model, messages, stall_temp, args.max_output_tokens)
            txt = (txt or "").strip() or "…"
            print(f"{burst_agent.name}> {txt}")
            log_chat(burst_agent.name, txt)

    print(f"Chat room id: {chat_room_id}")
    print(f"Agents: A={agent_configs['A']['emotion']}+{agent_configs['A']['decision']}  "
          f"B={agent_configs['B']['emotion']}+{agent_configs['B']['decision']}  "
          f"C={agent_configs['C']['emotion']}+{agent_configs['C']['decision']}")
    print(f"Moderator: every {MODERATOR_INTERVAL} user turns | stall threshold={MODERATOR_STALL_TURNS}")
    print("Commands: /exit to quit | /next to force moderator update\n")

    with open(chat_path, "a", encoding="utf-8") as chat_fp, \
         open(thinking_path, "a", encoding="utf-8") as thinking_fp, \
         open(moderator_path, "a", encoding="utf-8") as moderator_fp:

        def user_turn():
            nonlocal consecutive_agent_turns, user_turn_count
            consecutive_agent_turns = 0
            try:
                user_txt = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                user_txt = "/exit"

            if user_txt.lower() in {"/exit", "exit", "quit"}:
                return False

            if user_txt.lower() == "/next":
                print("[SYSTEM] Forcing moderator update...")
                run_moderator()
                print(f"[SYSTEM] Moderator state: {moderator_state['state']} | Goal: {moderator_state['goal']}")
                nxt = admin_choose_next()
                if nxt in key_to_agent:
                    agent_turn(key_to_agent[nxt], force_intro=not intro_done[nxt])
                    intro_done[nxt] = True
                return True

            log_chat("user", user_txt)
            user_turn_count += 1
            if user_turn_count % MODERATOR_INTERVAL == 0 or turns_in_current_state > MODERATOR_STALL_TURNS:
                run_moderator()
            return True

        def agent_turn(agent: ChatAgent, force_intro: bool = False):
            nonlocal consecutive_agent_turns
            consecutive_agent_turns += 1
            agent.spoke += 1

            stall_triggered = moderator_state["stall"]

            history = clamp_history(transcript_lines, args.max_history_chars)
            extra = ""
            if force_intro:
                extra = f"\n\n(Important) This is your FIRST message. Start with: Hi, I'm {agent.name}"

            # Stall: use elevated temperature + locked assignment wording
            effective_temp = args.temperature
            if stall_triggered:
                effective_temp = min(args.temperature + 0.25, 1.4)

            phase_context = get_phase_context(agent.key)

            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "Each line is formatted as: Speaker: message\n"
                "Continue the conversation as your character.\n"
                "Try to keep a lively group dynamic by engaging other bots (react, ask them questions, build on their points), "
                "while still keeping the user included.\n\n"
                f"{history}\n{extra}"
            )

            messages = [
                {"role": "system", "content": agent.system_prompt(scene, name_map, phase_context)},
                {"role": "user", "content": user_prompt},
            ]
            txt = create_response(args.model, messages, effective_temp, args.max_output_tokens)
            txt = (txt or "").strip() or "…"

            print(f"{agent.name}> {txt}")
            log_chat(agent.name, txt)

            # After the triggering agent speaks, run the burst for remaining agents
            if stall_triggered:
                stall_burst()

            return True

        def admin_choose_next() -> str:
            if consecutive_agent_turns >= 5:
                log_thinking("admin_rule", "Force U: consecutive_agent_turns >= 5")
                return "U"

            li = last_user_index(transcript_lines)
            gap = (len(transcript_lines) - 1 - li) if li is not None else len(transcript_lines)
            if gap >= args.max_user_gap:
                log_thinking("admin_rule", f"Force U: user gap {gap} >= max_user_gap {args.max_user_gap}")
                return "U"

            history = clamp_history(transcript_lines, args.max_history_chars)
            roles_summary = build_roles_summary(agents)
            stats = (
                f"Spoke counts: A={key_to_agent['A'].spoke}, "
                f"B={key_to_agent['B'].spoke}, C={key_to_agent['C'].spoke}. "
                f"Consecutive agent turns={consecutive_agent_turns}. "
                f"User gap(lines)={gap}. "
                f"Moderator state={moderator_state['state']}."
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

            if admin2_out not in {"A", "B", "C", "U"}:
                log_thinking("admin_fallback", f"Invalid admin2_out={admin2_out!r}, fallback to agent")
                admin2_out = random.choice(["A", "B", "C"])

            if admin2_out == "U":
                if random.random() < float(args.prefer_agents):
                    pick = random.choice(["A", "B", "C"])
                    log_thinking("admin_bias", f"Override U -> {pick} (prefer_agents={args.prefer_agents})")
                    return pick
                return "U"

            return admin2_out

        # Start order
        start_order = (args.start_order or "").upper()[:4]
        intro_done: Dict[str, bool] = {a.key: False for a in agents}

        for ch in start_order:
            if ch in {"A", "B", "C"}:
                agent_turn(key_to_agent[ch], force_intro=not intro_done[ch])
                intro_done[ch] = True
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
                agent_turn(a, force_intro=not intro_done[nxt])
                intro_done[nxt] = True

    print(f"\nSaved chat log:      {chat_path}")
    print(f"Saved thinking log:  {thinking_path}")
    print(f"Saved moderator log: {moderator_path}")

if __name__ == "__main__":
    main()