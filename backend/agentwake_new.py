# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
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

# Stance Knowledge: keyword-triggered, per-stance background cards injected into
# the speaking agent's prompt. Pure local dict lookup (no network / no LLM). See
# stance_knowledge.py. Optional import so the script still runs standalone.
try:
    # _match_topic_card is reused (not reimplemented) so the "did a keyword hit"
    # gate below shares one source of truth with the module's own matching.
    from stance_knowledge import (
        load_stance_knowledge,
        get_stance_knowledge_block,
        peek_matched_card_id,
        _match_topic_card as sk_match_topic_card,
    )
    HAVE_STANCE_KNOWLEDGE = True
except ImportError:
    HAVE_STANCE_KNOWLEDGE = False
    peek_matched_card_id = None  # type: ignore

# Cross-session memory: carry a short recap of the last few sessions into the
# next one (implicit auto-carry, keyed by user_id + scenario_type). Adds exactly
# one extra LLM call at session end, reusing create_response. See session_memory.py.
try:
    from session_memory import (
        load_recent_sessions,
        build_session_memory_text,
        summarize_session,
        append_session_record,
    )
    HAVE_SESSION_MEMORY = True
except ImportError:
    HAVE_SESSION_MEMORY = False

# ===============================
# API KEY — read from the environment, never hardcode.
# The key that used to sit here was committed to git history and must be
# treated as leaked: revoke it in the OpenAI dashboard.
# ===============================
API_KEY = ""  # unused; _effective_api_key reads OPENAI_API_KEY
MIN_OUTPUT_TOKENS = 16

# ===============================
# MODERATOR CONFIG
# ===============================
# Phase progression is driven by USER participation, with a total-turn backstop.
#
# History of this trigger, because both extremes were observed in real runs:
#   v1 counted user inputs only, at 3 — with --prefer_agents 0.85 the user
#     speaks about once every 8-9 lines, so the moderator effectively never ran
#     and the whole four-phase machinery was unreachable.
#   v2 counted turns of ANY kind, at 4 — which decoupled progression from the
#     user entirely: in logs/316347 three agents exchanged greetings and that
#     alone advanced Exploration -> Structuring before the user had typed a
#     single character. All four phases completed on three user sentences.
# The deliberation belongs to the user, so a phase advances when the USER has
# contributed; the total-turn backstop only exists so a silent user can't
# freeze the state machine forever.
MODERATOR_USER_TURN_INTERVAL = 2   # primary: moderator re-runs every N user turns
MODERATOR_TURN_FALLBACK = 10       # backstop: ...or after N turns of any kind
# How many consecutive turns in the same state before moderator tries to unstick (strictly greater, first turn excluded)
MODERATOR_STALL_TURNS = 6
# Once past the stall threshold, re-check this often instead of waiting for the
# full interval — but not every single turn, which would be one extra API call
# per line for the rest of the session.
MODERATOR_STALL_RECHECK = 2

# Terminal state. Convergence is a phase the group works IN; without an exit it
# has no floor — logs/316347 shows three consecutive Convergence verdicts whose
# goals decayed into noise ("confirm alignment" -> "encourage the user to
# finalize" -> "address remaining concerns") while the agents recycled the same
# recommendation at novelty 0.00. Once the group has converged twice with no new
# user input, the discussion is over: the state latches to CONCLUDED and the
# floor goes to the user instead of to another agent.
CONCLUDED_STATE = "Concluded"

# Upper bound on how many agents a stall burst may force to speak. The burst is
# exempt from the consecutive-turn valve (see stall_burst), so it needs a bound
# of its own — without one, a large agent pool could monopolise the floor.
MAX_STALL_BURST_TURNS = 3

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
        raise RuntimeError("No API key. Set the OPENAI_API_KEY environment variable.")
    url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/responses"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    if not r.ok:
        raise RuntimeError(f"OpenAI HTTP error {r.status_code}: {r.text}")
    return r.json()

def _collect_meta_sdk(resp, meta: dict) -> None:
    """
    Why this exists: a run produced the bare string "I'm sorry, I can't assist
    with that." as a chat message, and the logs gave no way to tell whether it
    was a content filter, a truncation, or a normal completion. The Responses
    API carries that answer in status/incomplete_details/refusal — record it so
    the next occurrence is diagnosable instead of a guess.
    """
    meta["status"] = getattr(resp, "status", None)
    details = getattr(resp, "incomplete_details", None)
    if details is not None:
        meta["incomplete_reason"] = getattr(details, "reason", None) or (
            details.get("reason") if isinstance(details, dict) else None)
    try:
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) == "refusal":
                meta["refusal"] = getattr(item, "refusal", "") or "(refusal item)"
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", None) == "refusal":
                    meta["refusal"] = getattr(c, "refusal", "") or "(refusal content)"
        usage = getattr(resp, "usage", None)
        if usage is not None:
            meta["output_tokens"] = getattr(usage, "output_tokens", None)
    except Exception:
        pass


def create_response(model: str, messages: List[dict], temperature: float, max_output_tokens: int,
                    meta: Optional[dict] = None) -> str:
    """
    meta: optional dict filled in-place with generation metadata (status,
    incomplete_reason, refusal, output_tokens). Callers that want to log why a
    generation came back short/empty/refused pass a dict; everyone else omits it.
    """
    max_output_tokens = max(int(max_output_tokens), MIN_OUTPUT_TOKENS)
    if meta is None:
        meta = {}
    client = _load_openai_client()
    if client is not None:
        resp = client.responses.create(
            model=model, input=messages,
            temperature=temperature, max_output_tokens=max_output_tokens,
        )
        _collect_meta_sdk(resp, meta)
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
    meta["status"] = resp.get("status")
    if isinstance(resp.get("incomplete_details"), dict):
        meta["incomplete_reason"] = resp["incomplete_details"].get("reason")
    if isinstance(resp.get("usage"), dict):
        meta["output_tokens"] = resp["usage"].get("output_tokens")
    out_parts: List[str] = []
    for item in resp.get("output", []) or []:
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text" and "text" in c:
                out_parts.append(c["text"])
            elif c.get("type") == "refusal":
                meta["refusal"] = c.get("refusal") or "(refusal content)"
    return "".join(out_parts).strip()


def format_generation_meta(meta: dict) -> str:
    """Compact one-line rendering for the log; empty when nothing notable."""
    parts = [f"{k}={v}" for k, v in meta.items() if v not in (None, "")]
    return " ".join(parts)

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


def stance_knowledge_on_hit(scenario_type, stance, message, lang, knowledge,
                            include_header: bool = True,
                            include_related: bool = False) -> str:
    """Stance-knowledge block for `message`, but ONLY when it actually hits a
    topic-card keyword; "" otherwise. This suppresses the module's generic
    fallback so the block is tied to a real keyword match — the single rule both
    channels share: the per-turn dynamic trigger (get_phase_context, latest user
    message) and the session-start preloaded hint (build once from info.jsonl's
    hint). include_header=False returns the body alone, for callers that add
    their own distinct block title.

    include_related: expand one-hop related_cards (A-OR-B trigger decided by caller).
    """
    if not (HAVE_STANCE_KNOWLEDGE and knowledge and stance and message):
        return ""
    scenario_cfg = knowledge.get(scenario_type, {}) or {}
    stance_cfg = scenario_cfg.get(stance)
    topic_cards = stance_cfg.get("topic_cards", []) if isinstance(stance_cfg, dict) else []
    if not sk_match_topic_card(message, topic_cards, lang):
        return ""
    return get_stance_knowledge_block(
        scenario_type, stance, message, lang,
        knowledge=knowledge, include_header=include_header,
        include_related=include_related,
    )


def resolve_dynamic_stance_knowledge(
    *,
    scenario_type: Optional[str],
    stance: Optional[str],
    last_user_message: str,
    lang: str,
    knowledge,
    hit_history: Dict[str, List[str]],
    agent_key: str,
    deliberation_state: str,
) -> str:
    """
    Dynamic stance-knowledge channel with one-hop related_cards expansion.

    Expansion (include_related=True) when EITHER:
      A. this agent already hit the SAME card earlier this session (repeat hit), or
      B. deliberation is in Convergence.
    Records the card_id into hit_history after the repeat check.
    """
    if not (HAVE_STANCE_KNOWLEDGE and knowledge and stance and last_user_message and peek_matched_card_id):
        return ""
    card_id = peek_matched_card_id(
        scenario_type or "",
        stance,
        last_user_message,
        lang,
        knowledge=knowledge,
    )
    if not card_id:
        return ""
    hits = hit_history.setdefault(agent_key, [])
    repeat_hit = card_id in hits  # trigger A (check BEFORE recording)
    in_convergence = deliberation_state == "Convergence"  # trigger B
    hits.append(card_id)
    return stance_knowledge_on_hit(
        scenario_type,
        stance,
        last_user_message,
        lang,
        knowledge,
        include_header=True,
        include_related=(repeat_hit or in_convergence),
    )

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
                       preloaded_knowledge_text: str = "",
                       stance_labels: Dict[str, str] = None) -> str:
        # The cast list ("A represents the child's needs, B the parent's...") is
        # built HERE from the actual pool rather than written into the scene file,
        # which used to hardcode "three assistants (A / B / C)" and contradict the
        # roster as soon as the pool was any other size.
        stance_labels = stance_labels or {}
        roster = "\n".join(
            f"- {k}: {v}" + (f" — represents {stance_labels[k]}" if stance_labels.get(k) else "")
            for k, v in name_map.items()
        )
        # The scene, the intake questions and the user's own input all follow --lang,
        # but nothing here ever told the agent which language to answer in — runs with
        # --lang zh came back in English with Chinese company names spliced in.
        lang_line = ("Write every message in Chinese (简体中文). Do not switch language mid-message."
                     if lang == "zh" else
                     "Write every message in English. Do not switch language mid-message.")
        others = ", ".join(f"@{v}" for k, v in name_map.items() if k != self.key)
        # Any other agent's name works for the "defer to" example — take the first.
        defer_name = next((v for k, v in name_map.items() if k != self.key), "another bot")
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
            f"- The decision is the user's to make. Put your reasoning and your recommendation on the "
            f"table as input they weigh — do not narrate their choice back to them as already settled, "
            f"and do not issue them a list of instructions to go carry out. Say what you would pick and "
            f"why; leave the deciding to them.\n"
            f"- Output ONLY what {self.name} says (no speaker label, no quotes).\n\n"
            f"=== SCENE (shared) ===\n{scene}\n\n"
            f"=== ROLE INSTRUCTIONS (for {self.name}) ===\n{self.role_text}\n"
            f"\n=== WHAT COUNTS AS A USEFUL MESSAGE ===\n"
            f"These are in PRIORITY ORDER. When they compete, the higher one wins — including over the "
            f"phase task and the style rules further down.\n"
            f"1. ANSWER WHAT WAS ACTUALLY ASKED. If the user asked for concrete options, for a "
            f"recommendation, or what they should do, then name specific options and say which one you "
            f"back and why. Offering another abstract dimension or framework instead of answering is a "
            f"failed turn, no matter how well argued.\n"
            f"2. HOLD YOUR STANCE. If the group is heading somewhere your stance would not choose, say so "
            f"in this message and name what is being given up. Never soften your stance to keep the peace.\n"
            f"3. ADD SOMETHING NEW — at least one of these, and it must not already be in the transcript:\n"
            f"   - a concrete comparison of two NAMED options along one dimension\n"
            f"   - an elimination: which option should be dropped, plus the reason\n"
            f"   - a direct challenge to a specific claim someone made\n"
            f"   - a specific fact, number or constraint taken from KNOWN USER CONTEXT\n"
            f"   - a new evaluation dimension — ONLY while the concrete options are not yet on the table. "
            f"Once they are, argue about the options themselves instead of adding more dimensions.\n"
            f"If you genuinely have nothing new, say so in one sentence (\"I have nothing to add beyond X; "
            f"I'll defer to @{defer_name} on Y\") and stop. That is a valid, useful turn.\n"
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
        # Preloaded background from the user's setup hint — fixed for the whole
        # session. Distinct title from the per-turn "=== BACKGROUND KNOWLEDGE ==="
        # block (carried in phase_context) so the two channels never blur together.
        if preloaded_knowledge_text:
            prompt += f"\n=== BACKGROUND (from setup) ===\n{preloaded_knowledge_text}\n"
        if known_context:
            prompt += f"\n{known_context}\n"
        if domain_background:
            prompt += f"\n{domain_background}\n"
        if session_memory_text:
            prompt += f"\n{session_memory_text}\n"
        if phase_context:
            prompt += f"\n{phase_context}"
        prompt += (
            "\n\nOUTPUT FORMAT (required):\n"
            "[MESSAGE]\n"
            "your chat message here\n"
            "[/MESSAGE]\n"
            "[RATIONALE]\n"
            "one short sentence: why you said this, given your persona and the current phase goal\n"
            "[/RATIONALE]\n"
            "The four tags are literal markers, not text: write them in English exactly as shown, "
            "even though the message inside them is not in English. Do NOT translate them "
            "(no [消息], no [理由]) — a translated tag is not recognised and your private rationale "
            "ends up published in the chat.\n"
            # Restated here on purpose. The directive at the top is separated from
            # the actual generation by everything above — most of it English — and
            # agents were observed replying wholly in English in zh sessions.
            f"LANGUAGE, again: {lang_line} This applies to both blocks above.\n"
        )
        return prompt

