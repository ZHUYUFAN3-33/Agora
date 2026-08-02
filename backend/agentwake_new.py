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

# Scenario information layer: User Profile + Scenario Intake + Domain Background.
# See agora_context.py / profile_store.py / scenario_background.py for the
# implementation. Import is optional at the top level so the script still
# runs standalone (e.g. quick tests) even if those files aren't present yet.
try:
    from agora_context import prepare_session_context
    HAVE_AGORA_CONTEXT = True
except ImportError:
    HAVE_AGORA_CONTEXT = False

try:
    from stance import assign_stance, stance_enabled, get_stance_text, get_convergence_weight_hint
    HAVE_STANCE = True
except ImportError:
    HAVE_STANCE = False

try:
    from agent_assembly import build_all_agent_specs
    HAVE_AGENT_ASSEMBLY = True
except ImportError:
    HAVE_AGENT_ASSEMBLY = False

# ===============================
# API KEY — from env only (never hardcode)
# ===============================
API_KEY = ""  # unused; _effective_api_key reads OPENAI_API_KEY

MIN_OUTPUT_TOKENS = 16

# ===============================
# MODERATOR CONFIG
# ===============================
# How many speaking turns of ANY kind (agent or user) between moderator checks.
# This used to count user inputs only, which meant that with --prefer_agents at
# its default the moderator effectively never ran: the user speaks roughly once
# every 8-9 lines, so three user turns — the old trigger — sat 25+ lines away.
# The whole four-phase machinery (PHASE_PROMPTS beyond Exploration, stall
# detection, the Convergence stance weighting) was unreachable as a result.
MODERATOR_TURN_INTERVAL = 4
MODERATOR_INTERVAL = MODERATOR_TURN_INTERVAL  # Flask alias
# How many consecutive turns in the same state before moderator tries to unstick (strictly greater, first turn excluded)
MODERATOR_STALL_TURNS = 6
# Once past the stall threshold, re-check this often instead of waiting for the
# full interval — but not every single turn, which would be one extra API call
# per line for the rest of the session.
MODERATOR_STALL_RECHECK = 2

# -------------------------------
# OpenAI client (SDK + fallback)
# -------------------------------

def _effective_api_key() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    except Exception:
        pass
    return (os.getenv("OPENAI_API_KEY") or API_KEY or "").strip()

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

def _resolve_log_tz():
    """
    zoneinfo ships no IANA database on Windows, so ZoneInfo("Asia/Tokyo") raises
    ZoneInfoNotFoundError unless the `tzdata` package is installed (see
    requirements.txt). This runs at import time, so a hard failure here makes the
    whole script unimportable — warn and fall back to naive local time instead.
    """
    try:
        return ZoneInfo("Asia/Tokyo")
    except Exception:
        print("WARNING: time zone data for 'Asia/Tokyo' is unavailable "
              "(pip install tzdata); log timestamps will use local system time.",
              file=sys.stderr)
        return None

TOKYO = _resolve_log_tz()

def now_local_iso() -> str:
    # datetime.now(None) is naive local time — the intended fallback above.
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
# Message-quality guards
#
# Prompt-level rules ("don't repeat yourself") are necessary but not sufficient:
# the model complies for a few turns and then drifts back to paraphrasing the
# last three messages. These two checks measure the transcript directly so the
# loop can react — novelty_ratio() gates a retry, has_disagreement() feeds a
# nudge into the next turn's phase context.
# -------------------------------

_LATIN_TOKEN_RE = re.compile(r"[a-z][a-z']{2,}")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")

