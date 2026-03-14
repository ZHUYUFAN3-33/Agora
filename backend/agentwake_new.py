# -*- coding: utf-8 -*-
"""
Agent wakeup module (Newst) - Phase-based multi-agent deliberation.
Can be used as library by app.py or run as CLI via main().
"""
from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

MIN_OUTPUT_TOKENS = 16
MODERATOR_INTERVAL = 2
MODERATOR_STALL_TURNS = 5

TOKYO = ZoneInfo("Asia/Tokyo")


def now_local_iso() -> str:
    return datetime.now(TOKYO).isoformat(timespec="seconds")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def safe_read_text(path: Optional[str], default: str) -> str:
    if not path or not os.path.exists(path):
        return default
    return read_text(path)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def make_room_id_6() -> str:
    return f"{random.randint(0, 999999):06d}"


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


def history_to_transcript_lines(history: List[dict]) -> List[str]:
    """Convert app.py history format to 'Speaker: message' lines."""
    return [f"{m.get('character', '?')}: {m.get('txt', '')}" for m in history]


def build_transcript(history: List[dict], max_turns: int = 0) -> str:
    """Build transcript string from history. max_turns=0 means all, else last N messages."""
    items = history if max_turns <= 0 else history[-max_turns:]
    return "\n".join(f"{m.get('character', '?')}: {m.get('txt', '')}" for m in items) or "(none)"


def last_user_index(transcript_lines: List[str]) -> Optional[int]:
    for i in range(len(transcript_lines) - 1, -1, -1):
        if transcript_lines[i].startswith("user:"):
            return i
    return None