# -------------------------------
# Admin prompts
# -------------------------------

def build_admin_prompts(agent_keys: List[str], max_consecutive: int) -> tuple[str, str]:
    """
    Admin-1/Admin-2 system prompts, built at runtime from the actual agent key
    set (info.jsonl's "agents" field is the single source of truth for how many
    agents exist). The old module-level constants hardcoded "A or B or C or U"
    and "after 5 consecutive agent turns", which silently broke any pool size
    other than three.
    """
    keys_or = " or ".join(agent_keys)
    keys_slash = "/".join(agent_keys)
    admin1 = f"""You are Admin-1: the group-chat pacing analyst.
You will read: the shared scene, the {len(agent_keys)} role settings, and the full transcript.

Your job: infer who SHOULD speak next and give a brief reason.

PACING GOAL (important):
- Strongly prefer {keys_slash} speaking over the user, as long as the conversation still feels coherent.
- Promote natural FRIEND group dynamics with more bot-to-bot discussion.
- Still keep the user included regularly, but less frequently than the bots.
- Always obey the hard rule: after {max_consecutive} consecutive agent turns, the next speaker must be U.

You MUST end your output with a single clear decision:
NEXT = {keys_or} or U (choose exactly one).
This analysis is NOT shown to the user, but is saved to the thinking log."""

    admin2 = f"""You are Admin-2: the strict next-speaker selector.
You will receive Admin-1's analysis text.
Your job: output ONLY ONE choice: {keys_or} or U.
Do not output anything else (no spaces, punctuation, explanation, or newline)."""
    return admin1, admin2

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

    # The "agents" object in info.jsonl is the single source of truth for how
    # many agents exist and what their keys are — no fixed key set is assumed.
    if not agent_configs:
        problems.append("no agent keys found (expected a non-empty \"agents\" object)")

    available = {"decision": [], "emotion": []}
    if HAVE_AGENT_ASSEMBLY:
        try:
            from agent_assembly import list_available_presets
            available = list_available_presets(decision_dir, emotion_dir)
        except Exception:
            pass  # preset listing is a nicety; never let it block startup

    for key in sorted(agent_configs):
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

def validate_persona_uniqueness(agent_configs: Dict[str, dict], info_path: str) -> None:
    """No two agents may be indistinguishable in the prompt.

    A scenario defines a fixed, small set of stances (three), while the pool size
    comes from info.jsonl. A pool larger than that set therefore REUSES stances by
    design — agent D gets the same stance as agent A. That is fine on its own:
    what is not fine is two agents whose stance, decision style AND emotion are
    all identical, because then every block that shapes their behaviour is the
    same and they can only produce the same message twice. That manufactures, by
    configuration, exactly the stance homogenisation the per-stance turn tasks
    exist to prevent.

    So when stances are in play, a full three-way collision is a hard config
    error: differentiate the duplicated stance with a different decision or
    emotion in info.jsonl. Without stances (legacy runs with no --scenario_type)
    the same collision is only a warning, since that path never promised
    differentiated voices and has always allowed it.

    Must run AFTER stance assignment, since the stance is what it keys on.
    """
    groups: Dict[tuple, List[str]] = {}
    for key in sorted(agent_configs):
        cfg = agent_configs.get(key) or {}
        groups.setdefault(
            (cfg.get("stance"), cfg.get("decision"), cfg.get("emotion")), []).append(key)

    problems, warns = [], []
    for (stance, decision, emotion), keys in groups.items():
        if len(keys) < 2:
            continue
        who = ", ".join(keys)
        combo = f"decision={decision!r} + emotion={emotion!r}"
        if stance:
            problems.append(
                f"agents {who} are indistinguishable: they share stance {stance!r} AND {combo}. "
                f"A pool larger than the scenario's stance set reuses stances on purpose, so give "
                f"at least one of them a different decision or emotion in info.jsonl."
            )
        else:
            warns.append(
                f"agents {who} share {combo} and have no stance, so their prompts are identical "
                f"and they can only repeat each other."
            )

    for w in warns:
        print(f"WARNING: {info_path}: {w}", file=sys.stderr)
    if problems:
        detail = "\n".join(f"  - {p}" for p in problems)
        print(f"ERROR: {info_path} defines duplicate agents:\n{detail}", file=sys.stderr)
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
# Agent turn output parser (message / rationale split)
# -------------------------------

RATIONALE_MAX_WORDS = 30

# A model refusal ("I'm sorry, I can't assist with that.") comes back as ordinary
# COMPLETED content, so generation metadata never flags it — only the text does.
# Seen live when the group had drifted into issuing a parent directives about
# their child. Publishing it verbatim breaks the fiction and tells the user
# nothing, so enforce_no_refusal() reframes and retries, then drops the turn.
_REFUSAL_RE = re.compile(
    r"^\W{0,3}(i'?m sorry|sorry|i apologi[sz]e|unfortunately)?\W{0,3}"
    r"(i\s+(can'?t|cannot|am not able to|won'?t)\s+"
    r"(assist|help|comply|do that|continue|provide)"
    r"|i'?m (unable|not able) to (assist|help|provide))"
    r"|抱歉[，,]?\s*我(不能|无法)|对不起[，,]?\s*我(不能|无法)",
    re.I)


def looks_like_refusal(text: str) -> bool:
    """True when a reply is a bare content refusal rather than a turn.

    Deliberately anchored near the start and length-bounded: an agent legitimately
    ARGUING that it cannot support an option ("I can't back Option A because...")
    is a real contribution and must not be caught.
    """
    t = (text or "").strip()
    if not t or len(t) > 220:
        return False
    return bool(_REFUSAL_RE.search(t[:120]))

# Tag names, including the translations the model produces on its own.
#
# WHY THE ALIASES: the system prompt orders "write every message in Chinese, do
# not switch language mid-message", and the model obeys it on the TAGS too,
# emitting [消息]/[理由] instead of [MESSAGE]/[RATIONALE]. Matching only the
# English spelling meant no match, which fell through to the "no tags" branch —
# and that branch only stripped English tags, so the ENTIRE generation, private
# rationale and both tag pairs included, was published as the chat message while
# the rationale log got nothing. Observed live in a zh parent_child session.
# The prompt now also says not to translate the tags; this is the recovery for
# when it happens anyway.
_MSG_NAMES = r"MESSAGE|MSG|消息|訊息|信息"
_RAT_NAMES = r"RATIONALE|REASON|理由|原因|理由说明"

_MESSAGE_TAG_RE = re.compile(rf"\[(?:{_MSG_NAMES})\](.*?)\[/(?:{_MSG_NAMES})\]",
                             re.DOTALL | re.IGNORECASE)
_RATIONALE_TAG_RE = re.compile(rf"\[(?:{_RAT_NAMES})\](.*?)\[/(?:{_RAT_NAMES})\]",
                               re.DOTALL | re.IGNORECASE)
_STRAY_TAG_RE = re.compile(rf"\[/?(?:{_MSG_NAMES}|{_RAT_NAMES})\]", re.IGNORECASE)
# Last resort for the no-tags branch: a rationale block that opened but never
# closed would otherwise stay in the chat message.
_TRAILING_RATIONALE_RE = re.compile(rf"\[(?:{_RAT_NAMES})\].*$", re.DOTALL | re.IGNORECASE)


def parse_agent_turn(raw: str) -> dict:
    """
    Splits one LLM generation into the chat-visible message and the private
    rationale. Both fields come from the SAME generation (never a second call).
    Tolerant by design: a malformed output must never crash a turn — if the
    tags are missing, the whole raw text becomes the message (stray tag tokens
    stripped so they can't leak into the chat log) and rationale stays empty.
    """
    raw = (raw or "").strip()
    msg_match = _MESSAGE_TAG_RE.search(raw)
    rat_match = _RATIONALE_TAG_RE.search(raw)

    if msg_match:
        message = msg_match.group(1).strip()
    else:
        # No usable MESSAGE block. Drop anything from an opening RATIONALE tag
        # onward first — otherwise a half-formed generation publishes the private
        # rationale — then clear any stray tag tokens from what is left.
        message = _STRAY_TAG_RE.sub("", _TRAILING_RATIONALE_RE.sub("", raw)).strip()

    rationale = rat_match.group(1).strip() if rat_match else ""
    words = rationale.split()
    if len(words) > RATIONALE_MAX_WORDS:
        rationale = " ".join(words[:RATIONALE_MAX_WORDS]) + "..."

    return {"message": message, "rationale": rationale}


def enforce_no_refusal(agent: "ChatAgent", messages: List[dict], parsed: dict, temp: float,
                       *, create_fn, model: str, max_output_tokens: int,
                       log_event=None, log_think=None) -> dict:
    """Catch a bare content refusal, reframe once, drop the turn if it holds."""
    txt = parsed.get("message", "")
    if not looks_like_refusal(txt):
        return parsed
    if log_event:
        log_event(agent.key, "refusal_detected", txt[:200])
    if log_think:
        log_think("refusal_retry", f"{agent.key}: refusal detected, reframing once")
    retry_messages = messages + [
        {"role": "assistant", "content": txt},
        {"role": "user", "content": (
            "That was a refusal, and it is not warranted here. This is a deliberation "
            "among assistants with assigned perspectives; nothing is being decided for "
            "anyone. The user makes the decision and is simply hearing the considerations "
            "out loud.\n"
            "Reply again, in character. Do not instruct the user to do anything and do not "
            "speak as if the matter is settled — state what your assigned perspective "
            "weighs, name the trade-off it sees, and leave the choice with the user. "
            "Keep the required [MESSAGE]/[RATIONALE] output format, tags in English."
        )},
    ]
    retry_raw = create_fn(retry_messages, min(temp + 0.1, 1.4), max_output_tokens)
    retry_parsed = parse_agent_turn(retry_raw)
    if retry_parsed.get("message") and not looks_like_refusal(retry_parsed["message"]):
        if log_think:
            log_think("refusal_retry", f"{agent.key}: reframed reply accepted")
        return retry_parsed
    if log_event:
        log_event(agent.key, "turn_dropped",
                  "refusal survived one reframing retry; agent stayed silent this turn")
    if log_think:
        log_think("refusal_retry", f"{agent.key}: still refusing — turn dropped")
    return {"message": "", "rationale": "", "dropped": True}


# -------------------------------
# @-mention parsing
#
# User-side mentions are a HARD route (the mentioned agents speak next, in
# order, bypassing Admin-1/2). Agent-side mentions are a SOFT cue: recorded to
# the rationale log only, never routed — Admin-1/2 still pick the next speaker.
# -------------------------------

MAX_MENTIONS_PER_MESSAGE = 4