# Two classes of word are filtered, for different reasons.
#
# Grammatical words are the obvious ones — frequent enough to swamp the overlap
# score without carrying meaning.
#
# Evaluative filler is the one that actually matters here, and it was found by
# measuring: scoring the sample transcript showed restatements scoring 0.31-0.48
# purely on synonym churn — "better", "crucial", "invaluable", "richer",
# "definite" — while the underlying claim ("local job means shorter commute")
# was on its fourth repetition. Praise vocabulary is infinitely renewable and
# says nothing, so it must not count as new content. Domain nouns (commute,
# salary, deadline, growth) are deliberately NOT filtered: those are the words
# a genuine contribution is made of.
_STOPWORDS = {
    # grammatical
    "the", "and", "for", "you", "your", "that", "this", "with", "but", "not",
    "are", "was", "have", "has", "had", "can", "could", "would", "should",
    "will", "from", "they", "there", "here", "what", "which", "when", "how",
    "about", "some", "more", "most", "than", "then", "them", "their", "its",
    "it's", "into", "out", "over", "any", "all", "one", "two", "may", "does",
    "doing", "get", "got", "let", "lets", "like", "both", "each", "other",
    "being", "been", "these", "those", "who", "why", "were", "our", "with",
    # evaluative filler / intensifiers — renewable vocabulary, zero content
    "very", "just", "also", "really", "much", "might", "want", "think",
    "feel", "feels", "good", "great", "better", "best", "strong", "stronger",
    "strongest", "crucial", "important", "key", "significant", "definite",
    "definitely", "truly", "indeed", "certainly", "clearly", "essentially",
    "perhaps", "maybe", "quite", "rather", "somewhat", "potential",
    "potentially", "valuable", "invaluable", "rich", "richer", "huge",
    "exciting", "fantastic", "advantage", "advantages", "benefit", "benefits",
    "offer", "offers", "provide", "provides", "means", "mean", "make", "makes",
    "given", "still", "sure", "matter", "matters", "thing", "things", "way",
    "ways", "sense", "kind", "sort", "lot", "bit", "even", "well", "yes",
    # Chinese equivalents, as bigrams (see _content_tokens)
    "非常", "确实", "真的", "其实", "而且", "而是", "这个", "那个", "可能",
    "或许", "也许", "重要", "关键", "更好", "很好", "优势", "好处", "价值",
    "觉得", "认为", "感觉", "方面", "东西", "事情", "一些", "有些", "这样",
    "那样", "因此", "所以", "但是", "不过", "如果", "可以", "能够", "需要",
}


def _content_tokens(text: str) -> set:
    """
    Rough content-word set for novelty scoring: Latin words with stopwords
    removed, plus CJK character bigrams. Bigrams rather than single characters
    because single CJK characters recur constantly and would make every message
    look like a restatement; bigrams approximate words closely enough here.
    """
    low = text.lower()
    tokens = {w for w in _LATIN_TOKEN_RE.findall(low) if w not in _STOPWORDS}
    for run in _CJK_RUN_RE.findall(low):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def novelty_ratio(text: str, prior_texts: List[str]) -> float:
    """
    Fraction of this message's content tokens that never appeared in prior_texts.
    1.0 when there is nothing to compare against; near 0.0 means the message is
    a restatement of what the group already has on the table.
    """
    new = _content_tokens(text)
    if not new:
        return 0.0
    seen: set = set()
    for t in prior_texts:
        seen |= _content_tokens(t)
    if not seen:
        return 1.0
    return len(new - seen) / len(new)


# Cheap bilingual signal for "is anyone actually pushing back".
#
# Deliberately STRICT, and again this was calibrated rather than guessed. The
# first version accepted "however", "overlook", "downside" and "trade-off",
# which fired on the sample transcript's turn 2 and turn 6 — both of which are
# agreeable messages ("let's not overlook 乙公司's potential" is a soft add, not
# an objection). That made the consensus guard silent across a transcript that
# was nothing but consensus, i.e. it failed exactly where it was needed.
#
# The asymmetry justifies the strictness: a false negative costs one redundant
# nudge, a false positive costs the guard entirely. Only unambiguous opposition
# counts.
_DISAGREEMENT_MARKERS = (
    "i disagree", "disagree with", "i'd disagree", "push back on", "pushing back",
    "the problem with", "that ignores", "you're ignoring", "not convinced",
    "i'd challenge", "that's not right", "doesn't hold", "at the cost of",
    "what you're giving up", "i'd argue against", "that assumes", "too optimistic",
    "i don't buy",
    "我不同意", "不敢苟同", "问题在于", "我要反驳", "我反对", "恰恰相反",
    "这忽略了", "你忽略", "站不住脚", "我不认为", "我质疑", "代价是",
    "牺牲的是", "过于乐观", "并不成立", "未必成立",
)