def load_agent_configs(info_path: str) -> Dict[str, dict]:
    """Load emotion/decision per agent from info.jsonl."""
    if not os.path.exists(info_path):
        return {"A": {"decision": "Rational", "emotion": "Joy"},
                "B": {"decision": "Rational", "emotion": "Joy"},
                "C": {"decision": "Rational", "emotion": "Joy"}}
    with open(info_path, "r", encoding="utf-8-sig") as f:
        raw = f.read().strip()
    if not raw:
        return {"A": {"decision": "Rational", "emotion": "Joy"},
                "B": {"decision": "Rational", "emotion": "Joy"},
                "C": {"decision": "Rational", "emotion": "Joy"}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        for line in raw.splitlines():
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        else:
            data = {}
    return data.get("agents", {"A": {"decision": "Rational", "emotion": "Joy"},
                               "B": {"decision": "Rational", "emotion": "Joy"},
                               "C": {"decision": "Rational", "emotion": "Joy"}})


# -------------------------------
# ChatAgent
# -------------------------------

@dataclass
class ChatAgent:
    key: str
    name: str
    role_text: str
    spoke: int = 0

    def system_prompt(self, scene: str, name_map: Dict[str, str], phase_context: str = "") -> str:
        roster = "\n".join([f"- {v}" for _, v in name_map.items()])
        prompt = (
            f"You are {self.name} in a group chat.\n"
            f"Participants (remember their names):\n{roster}\n"
            f"- user (the human participant)\n\n"
            f"GROUP DYNAMICS (important):\n"
            f"- This is a FRIEND group chat. Actively talk WITH the other bots, not only the user.\n"
            f"- Frequently react to what another bot said, build on it, or gently disagree.\n"
            f"- Often ask another bot a direct question. Vary your phrasing.\n"
            f"- Keep it natural: don't force a question every single time, but aim for more bot-to-bot back-and-forth.\n"
            f"- Ask at most one person per message. Do not end every message with a question — if you have a point to make, make it and let others respond naturally.\n"
            f"- Never use internal labels like A/B/C/U in visible text. Use names and 'user' instead.\n"
            f"- Never call the human participant 'U'. Always address them as 'user' or by the nickname shown in the chat.\n"
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
Your job: infer who SHOULD speak next and give a brief reason.

PACING GOAL (important):
- Strongly prefer A/B/C speaking over the user, as long as the conversation still feels coherent.
- Promote natural FRIEND group dynamics with more bot-to-bot discussion.
- Still keep the user included regularly, but less frequently than the bots.
- Always obey the hard rule: after 5 consecutive agent turns, the next speaker must be U.
- If the user's last message explicitly addresses or mentions a specific agent by name, that agent MUST speak next regardless of other pacing considerations.

You MUST end your output with a single clear decision:
NEXT = A or B or C or U (choose exactly one).
This analysis is NOT shown to the user, but is saved to the thinking log."""

ADMIN2_SYSTEM = """You are Admin-2: output ONLY ONE character: A or B or C or U.
Do not output anything else."""

ADMIN3_SYSTEM = """You are the deliberation moderator. Classify where the conversation is.

STATES: Exploration | Structuring | Narrowing | Convergence
DECISION MODE: S (Selection) or P (Package)
STALL: true only if circling without progress.

Output ONLY:
[Moderator]
mode: <S|P>
state: <Exploration|Structuring|Narrowing|Convergence>
stall: <true|false>
goal: <one sentence>
[/Moderator]"""

PHASE_PROMPTS: Dict[tuple, str] = {
    ("Exploration", "S", "Spontaneous"): "Check transcript: if user needs unclear, ask ONE question. Else name strongest option with one reason.",
    ("Exploration", "P", "Spontaneous"): "Name one component that must be part of any solution.",
    ("Exploration", "S", "Rational"): "If requirements unclear, ask. Else define objective and list what's needed to compare.",
    ("Exploration", "P", "Rational"): "Define objective, identify functional components.",
    ("Exploration", "S", "Avoidant"): "If vague, ask one simple question. Else name two obvious options.",
    ("Exploration", "P", "Avoidant"): "Name two essential components.",
    ("Exploration", "S", "Dependent"): "If needs unknown, ask. Else ask group to surface an option.",
    ("Exploration", "P", "Dependent"): "Ask which component is non-negotiable.",
    ("Exploration", "S", "Intuitive"): "If unclear, ask. Else state which option feels aligned.",
    ("Exploration", "P", "Intuitive"): "State which combination feels fitted and why.",
    ("Structuring", "S", "Spontaneous"): "Name the single most important trade-off.",
    ("Structuring", "P", "Spontaneous"): "Identify sharpest tension between two components.",
    ("Structuring", "S", "Rational"): "Introduce one evaluation dimension, apply to two options.",
    ("Structuring", "P", "Rational"): "Introduce one dimension, assess two components.",
    ("Structuring", "S", "Avoidant"): "Pick two similar options, name clearest difference.",
    ("Structuring", "P", "Avoidant"): "Identify two components with overlap, state distinction.",
    ("Structuring", "S", "Dependent"): "Reflect dimensions used, ask which carries most weight.",
    ("Structuring", "P", "Dependent"): "Reflect consensus, ask group to confirm.",
    ("Structuring", "S", "Intuitive"): "State most relevant dimension for priorities.",
    ("Structuring", "P", "Intuitive"): "Say which components belong together.",
    ("Narrowing", "S", "Spontaneous"): "Eliminate one option, state reason.",
    ("Narrowing", "P", "Spontaneous"): "Drop one weak component.",
    ("Narrowing", "S", "Rational"): "Summarize evidence, identify stronger option.",
    ("Narrowing", "P", "Rational"): "Assess components, recommend dropping weakest.",
    ("Narrowing", "S", "Avoidant"): "Identify lowest-risk option.",
    ("Narrowing", "P", "Avoidant"): "Identify minimal downside combination.",
    ("Narrowing", "S", "Dependent"): "State option with most support.",
    ("Narrowing", "P", "Dependent"): "Identify aligned components, propose locking.",
    ("Narrowing", "S", "Intuitive"): "State best fit, name what would change your mind.",
    ("Narrowing", "P", "Intuitive"): "Say coherent combination, identify doubt.",
    ("Convergence", "S", "Spontaneous"): "State final recommendation, name first action.",
    ("Convergence", "P", "Spontaneous"): "State final package, name first step.",
    ("Convergence", "S", "Rational"): "Confirm option with trade-off justification.",
    ("Convergence", "P", "Rational"): "Confirm package, state accepted trade-off.",
    ("Convergence", "S", "Avoidant"): "Confirm reversible, give sign-off.",
    ("Convergence", "P", "Avoidant"): "Confirm adjustable, give sign-off.",
    ("Convergence", "S", "Dependent"): "Endorse option, propose next step.",
    ("Convergence", "P", "Dependent"): "Endorse package, propose first step.",
    ("Convergence", "S", "Intuitive"): "Confirm feels right, name watch-out.",
    ("Convergence", "P", "Intuitive"): "Confirm coherent, name assumption.",
}

STALL_PROMPTS: Dict[str, str] = {
    "Spontaneous": "Discussion stuck. Pick strongest option, defend in two sentences.",
    "Rational": "Stop adding dimensions. Summarize evidence, name leading candidate.",
    "Avoidant": "Identify lowest-risk path, say you'll move on it.",
    "Dependent": "State your preference clearly, stop waiting for consensus.",
    "Intuitive": "State direction that feels right, push to commit.",
}


def get_phase_prompt(state: str, mode: str, decision: str, stall: bool) -> str:
    if stall:
        return STALL_PROMPTS.get(decision, "Break deadlock: state position, push for decision.")
    return PHASE_PROMPTS.get(
        (state, mode, decision),
        PHASE_PROMPTS.get((state, "S", decision), "Contribute to moving the discussion forward.")
    )


def build_roles_summary(agents: List[ChatAgent]) -> str:
    return "\n".join(f"{a.key}={a.name}: {(a.role_text.splitlines()[0] or '(empty)')[:80]}" for a in agents)


def parse_moderator_plan(text: str) -> Optional[dict]:
    block = re.search(r"\[Moderator\](.*?)\[/Moderator\]", text, re.DOTALL)
    if not block:
        return None
    body = block.group(1)
    def ext(p, d=""):
        m = re.search(p, body, re.MULTILINE)
        return m.group(1).strip() if m else d
    stall_raw = ext(r"^stall:\s*(.+)", "false")
    return {
        "mode": ext(r"^mode:\s*([SP])", "S"),
        "state": ext(r"^state:\s*(\w+)", "Exploration"),
        "stall": stall_raw.lower() == "true",
        "goal": ext(r"^goal:\s*(.+)", ""),
    }


def sanitize_single_message(text: str, agent_name: str, all_names: List[str]) -> str:
    if not text:
        return "..."
    t = text.strip()
    t = re.sub(rf"^\s*{re.escape(agent_name)}\s*:\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*(USER|user|You|YOU)\s*:\s*", "", t)
    others = [n for n in all_names if n != agent_name] + ["user", "You"]
    pat = r"(?m)^\s*(" + "|".join(re.escape(p) for p in others) + r")\s*:\s*"
    m = re.search(pat, t)
    if m:
        t = t[: m.start()].rstrip()
    # Normalize leaked internal user label only in direct-address contexts.
    t = re.sub(
        r"(?<!\w)U(?=(?:['’]s\b|[,\.\!\?\:\;]|\s+(?:could|can|would|will|do|did|have|are|please|let(?:'s|s)|what|which|when|where|why|how)\b))",
        "user",
        t,
    )
    return t.strip() or "..."


# -------------------------------
# API: create_response with client
# -------------------------------

def extract_text(resp) -> str:
    """Extract text from OpenAI responses API response object."""
    if hasattr(resp, "output_text") and resp.output_text:
        return (resp.output_text or "").strip()
    parts = []
    for item in (getattr(resp, "output", None) or []):
        for c in (getattr(item, "content", None) or []):
            text = getattr(c, "text", None)
            if text:
                parts.append(text)
    return "".join(parts).strip()


def create_response_with_client(client, model: str, messages: List[dict], temperature: float, max_output_tokens: int) -> str:
    """Call OpenAI responses API with provided client. For app.py use."""
    max_output_tokens = max(int(max_output_tokens), MIN_OUTPUT_TOKENS)
    resp = client.responses.create(
        model=model, input=messages,
        temperature=temperature, max_output_tokens=max_output_tokens,
    )
    return extract_text(resp)


# -------------------------------
# User facts (from old agent)
# -------------------------------

def normalize_quotes(s: str) -> str:
    return (s or "").replace("'", "'").replace(""", '"').replace(""", '"')


def update_user_facts(facts: Dict[str, str], user_text: str) -> Dict[str, str]:
    t = normalize_quotes(user_text).lower()
    if re.search(r"\b(battery|battery life)\b", t):
        if re.search(r"\b(no\s+high\s+requirements?|don't\s+care|not\s+important)\b", t):
            facts["battery"] = "User does not have high requirements for battery life."
        elif re.search(r"\bimportant|care|need\b", t):
            facts["battery"] = "Battery life matters to the user."
    if re.search(r"\b(one fixed place|stationary|desk)\b", t):
        facts["portability"] = "User usually uses in one fixed place."
    if re.search(r"\bportable|travel|on the go\b", t) and re.search(r"\bimportant|need\b", t):
        facts["portability"] = "User wants portability."
    if re.search(r"\b(aaa|triple a)\b.*\b(game|gaming)\b", t):
        facts["use_case"] = "User wants to play AAA games."
    if re.search(r"\bnoise\b|\bquiet\b", t) and re.search(r"\bconcern\b|\bimportant\b", t):
        facts["noise"] = "Noise level is a concern."
    if re.search(r"\bspace\b|\bsmall\b|\blimited\b", t):
        facts["space"] = "Space is limited."
    return facts


def facts_to_bullets(facts: Dict[str, str]) -> str:
    if not facts:
        return "- (none yet)"
    return "\n".join([f"- {v}" for v in facts.values()])