def build_mention_patterns(agent_keys: List[str], name_map: Dict[str, str]) -> Dict[str, str]:
    """Maps every accepted @-alias (lowercased) to its canonical agent key:
    both the key itself (@A) and the display name (@ChatbotA)."""
    patterns: Dict[str, str] = {}
    for key in agent_keys:
        patterns[key.lower()] = key
        name = name_map.get(key)
        if name:
            patterns[name.lower()] = key
    return patterns


def parse_mentions(text: str, mention_patterns: Dict[str, str],
                   max_mentions: int = MAX_MENTIONS_PER_MESSAGE) -> List[str]:
    """Canonical agent keys @-mentioned in text, in order of first appearance,
    deduplicated, capped at max_mentions. Unknown names (@Z) are ignored."""
    found: List[str] = []
    for token in re.findall(r"@(\w+)", text or ""):
        key = mention_patterns.get(token.lower())
        if key and key not in found:
            found.append(key)
            if len(found) >= max_mentions:
                break
    return found

# -------------------------------
# Memory snippet distillation
# -------------------------------

# Fallback trigger: an agent gets a snippet at latest every N of its own
# speaking turns, even with no phase change or stall in between. The trigger
# decision itself is fully deterministic — the LLM is only used to write the
# snippet text once a trigger has fired.
DISTILL_TRIGGER_INTERVAL = 4

# -------------------------------
# Core loop
# -------------------------------

# -------------------------------
# Flask / HTTP turn API (shared scheduling core)
# -------------------------------

CreateFn = Callable[[Any, str, List[dict], float, int], str]