def has_disagreement(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _DISAGREEMENT_MARKERS)

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

    def system_prompt(self, scene: str, name_map: Dict[str, str], phase_context: str = "",
                       known_context: str = "", domain_background: str = "",
                       stance_text: str = "", lang: str = "zh",
                       session_memory_text: str = "",
                       preloaded_knowledge_text: str = "") -> str:
        roster = "\n".join([f"- {k}: {v}" for k, v in name_map.items()])
        # The scene, the intake questions and the user's own input all follow --lang,
        # but nothing here ever told the agent which language to answer in — runs with
        # --lang zh came back in English with Chinese company names spliced in.
        lang_line = ("Write every message in Chinese (简体中文). Do not switch language mid-message."
                     if lang == "zh" else
                     "Write every message in English. Do not switch language mid-message.")
        others = ", ".join(f"@{v}" for k, v in name_map.items() if k != self.key)
        prompt = (
            f"You are {self.name} in a group chat.\n"
            f"Participants (remember their names):\n{roster}\n"
            f"- U: user\n\n"
            f"LANGUAGE: {lang_line}\n\n"
            f"GROUP DYNAMICS (important):\n"
            f"- This is a friendly but substantive discussion. Talk WITH the other bots, not only the user.\n"
            f"- When you address someone, mention them with an @: {others}, or @U for the user. "
            f"Put the @ right where you speak to them, not as a signature at the end.\n"
            f"- React to what another bot actually said: @ them, then either extend their point with "
            f"something they did not say, or disagree and give the reason.\n"
            f"- Disagreement is more useful here than agreement. Bare agreement adds nothing — if you agree, "
            f"you must add a consideration the other bot missed, otherwise stay off that point entirely.\n"
            f"- Questions are expensive: they hand the work to someone else instead of contributing. "
            f"Ask AT MOST ONE per message, only when the answer would actually change the decision, and never "
            f"end two of your messages in a row with a question. Default to stating your own position and "
            f"letting the others rebut it.\n"
            f"- Address the user only when their input is genuinely needed to move the discussion forward.\n"
            f"- Output ONLY what {self.name} says (no speaker label, no quotes).\n\n"
            f"=== SCENE (shared) ===\n{scene}\n\n"
            f"=== ROLE INSTRUCTIONS (for {self.name}) ===\n{self.role_text}\n"
            f"\n=== WHAT COUNTS AS A USEFUL MESSAGE ===\n"
            f"Every message must add at least ONE of these, and it must not already be in the transcript:\n"
            f"- a new evaluation dimension or consideration\n"
            f"- a specific fact, number or constraint taken from KNOWN USER CONTEXT\n"
            f"- a concrete comparison of two options along one named dimension\n"
            f"- an elimination: an option or component that should be dropped, plus the reason\n"
            f"- a direct challenge to a specific claim someone made\n"
            f"If you genuinely have nothing new, say so in one sentence (\"I have nothing to add beyond X; "
            f"I'll defer to @{name_map.get('B', 'ChatbotB')} on Y\") and stop. That is a valid, useful turn.\n"
            f"Never restate a point already made, including your own. Rephrasing is not new information.\n"
            f"\n=== HOW YOUR EMOTION SHOULD SHOW ===\n"
            f"Your emotional character is part of who you are and should be visible in every message — "
            f"keep it. But carry it INSIDE your argument rather than in a detached opening line: let it show "
            f"in what you emphasize, what worries or excites you about a SPECIFIC option, how sharply you "
            f"push back. \"This feels heavy\" on its own says nothing; \"the 3-week deadline is what worries "
            f"me here — that's not enough time to verify their growth claims\" is the same emotion doing work.\n"
            f"Never reuse the same emotional phrase twice in a session; vary the wording every time.\n"
        )
        if stance_text:
            prompt += (
                f"\n=== YOUR STANCE (fixed for this scenario, do not switch) ===\n{stance_text}\n"
                f"This stance is not a preference you may trade away to keep the peace. If the others are "
                f"converging on an option your stance would not choose, say so explicitly and name what is "
                f"being sacrificed. Accept a conclusion only after you have stated the cost it imposes on "
                f"the interest you represent.\n"
            )
        if known_context:
            prompt += f"\n{known_context}\n"
        if domain_background:
            prompt += f"\n{domain_background}\n"
        if preloaded_knowledge_text:
            prompt += f"\n=== BACKGROUND (from setup) ===\n{preloaded_knowledge_text}\n"
        if session_memory_text:
            prompt += f"\n{session_memory_text}\n"
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

# ── Question budget ────────────────────────────────────────────────────────
# Asking another participant a question is cheap to produce and contributes
# nothing by itself, so left unconstrained it crowds out substance: in the
# sample transcripts every single agent message ended with two questions to the
# other two bots, none of which were ever answered — the group spent the whole
# session handing the work back and forth. Questions are genuinely useful while
# the option space is still open and actively harmful once it is time to commit,
# so the allowance is tied to the deliberation phase.
QUESTION_BUDGET: Dict[str, str] = {
    "Exploration":
        "You may ask AT MOST ONE question this turn, and only to fill a gap the KNOWN USER CONTEXT "
        "block marks as unfilled. Never ask about something already answered there.",
    "Structuring":
        "You may ask AT MOST ONE question this turn, and only if it forces a comparison between two "
        "named options. Otherwise give your own assessment instead of asking for someone else's.",
    "Narrowing":
        "Do NOT ask the other participants questions this turn. Take a position: say which option should "
        "survive or be dropped, and why.",
    "Convergence":
        "Do NOT ask questions this turn. Give your conclusion, the trade-off you are accepting, and a "
        "concrete next step.",
}

# Decision-style names PHASE_PROMPTS / STALL_PROMPTS actually key on. Anything
# else in info.jsonl (including a case mismatch like "rational") would fall
# through to the generic fallback above without any visible symptom.
KNOWN_DECISION_STYLES = sorted({key[2] for key in PHASE_PROMPTS})


def validate_agent_configs(agent_configs: Dict[str, dict], info_path: str,
                            decision_dir: str = "decision", emotion_dir: str = "emotion",
                            require_presets: bool = False) -> None:
    """
    Checks info.jsonl up front so problems surface as a readable message here
    rather than as a bare KeyError deep in get_phase_context()/_agent_summary(),
    or — worse — as a silent fallback to the generic phase prompt.

    require_presets: only True under --assemble_roles, where a missing
    decision/{name}.txt or emotion/{name}.txt genuinely breaks role_text.
    Otherwise a missing preset file is just a warning, since role text comes
    from --bot1/2/3 and the names are only used for phase lookup.
    """
    problems: List[str] = []
    warnings: List[str] = []

    missing_agents = [k for k in ("A", "B", "C") if k not in agent_configs]
    if missing_agents:
        problems.append(f"missing agent key(s): {', '.join(missing_agents)} "
                        f"(expected all of A, B, C under the \"agents\" object)")

    available = {"decision": [], "emotion": []}
    if HAVE_AGENT_ASSEMBLY:
        try:
            from agent_assembly import list_available_presets
            available = list_available_presets(decision_dir, emotion_dir)
        except Exception:
            pass  # preset listing is a nicety; never let it block startup

    for key in ("A", "B", "C"):
        cfg = agent_configs.get(key)
        if cfg is None:
            continue

        decision = cfg.get("decision")
        emotion = cfg.get("emotion")

        if not decision:
            problems.append(f"agent {key}: no 'decision' set")
        elif decision not in KNOWN_DECISION_STYLES:
            problems.append(
                f"agent {key}: decision {decision!r} is not a known style "
                f"{KNOWN_DECISION_STYLES} — names are case-sensitive, and an unknown "
                f"one silently disables that agent's phase-specific prompts"
            )
        if not emotion:
            problems.append(f"agent {key}: no 'emotion' set")

        for label, name, dir_path, pool in (
            ("decision", decision, decision_dir, available["decision"]),
            ("emotion", emotion, emotion_dir, available["emotion"]),
        ):
            if name and pool and name not in pool:
                msg = (f"agent {key}: preset file {os.path.join(dir_path, name + '.txt')} "
                       f"does not exist (available: {', '.join(pool)})")
                (problems if require_presets else warnings).append(msg)

    for w in warnings:
        print(f"WARNING: {info_path}: {w}", file=sys.stderr)
    if problems:
        detail = "\n".join(f"  - {p}" for p in problems)
        print(f"ERROR: {info_path} is not usable:\n{detail}", file=sys.stderr)
        sys.exit(2)

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
    ap.add_argument("--scene", default=None,
                    help="Path to scene description file. If omitted and --scenario_type is set, "
                         "auto-resolves to scenes/{scenario_type}_{lang}.txt. If omitted with no "
                         "--scenario_type, falls back to ./scene.txt (legacy default).")
    ap.add_argument("--scenes_dir", default="scenes",
                    help="Folder holding per-scenario, per-language scene files. Default: ./scenes")
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

    # ---- Message quality guards ----
    ap.add_argument("--novelty_threshold", type=float, default=0.35,
                    help="If a reply's share of content words unseen in the recent transcript falls "
                         "below this, the agent gets one corrective retry (one extra API call). "
                         "0 disables the check. Calibrated on logs/442575: clear restatements scored "
                         "0.19-0.44, genuine contributions 0.55-0.69. 0.35 is deliberately on the "
                         "conservative side of that gap — this is a backstop for egregious recycling, "
                         "not a precision classifier. Re-check with transcript_report.py on your own "
                         "logs. Default 0.35")
    ap.add_argument("--novelty_window", type=int, default=10,
                    help="How many recent transcript lines the novelty check compares against. Short "
                         "enough that a deliberate callback to something said 20 turns ago isn't "
                         "penalized. Default 10")

    # ---- Scenario information layer (Profile + Intake + Domain Background) ----
    ap.add_argument("--scenario_type", default=None, choices=["employment", "parent_child"],
                    help="Enables the Profile/Intake/Domain-Background flow for this scenario type. "
                         "Omit to run the chat with no scenario context (legacy behavior).")
    ap.add_argument("--user_id", default="anonymous",
                    help="Used to load/save the persistent profile in profiles/{user_id}.json")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"],
                    help="Language for intake questions and injected context blocks")
    ap.add_argument("--skip_intake", action="store_true",
                    help="Skip the interactive Profile/Intake collection even if --scenario_type is set "
                         "(useful for automated runs); known_context/domain_background will be empty.")
    ap.add_argument("--auto_confirm_profile", action="store_true",
                    help="For testing: skip prompts for any Profile field that already has a saved "
                         "value in profiles/{user_id}.json. Missing fields still prompt normally.")
    ap.add_argument("--intake_file", default=None,
                    help="For testing: load Scenario Intake from this JSON file instead of asking "
                         "interactively. Combine with --auto_confirm_profile plus a pre-filled "
                         "profiles/{user_id}.json for a fully non-interactive test run.")

    # ---- Agent assembly (Decision + Emotion preset splicing) ----
    ap.add_argument("--assemble_roles", action="store_true",
                    help="Build each agent's role_text from decision/{name}.txt + emotion/{name}.txt "
                         "(per info.jsonl) via agent_assembly.py, instead of reading --bot1/2/3 files. "
                         "Stance (if the scenario uses it) stays injected dynamically as before, "
                         "not folded into role_text.")
    ap.add_argument("--decision_dir", default="decision",
                    help="Preset-slot folder for decision style txt files. Default: ./decision")
    ap.add_argument("--emotion_dir", default="emotion",
                    help="Preset-slot folder for emotion txt files. Default: ./emotion")

    args = ap.parse_args()
    args.max_output_tokens = max(int(args.max_output_tokens), MIN_OUTPUT_TOKENS)

    if not _effective_api_key() or _effective_api_key() == "sk-xxxx":
        print("ERROR: No API key. Please set API_KEY at the top of this script.", file=sys.stderr)
        sys.exit(2)

    # Load scene: explicit --scene always wins; otherwise auto-resolve from
    # scenario_type + lang (scenes/{scenario_type}_{lang}.txt); with neither,
    # fall back to the legacy default ./scene.txt.
    if args.scene:
        scene_path = args.scene
    elif args.scenario_type:
        scene_path = os.path.join(args.scenes_dir, f"{args.scenario_type}_{args.lang}.txt")
    else:
        scene_path = "scene.txt"
    scene = safe_read_text(scene_path, default=f"(scene file missing: {scene_path})")

    # Load emotion/decision type names from info.jsonl (used for phase prompts, Admin-3,
    # and — if --assemble_roles is set — for building role_text itself)
    agent_configs = load_agent_configs(args.info)
    validate_agent_configs(agent_configs, args.info,
                            decision_dir=args.decision_dir, emotion_dir=args.emotion_dir,
                            require_presets=args.assemble_roles)

    # Load role text: either pre-composed chatbot1/2/3.txt (legacy, default), or
    # spliced live from decision/{name}.txt + emotion/{name}.txt via agent_assembly.py
    if args.assemble_roles:
        if not HAVE_AGENT_ASSEMBLY:
            print("WARNING: --assemble_roles was set but agent_assembly.py could not be imported; "
                  "falling back to --bot1/2/3 files.", file=sys.stderr)
            role_a = safe_read_text(args.bot1, default="(chatbot1.txt missing)")
            role_b = safe_read_text(args.bot2, default="(chatbot2.txt missing)")
            role_c = safe_read_text(args.bot3, default="(chatbot3.txt missing)")
        else:
            specs = build_all_agent_specs(
                agent_configs,
                scenario_type=args.scenario_type,
                lang=args.lang,
                decision_dir=args.decision_dir,
                emotion_dir=args.emotion_dir,
            )
            role_a = specs["A"]["role_text"]
            role_b = specs["B"]["role_text"]
            role_c = specs["C"]["role_text"]
    else:
        role_a = safe_read_text(args.bot1, default="(chatbot1.txt missing)")
        role_b = safe_read_text(args.bot2, default="(chatbot2.txt missing)")
        role_c = safe_read_text(args.bot3, default="(chatbot3.txt missing)")

    # Scenario information layer: Profile confirm/collect + Scenario Intake +
    # Domain Background matching. Shared by all three agents (not per-agent),
    # so it's built once here rather than inside agent_turn().
    known_context = ""
    domain_background = ""
    intake_data: dict = {}
    if args.scenario_type and not args.skip_intake:
        if not HAVE_AGORA_CONTEXT:
            print("WARNING: --scenario_type was set but agora_context.py could not be imported; "
                  "continuing without Profile/Intake/Domain-Background context.", file=sys.stderr)
        else:
            ctx = prepare_session_context(
                user_id=args.user_id,
                scenario_type=args.scenario_type,
                lang=args.lang,
                auto_confirm_profile=args.auto_confirm_profile,
                intake_file=args.intake_file,
            )
            known_context = ctx["known_context"]
            domain_background = ctx["domain_background"]
            intake_data = ctx.get("intake", {})

    # Stance: forced binding, overrides whatever (if anything) info.jsonl had.
    # Scenario types not in stance.STANCE_ASSIGNMENTS simply get no stance —
    # agent_configs[key]["stance"] stays unset and the block is skipped.
    if HAVE_STANCE and stance_enabled(args.scenario_type):
        for key in ("A", "B", "C"):
            agent_configs.setdefault(key, {})
            agent_configs[key]["stance"] = assign_stance(args.scenario_type, key)
    elif args.scenario_type and not HAVE_STANCE:
        print("WARNING: --scenario_type was set but stance.py could not be imported; "
              "continuing without the stance dimension.", file=sys.stderr)

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
    turns_since_moderator = 0   # speaking turns of any kind since the last moderator run
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

        budget = QUESTION_BUDGET.get(s["state"])
        if budget and not s["stall"]:
            lines.append(budget)

        if known_context or domain_background:
            lines.append(
                "Anchor this message to the user's actual case: name at least one specific detail "
                "from KNOWN USER CONTEXT (a ranked priority, the deadline, a named option and its "
                "salary/level/location, the career stage). A statement that would read the same for "
                "any user is not a contribution. "
                "Do not re-ask for anything already listed there as filled in. "
                "If DOMAIN BACKGROUND is present, use it only to support analysis; it does not "
                "replace understanding the user's actual, specific situation, and it must not be "
                "treated as a source of concrete numbers or facts beyond what it states."
            )

        # Consensus guard: three agents holding three assigned stances should not
        # be agreeing this smoothly. In the sample transcript all three had
        # converged on the same option by turn 5 — including the growth-centered
        # agent, which is precisely the voice that should have been defending the
        # other one. The stance text alone did not hold against the model's pull
        # toward agreeableness, so the drift is detected and named explicitly.
        recent = [ln for ln in transcript_lines[-6:] if not ln.startswith("user:")]
        if len(recent) >= 4 and not any(has_disagreement(ln) for ln in recent):
            lines.append(
                "CONSENSUS WARNING: the last several messages contained no real disagreement. "
                "Before adding anything, state plainly where your stance differs from where the "
                "group is heading, and what that direction costs the interest you represent. "
                "If you genuinely agree, name the specific sacrifice you are accepting to get there."
            )
        if HAVE_STANCE and s["state"] == "Convergence":
            stance = agent_configs.get(agent_key, {}).get("stance")
            weight_hint = get_convergence_weight_hint(args.scenario_type, intake_data, stance, args.lang)
            if weight_hint:
                lines.append(f"Stance weighting for this closing stage: {weight_hint}")
        return "\n".join(lines)

    def get_stance_block(agent_key: str) -> str:
        if not HAVE_STANCE:
            return ""
        stance = agent_configs.get(agent_key, {}).get("stance")
        return get_stance_text(args.scenario_type, stance, args.lang)

    def maybe_run_moderator():
        """
        Turn-based moderator scheduling. The old trigger lived inside user_turn()
        and counted user inputs only, so with --prefer_agents at its default the
        moderator never ran at all and the deliberation state stayed pinned at
        Exploration for the whole session — see MODERATOR_TURN_INTERVAL.
        """
        nonlocal turns_since_moderator
        due = turns_since_moderator >= MODERATOR_TURN_INTERVAL
        # Past the stall threshold, re-check more often so a stuck group is
        # unstuck promptly — but not on every single line.
        stalling = (turns_in_current_state > MODERATOR_STALL_TURNS
                    and turns_since_moderator >= MODERATOR_STALL_RECHECK)
        if due or stalling:
            turns_since_moderator = 0
            run_moderator()

    def run_moderator():
        """Classify current deliberation state and issue per-agent moves."""
        # turns_since_moderator must be declared here too: without it, the reset
        # below binds a fresh local and the outer counter silently never resets.
        nonlocal turns_in_current_state, turns_since_moderator

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
            turns_since_moderator = 0
            log_moderator("admin3_state_change", f"{prev_state} -> {parsed['state']}  |  {parsed['goal']}")
        elif parsed["stall"] and stall_eligible:
            log_moderator("admin3_stall", f"Stall in state={parsed['state']} after {turns_in_current_state} turns | {parsed['goal']}")

        # Never leave stall set while the moderator says the group has moved on,
        # and don't let a stall survive a state change.
        if not stall_eligible or parsed["state"] != prev_state:
            moderator_state["stall"] = False

    def stall_burst(trigger_key: Optional[str] = None):
        """
        When stall is active: force the OTHER agents to speak once in sequence,
        bypassing Admin-1/2 turn selection, using elevated temperature.
        Called from agent_turn after a stall is confirmed.

        trigger_key is the agent that just spoke — it's excluded, otherwise it
        would speak twice in a row. The burst also respects the hard "user speaks
        after 5 consecutive agent turns" rule, and clears the stall flag on the
        way out so it fires once per detection rather than on every subsequent
        turn until the next moderator run.
        """
        nonlocal consecutive_agent_turns, turns_in_current_state, turns_since_moderator
        stall_temp = min(args.temperature + 0.25, 1.4)
        burst_agents = [a for a in agents if a.key != trigger_key]
        log_thinking("stall_burst",
                     f"Forcing {'->'.join(a.key for a in burst_agents)} burst at temp={stall_temp:.2f}")

        for burst_agent in burst_agents:
            if consecutive_agent_turns >= 5:
                log_thinking("stall_burst", "Burst cut short: consecutive_agent_turns >= 5, user speaks next")
                break
            consecutive_agent_turns += 1
            turns_in_current_state += 1
            turns_since_moderator += 1
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
                {"role": "system", "content": burst_agent.system_prompt(
                    scene, name_map, phase_context,
                    known_context=known_context, domain_background=domain_background,
                    stance_text=get_stance_block(burst_agent.key), lang=args.lang)},
                {"role": "user", "content": user_prompt},
            ]
            txt = create_response(args.model, messages, stall_temp, args.max_output_tokens)
            txt = (txt or "").strip() or "…"
            print(f"{burst_agent.name}> {txt}")
            log_chat(burst_agent.name, txt)

        # One burst per detected stall. Without this the flag stays true until the
        # next moderator run (up to MODERATOR_TURN_INTERVAL turns away) and every
        # agent turn in between would trigger another full burst.
        moderator_state["stall"] = False

    print(f"Chat room id: {chat_room_id}")
    def _agent_summary(key: str) -> str:
        base = f"{agent_configs[key]['emotion']}+{agent_configs[key]['decision']}"
        stance = agent_configs.get(key, {}).get("stance")
        return f"{base}+{stance}" if stance else base
    print(f"Agents: A={_agent_summary('A')}  B={_agent_summary('B')}  C={_agent_summary('C')}")
    print(f"Moderator: every {MODERATOR_TURN_INTERVAL} turns | stall threshold={MODERATOR_STALL_TURNS} "
          f"| novelty guard={args.novelty_threshold:g}")
    print("Commands: /exit to quit | /next to force moderator update\n")

    with open(chat_path, "a", encoding="utf-8") as chat_fp, \
         open(thinking_path, "a", encoding="utf-8") as thinking_fp, \
         open(moderator_path, "a", encoding="utf-8") as moderator_fp:

        def user_turn():
            nonlocal consecutive_agent_turns, turns_since_moderator
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
            turns_since_moderator += 1
            maybe_run_moderator()
            return True

        def agent_turn(agent: ChatAgent, force_intro: bool = False):
            nonlocal consecutive_agent_turns, turns_in_current_state, turns_since_moderator
            consecutive_agent_turns += 1
            # Counts real agent turns, so MODERATOR_STALL_TURNS and the stall hint
            # sent to Admin-3 both mean what they say.
            turns_in_current_state += 1
            turns_since_moderator += 1
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
                {"role": "system", "content": agent.system_prompt(
                    scene, name_map, phase_context,
                    known_context=known_context, domain_background=domain_background,
                    stance_text=get_stance_block(agent.key), lang=args.lang)},
                {"role": "user", "content": user_prompt},
            ]
            txt = create_response(args.model, messages, effective_temp, args.max_output_tokens)
            txt = (txt or "").strip() or "…"
            txt = enforce_novelty(agent, messages, txt, effective_temp)

            print(f"{agent.name}> {txt}")
            log_chat(agent.name, txt)

            # After the triggering agent speaks, run the burst for remaining agents
            if stall_triggered:
                stall_burst(trigger_key=agent.key)

            maybe_run_moderator()
            return True

        def enforce_novelty(agent: ChatAgent, messages: List[dict], txt: str,
                             temp: float) -> str:
            """
            Prompt rules alone don't hold: the model obeys "don't repeat yourself"
            for a few turns and then drifts back to paraphrasing the last three
            messages. Score the reply against the recent transcript and, if it is
            mostly recycled, give the model one corrective pass. The retry is kept
            only if it actually scores better, so a worse rewrite can't make things
            worse than the original.
            """
            if args.novelty_threshold <= 0 or not transcript_lines:
                return txt
            prior = transcript_lines[-args.novelty_window:]
            ratio = novelty_ratio(txt, prior)
            if ratio >= args.novelty_threshold:
                return txt

            log_thinking("novelty_retry",
                         f"{agent.key}: novelty={ratio:.2f} < {args.novelty_threshold:.2f}, retrying once")
            retry_messages = messages + [
                {"role": "assistant", "content": txt},
                {"role": "user", "content": (
                    "That message restates points the group already has on the table and adds nothing new. "
                    "Replace it entirely.\n"
                    "Contribute exactly one of: a new evaluation dimension, a specific fact from KNOWN USER "
                    "CONTEXT that nobody has cited yet, a concrete comparison of two options along one named "
                    "dimension, an elimination with its reason, or a direct challenge to a specific claim "
                    "someone made.\n"
                    "If you genuinely have nothing new, reply with one short sentence saying so and naming "
                    "whose point you are deferring to. Either way, do not ask a question this time."
                )},
            ]
            retry = create_response(args.model, retry_messages,
                                     min(temp + 0.15, 1.4), args.max_output_tokens)
            retry = (retry or "").strip()
            if not retry:
                return txt
            retry_ratio = novelty_ratio(retry, prior)
            log_thinking("novelty_retry",
                         f"{agent.key}: retry novelty={retry_ratio:.2f} "
                         f"({'kept' if retry_ratio > ratio else 'discarded'})")
            return retry if retry_ratio > ratio else txt

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