def run_user_turn(
    *,
    session: dict,
    user_message: str,
    agents: Dict[str, "ChatAgent"],
    agent_list: List["ChatAgent"],
    all_agent_names: List[str],
    client_chat,
    client_admin,
    scene: str,
    known_context: str = "",
    domain_background: str = "",
    session_memory_text: str = "",
    preloaded_knowledge_text: str = "",
    intake_data: Optional[dict] = None,
    scenario_type: Optional[str] = None,
    lang: str = "en",
    model: str = "gpt-4o",
    temperature: float = 0.8,
    max_output_tokens: int = 320,
    max_history_chars: int = 12000,
    max_user_gap: int = 12,
    max_agent_turns_before_user: Optional[int] = None,
    prefer_agents: Optional[float] = None,
    novelty_threshold: Optional[float] = None,
    novelty_window: int = 10,
    persist_chat: Optional[Callable[[dict], None]] = None,
    create_response_with_client: Optional[CreateFn] = None,
) -> Dict[str, Any]:
    """Run one user turn; mutate session; return API-shaped responses."""
    intake_data = intake_data or {}
    prefer = float(
        prefer_agents if prefer_agents is not None else os.getenv("AGORA_PREFER_AGENTS", "0.85")
    )
    nov_th = float(
        novelty_threshold
        if novelty_threshold is not None
        else os.getenv("AGORA_NOVELTY_THRESHOLD", "0.35")
    )

    key_to_agent = agents
    agent_keys = [a.key for a in agent_list]
    name_map = {a.key: a.name for a in agent_list}
    mention_patterns = build_mention_patterns(agent_keys, name_map)

    if max_agent_turns_before_user is None:
        max_consecutive = min(len(agent_keys) + 2, 8)
    else:
        max_consecutive = int(max_agent_turns_before_user)

    admin1_system, admin2_system = build_admin_prompts(agent_keys, max_consecutive)

    agent_configs = {
        slot: {
            "decision": (session.get("agent_runtime_config") or {}).get(slot, {}).get(
                "decision", "Rational"
            ),
            "emotion": (session.get("agent_runtime_config") or {}).get(slot, {}).get(
                "emotion", "Joy"
            ),
            "stance": (session.get("agent_runtime_config") or {}).get(slot, {}).get("stance"),
            "preloaded_knowledge": (
                (session.get("agora2_specs") or {}).get(slot) or {}
            ).get("preloaded_knowledge")
            or preloaded_knowledge_text
            or "",
        }
        for slot in agent_keys
    }

    moderator_state = session.setdefault(
        "moderator_state", {"mode": None, "state": "Exploration", "stall": False, "goal": ""}
    )
    session.setdefault("turns_in_current_state", 0)
    session.setdefault("turns_since_moderator", 0)
    session.setdefault("user_turns_since_moderator", 0)
    session.setdefault("user_spoke_since_moderator", False)
    session.setdefault("bots_since_user", 0)
    session.setdefault("has_spoken", {k: False for k in agent_keys})
    session.setdefault("mention_queue", [])
    session.setdefault("last_speaker_key", None)
    session.setdefault("memory_snippets", {k: [] for k in agent_keys})
    session.setdefault("turns_since_distill", {k: 0 for k in agent_keys})
    session.setdefault("latest_rationale", {k: "" for k in agent_keys})
    session.setdefault("latest_snippet_id", {k: None for k in agent_keys})
    session.setdefault("snippet_counters", {k: 0 for k in agent_keys})
    session.setdefault("agent_knowledge_hit_history", {k: [] for k in agent_keys})
    # Ensure keys exist even if session was created with a fixed A/B/C dict.
    for k in agent_keys:
        session["memory_snippets"].setdefault(k, [])
        session["turns_since_distill"].setdefault(k, 0)
        session["latest_rationale"].setdefault(k, "")
        session["latest_snippet_id"].setdefault(k, None)
        session["snippet_counters"].setdefault(k, 0)
        session["agent_knowledge_hit_history"].setdefault(k, [])

    stance_knowledge_data = load_stance_knowledge() if HAVE_STANCE_KNOWLEDGE else None

    transcript_lines = history_to_transcript_lines(session.get("history") or [])
    responses: List[dict] = []
    room_id = session.get("room_id")

    def _append_jsonl(fp, obj: dict) -> None:
        if fp is None:
            return
        import json

        fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fp.flush()

    def create(client, messages: List[dict], temp: float, max_tok: int, meta: Optional[dict] = None) -> str:
        if create_response_with_client is not None and client is not None:
            return create_response_with_client(client, model, messages, temp, max_tok) or ""
        return create_response(model, messages, temp, max_tok, meta=meta) or ""

    def log_thinking(character: str, txt: str) -> None:
        _append_jsonl(
            session.get("think_fp"),
            {"chat_room_id": room_id, "time": now_local_iso(), "character": character, "txt": txt},
        )

    def log_moderator(character: str, txt: str) -> None:
        _append_jsonl(
            session.get("moderator_fp"),
            {"chat_room_id": room_id, "time": now_local_iso(), "character": character, "txt": txt},
        )

    def log_agent_event(agent_key: str, event_type: str, detail: str) -> None:
        _append_jsonl(
            session.get("rationale_fp"),
            {
                "chat_room_id": room_id,
                "time": now_local_iso(),
                "agent": agent_key,
                "event": event_type,
                "detail": detail,
            },
        )

    def log_memory(record: dict) -> None:
        _append_jsonl(session.get("memory_fp"), record)

    def get_memory_context(agent_key: str, max_snippets: int = 3) -> str:
        snips = (session.get("memory_snippets") or {}).get(agent_key) or []
        snips = snips[-max_snippets:]
        if not snips:
            return ""
        lines = ["\n=== YOUR MEMORY (your own recent position snapshots, oldest first) ==="]
        lines += [f"- [{s['trigger']}] {s['content']}" for s in snips]
        lines.append(
            "Stay consistent with this trajectory unless you explicitly say you are revising it."
        )
        return "\n".join(lines)

    def maybe_distill_snippet(agent_key: str, last_message: str, stall_active: bool) -> None:
        """Rule-triggered in-session position snapshot (CLI-faithful)."""
        turns_since = session["turns_since_distill"]
        turns_since[agent_key] = int(turns_since.get(agent_key) or 0) + 1

        phase_changed = moderator_state.pop("_just_changed", False)
        if phase_changed:
            trigger = "phase_change"
        elif stall_active:
            trigger = "stall"
        elif turns_since[agent_key] >= DISTILL_TRIGGER_INTERVAL:
            trigger = "periodic"
        else:
            return

        source = (session.get("latest_rationale") or {}).get(agent_key) or last_message
        snippets = session["memory_snippets"][agent_key]
        parent = snippets[-1] if snippets else None

        prompt_lines = [
            f"Agent {agent_key} in a group deliberation (phase: {moderator_state['state']}) "
            f"just explained its last message with: \"{source}\"",
        ]
        if parent:
            prompt_lines.append(
                f"The agent's previously recorded position was: \"{parent['content']}\" — "
                f"state whether the new snapshot continues, refines, or reverses it."
            )
        prompt_lines.append(
            "Distill the agent's CURRENT position into 1-2 short sentences. "
            "Output only the distilled sentences, nothing else."
        )
        try:
            content = create(
                client_chat,
                [{"role": "user", "content": "\n".join(prompt_lines)}],
                0.3,
                60,
            ).strip()
        except Exception as e:
            log_thinking("memory_distill_error", f"{agent_key}: {e}")
            content = ""
        if not content:
            content = source

        session["snippet_counters"][agent_key] = int(session["snippet_counters"].get(agent_key) or 0) + 1
        snippet = {
            "id": f"snip_{agent_key}_{session['snippet_counters'][agent_key]:04d}",
            "agent_key": agent_key,
            "chat_room_id": room_id,
            "time": now_local_iso(),
            "content": content,
            "trigger": trigger,
            "parent_id": session["latest_snippet_id"].get(agent_key),
        }
        snippets.append(snippet)
        session["latest_snippet_id"][agent_key] = snippet["id"]
        turns_since[agent_key] = 0
        log_memory(snippet)

    def get_stance_block(agent_key: str) -> str:
        try:
            from stance import get_stance_text, stance_enabled

            if not scenario_type or not stance_enabled(scenario_type):
                return ""
            stance = agent_configs.get(agent_key, {}).get("stance")
            return get_stance_text(scenario_type, stance, lang) if stance else ""
        except Exception:
            return ""

    def get_phase_context(agent_key: str) -> str:
        s = moderator_state
        decision = agent_configs.get(agent_key, {}).get("decision", "Rational")
        mode = s.get("mode") or "S"
        lookup_state = "Convergence" if s.get("state") == CONCLUDED_STATE else s.get("state", "Exploration")
        assignment = get_phase_prompt(lookup_state, mode, decision, bool(s.get("stall")))
        lines = ["=== DELIBERATION STATE ==="]
        if s.get("mode"):
            lines.append(
                f"Mode: {'Selection' if mode == 'S' else 'Package'} | Phase: {s['state']}"
            )
        else:
            lines.append(f"Phase: {s['state']}")
        if s.get("goal"):
            lines.append(f"Current goal: {s['goal']}")
        lines.append(f"Your task this turn: {assignment}")
        budget = QUESTION_BUDGET.get(lookup_state)
        if budget and not s.get("stall") and s.get("state") != CONCLUDED_STATE:
            lines.append(budget)
        if known_context or domain_background:
            lines.append(
                "Anchor this message to the user's actual case: name at least one specific detail "
                "from KNOWN USER CONTEXT. A statement that would read the same for any user is not "
                "a contribution. Do not re-ask for anything already listed there as filled in."
            )
        recent = [ln for ln in transcript_lines[-6:] if not ln.lower().startswith("user:")]
        if len(recent) >= 4 and not any(has_disagreement(ln) for ln in recent):
            lines.append(
                "CONSENSUS WARNING: the last several messages contained no real disagreement. "
                "Before adding anything, state plainly where your stance differs from where the "
                "group is heading, and what that direction costs the interest you represent."
            )
        try:
            from stance import get_convergence_weight_hint

            if lookup_state == "Convergence":
                stance = agent_configs.get(agent_key, {}).get("stance")
                weight_hint = get_convergence_weight_hint(scenario_type, intake_data, stance, lang)
                if weight_hint:
                    lines.append(f"Stance weighting for this closing stage: {weight_hint}")
        except Exception:
            pass

        # Stance Knowledge — DYNAMIC channel + related_cards A-OR-B expand
        # (repeat hit of same card, or Convergence / Concluded).
        if HAVE_STANCE_KNOWLEDGE and stance_knowledge_data:
            stance = agent_configs.get(agent_key, {}).get("stance")
            li = last_user_index(transcript_lines)
            last_user_message = (
                transcript_lines[li].split(":", 1)[1].strip() if li is not None else ""
            )
            sk_block = resolve_dynamic_stance_knowledge(
                scenario_type=scenario_type,
                stance=stance,
                last_user_message=last_user_message,
                lang=lang,
                knowledge=stance_knowledge_data,
                hit_history=session["agent_knowledge_hit_history"],
                agent_key=agent_key,
                deliberation_state=lookup_state,
            )
            if sk_block:
                lines.append(sk_block)
        return "\n".join(lines)

    def append_agent(agent: "ChatAgent", txt: str) -> None:
        txt = sanitize_single_message(txt, agent.name, all_agent_names)
        msg = {
            "chat_room_id": room_id,
            "time": now_local_iso(),
            "character": agent.name,
            "txt": txt,
        }
        session.setdefault("history", []).append(msg)
        _append_jsonl(session.get("chat_fp"), msg)
        if persist_chat:
            persist_chat(msg)
        transcript_lines.append(f"{agent.name}: {txt}")
        responses.append({"agent_key": agent.key, "agent": agent.name, "message": txt})
        session.setdefault("has_spoken", {})[agent.key] = True
        agent.spoke += 1

    def run_moderator(allow_state_change: bool = True) -> None:
        history = clamp_history(transcript_lines, max_history_chars)
        roles_summary = build_roles_summary(agent_list)
        turns_in_state = int(session.get("turns_in_current_state") or 0)
        stall_eligible = turns_in_state > MODERATOR_STALL_TURNS
        had_user_input = bool(session.get("user_spoke_since_moderator"))
        session["turns_since_moderator"] = 0
        session["user_turns_since_moderator"] = 0
        session["user_spoke_since_moderator"] = False

        reported_state = (
            "Convergence"
            if moderator_state.get("state") == CONCLUDED_STATE
            else moderator_state.get("state", "Exploration")
        )
        stall_hint = (
            f"The conversation has been in '{reported_state}' state for "
            f"{turns_in_state} agent turns."
            + ("" if stall_eligible else " Do NOT set stall: true — not enough turns yet.")
        )
        msgs = [
            {"role": "system", "content": ADMIN3_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"=== SCENE ===\n{scene}\n\n"
                    f"=== AGENT PERSONALITIES ===\n{roles_summary}\n\n"
                    f"=== CURRENT STATE ===\n{reported_state}\n"
                    f"{stall_hint}\n\n"
                    f"=== TRANSCRIPT ===\n{history}\n"
                ),
            },
        ]
        raw = create(client_admin, msgs, 0.0, 300)
        log_moderator("admin3_moderator", raw or "")
        parsed = parse_moderator_plan(raw or "")
        if not parsed:
            return

        prev_state = moderator_state.get("state")
        if not allow_state_change and parsed["state"] != prev_state:
            log_moderator(
                "admin3_state_change_suppressed",
                f"{prev_state} -> {parsed['state']} withheld: stall re-check only, "
                f"no user input since the last classification.",
            )
            parsed = dict(parsed)
            parsed["state"] = prev_state

        if (
            parsed["state"] == "Convergence"
            and prev_state in ("Convergence", CONCLUDED_STATE)
            and not had_user_input
        ):
            parsed = dict(parsed)
            parsed["state"] = CONCLUDED_STATE
            parsed["stall"] = False
            parsed["goal"] = (
                "The group has converged. Stop discussing; the floor is the "
                "user's until they confirm, object, or raise something new."
            )

        moderator_state.update(parsed)
        # One-shot phase-change signal for memory distillation (consumed via .pop()).
        moderator_state["_just_changed"] = parsed["state"] != prev_state
        if parsed["state"] != prev_state:
            session["turns_in_current_state"] = 0
            log_moderator(
                "admin3_state_change",
                f"{prev_state} -> {parsed['state']}  |  {parsed['goal']}",
            )
            if parsed["state"] == CONCLUDED_STATE:
                log_moderator(
                    "admin3_concluded",
                    "Converged twice with no user input in between — discussion closed, "
                    "floor returns to the user.",
                )
        elif parsed["stall"] and stall_eligible:
            log_moderator(
                "admin3_stall",
                f"Stall in state={parsed['state']} after {session.get('turns_in_current_state')} turns | {parsed['goal']}",
            )
        if not stall_eligible or parsed["state"] != prev_state:
            moderator_state["stall"] = False

    def maybe_run_moderator() -> None:
        user_turns = int(session.get("user_turns_since_moderator") or 0)
        any_turns = int(session.get("turns_since_moderator") or 0)
        due_user = user_turns >= MODERATOR_USER_TURN_INTERVAL
        due_fallback = (not session.get("user_spoke_since_moderator")) and (
            any_turns >= MODERATOR_TURN_FALLBACK
        )
        stalling = (
            int(session.get("turns_in_current_state") or 0) > MODERATOR_STALL_TURNS
            and any_turns >= MODERATOR_STALL_RECHECK
        )
        if due_user or due_fallback or stalling:
            # Stall-only recheck must not advance phase (CLI semantics).
            allow = due_user or due_fallback
            run_moderator(allow_state_change=allow)

    def enforce_novelty(agent: "ChatAgent", messages: List[dict], parsed: dict, temp: float) -> dict:
        txt = parsed.get("message") or ""
        if nov_th <= 0 or not transcript_lines or not txt:
            return parsed
        prior = transcript_lines[-novelty_window:]
        ratio = novelty_ratio(txt, prior)
        if ratio >= nov_th:
            return parsed
        log_thinking(
            "novelty_retry",
            f"{agent.key}: novelty={ratio:.2f} < {nov_th:.2f}, retrying once",
        )
        retry_messages = messages + [
            {"role": "assistant", "content": txt},
            {
                "role": "user",
                "content": (
                    "That message restates points the group already has on the table and adds nothing new. "
                    "Replace it entirely.\n"
                    "Contribute exactly one of: a new evaluation dimension, a specific fact from KNOWN USER "
                    "CONTEXT that nobody has cited yet, a concrete comparison of two options along one named "
                    "dimension, an elimination with its reason, or a direct challenge to a specific claim "
                    "someone made.\n"
                    "If you genuinely have nothing new, reply with one short sentence saying so and naming "
                    "whose point you are deferring to. Either way, do not ask a question this time. "
                    "Keep the required [MESSAGE]/[RATIONALE] output format."
                ),
            },
        ]
        retry_raw = create(client_chat, retry_messages, min(temp + 0.15, 1.4), max_output_tokens)
        retry_parsed = parse_agent_turn(retry_raw)
        retry_ratio = (
            novelty_ratio(retry_parsed["message"], prior) if retry_parsed.get("message") else 0.0
        )
        if retry_ratio >= nov_th:
            log_thinking("novelty_retry", f"{agent.key}: retry novelty={retry_ratio:.2f} (kept)")
            return retry_parsed
        log_thinking(
            "novelty_retry",
            f"{agent.key}: retry novelty={retry_ratio:.2f}, still below {nov_th:.2f} — turn dropped",
        )
        return {"message": "", "rationale": "", "dropped": True}

    def stall_burst(trigger_key: Optional[str] = None) -> None:
        stall_temp = min(temperature + 0.25, 1.4)
        burst_agents = [a for a in agent_list if a.key != trigger_key][:MAX_STALL_BURST_TURNS]
        log_thinking(
            "stall_burst",
            f"Forcing {'->'.join(a.key for a in burst_agents)} burst at temp={stall_temp:.2f} "
            f"(exempt from the consecutive-turn valve by design)",
        )
        for burst_agent in burst_agents:
            session["bots_since_user"] = int(session.get("bots_since_user") or 0) + 1
            session["turns_in_current_state"] = int(session.get("turns_in_current_state") or 0) + 1
            session["turns_since_moderator"] = int(session.get("turns_since_moderator") or 0) + 1
            history = clamp_history(transcript_lines, max_history_chars)
            phase_context = get_phase_context(burst_agent.key)
            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "The moderator has flagged a stall — the group is going in circles.\n"
                "You MUST make a decisive move: propose something new, force a comparison, "
                "ask a direct question that demands an answer, or take a clear position.\n"
                "Do NOT repeat what has already been said.\n\n"
                f"{history}"
            )
            pk = agent_configs.get(burst_agent.key, {}).get("preloaded_knowledge") or ""
            messages = [
                {
                    "role": "system",
                    "content": burst_agent.system_prompt(
                        scene,
                        name_map,
                        phase_context,
                        known_context=known_context,
                        domain_background=domain_background,
                        stance_text=get_stance_block(burst_agent.key),
                        lang=lang,
                        session_memory_text=session_memory_text,
                        preloaded_knowledge_text=pk,
                    )
                    + get_memory_context(burst_agent.key),
                },
                {"role": "user", "content": user_prompt},
            ]
            raw = create(client_chat, messages, stall_temp, max_output_tokens)
            parsed = parse_agent_turn(raw)
            txt = parsed.get("message") or "…"
            if parsed.get("rationale"):
                session["latest_rationale"][burst_agent.key] = parsed["rationale"]
                log_agent_event(burst_agent.key, "rationale", parsed["rationale"])
            agent_mentions = parse_mentions(txt, mention_patterns)
            if agent_mentions:
                log_agent_event(
                    burst_agent.key,
                    "agent_mention",
                    f"{burst_agent.key} mentioned {agent_mentions} "
                    f"(soft cue, not routed, admin still decides next speaker)",
                )
            append_agent(burst_agent, txt)
            session["last_speaker_key"] = burst_agent.key
            maybe_distill_snippet(burst_agent.key, txt, stall_active=True)
        moderator_state["stall"] = False

    def agent_turn(
        agent: "ChatAgent", force_intro: bool = False, mention_trigger: bool = False
    ) -> None:
        session["last_speaker_key"] = agent.key
        session["bots_since_user"] = int(session.get("bots_since_user") or 0) + 1
        session["turns_in_current_state"] = int(session.get("turns_in_current_state") or 0) + 1
        session["turns_since_moderator"] = int(session.get("turns_since_moderator") or 0) + 1
        stall_triggered = bool(moderator_state.get("stall"))
        history = clamp_history(transcript_lines, max_history_chars)
        extra = ""
        if force_intro:
            extra = f"\n\n(Important) This is your FIRST message. Start with: Hi, I'm {agent.name}"
        effective_temp = temperature
        if stall_triggered:
            effective_temp = min(temperature + 0.25, 1.4)
        phase_context = get_phase_context(agent.key)
        if mention_trigger:
            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "Each line is formatted as: Speaker: message\n"
                "The user just mentioned YOU by name in their last message. "
                "Respond to the user directly first — address what they asked or said to you — "
                "before anything else. Stay in character.\n\n"
                f"{history}\n{extra}"
            )
        else:
            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "Each line is formatted as: Speaker: message\n"
                "Continue the conversation as your character.\n"
                "Try to keep a lively group dynamic by engaging other bots (react, ask them questions, build on their points), "
                "while still keeping the user included.\n\n"
                f"{history}\n{extra}"
            )
        pk = agent_configs.get(agent.key, {}).get("preloaded_knowledge") or ""
        messages = [
            {
                "role": "system",
                "content": agent.system_prompt(
                    scene,
                    name_map,
                    phase_context,
                    known_context=known_context,
                    domain_background=domain_background,
                    stance_text=get_stance_block(agent.key),
                    lang=lang,
                    session_memory_text=session_memory_text,
                    preloaded_knowledge_text=pk,
                )
                + get_memory_context(agent.key),
            },
            {"role": "user", "content": user_prompt},
        ]
        raw = create(client_chat, messages, effective_temp, max_output_tokens)
        parsed = parse_agent_turn(raw)
        parsed = enforce_no_refusal(
            agent,
            messages,
            parsed,
            effective_temp,
            create_fn=lambda msgs, t, mt: create(client_chat, msgs, t, mt),
            model=model,
            max_output_tokens=max_output_tokens,
            log_event=log_agent_event,
            log_think=log_thinking,
        )
        if not parsed.get("dropped"):
            parsed = enforce_novelty(agent, messages, parsed, effective_temp)
        if parsed.get("dropped"):
            log_agent_event(
                agent.key,
                "turn_dropped",
                "refusal or novelty guard rejected the turn; "
                "agent stayed silent this turn",
            )
            maybe_run_moderator()
            return
        txt = parsed.get("message") or "…"
        if parsed.get("rationale"):
            session["latest_rationale"][agent.key] = parsed["rationale"]
            log_agent_event(agent.key, "rationale", parsed["rationale"])
        agent_mentions = parse_mentions(txt, mention_patterns)
        if agent_mentions:
            log_agent_event(
                agent.key,
                "agent_mention",
                f"{agent.key} mentioned {agent_mentions} "
                f"(soft cue, not routed, admin still decides next speaker)",
            )
        append_agent(agent, txt)
        maybe_distill_snippet(agent.key, txt, stall_active=stall_triggered)
        if stall_triggered:
            stall_burst(trigger_key=agent.key)
        maybe_run_moderator()

    def admin_choose_next() -> str:
        consecutive = int(session.get("bots_since_user") or 0)
        if consecutive >= max_consecutive:
            log_thinking(
                "admin_rule",
                f"Force U: consecutive_agent_turns >= {max_consecutive}",
            )
            return "U"
        li = last_user_index(transcript_lines)
        gap = (len(transcript_lines) - 1 - li) if li is not None else len(transcript_lines)
        if gap >= max_user_gap:
            log_thinking("admin_rule", f"Force U: user gap {gap} >= max_user_gap {max_user_gap}")
            return "U"

        history = clamp_history(transcript_lines, max_history_chars)
        roles_summary = build_roles_summary(agent_list)
        last_speaker_key = session.get("last_speaker_key")
        spoke_counts = ", ".join(f"{k}={key_to_agent[k].spoke}" for k in agent_keys)
        stats = (
            f"Spoke counts: {spoke_counts}. "
            f"Consecutive agent turns={consecutive}. "
            f"User gap(lines)={gap}. "
            f"Moderator state={moderator_state['state']}."
        )
        admin1_messages = [
            {"role": "system", "content": admin1_system},
            {
                "role": "user",
                "content": (
                    f"=== SCENE ===\n{scene}\n\n"
                    f"=== ROLES ===\n{roles_summary}\n\n"
                    f"=== STATS ===\n{stats}\n\n"
                    f"=== TRANSCRIPT (Speaker: message) ===\n{history}\n\n"
                    f"Decide NEXT."
                ),
            },
        ]
        admin1_out = create(client_admin, admin1_messages, 0.2, 260)
        log_thinking("admin1", admin1_out or "")
        admin2_messages = [
            {"role": "system", "content": admin2_system},
            {"role": "user", "content": admin1_out or ""},
        ]
        admin2_out = (create(client_admin, admin2_messages, 0.0, MIN_OUTPUT_TOKENS) or "").strip().upper()
        log_thinking("admin2", admin2_out)

        def eligible() -> List[str]:
            pool = [k for k in agent_keys if k != last_speaker_key]
            return pool or list(agent_keys)

        if admin2_out not in set(agent_keys) | {"U"}:
            pick = random.choice(eligible())
            log_thinking("admin_fallback", f"Invalid admin2_out={admin2_out!r}, fallback to {pick}")
            admin2_out = pick

        if admin2_out == "U":
            if random.random() < prefer:
                pick = random.choice(eligible())
                log_thinking("admin_bias", f"Override U -> {pick} (prefer_agents={prefer})")
                return pick
            return "U"

        if admin2_out == last_speaker_key:
            pick = random.choice(eligible())
            if pick != admin2_out:
                log_thinking(
                    "admin_no_repeat",
                    f"Admin re-picked {admin2_out} (just spoke) -> rerouted to {pick}",
                )
                return pick
        return admin2_out

    # --- user message already appended by Flask caller ---
    session["bots_since_user"] = 0
    session["last_speaker_key"] = None
    session["user_turn_count"] = int(session.get("user_turn_count") or 0) + 1
    session["turns_since_moderator"] = int(session.get("turns_since_moderator") or 0) + 1
    session["user_turns_since_moderator"] = int(session.get("user_turns_since_moderator") or 0) + 1
    session["user_spoke_since_moderator"] = True

    if moderator_state.get("state") == CONCLUDED_STATE:
        moderator_state["state"] = "Convergence"
        moderator_state["goal"] = ""
        log_moderator(
            "admin3_reopened",
            "User spoke after Concluded — back to Convergence for re-classification.",
        )

    mentioned = parse_mentions(user_message or "", mention_patterns)
    if mentioned:
        q = session.setdefault("mention_queue", [])
        q.extend(mentioned)
        log_agent_event(
            "user",
            "mention_override",
            f"user mentioned {mentioned}; queued for hard-routed replies",
        )

    maybe_run_moderator()

    # Burst: mention hard-route (bypasses consecutive valve, CLI-faithful),
    # then Admin picks until U / Concluded / safety bound.
    safety = max_consecutive + MAX_MENTIONS_PER_MESSAGE + MAX_STALL_BURST_TURNS + 4
    for _ in range(safety):
        mq = session.get("mention_queue") or []
        if mq:
            key = mq.pop(0)
            session["mention_queue"] = mq
            if key not in key_to_agent:
                continue
            log_agent_event(
                key,
                "mention_dispatch",
                f"hard-routing {key} to speak (from user mention queue, "
                f"admin selection skipped)",
            )
            force_intro = not bool((session.get("has_spoken") or {}).get(key))
            agent_turn(key_to_agent[key], force_intro=force_intro, mention_trigger=True)
            if moderator_state.get("state") == CONCLUDED_STATE:
                break
            continue

        if moderator_state.get("state") == CONCLUDED_STATE:
            break

        nxt = admin_choose_next()
        if nxt == "U":
            break
        if nxt not in key_to_agent:
            break
        force_intro = not bool((session.get("has_spoken") or {}).get(nxt))
        agent_turn(key_to_agent[nxt], force_intro=force_intro)
        if moderator_state.get("state") == CONCLUDED_STATE:
            break

    phase = moderator_state.get("state", "Exploration")
    concluded = phase == CONCLUDED_STATE
    return {
        "responses": responses,
        "phase": phase,
        "stall": bool(moderator_state.get("stall")),
        "concluded": concluded,
        "moderator_state": dict(moderator_state),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default=None,
                    help="Path to scene description file. If omitted and --scenario_type is set, "
                         "auto-resolves to scenes/{scenario_type}_{lang}.txt. If omitted with no "
                         "--scenario_type, falls back to ./scene.txt (legacy default).")
    ap.add_argument("--scenes_dir", default="scenes",
                    help="Folder holding per-scenario, per-language scene files. Default: ./scenes")
    ap.add_argument("--info", default="info.jsonl", help="Path to info.jsonl (agent emotion+decision type names)")
    ap.add_argument("--bot1", default="chatbot1.txt", help="Path to chatbot1.txt (A) — legacy, only valid when agent keys are exactly A/B/C")
    ap.add_argument("--bot2", default="chatbot2.txt", help="Path to chatbot2.txt (B) — legacy, only valid when agent keys are exactly A/B/C")
    ap.add_argument("--bot3", default="chatbot3.txt", help="Path to chatbot3.txt (C) — legacy, only valid when agent keys are exactly A/B/C")
    ap.add_argument("--roles-dir", dest="roles_dir", default=None,
                    help="Folder holding one role file per agent key, named {KEY}.txt (A.txt, B.txt, "
                         "D.txt, ...). The agent key set itself always comes from info.jsonl's "
                         "\"agents\" field. Default: ./roles (used automatically when the key set "
                         "is not exactly A/B/C)")
    ap.add_argument("--start_order", default="ABCU", help="Chars from the agent key set plus U, default ABCU")
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--max_output_tokens", type=int, default=320,
                    help="Raised from 220 once agents had to emit [MESSAGE] plus [RATIONALE] in one "
                         "generation: in logs/316347 two thirds of turns ran out of budget before "
                         "the rationale block (one message was cut off mid-sentence). Watch for "
                         "TRUNCATED in the rationale log if you lower it. Default 320")
    ap.add_argument("--max_history_chars", type=int, default=12000)
    ap.add_argument("--log_dir", default="logs", help="Directory to write jsonl logs")
    ap.add_argument("--prefer_agents", type=float, default=0.85,
                    help="Probability to override Admin output to an agent when it picks U (0..1). Default 0.85")
    ap.add_argument("--max_user_gap", type=int, default=12,
                    help="Force U if user hasn't spoken in this many transcript lines. Default 12")

    # ---- Message quality guards ----
    ap.add_argument("--novelty_threshold", type=float, default=0.5,
                    help="If a reply's share of content words unseen in the recent transcript falls "
                         "below this, the agent gets one corrective retry (one extra API call); if "
                         "the retry still misses the bar the turn is DROPPED and the agent stays "
                         "silent. 0 disables the check. Calibrated on logs/442575: clear "
                         "restatements scored 0.19-0.44, genuine contributions 0.55-0.69. Raised "
                         "from 0.35 to 0.5 after logs/316347. Note the bigger change is the drop "
                         "rule: retries used to be kept merely for scoring better than the "
                         "original (0.52 > 0.00 was 'kept'), independently of this threshold. "
                         "Default 0.5")
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
        print("ERROR: No API key. Set the OPENAI_API_KEY environment variable.", file=sys.stderr)
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

    # The agent key set — and therefore the pool size — comes from info.jsonl's
    # "agents" field alone. Nothing below is allowed to hardcode agent count.
    agent_keys: List[str] = sorted(agent_configs.keys())
    is_legacy_abc = set(agent_keys) == {"A", "B", "C"}

    def _load_roles_from_dir(roles_dir: str) -> Dict[str, str]:
        missing = [k for k in agent_keys
                   if not os.path.exists(os.path.join(roles_dir, f"{k}.txt"))]
        if missing:
            print(f"ERROR: info.jsonl defines agent keys {agent_keys}, but role file(s) "
                  f"{', '.join(os.path.join(roles_dir, k + '.txt') for k in missing)} "
                  f"do not exist. Each key needs a {{KEY}}.txt in --roles-dir.", file=sys.stderr)
            sys.exit(2)
        return {k: read_text(os.path.join(roles_dir, f"{k}.txt")) for k in agent_keys}

    # Role-text source, resolved by deterministic priority:
    #   1. --assemble_roles       -> spliced from decision/emotion presets (any key set)
    #   2. explicit --roles-dir   -> {roles_dir}/{KEY}.txt per key
    #   3. keys exactly {A,B,C}   -> legacy --bot1/2/3 files (backward compatible default)
    #   4. otherwise              -> default ./roles dir; a clear startup error if absent
    role_texts: Dict[str, str] = {}
    if args.assemble_roles and HAVE_AGENT_ASSEMBLY:
        specs = build_all_agent_specs(
            agent_configs,
            scenario_type=args.scenario_type,
            lang=args.lang,
            decision_dir=args.decision_dir,
            emotion_dir=args.emotion_dir,
        )
        role_texts = {k: specs[k]["role_text"] for k in agent_keys}
    else:
        if args.assemble_roles:
            print("WARNING: --assemble_roles was set but agent_assembly.py could not be imported; "
                  "falling back to role files.", file=sys.stderr)
        if args.roles_dir is not None:
            role_texts = _load_roles_from_dir(args.roles_dir)
        elif is_legacy_abc:
            role_texts = {
                "A": safe_read_text(args.bot1, default="(chatbot1.txt missing)"),
                "B": safe_read_text(args.bot2, default="(chatbot2.txt missing)"),
                "C": safe_read_text(args.bot3, default="(chatbot3.txt missing)"),
            }
        elif os.path.isdir("roles"):
            role_texts = _load_roles_from_dir("roles")
        else:
            print(f"ERROR: info.jsonl defines agent keys {agent_keys}. The legacy --bot1/2/3 "
                  f"path only supports exactly A/B/C; use --roles-dir with one {{KEY}}.txt "
                  f"file per key instead.", file=sys.stderr)
            sys.exit(2)

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

    # Stance Knowledge base: load the per-scenario keyword cards once here and
    # reuse across every turn (never re-read per turn). None when the module is
    # unavailable; get_stance_knowledge_block() is a no-op in that case.
    stance_knowledge_data = load_stance_knowledge() if HAVE_STANCE_KNOWLEDGE else None

    # Cross-session memory (read side): pull the last few sessions for this
    # user_id + scenario_type and build the recap block injected into every
    # agent's system prompt this session. Empty in legacy runs (no scenario_type)
    # or on the first-ever session for this pair. The write side runs at shutdown.
    session_memory_text = ""
    if HAVE_SESSION_MEMORY and args.scenario_type:
        recent_sessions = load_recent_sessions(args.user_id, args.scenario_type, limit=3)
        session_memory_text = build_session_memory_text(recent_sessions, args.lang)

    # Stance: forced binding, overrides whatever (if anything) info.jsonl had.
    # Scenario types not in stance.STANCE_ASSIGNMENTS simply get no stance —
    # agent_configs[key]["stance"] stays unset and the block is skipped.
    if HAVE_STANCE and stance_enabled(args.scenario_type):
        for key in agent_keys:
            agent_configs[key]["stance"] = assign_stance(args.scenario_type, key, list(agent_configs))
    elif args.scenario_type and not HAVE_STANCE:
        print("WARNING: --scenario_type was set but stance.py could not be imported; "
              "continuing without the stance dimension.", file=sys.stderr)

    # Runs here, not in validate_agent_configs, because it keys on the stance.
    validate_persona_uniqueness(agent_configs, args.info)

    # Stance Knowledge — PRELOADED channel: each agent's optional info.jsonl
    # `hint` is matched against the knowledge base ONCE here, and the matched card
    # body becomes that agent's fixed, whole-session background (body only — the
    # distinct "=== BACKGROUND (from setup) ===" header is added in system_prompt).
    # A missing/empty hint, or one that hits no keyword, stores "" (no fallback).
    # This is a separate channel from the per-turn dynamic trigger above.
    for key in agent_keys:
        hint = agent_configs.get(key, {}).get("hint")
        agent_configs[key]["preloaded_knowledge"] = stance_knowledge_on_hit(
            args.scenario_type, agent_configs[key].get("stance"),
            hint, args.lang, stance_knowledge_data, include_header=False,
        ) if hint else ""

    agents: List[ChatAgent] = [
        ChatAgent(k, f"Chatbot{k}", role_texts[k]) for k in agent_keys
    ]
    key_to_agent = {a.key: a for a in agents}
    name_map = {a.key: a.name for a in agents}

    # Hard "pull the user back in" threshold, scaled to the pool size: with more
    # agents a longer bot-to-bot stretch is natural, capped so the user is never
    # sidelined for long. Must be computed after agent_keys is known.
    MAX_CONSECUTIVE_AGENT_TURNS = min(len(agent_keys) + 2, 8)
    admin1_system, admin2_system = build_admin_prompts(agent_keys, MAX_CONSECUTIVE_AGENT_TURNS)

    chat_room_id = f"{random.randint(0, 999999):06d}"
    os.makedirs(args.log_dir, exist_ok=True)
    # Log file layout:
    #   {room}.jsonl            chat transcript                       (unchanged)
    #   {room}_thinking.jsonl   admin1/admin2 reasoning traces        (unchanged)
    #   {room}_moderator.jsonl  admin3 state classification           (unchanged)
    #   {room}_rationale.jsonl  per-agent rationale + mention events  (new)
    #   {room}_memory.jsonl     memory snippet chains                 (new)
    chat_path = os.path.join(args.log_dir, f"{chat_room_id}.jsonl")
    thinking_path = os.path.join(args.log_dir, f"{chat_room_id}_thinking.jsonl")
    moderator_path = os.path.join(args.log_dir, f"{chat_room_id}_moderator.jsonl")
    rationale_path = os.path.join(args.log_dir, f"{chat_room_id}_rationale.jsonl")
    memory_path = os.path.join(args.log_dir, f"{chat_room_id}_memory.jsonl")

    transcript_lines: List[str] = []
    consecutive_agent_turns = 0
    # Key of the agent that most recently held the floor (published OR dropped);
    # reset to None when the user speaks. admin_choose_next() excludes it so the
    # same agent is never handed the floor twice in a row — otherwise a random
    # override (prefer_agents / fallback) could re-pick the agent that just spoke,
    # whose second turn is a restatement the novelty guard then drops.
    last_speaker_key: Optional[str] = None
    turns_since_moderator = 0        # turns of any kind since the last moderator run (backstop)
    user_turns_since_moderator = 0   # user turns since the last moderator run (primary trigger)
    turns_in_current_state = 0       # stall detection: turns since last state change
    user_spoke_since_moderator = False  # did the user contribute between the last two runs?

    # Moderator state (assignments now come from PHASE_PROMPTS lookup, not LLM)
    moderator_state = {
        "mode":  None,
        "state": "Exploration",
        "stall": False,
        "goal":  "",
    }

    # Memory snippet chains: one independent LINEAR chain per agent (not a
    # tree) — each new snippet's parent_id points at that agent's previous one.
    snippet_counters: Dict[str, int] = {k: 0 for k in agent_keys}
    turns_since_distill: Dict[str, int] = {k: 0 for k in agent_keys}
    latest_snippet_id: Dict[str, Optional[str]] = {k: None for k in agent_keys}
    latest_rationale: Dict[str, str] = {k: "" for k in agent_keys}
    memory_snippets: Dict[str, List[dict]] = {k: [] for k in agent_keys}

    # Per-agent history of stance-knowledge card_ids hit this session. When the
    # DYNAMIC channel matches a topic card against the user's latest message, its
    # card_id is appended here. A repeat hit of the same card is one of the two
    # triggers (the other being the Convergence phase) for expanding one-hop
    # related cards.
    agent_knowledge_hit_history: Dict[str, List[str]] = {k: [] for k in agent_keys}

    # User @-mention hard routing: keys queued here speak next, in order,
    # before Admin-1/2 get to choose again.
    mention_patterns = build_mention_patterns(agent_keys, name_map)
    mention_queue: List[str] = []

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

    def log_generation_meta(agent_key: str, meta: dict, raw: str = "", note: str = ""):
        """
        Record why a generation ended the way it did. A run once produced the
        bare string "I'm sorry, I can't assist with that." as a chat message
        with no way to tell a content filter from a truncation; status /
        incomplete_reason / refusal answer that. Also flags truncation, which
        silently eats the [RATIONALE] block when max_output_tokens is too low.
        """
        summary = format_generation_meta(meta)
        flags = []
        if meta.get("refusal"):
            flags.append("REFUSAL")
        if meta.get("incomplete_reason") == "max_output_tokens":
            flags.append("TRUNCATED(raise --max_output_tokens)")
        if raw and "[/MESSAGE]" not in raw:
            flags.append("NO_CLOSING_MESSAGE_TAG")
        if not summary and not flags:
            return
        detail = " | ".join(p for p in (note, summary, " ".join(flags)) if p)
        log_agent_event(agent_key, "generation_meta", detail)

    def log_agent_event(agent_key: str, event_type: str, detail: str):
        """event_type ∈ {"rationale", "agent_mention", "mention_override",
        "mention_dispatch", "generation_meta", "turn_dropped"}"""
        record = {
            "chat_room_id": chat_room_id,
            "time": now_local_iso(),
            "agent": agent_key,
            "event": event_type,
            "detail": detail,
        }
        write_jsonl_line(rationale_fp, record)

    def log_memory(record: dict):
        write_jsonl_line(memory_fp, record)

    def get_phase_context(agent_key: str) -> str:
        s = moderator_state
        decision = agent_configs[agent_key]["decision"]
        mode = s["mode"] or "S"  # default to Selection until mode is determined
        # Concluded has no PHASE_PROMPTS rows of its own — an agent only speaks
        # in that state when the user forces it (/next or an @-mention), and
        # Convergence is the right brief for that.
        lookup_state = "Convergence" if s["state"] == CONCLUDED_STATE else s["state"]
        assignment = get_phase_prompt(lookup_state, mode, decision, s["stall"])
        lines = ["=== DELIBERATION STATE ==="]
        if s["mode"]:
            lines.append(f"Mode: {'Selection' if mode == 'S' else 'Package'} | Phase: {s['state']}")
        else:
            lines.append(f"Phase: {s['state']}")
        if s["goal"]:
            lines.append(f"Current goal: {s['goal']}")
        lines.append(f"Your task this turn: {assignment}")

        budget = QUESTION_BUDGET.get(lookup_state)
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

        # Stance Knowledge — DYNAMIC channel: keyword-triggered card for this
        # agent's stance, matched against the user's LATEST message and re-checked
        # every turn. Independent of the session-start preloaded hint channel
        # (=== BACKGROUND (from setup) ===); both can appear in one prompt.
        #
        # One-hop related_cards expansion (the [相关背景] block) is switched on when
        # EITHER trigger fires:
        #   A. this agent hit this SAME card earlier this session (repeat hit), or
        #   B. the deliberation is in the Convergence phase.
        # Otherwise only the single matched card is shown (include_related=False).
        if HAVE_STANCE_KNOWLEDGE and stance_knowledge_data:
            stance = agent_configs.get(agent_key, {}).get("stance")
            li = last_user_index(transcript_lines)
            last_user_message = (
                transcript_lines[li].split(":", 1)[1].strip() if li is not None else ""
            )
            sk_block = resolve_dynamic_stance_knowledge(
                scenario_type=args.scenario_type,
                stance=stance,
                last_user_message=last_user_message,
                lang=args.lang,
                knowledge=stance_knowledge_data,
                hit_history=agent_knowledge_hit_history,
                agent_key=agent_key,
                deliberation_state=s["state"],
            )
            if sk_block:
                lines.append(sk_block)
        return "\n".join(lines)

    def get_stance_block(agent_key: str) -> str:
        if not HAVE_STANCE:
            return ""
        stance = agent_configs.get(agent_key, {}).get("stance")
        return get_stance_text(args.scenario_type, stance, args.lang)

    def maybe_distill_snippet(agent_key: str, last_message: str, stall_active: bool):
        """
        Called once after every agent utterance. The DECISION to distill is
        purely rule-based (no LLM guessing "should I remember this"); the LLM
        is only invoked to write the 1-2 sentence snippet once a trigger fires:
          1. phase_change : the moderator just moved the deliberation state
          2. stall        : this utterance happened under an active stall
          3. periodic     : fallback, every DISTILL_TRIGGER_INTERVAL utterances
        """
        turns_since_distill[agent_key] += 1

        # One-shot consumption via .pop(): a plain read would leave the flag
        # True until the next run_moderator() and over-trigger for every agent
        # turn in between.
        phase_changed = moderator_state.pop("_just_changed", False)

        if phase_changed:
            trigger = "phase_change"
        elif stall_active:
            trigger = "stall"
        elif turns_since_distill[agent_key] >= DISTILL_TRIGGER_INTERVAL:
            trigger = "periodic"
        else:
            return

        # Distill from the agent's own latest rationale — that is where the
        # "why" lives; the message is only the fallback when parsing failed.
        source = latest_rationale.get(agent_key) or last_message
        parent = memory_snippets[agent_key][-1] if memory_snippets[agent_key] else None

        prompt_lines = [
            f"Agent {agent_key} in a group deliberation (phase: {moderator_state['state']}) "
            f"just explained its last message with: \"{source}\"",
        ]
        if parent:
            prompt_lines.append(
                f"The agent's previously recorded position was: \"{parent['content']}\" — "
                f"state whether the new snapshot continues, refines, or reverses it."
            )
        prompt_lines.append(
            "Distill the agent's CURRENT position into 1-2 short sentences. "
            "Output only the distilled sentences, nothing else."
        )
        try:
            content = create_response(
                args.model,
                [{"role": "user", "content": "\n".join(prompt_lines)}],
                temperature=0.3, max_output_tokens=60,
            ).strip()
        except Exception as e:
            log_thinking("memory_distill_error", f"{agent_key}: {e}")
            content = ""
        if not content:
            content = source  # keep the chain intact even if the distill call fails

        snippet_counters[agent_key] += 1
        snippet = {
            "id": f"snip_{agent_key}_{snippet_counters[agent_key]:04d}",
            "agent_key": agent_key,
            "chat_room_id": chat_room_id,
            "time": now_local_iso(),
            "content": content,
            "trigger": trigger,
            "parent_id": latest_snippet_id[agent_key],
        }
        memory_snippets[agent_key].append(snippet)
        latest_snippet_id[agent_key] = snippet["id"]
        # Any trigger resets the periodic counter, so a phase-change snippet
        # isn't immediately followed by a near-duplicate periodic one.
        turns_since_distill[agent_key] = 0
        log_memory(snippet)

    def get_memory_context(agent_key: str, max_snippets: int = 3) -> str:
        """Most recent snippets of this agent's own chain, as a prompt block.
        Appended AFTER system_prompt()'s return value, never baked into
        role_text (role_text stays static)."""
        snips = memory_snippets[agent_key][-max_snippets:]
        if not snips:
            return ""
        lines = ["\n=== YOUR MEMORY (your own recent position snapshots, oldest first) ==="]
        lines += [f"- [{s['trigger']}] {s['content']}" for s in snips]
        lines.append("Stay consistent with this trajectory unless you explicitly say you are revising it.")
        return "\n".join(lines)

    def maybe_run_moderator():
        """
        Moderator scheduling: USER participation is the primary clock, total
        turns are only a backstop. See MODERATOR_USER_TURN_INTERVAL for why —
        counting turns of any kind let three agents greet each other into a
        phase advance before the user had said anything.
        """
        nonlocal turns_since_moderator, user_turns_since_moderator
        due_user = user_turns_since_moderator >= MODERATOR_USER_TURN_INTERVAL
        # The backstop only applies while the user is SILENT. Letting it fire
        # regardless would re-introduce exactly what it is meant to prevent: a
        # busy agent-to-agent stretch between two user sentences would trip the
        # total-turn counter and advance the phase a second time, so two user
        # sentences could still burn through two phases.
        due_fallback = (not user_spoke_since_moderator
                        and turns_since_moderator >= MODERATOR_TURN_FALLBACK)
        # Past the stall threshold, re-check more often so a stuck group is
        # unstuck promptly — but not on every single line.
        stalling = (turns_in_current_state > MODERATOR_STALL_TURNS
                    and turns_since_moderator >= MODERATOR_STALL_RECHECK)
        if due_user or due_fallback or stalling:
            # A run triggered ONLY by the stall re-check must not advance the
            # phase: it exists to detect and clear stalls, and it is clocked on
            # agent turns, so letting it move the state would smuggle back the
            # agent-driven progression this whole trigger was rewritten to stop.
            # The fallback keeps its power to advance — that is its job as the
            # freeze breaker.
            run_moderator(allow_state_change=due_user or due_fallback)

    def run_moderator(allow_state_change: bool = True):
        """Classify current deliberation state and issue per-agent moves.

        allow_state_change=False: run the classifier and honour its stall/goal
        output, but keep the current phase (see maybe_run_moderator)."""
        # These must be declared here too: without it, the resets below bind
        # fresh locals and the outer counters silently never reset.
        nonlocal turns_in_current_state, turns_since_moderator
        nonlocal user_turns_since_moderator, user_spoke_since_moderator

        history = clamp_history(transcript_lines, args.max_history_chars)
        roles_summary = build_roles_summary(agents)

        # Consume the scheduling counters for this run, but keep the "did the
        # user contribute since last time" answer — the Concluded latch below
        # needs it.
        had_user_input = user_spoke_since_moderator
        turns_since_moderator = 0
        user_turns_since_moderator = 0
        user_spoke_since_moderator = False

        # Include stall context so Admin-3 knows how long we've been here
        # Only allow stall detection after MODERATOR_STALL_TURNS (first turn excluded)
        stall_eligible = turns_in_current_state > MODERATOR_STALL_TURNS
        # Admin-3 only knows the four deliberation phases; Concluded is derived
        # here in code, so report it back to Admin-3 as the phase it came from.
        reported_state = ("Convergence" if moderator_state["state"] == CONCLUDED_STATE
                          else moderator_state["state"])
        stall_hint = (
            f"The conversation has been in '{reported_state}' state for "
            f"{turns_in_current_state} agent turns."
            + ("" if stall_eligible else " Do NOT set stall: true — not enough turns yet.")
        )

        admin3_messages = [
            {"role": "system", "content": ADMIN3_SYSTEM},
            {"role": "user", "content": (
                f"=== SCENE ===\n{scene}\n\n"
                f"=== AGENT PERSONALITIES ===\n{roles_summary}\n\n"
                f"=== CURRENT STATE ===\n{reported_state}\n"
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

        if not allow_state_change and parsed["state"] != prev_state:
            log_moderator("admin3_state_change_suppressed",
                          f"{prev_state} -> {parsed['state']} withheld: stall re-check only, "
                          f"no user input since the last classification.")
            parsed = dict(parsed)
            parsed["state"] = prev_state

        # Terminal-state latch (deterministic, not asked of the LLM): the group
        # reaching Convergence twice in a row with no user input in between
        # means the discussion is finished, not that it needs another round of
        # "encourage the user to finalize". Latching here is what stops the
        # recycling loop seen in logs/316347.
        if (parsed["state"] == "Convergence"
                and prev_state in ("Convergence", CONCLUDED_STATE)
                and not had_user_input):
            parsed = dict(parsed)
            parsed["state"] = CONCLUDED_STATE
            parsed["stall"] = False
            parsed["goal"] = ("The group has converged. Stop discussing; the floor is the "
                              "user's until they confirm, object, or raise something new.")

        moderator_state.update(parsed)

        # One-shot phase-change signal for memory distillation. It is consumed
        # with .pop() in maybe_distill_snippet(), so it triggers exactly one
        # snippet (for the next agent that speaks) instead of staying True and
        # over-triggering until the next moderator run.
        moderator_state["_just_changed"] = (parsed["state"] != prev_state)

        if parsed["state"] != prev_state:
            turns_in_current_state = 0
            log_moderator("admin3_state_change", f"{prev_state} -> {parsed['state']}  |  {parsed['goal']}")
            if parsed["state"] == CONCLUDED_STATE:
                log_moderator("admin3_concluded",
                              "Converged twice with no user input in between — discussion closed, "
                              "floor returns to the user.")
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
        would speak twice in a row. The burst clears the stall flag on the way
        out so it fires once per detection rather than on every subsequent turn
        until the next moderator run.

        DELIBERATE EXEMPTION from the MAX_CONSECUTIVE_AGENT_TURNS valve: the
        burst used to test that counter per iteration and, in logs/316347, a
        stall detected at consecutive_agent_turns == 5 produced the sequence
        "Forcing A->C burst" immediately followed by "Burst cut short" — the
        recovery mechanism never emitted a single message, making stall
        detection decorative. A stall is precisely the situation where more
        agent turns are the intended remedy, so the burst runs its own bounded
        budget (at most one turn per other agent, i.e. len(agents)-1) and the
        valve reasserts itself right after: the burst leaves
        consecutive_agent_turns elevated, so admin_choose_next() hands the floor
        straight back to the user.
        """
        nonlocal consecutive_agent_turns, turns_in_current_state, turns_since_moderator
        nonlocal last_speaker_key
        stall_temp = min(args.temperature + 0.25, 1.4)
        burst_agents = [a for a in agents if a.key != trigger_key][:MAX_STALL_BURST_TURNS]
        log_thinking("stall_burst",
                     f"Forcing {'->'.join(a.key for a in burst_agents)} burst at temp={stall_temp:.2f} "
                     f"(exempt from the consecutive-turn valve by design)")

        for burst_agent in burst_agents:
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
                    stance_text=get_stance_block(burst_agent.key), lang=args.lang,
                    session_memory_text=session_memory_text,
                    preloaded_knowledge_text=agent_configs[burst_agent.key].get("preloaded_knowledge", ""))
                    + get_memory_context(burst_agent.key)},
                {"role": "user", "content": user_prompt},
            ]
            meta: dict = {}
            raw = create_response(args.model, messages, stall_temp,
                                  args.max_output_tokens, meta=meta)
            log_generation_meta(burst_agent.key, meta, raw=raw, note="stall burst")
            parsed = parse_agent_turn(raw)
            txt = parsed["message"] or "…"
            if parsed["rationale"]:
                latest_rationale[burst_agent.key] = parsed["rationale"]
                log_agent_event(burst_agent.key, "rationale", parsed["rationale"])
            agent_mentions = parse_mentions(txt, mention_patterns, MAX_MENTIONS_PER_MESSAGE)
            if agent_mentions:
                log_agent_event(burst_agent.key, "agent_mention",
                                f"{burst_agent.key} mentioned {agent_mentions} "
                                f"(soft cue, not routed, admin still decides next speaker)")
            print(f"{burst_agent.name}> {txt}")
            log_chat(burst_agent.name, txt)
            last_speaker_key = burst_agent.key
            maybe_distill_snippet(burst_agent.key, txt, stall_active=True)

        # One burst per detected stall. Without this the flag stays true until the
        # next moderator run (potentially many turns away) and every
        # agent turn in between would trigger another full burst.
        moderator_state["stall"] = False

    print(f"Chat room id: {chat_room_id}")
    def _agent_summary(key: str) -> str:
        base = f"{agent_configs[key]['emotion']}+{agent_configs[key]['decision']}"
        stance = agent_configs.get(key, {}).get("stance")
        return f"{base}+{stance}" if stance else base
    print("Agents: " + "  ".join(f"{k}={_agent_summary(k)}" for k in agent_keys))
    print(f"Moderator: every {MODERATOR_USER_TURN_INTERVAL} user turns "
          f"(or {MODERATOR_TURN_FALLBACK} turns of any kind) | "
          f"stall threshold={MODERATOR_STALL_TURNS} | novelty guard={args.novelty_threshold:g}")
    print("Commands: /exit to quit | /next to force moderator update\n")

    with open(chat_path, "a", encoding="utf-8") as chat_fp, \
         open(thinking_path, "a", encoding="utf-8") as thinking_fp, \
         open(moderator_path, "a", encoding="utf-8") as moderator_fp, \
         open(rationale_path, "a", encoding="utf-8") as rationale_fp, \
         open(memory_path, "a", encoding="utf-8") as memory_fp:

        def user_turn():
            nonlocal consecutive_agent_turns, turns_since_moderator
            nonlocal user_turns_since_moderator, user_spoke_since_moderator
            nonlocal last_speaker_key
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
            # The user just spoke: every agent is eligible again next.
            last_speaker_key = None

            # New user input reopens a concluded discussion — that is the whole
            # point of latching to Concluded rather than ending the session.
            if moderator_state["state"] == CONCLUDED_STATE:
                moderator_state["state"] = "Convergence"
                moderator_state["goal"] = ""
                log_moderator("admin3_reopened",
                              "User spoke after Concluded — back to Convergence for re-classification.")

            # Hard route: agents the user @-mentioned reply next, in order,
            # before Admin-1/2 pick speakers again (see the main loop).
            mentioned = parse_mentions(user_txt, mention_patterns, MAX_MENTIONS_PER_MESSAGE)
            if mentioned:
                mention_queue.extend(mentioned)
                log_agent_event("user", "mention_override",
                                f"user mentioned {mentioned}; queued for hard-routed replies")

            turns_since_moderator += 1
            user_turns_since_moderator += 1
            user_spoke_since_moderator = True
            maybe_run_moderator()
            return True

        def agent_turn(agent: ChatAgent, force_intro: bool = False,
                       mention_trigger: bool = False):
            nonlocal consecutive_agent_turns, turns_in_current_state, turns_since_moderator
            nonlocal last_speaker_key
            last_speaker_key = agent.key
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

            if mention_trigger:
                # The user @-mentioned this agent by name: answer them first,
                # instead of the generic "continue the group chat" framing.
                user_prompt = (
                    "Below is the full group chat transcript so far.\n"
                    "Each line is formatted as: Speaker: message\n"
                    "The user just mentioned YOU by name in their last message. "
                    "Respond to the user directly first — address what they asked or said to you — "
                    "before anything else. Stay in character.\n\n"
                    f"{history}\n{extra}"
                )
            else:
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
                    stance_text=get_stance_block(agent.key), lang=args.lang,
                    session_memory_text=session_memory_text,
                    preloaded_knowledge_text=agent_configs[agent.key].get("preloaded_knowledge", ""))
                    + get_memory_context(agent.key)},
                {"role": "user", "content": user_prompt},
            ]
            meta: dict = {}
            raw = create_response(args.model, messages, effective_temp,
                                  args.max_output_tokens, meta=meta)
            log_generation_meta(agent.key, meta, raw=raw)
            parsed = parse_agent_turn(raw)
            parsed = enforce_no_refusal(
                agent,
                messages,
                parsed,
                effective_temp,
                create_fn=lambda msgs, t, mt: create_response(args.model, msgs, t, mt),
                model=args.model,
                max_output_tokens=args.max_output_tokens,
                log_event=log_agent_event,
                log_think=log_thinking,
            )
            if not parsed.get("dropped"):
                parsed = enforce_novelty(agent, messages, parsed, effective_temp)

            # Refusal / novelty guard rejected: silence is an allowed turn.
            if parsed.get("dropped"):
                agent.spoke -= 1
                log_agent_event(agent.key, "turn_dropped",
                                "refusal or novelty guard rejected the turn; "
                                "agent stayed silent this turn")
                print(f"[SYSTEM] {agent.name} had nothing new to add this turn.")
                maybe_run_moderator()
                return True

            txt = parsed["message"] or "…"
            if parsed["rationale"]:
                latest_rationale[agent.key] = parsed["rationale"]
                log_agent_event(agent.key, "rationale", parsed["rationale"])

            # Agent-side mentions are a soft cue only (recorded, never routed —
            # Admin-1/2 still decide the next speaker as usual).
            agent_mentions = parse_mentions(txt, mention_patterns, MAX_MENTIONS_PER_MESSAGE)
            if agent_mentions:
                log_agent_event(agent.key, "agent_mention",
                                f"{agent.key} mentioned {agent_mentions} "
                                f"(soft cue, not routed, admin still decides next speaker)")

            print(f"{agent.name}> {txt}")
            log_chat(agent.name, txt)
            maybe_distill_snippet(agent.key, txt, stall_active=stall_triggered)

            # After the triggering agent speaks, run the burst for remaining agents
            if stall_triggered:
                stall_burst(trigger_key=agent.key)

            maybe_run_moderator()
            return True

        def enforce_novelty(agent: ChatAgent, messages: List[dict], parsed: dict,
                             temp: float) -> dict:
            """
            Prompt rules alone don't hold: the model obeys "don't repeat yourself"
            for a few turns and then drifts back to paraphrasing the last three
            messages. Score the reply against the recent transcript and, if it is
            mostly recycled, give the model one corrective pass. The retry is kept
            only if it actually scores better, so a worse rewrite can't make things
            worse than the original.

            Takes and returns a parse_agent_turn() dict: only the MESSAGE part is
            scored, and a kept retry replaces the rationale along with it (the
            retry is re-parsed, since it comes back in the same tagged format).

            A returned dict with "dropped": True means the agent stays silent
            this turn — see the end of this function for why keeping a failed
            retry was worse than dropping it.
            """
            txt = parsed["message"]
            if args.novelty_threshold <= 0 or not transcript_lines or not txt:
                return parsed
            prior = transcript_lines[-args.novelty_window:]
            ratio = novelty_ratio(txt, prior)
            if ratio >= args.novelty_threshold:
                return parsed

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
                    "whose point you are deferring to. Either way, do not ask a question this time. "
                    "Keep the required [MESSAGE]/[RATIONALE] output format."
                )},
            ]
            meta: dict = {}
            retry_raw = create_response(args.model, retry_messages,
                                        min(temp + 0.15, 1.4), args.max_output_tokens, meta=meta)
            log_generation_meta(agent.key, meta, note="novelty retry")
            retry_parsed = parse_agent_turn(retry_raw)
            retry_ratio = novelty_ratio(retry_parsed["message"], prior) if retry_parsed["message"] else 0.0

            # The retry is the last chance: it must clear the threshold on its
            # own, or the agent says nothing at all. The old rule kept a retry
            # whenever it merely scored HIGHER than the original — in
            # logs/316347 that published 0.50 and 0.52 rewrites of 0.00 turns,
            # i.e. content the guard itself had flagged as recycled, promoted
            # purely for being less bad. Silence is an allowed turn (the system
            # prompt says so explicitly); a rephrased restatement is not.
            if retry_ratio >= args.novelty_threshold:
                log_thinking("novelty_retry", f"{agent.key}: retry novelty={retry_ratio:.2f} (kept)")
                return retry_parsed
            best = max(ratio, retry_ratio)
            log_thinking("novelty_retry",
                         f"{agent.key}: retry novelty={retry_ratio:.2f}, still below "
                         f"{args.novelty_threshold:.2f} — turn dropped (best={best:.2f})")
            return {"message": "", "rationale": "", "dropped": True}

        def admin_choose_next() -> str:
            if consecutive_agent_turns >= MAX_CONSECUTIVE_AGENT_TURNS:
                log_thinking("admin_rule",
                             f"Force U: consecutive_agent_turns >= {MAX_CONSECUTIVE_AGENT_TURNS}")
                return "U"

            li = last_user_index(transcript_lines)
            gap = (len(transcript_lines) - 1 - li) if li is not None else len(transcript_lines)
            if gap >= args.max_user_gap:
                log_thinking("admin_rule", f"Force U: user gap {gap} >= max_user_gap {args.max_user_gap}")
                return "U"

            history = clamp_history(transcript_lines, args.max_history_chars)
            roles_summary = build_roles_summary(agents)
            spoke_counts = ", ".join(f"{k}={key_to_agent[k].spoke}" for k in agent_keys)
            stats = (
                f"Spoke counts: {spoke_counts}. "
                f"Consecutive agent turns={consecutive_agent_turns}. "
                f"User gap(lines)={gap}. "
                f"Moderator state={moderator_state['state']}."
            )

            admin1_messages = [
                {"role": "system", "content": admin1_system},
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
                {"role": "system", "content": admin2_system},
                {"role": "user", "content": admin1_out},
            ]
            admin2_out = create_response(args.model, admin2_messages, temperature=0.0, max_output_tokens=MIN_OUTPUT_TOKENS)
            admin2_out = (admin2_out or "").strip().upper()
            log_thinking("admin2", admin2_out)

            # Never hand the floor straight back to the agent that just held it.
            # Falls back to the full set only when there is no alternative (e.g. a
            # single-agent pool), so this can never deadlock or return an empty pick.
            def eligible() -> List[str]:
                pool = [k for k in agent_keys if k != last_speaker_key]
                return pool or agent_keys

            if admin2_out not in set(agent_keys) | {"U"}:
                pick = random.choice(eligible())
                log_thinking("admin_fallback", f"Invalid admin2_out={admin2_out!r}, fallback to {pick}")
                admin2_out = pick

            if admin2_out == "U":
                if random.random() < float(args.prefer_agents):
                    pick = random.choice(eligible())
                    log_thinking("admin_bias", f"Override U -> {pick} (prefer_agents={args.prefer_agents})")
                    return pick
                return "U"

            # Admin picked a specific agent — honour it unless it is the agent that
            # just spoke, in which case reroute to someone else rather than produce
            # a back-to-back turn the novelty guard would only drop.
            if admin2_out == last_speaker_key:
                pick = random.choice(eligible())
                if pick != admin2_out:
                    log_thinking("admin_no_repeat",
                                 f"Admin re-picked {admin2_out} (just spoke) -> rerouted to {pick}")
                    return pick

            return admin2_out

        # Start order: any agent key from info.jsonl plus U; unknown chars ignored
        start_order = (args.start_order or "").upper()[: len(agent_keys) + 1]
        intro_done: Dict[str, bool] = {a.key: False for a in agents}

        for ch in start_order:
            if ch in key_to_agent:
                agent_turn(key_to_agent[ch], force_intro=not intro_done[ch])
                intro_done[ch] = True
            elif ch == "U":
                ok = user_turn()
                if not ok:
                    return

        while True:
            # User @-mentions take absolute priority over Admin-1/2 selection.
            # DESIGN TRADE-OFF (intentional, not a bug): because this path never
            # goes through admin_choose_next(), it also bypasses the
            # consecutive_agent_turns >= MAX_CONSECUTIVE_AGENT_TURNS safety
            # valve that normally forces the user back in. The user explicitly
            # summoned these agents, so honoring the summons wins; the queue is
            # capped at MAX_MENTIONS_PER_MESSAGE per user message anyway.
            if mention_queue:
                key = mention_queue.pop(0)
                log_agent_event(key, "mention_dispatch",
                                f"hard-routing {key} to speak (from user mention queue, "
                                f"admin selection skipped)")
                agent_turn(key_to_agent[key], force_intro=not intro_done[key],
                           mention_trigger=True)
                intro_done[key] = True
                continue

            # Concluded: the group has said everything it has. Do not spend an
            # Admin-1/2 call deciding which agent gets to repeat the conclusion
            # — hand the floor to the user unconditionally. user_turn() lifts
            # the latch as soon as they say anything.
            if moderator_state["state"] == CONCLUDED_STATE:
                print("[SYSTEM] 讨论已收敛。补充信息或提出新问题可以继续，/exit 结束。"
                      if args.lang == "zh" else
                      "[SYSTEM] The group has converged. Add information or raise a new "
                      "question to continue, or /exit to finish.")
                ok = user_turn()
                if not ok:
                    break
                continue

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
    print(f"Saved rationale log: {rationale_path}")
    print(f"Saved memory log:    {memory_path}")

    # Cross-session memory (write side): one extra LLM call over the full
    # transcript, then APPEND a recap record to memory/{user_id}__{scenario_type}
    # .jsonl (never overwrite). Only when a scenario_type keys the file and the
    # session actually produced dialogue. Failures here never crash the shutdown.
    if HAVE_SESSION_MEMORY and args.scenario_type:
        transcript_text = "\n".join(transcript_lines).strip()
        if transcript_text:
            try:
                result = summarize_session(transcript_text, args.lang, create_response, args.model)
                rec = append_session_record(
                    args.user_id, args.scenario_type, chat_room_id, now_local_iso(),
                    result["summary"], result["open_threads"],
                )
                if rec is not None:
                    print(f"Saved session memory: memory/{args.user_id}__{args.scenario_type}.jsonl "
                          f"(+1 record, {len(result['open_threads'])} open thread(s))")
            except Exception as e:  # noqa: BLE001 — shutdown must not fail on this
                print(f"[SYSTEM] session-memory summary skipped: {e}", file=sys.stderr)

# -------------------------------
# Flask / library helpers (Agora web)
# -------------------------------

# Legacy aliases expected by app.py (Admin-1/2 are built dynamically in the turn loop).
ADMIN1_SYSTEM, ADMIN2_SYSTEM = build_admin_prompts(["A", "B", "C"], 5)
MODERATOR_INTERVAL = MODERATOR_USER_TURN_INTERVAL


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