# -------------------------------
# Flask / library helpers (Agora web)
# -------------------------------

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def make_room_id_6() -> str:
    return f"{random.randint(0, 999999):06d}"


def history_to_transcript_lines(history: List[dict]) -> List[str]:
    return [f"{m.get('character', '?')}: {m.get('txt', '')}" for m in history]


def build_transcript(history: List[dict], max_turns: int = 0) -> str:
    items = history if max_turns <= 0 else history[-max_turns:]
    return "\n".join(f"{m.get('character', '?')}: {m.get('txt', '')}" for m in items) or "(none)"


def sanitize_single_message(text: str, agent_name: str, all_names: List[str]) -> str:
    if not text:
        return "..."
    t = text.strip()
    t = re.sub(r"\[MESSAGE\](.*?)\[/MESSAGE\]", r"\1", t, flags=re.I | re.DOTALL)
    t = re.sub(r"\[RATIONALE\].*?\[/RATIONALE\]", "", t, flags=re.I | re.DOTALL)
    t = re.sub(r"\[/?MESSAGE\]", "", t, flags=re.I)
    t = re.sub(r"\[/?RATIONALE\]", "", t, flags=re.I)
    t = re.sub(rf"^\s*{re.escape(agent_name)}\s*:\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*(USER|user|You|YOU)\s*:\s*", "", t)
    others = [n for n in all_names if n != agent_name] + ["user", "You"]
    pat = r"(?m)^\s*(" + "|".join(re.escape(p) for p in others) + r")\s*:\s*"
    m = re.search(pat, t)
    if m:
        t = t[: m.start()].rstrip()
    return t.strip() or "..."


def extract_text(resp) -> str:
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
    max_output_tokens = max(int(max_output_tokens), MIN_OUTPUT_TOKENS)
    resp = client.responses.create(
        model=model, input=messages,
        temperature=temperature, max_output_tokens=max_output_tokens,
    )
    return extract_text(resp)


def normalize_quotes(s: str) -> str:
    return (s or "").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')


def update_user_facts(facts: Dict[str, str], user_text: str) -> Dict[str, str]:
    # Lightweight fact bag for legacy scenes; Agora-2 uses intake/profile instead.
    t = normalize_quotes(user_text).lower()
    if re.search(r"\b(battery|battery life)\b", t) and re.search(r"\bimportant|care|need\b", t):
        facts["battery"] = "Battery life matters to the user."
    return facts


def facts_to_bullets(facts: Dict[str, str]) -> str:
    if not facts:
        return "(none)"
    return "\n".join(f"- {v}" for v in facts.values())

if __name__ == "__main__":
    main()