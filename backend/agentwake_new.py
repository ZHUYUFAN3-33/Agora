# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import uuid
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
    from stance import (assign_stance, stance_enabled, get_stance_text,
                        get_convergence_weight_hint, get_stance_phase_focus,
                        get_stance_label)
    HAVE_STANCE = True
except ImportError:
    HAVE_STANCE = False

try:
    from agent_assembly import build_all_agent_specs
    HAVE_AGENT_ASSEMBLY = True
except ImportError:
    HAVE_AGENT_ASSEMBLY = False

# Option Board: room-level option state. Agent [OPTIONS] output is a proposal
# reconciled into the board at write time; the board decides when chips render.
try:
    import option_board
    HAVE_OPTION_BOARD = True
except ImportError:
    HAVE_OPTION_BOARD = False

# Stance Knowledge: keyword-triggered, per-stance background cards injected into
# the speaking agent's prompt. Pure local dict lookup (no network / no LLM). See
# stance_knowledge.py. Optional import so the script still runs standalone.
try:
    # _match_topic_card is reused (not reimplemented) so the "did a keyword hit"
    # gate below shares one source of truth with the module's own matching.
    from stance_knowledge import (
        load_stance_knowledge,
        get_stance_knowledge_block,
        get_stance_knowledge_hit,
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
    # The model that actually served the request, which can differ from the one asked for
    # when an alias resolves to a dated snapshot.
    meta["model"] = getattr(resp, "model", None)
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
            # getattr rather than attribute access throughout: the project pins
            # openai>=1.40,<2 but the field set differs across versions, and a missing
            # richer field must not take down a generation.
            meta["output_tokens"] = getattr(usage, "output_tokens", None)
            meta["input_tokens"] = getattr(usage, "input_tokens", None)
            meta["total_tokens"] = getattr(usage, "total_tokens", None)
            in_details = getattr(usage, "input_tokens_details", None)
            if in_details is not None:
                meta["cached_tokens"] = getattr(in_details, "cached_tokens", None)
            out_details = getattr(usage, "output_tokens_details", None)
            if out_details is not None:
                meta["reasoning_tokens"] = getattr(out_details, "reasoning_tokens", None)
    except Exception:
        pass


def _is_reasoning_model(model: str) -> bool:
    """True for the GPT-5 line and the o-series, which reject `temperature`.

    Measured, not assumed: gpt-5.6-terra answers a plain Responses call fine but
    returns 400 "Unsupported parameter: 'temperature' is not supported with this
    model" the moment the knob is present, and gpt-4o returns the mirror-image 400
    for 'reasoning.effort'. So the sampling params have to be built per model
    instead of passed blindly.

    Prefix match rather than a list of exact ids on purpose: dated snapshots
    (gpt-5.6-terra-2026-..) and future tiers must inherit the behaviour instead of
    silently 400ing the whole app the first time someone pins one.
    """
    return (model or "").lower().startswith(("gpt-5", "o1", "o3", "o4"))


def _sampling_params(model: str, temperature: float) -> dict:
    """Sampling knobs this model actually accepts, as **kwargs for a Responses call."""
    if not _is_reasoning_model(model):
        return {"temperature": temperature}
    # NOTE: temperature is dropped here, and the callers that bump it to escape a
    # stall / repetition / refusal (enforce_novelty, the stall path, the refusal
    # retry) therefore become no-ops on these models -- the retry goes out with
    # exactly the parameters that just failed. Diversity has to come from the
    # prompt instead. See AGORA_REASONING_EFFORT below for the one knob left.
    effort = os.getenv("AGORA_REASONING_EFFORT", "").strip().lower()
    # Agora turns are short in-character utterances, not analysis: paying reasoning
    # latency and tokens per turn buys nothing, so default to no thinking budget.
    return {"reasoning": {"effort": effort or "none"}}


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
        _t0 = time.perf_counter()
        resp = client.responses.create(
            model=model, input=messages,
            max_output_tokens=max_output_tokens,
            **_sampling_params(model, temperature),
        )
        meta["latency_ms"] = int((time.perf_counter() - _t0) * 1000)
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

    payload = {"model": model, "input": messages, "max_output_tokens": max_output_tokens,
               **_sampling_params(model, temperature)}
    _t0 = time.perf_counter()
    resp = _responses_create_http(payload)
    meta["latency_ms"] = int((time.perf_counter() - _t0) * 1000)
    meta["status"] = resp.get("status")
    meta["model"] = resp.get("model")
    if isinstance(resp.get("incomplete_details"), dict):
        meta["incomplete_reason"] = resp["incomplete_details"].get("reason")
    if isinstance(resp.get("usage"), dict):
        meta["output_tokens"] = resp["usage"].get("output_tokens")
        meta["input_tokens"] = resp["usage"].get("input_tokens")
        meta["total_tokens"] = resp["usage"].get("total_tokens")
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
                            include_related: bool = False,
                            allow_soft: bool = False) -> str:
    """Stance-knowledge block for `message`, but ONLY when it actually hits a
    topic-card keyword; "" otherwise. This suppresses the module's generic
    fallback so the block is tied to a real keyword match — the single rule both
    channels share: the per-turn dynamic trigger (get_phase_context, latest user
    message) and the session-start preloaded hint (build once from info.jsonl's
    hint). include_header=False returns the body alone, for callers that add
    their own distinct block title.

    include_related: expand one-hop related_cards (A-OR-B trigger decided by caller).

    allow_soft: opt into the fork-local reverse-containment pass in
    _match_topic_card. TRUE only for the session-start preload, whose input is a
    short setup hint; FALSE (upstream-identical) for the per-turn dynamic
    channel, whose input is a whole user message. It is passed to BOTH the gate
    and the block below on purpose — if they disagreed, a soft hit would clear
    the gate and then render the stance's GENERIC FALLBACK as if it were the
    matched card.
    """
    if not (HAVE_STANCE_KNOWLEDGE and knowledge and stance and message):
        return ""
    scenario_cfg = knowledge.get(scenario_type, {}) or {}
    stance_cfg = scenario_cfg.get(stance)
    topic_cards = stance_cfg.get("topic_cards", []) if isinstance(stance_cfg, dict) else []
    if not sk_match_topic_card(message, topic_cards, lang, allow_soft=allow_soft):
        return ""
    return get_stance_knowledge_block(
        scenario_type, stance, message, lang,
        knowledge=knowledge, include_header=include_header,
        include_related=include_related, allow_soft=allow_soft,
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
    on_match: Optional[Callable[[dict], None]] = None,
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
    hit = get_stance_knowledge_hit(
        scenario_type or "",
        stance,
        last_user_message,
        lang,
        knowledge=knowledge,
    )
    if not hit or hit.get("is_fallback"):
        return ""
    hits = hit_history.setdefault(agent_key, [])
    repeat_hit = card_id in hits  # trigger A (check BEFORE recording)
    in_convergence = deliberation_state == "Convergence"  # trigger B
    hits.append(card_id)
    if on_match is not None:
        on_match({
            "id": hit.get("id"),
            "tag": hit.get("tag") or card_id,
            "source": hit.get("source") or "",
        })
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


def novelty_ratio(text: str, prior_texts: List[str],
                  exclude_tokens: Optional[set] = None) -> float:
    """
    Fraction of this message's content tokens that never appeared in prior_texts.
    1.0 when there is nothing to compare against; near 0.0 means the message is
    a restatement of what the group already has on the table.

    exclude_tokens: tokens of the message this one REPLIES TO. Answering a claim
    necessarily reuses that claim's words, and before this parameter existed the
    metric punished exactly what the retry prompt demands — measured on the old
    calibration data, 11 of 28 novelty retries scored LOWER than the first
    attempt because engaging a specific point re-quotes it. Excluded tokens
    count neither as new nor toward the denominator, so the score becomes "how
    novel is the part that is not quotation". A message that is NOTHING but
    quotation scores 0.0 — same semantics as an empty message: no contribution.
    """
    new = _content_tokens(text)
    if exclude_tokens:
        new -= exclude_tokens
    if not new:
        return 0.0
    seen: set = set()
    for t in prior_texts:
        seen |= _content_tokens(t)
    if not seen:
        return 1.0
    return len(new - seen) / len(new)


# Low-content user turns: response effort should track the information in the
# user's message. Measured on gpt-5.6: a bare "你好" drew ~950 words per agent
# — the agents hold a mountain of intake context and an instruction to be
# helpful, so with nothing to react to they front-load the whole analysis.
# Analysis produced before the user has said anything substantive is generic,
# anchors the discussion prematurely, and (per the blind review) is skimmed,
# i.e. received as nothing. Detection is deterministic and cheap: fewer than
# LOW_CONTENT_TOKEN_MAX content tokens, with two escape hatches — a question
# mark or an @mention makes any message substantive regardless of length
# ("选A还是B?" is four tokens and a real request). Lives here rather than in
# app.py so tests need no Flask and the CLI can adopt it later.
LOW_CONTENT_TOKEN_MAX = 5


def is_low_content_message(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if "?" in t or "？" in t or "@" in t:
        return False
    return len(_content_tokens(t)) < LOW_CONTENT_TOKEN_MAX


# Injected per turn via the `extra` container when the user's message is low
# content. A contract, not a token cap: max_output_tokens stays 520 because a
# hard cap truncates the [MESSAGE] tail mid-sentence (the block order exists
# for exactly that reason). Length falls out of the role change instead.
LOW_CONTENT_TURN_DIRECTIVE = (
    "\n\n(This turn) The user's last message carries no new information (a "
    "greeting or acknowledgement). Do NOT analyze the decision this turn: "
    "nothing new to analyze has been said, and a wall of unprompted analysis "
    "reads as noise. Reply with at most two short sentences: one that states "
    "your standpoint or reacts in character, plus at most ONE question — the "
    "single thing you most need from the user. No lists, no headings, no "
    "[OPTIONS] block this turn. If this is your FIRST message, the required "
    "\"Hi, I'm ...\" introduction sentence counts as your standpoint sentence."
)


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
        if lang == "zh":
            lang_line = (
                "Write every message in Chinese (简体中文). "
                "Do not switch language mid-message."
            )
        elif lang == "ja":
            lang_line = (
                "Write every message in Japanese (日本語). "
                "Do not switch language mid-message."
            )
        else:
            lang_line = (
                "Write every message in English. "
                "Do not switch language mid-message."
            )
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
            # ORDER MATTERS: the two one-line metadata blocks come FIRST.
            # They used to trail the message, and since the message is the long
            # part, hitting max_output_tokens cut the tail off — measured in
            # room 001999, every turn whose message ran past ~250 tokens lost
            # its [RATIONALE] entirely (4 of 6 turns), which is what left the
            # decision map's edge tooltips with nothing to show.
            "\n\nOUTPUT FORMAT (required, in this order):\n"
            "[MOVE]\n"
            "one word for what this message DOES, optionally plus who it responds to, e.g. "
            "\"challenge @ChatbotB\". Exactly one of: challenge (you dispute a specific claim "
            "someone made) / extend (you build on someone's point with something they did not "
            "say) / new_point (you raise something not aimed at anyone) / concede (you accept "
            "a cost or genuinely adjust your position) / clarify (you answer a question or "
            "supply facts).\n"
            "[/MOVE]\n"
            "[RATIONALE]\n"
            "one short sentence: why you said this, given your persona and the current phase goal. "
            # The map shows this to the person being discussed, so an internal note that
            # calls them "the user" reads as being talked about rather than to. Measured
            # before this line existed: 5 of 26 rationales in one room said "the user",
            # none ever said "you".
            "Write it in your own voice and address the person you are advising as \"you\" — "
            "never refer to them in the third person (\"the user\", \"they\", \"用户\").\n"
            "[/RATIONALE]\n"
            "[MESSAGE]\n"
            "your chat message here\n"
            "[/MESSAGE]\n"
            "[OPTIONS]\n"
            '[{"id":"o1","label":"short option A"},{"id":"o2","label":"short option B"}]\n'
            "[/OPTIONS]\n"
            "Tag names are literal markers: write MESSAGE / OPTIONS / MOVE / RATIONALE in English "
            "exactly as shown. Do NOT translate them "
            "(never [消息]/[选项]/[選択肢]/[オプション]/[メッセージ]/[动作]/[理由]/[根拠]). "
            # This used to say MOVE and RATIONALE are "private", which is simply false:
            # both surface in the decision map, and the model wrote them as internal
            # notes because the prompt told it nobody would read them.
            "MESSAGE and OPTIONS are what the others in the room see. MOVE and RATIONALE are "
            "not spoken aloud, but the person you are advising sees them in the decision map "
            "when they open your turn — write them to be read by that person. "
            "Report the move honestly — an agreeable message labelled \"challenge\" defeats its "
            "purpose.\n"
            "Labels INSIDE OPTIONS must use the same language as the chat message "
            "(Chinese / English / Japanese as required by LANGUAGE).\n"
            "Include [OPTIONS] whenever you present 2–6 mutually exclusive choices the user could "
            "pick (jobs, plans, A/B paths). Omit the whole [OPTIONS]…[/OPTIONS] block when you are "
            "not offering a selectable set. Max 6 options; each label ≤ 24 characters.\n"
            # Restated here on purpose. The directive at the top is separated from
            # the actual generation by everything above — most of it English — and
            # agents were observed replying wholly in English in zh sessions.
            # RATIONALE used to be outside this scope, and it showed: in one zh room
            # 19 of 21 rationales came back in English, so the map's Chinese panel
            # rendered English tooltips.
            f"LANGUAGE, again: {lang_line} This applies to MESSAGE text, OPTIONS labels "
            "and the RATIONALE sentence (the MOVE keyword stays English).\n"
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
# Which KNOWN USER CONTEXT details the "anchor your message" nudge should point
# at, per scenario. Keyed by scenario_type; unknown/None scenarios fall back to a
# neutral phrasing at the call site, so a new scenario needs no entry to work.
ANCHOR_EXAMPLES: Dict[str, str] = {
    "employment":
        "a ranked priority, the deadline, a named option and its salary/level/location, "
        "the career stage",
    "parent_child":
        "the child's age, what the child actually said, the parent's stated worry, the "
        "deadline, how much say the child was given",
}

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
# Tag aliases: models sometimes translate markers despite prompt (zh / ja / en).
_MSG_NAMES = r"MESSAGE|MSG|消息|訊息|信息|メッセージ"
_RAT_NAMES = r"RATIONALE|REASON|理由|原因|理由说明|根拠|根拠説明"
_OPT_NAMES = r"OPTIONS|OPTION|CHOICES|选项|選項|選択肢|オプション"
# Kept deliberately identical to feature/dialogue-naturalness's list (no zh-TW or
# extra ja variants) so [MOVE] recognition is bit-for-bit what that layer was
# tuned against — this port took the tag, not the layer.
_MOVE_NAMES = r"MOVE|动作|行动|アクション"

_MESSAGE_TAG_RE = re.compile(rf"\[(?:{_MSG_NAMES})\](.*?)\[/(?:{_MSG_NAMES})\]",
                             re.DOTALL | re.IGNORECASE)
_RATIONALE_TAG_RE = re.compile(rf"\[(?:{_RAT_NAMES})\](.*?)\[/(?:{_RAT_NAMES})\]",
                               re.DOTALL | re.IGNORECASE)
_OPTIONS_TAG_RE = re.compile(rf"\[(?:{_OPT_NAMES})\](.*?)\[/(?:{_OPT_NAMES})\]",
                             re.DOTALL | re.IGNORECASE)
_MOVE_TAG_RE = re.compile(rf"\[(?:{_MOVE_NAMES})\](.*?)\[/(?:{_MOVE_NAMES})\]",
                          re.DOTALL | re.IGNORECASE)
_STRAY_TAG_RE = re.compile(
    rf"\[/?(?:{_MSG_NAMES}|{_RAT_NAMES}|{_OPT_NAMES}|{_MOVE_NAMES})\]", re.IGNORECASE
)
# Last resort for the no-tags branch: a rationale/options/move block that opened
# but never closed would otherwise stay in the chat message.
_TRAILING_RATIONALE_RE = re.compile(
    rf"\[(?:{_RAT_NAMES}|{_OPT_NAMES}|{_MOVE_NAMES})\].*$", re.DOTALL | re.IGNORECASE
)

# Structured self-report of what a turn DOES, emitted by the agent itself in a
# [MOVE] block (see system_prompt's OUTPUT FORMAT).
#
# Ported from feature/dialogue-naturalness, WITHOUT that branch's consumers.
# There it also fed a challenge_tracker that steered the consensus warning and
# the convergence gate; bringing that here would change speaker scheduling and
# break this fork's fidelity to agora2/backend-dev. So the tag is emitted and
# logged only: the move lands in {room}_rationale.jsonl as a "move" event, which
# is what map_facts.py joins against to build the reply graph deterministically.
# Nothing in the deliberation loop reads it.
AGENT_MOVES = ("challenge", "extend", "new_point", "concede", "clarify")

# Novelty defer exit. The retry prompt has always offered "say you have nothing
# new and name whose point you defer to" — but the defer sentence itself was
# scored, and naming the other agent's point necessarily reuses their words, so
# the exit was pinched shut by the very door it was meant to open (measured on
# 5.6: both dropped retries scored 0.0/0.08, i.e. they were short deferrals).
# A structural marker replaces the score: [MOVE] concede @Target plus a short
# message is published as an explicit hand-off instead of a silent vanish.
# Chars, not tokens: an English sentence runs ~90-120 chars, a Chinese one
# ~30-60, and CJK-bigram token counts are unstable across languages, while a
# runaway analysis is thousands of chars in either.
NOVELTY_DEFER_MAX_CHARS = 120
# One deferral in a row per agent: the second consecutive attempt to use the
# exit is dropped like before, so "always concede" cannot become the universal
# escape hatch. Any normally-published turn resets the streak.
NOVELTY_DEFER_MAX_STREAK = 1


def is_defer_turn(parsed: dict, mention_patterns: Dict[str, str],
                  self_key: str) -> Optional[str]:
    """Target key if this parsed turn is an explicit short deferral, else None.

    Three structural requirements, all cheap: the self-reported move is
    "concede", a non-self @target resolves, and the message is one short
    sentence. Content is deliberately NOT scored — a deferral quotes the point
    it yields to, which is exactly what the novelty metric punishes.
    """
    if (parsed.get("move") or "") != "concede":
        return None
    msg = (parsed.get("message") or "").strip()
    if not msg or len(msg) > NOVELTY_DEFER_MAX_CHARS:
        return None
    return resolve_reply_target(parsed.get("move_detail") or "", msg,
                                mention_patterns, self_key)


def normalize_move(body: str) -> str:
    """First recognised move keyword in a [MOVE] block body, or "".

    Tolerant on purpose: the block may carry an @target ("challenge @ChatbotB"),
    stray punctuation, or a hyphen/space variant ("new point"). Anything that
    does not resolve to a known move is treated as no self-report at all, so a
    garbled block degrades to nothing instead of mislabelling the turn.

    NOTE for map_facts.py: this scans AGENT_MOVES in TUPLE order, not text
    order, so 'extend @ChatbotB, not a challenge' resolves to 'challenge'. That
    is why the fact layer parses the kind off the first whitespace token of
    move_detail instead of calling this.
    """
    low = (body or "").strip().lower().replace("-", "_").replace(" ", "_")
    for move in AGENT_MOVES:
        if move in low:
            return move
    return ""


def _parse_options_block(raw_body: str) -> list:
    """Parse OPTIONS JSON array into [{id, label}, ...] (2–6 items)."""
    body = (raw_body or "").strip()
    if not body:
        return []
    data = None
    try:
        data = json.loads(body)
    except Exception:
        start, end = body.find("["), body.rfind("]")
        if start != -1 and end > start:
            try:
                data = json.loads(body[start : end + 1])
            except Exception:
                data = None
    if not isinstance(data, list):
        return []
    out = []
    seen = set()
    for i, item in enumerate(data):
        if isinstance(item, str):
            label = item.strip()
            oid = f"o{i + 1}"
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("text") or item.get("name") or "").strip()
            oid = str(item.get("id") or f"o{i + 1}").strip() or f"o{i + 1}"
        else:
            continue
        if not label or oid in seen:
            continue
        seen.add(oid)
        out.append({"id": oid, "label": label[:48]})
        if len(out) >= 6:
            break
    return out if len(out) >= 2 else []


def parse_agent_turn(raw: str) -> dict:
    """
    Splits one LLM generation into the chat-visible message, optional OPTIONS
    chips payload, and the private rationale. Both MESSAGE/RATIONALE come from
    the SAME generation (never a second call).
    Tolerant by design: a malformed output must never crash a turn — if the
    tags are missing, the whole raw text becomes the message (stray tag tokens
    stripped so they can't leak into the chat log) and rationale stays empty.
    """
    raw = (raw or "").strip()
    msg_match = _MESSAGE_TAG_RE.search(raw)
    rat_match = _RATIONALE_TAG_RE.search(raw)
    opt_match = _OPTIONS_TAG_RE.search(raw)
    move_match = _MOVE_TAG_RE.search(raw)

    if msg_match:
        message = msg_match.group(1).strip()
    else:
        # No usable MESSAGE block. Drop anything from an opening RATIONALE/OPTIONS
        # tag onward first — otherwise a half-formed generation publishes private
        # blocks — then clear any stray tag tokens from what is left.
        message = _STRAY_TAG_RE.sub("", _TRAILING_RATIONALE_RE.sub("", raw)).strip()

    rationale = rat_match.group(1).strip() if rat_match else ""
    words = rationale.split()
    if len(words) > RATIONALE_MAX_WORDS:
        rationale = " ".join(words[:RATIONALE_MAX_WORDS]) + "..."

    options = _parse_options_block(opt_match.group(1)) if opt_match else []
    # Strip a leaked OPTIONS block from the visible message if tags were mangled.
    if options and _OPTIONS_TAG_RE.search(message):
        message = _OPTIONS_TAG_RE.sub("", message).strip()
    # Same for a leaked MOVE block — it is private and must never reach the chat.
    if _MOVE_TAG_RE.search(message):
        message = _MOVE_TAG_RE.sub("", message).strip()

    # Missing or unrecognised MOVE degrades to "" — no caller guesses a move.
    # move_detail keeps the raw body (incl. any @target) for the fact layer.
    move_body = move_match.group(1).strip() if move_match else ""
    return {
        "message": message,
        "rationale": rationale,
        "options": options,
        "move": normalize_move(move_body),
        "move_detail": " ".join(move_body.split())[:80],
    }


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

# An @-handle only counts at the start of a line or after whitespace/an opening
# bracket. A bare `@(\w+)` also fires inside e-mail addresses — "a@b.com" used
# to hard-route agent B to speak — and after any word character generally.
_MENTION_RE = re.compile(r"(?:^|[\s(（\[【,，。;；:：!！?？'\"“”])@(\w+)")

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
    for token in _MENTION_RE.findall(text or ""):
        key = mention_patterns.get(token.lower())
        if key and key not in found:
            found.append(key)
            if len(found) >= max_mentions:
                break
    return found


def resolve_reply_target(move_detail: str, message: str,
                         mention_patterns: Dict[str, str],
                         self_key: str) -> Optional[str]:
    """Which agent this turn replies to, for quote-exclusion in novelty scoring.

    The [MOVE] self-report ("challenge @ChatbotB") is the primary signal — it is
    parsed before scoring runs, so it is free. Fall back to @-mentions in the
    message body. First non-self hit wins; @U and unknown names resolve to
    nothing (parse_mentions ignores them), and None means "no target": the
    caller falls back to the un-excluded score, i.e. exactly the old behavior.

    Module-level rather than inside either enforce_novelty closure because the
    HTTP and CLI twins must share it, and the recalibration script replays it.
    """
    for source in (move_detail, message):
        for key in parse_mentions(source or "", mention_patterns):
            if key != self_key:
                return key
    return None


def last_message_of(name: str, transcript_lines: List[str]) -> str:
    """Most recent utterance of `name` in prefixed transcript lines, unprefixed."""
    prefix = f"{name}: "
    for line in reversed(transcript_lines or []):
        if line.startswith(prefix):
            return line[len(prefix):]
    return ""

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
    intake_data: Optional[dict] = None,
    scenario_type: Optional[str] = None,
    lang: str = "en",
    model: str = "gpt-4o",
    temperature: float = 0.8,
    max_output_tokens: int = 520,
    max_history_chars: int = 12000,
    max_user_gap: int = 12,
    max_agent_turns_before_user: Optional[int] = None,
    prefer_agents: Optional[float] = None,
    novelty_threshold: Optional[float] = None,
    novelty_window: int = 10,
    self_novelty_threshold: Optional[float] = None,
    self_novelty_window: int = 6,
    novelty_drop_threshold: Optional[float] = None,
    # Per-turn instruction appended to every agent's user prompt this turn
    # (the low-content contract rides in here). Empty string = no directive =
    # exactly the old prompt, so production-shaped calls that omit it are
    # untouched. Deliberately NOT injected into stall bursts: those already
    # replace the whole user prompt with a stronger directive of their own.
    turn_directive: str = "",
    persist_chat: Optional[Callable[[dict], None]] = None,
    create_response_with_client: Optional[CreateFn] = None,
) -> Dict[str, Any]:
    """Run one user turn; mutate session; return API-shaped responses."""
    intake_data = intake_data or {}
    prefer = float(
        prefer_agents if prefer_agents is not None else os.getenv("AGORA_PREFER_AGENTS", "0.85")
    )
    # CLI argparse default is 0.5 — keep HTTP env fallback aligned (CLI-faithful).
    nov_th = float(
        novelty_threshold
        if novelty_threshold is not None
        else os.getenv("AGORA_NOVELTY_THRESHOLD", "0.5")
    )
    # Second novelty scope (self-repetition); CLI argparse default is 0.35.
    self_nov_th = float(
        self_novelty_threshold
        if self_novelty_threshold is not None
        else os.getenv("AGORA_SELF_NOVELTY_THRESHOLD", "0.35")
    )
    # Discarding a retry is a much heavier call than asking for one: the
    # alternative is the agent saying nothing at all. Separate, far lower bar.
    drop_th = float(
        novelty_drop_threshold
        if novelty_drop_threshold is not None
        else os.getenv("AGORA_NOVELTY_DROP_THRESHOLD", "0.25")
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
            # Setup-hint knowledge belongs to exactly one agent.  A global
            # fallback here would make another agent's matched card appear in
            # this agent's system prompt when its own hint has no match.
            "preloaded_knowledge": (
                (session.get("agora2_specs") or {}).get(slot) or {}
            ).get("preloaded_knowledge") or "",
        }
        for slot in agent_keys
    }

    # Short "represents X" phrase per agent, for the generated cast list in the
    # prompt roster (CLI-faithful). Empty for scenarios that use no stances.
    stance_labels: Dict[str, str] = {}
    if HAVE_STANCE:
        for key in agent_keys:
            label = get_stance_label(
                scenario_type, agent_configs.get(key, {}).get("stance"), lang
            )
            if label:
                stance_labels[key] = label

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
    session.setdefault("spoke_counts", {k: 0 for k in agent_keys})
    # Ensure keys exist even if session was created with a fixed A/B/C dict.
    for k in agent_keys:
        session["memory_snippets"].setdefault(k, [])
        session["turns_since_distill"].setdefault(k, 0)
        session["latest_rationale"].setdefault(k, "")
        session["latest_snippet_id"].setdefault(k, None)
        session["snippet_counters"].setdefault(k, 0)
        session["agent_knowledge_hit_history"].setdefault(k, [])
        session["spoke_counts"].setdefault(k, 0)
    # ChatAgent objects are rebuilt per HTTP request, so their spoke counters
    # start at 0 every turn — but Admin-1's STATS line ("Spoke counts: ...") is
    # meant to describe the whole session (CLI keeps one ChatAgent per session).
    # Restore the session-lifetime counts before scheduling.
    for a in agent_list:
        a.spoke = int(session["spoke_counts"].get(a.key, 0))

    stance_knowledge_data = load_stance_knowledge() if HAVE_STANCE_KNOWLEDGE else None

    transcript_lines = history_to_transcript_lines(session.get("history") or [])
    responses: List[dict] = []
    pending_knowledge_matches: Dict[str, dict] = {}
    room_id = session.get("room_id")

    # ---- Option Board (option_board.py) ------------------------------------
    # Room-level option state: agent [OPTIONS] output is reconciled into the
    # board (repeat proposals become endorsements), and whether chips render on
    # a message is the board's display policy — not each agent's whim.
    _board_dir = os.path.dirname(getattr(session.get("chat_fp"), "name", "") or "") or "logs"
    _board_on = HAVE_OPTION_BOARD and bool(room_id)
    board_state = option_board.load_board(_board_dir, room_id) if _board_on else None
    if _board_on and not option_board.board_has_content(board_state):
        _intake_opts = (intake_data or {}).get("options")
        if isinstance(_intake_opts, list) and len(_intake_opts) >= 2:
            option_board.seed_intake(board_state, _intake_opts)
            if option_board.board_has_content(board_state):
                option_board.save_board(_board_dir, room_id, board_state)

    def board_prompt_note() -> str:
        if not _board_on:
            return ""
        note = option_board.board_prompt_block(board_state)
        return f"\n\n{note}" if note else ""

    def process_agent_options(
        agent_key: str,
        speaker_name: str,
        proposed: Optional[list],
        *,
        force_intro: bool = False,
    ) -> Optional[list]:
        """Reconcile one turn's [OPTIONS] proposal; return canonical chips to
        stamp on this message, or None. The board accumulates either way —
        suppressing display never loses the proposal (it becomes endorsement
        history instead).

        A turn WITHOUT a proposal can still render chips when the user just
        asked to choose: the prompt block forbids re-proposing known options,
        so an established axis may never be "touched" again — the ask itself
        has to be able to surface it."""
        if not _board_on:
            return proposed or None  # standalone/test sessions keep old behavior
        idx = len(session.get("history") or [])

        def _last_user_index() -> Optional[int]:
            hist = session.get("history") or []
            for j in range(len(hist) - 1, -1, -1):
                if str(hist[j].get("character") or "").lower() == "user":
                    return j
            return None

        if not proposed:
            if force_intro or not option_board.user_asked_to_choose(user_message):
                return None
            axis = option_board.active_axis(board_state)
            if axis is None:
                return None
            chips = option_board.decide_display(
                board_state,
                axis,
                force_intro=force_intro,
                phase=moderator_state.get("state") or "Exploration",
                user_message=user_message,
                msg_index=idx,
                user_msg_index=_last_user_index(),
            )
            if chips:
                option_board.save_board(_board_dir, room_id, board_state)
                log_agent_event(
                    agent_key,
                    "option_board",
                    f"axis={axis.get('id')} rendered on user ask (no proposal)",
                )
            return chips

        rec = option_board.reconcile(
            board_state, proposed, speaker=speaker_name, msg_index=idx
        )
        chips = option_board.decide_display(
            board_state,
            rec.get("axis"),
            force_intro=force_intro,
            phase=moderator_state.get("state") or "Exploration",
            user_message=user_message,
            msg_index=idx,
            user_msg_index=_last_user_index(),
        )
        option_board.save_board(_board_dir, room_id, board_state)
        axis = rec.get("axis") or {}
        log_agent_event(
            agent_key,
            "option_board",
            f"axis={axis.get('id')} added={len(rec.get('added') or [])} "
            f"endorsed={len(rec.get('endorsed') or [])} displayed={bool(chips)}",
        )
        return chips

    def _append_jsonl(fp, obj: dict) -> None:
        if fp is None:
            return
        import json

        fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fp.flush()

    _gen_seq = {"n": 0}
    _nov_seq = {"n": 0}
    _meta_probe: Dict[str, bool] = {}

    def _client_accepts_meta() -> bool:
        if "v" not in _meta_probe:
            try:
                import inspect
                _meta_probe["v"] = "meta" in inspect.signature(create_response_with_client).parameters
            except (TypeError, ValueError):
                _meta_probe["v"] = False
        return _meta_probe["v"]

    def create(client, messages: List[dict], temp: float, max_tok: int,
               meta: Optional[dict] = None, *, call_kind: str = "unknown",
               agent_key: str = "", retry_index: int = 0) -> str:
        # Always allocate a meta dict, and pass it into BOTH branches. The branch taken in
        # production is the first one; it previously discarded metadata entirely, so the
        # caller's meta stayed empty no matter what it asked for.
        m = meta if meta is not None else {}
        if create_response_with_client is not None and client is not None:
            # Injected test doubles predate the meta parameter and take (client, model,
            # messages, temp, max_tok) only. Probing the signature keeps them working and
            # keeps a genuine TypeError from inside the call from being swallowed.
            if _client_accepts_meta():
                out = create_response_with_client(client, model, messages, temp, max_tok, meta=m) or ""
            else:
                out = create_response_with_client(client, model, messages, temp, max_tok) or ""
        else:
            out = create_response(model, messages, temp, max_tok, meta=m) or ""
        log_generation(m, call_kind=call_kind, agent_key=agent_key,
                       retry_index=retry_index, output_chars=len(out))
        return out

    def log_generation(meta: dict, *, call_kind: str, agent_key: str = "",
                       retry_index: int = 0, output_chars: int = 0) -> None:
        """One row per LLM call, including calls that produce nothing visible.

        Emitted before append_agent mints a message id, and dropped turns never reach
        append_agent at all, so a row cannot carry a message_id. message_index is the
        prospective history position -- the same convention choices.jsonl uses.
        """
        _gen_seq["n"] += 1
        _append_jsonl(session.get("generation_fp"), {
            "chat_room_id": room_id,
            "time": now_local_iso(),
            "seq": _gen_seq["n"],
            "call_kind": call_kind,
            "agent": agent_key,
            "retry_index": retry_index,
            "user_turn": session.get("user_turn_count"),
            "message_index": len(session.get("history") or []),
            "model": meta.get("model") or model,
            "input_tokens": meta.get("input_tokens"),
            "output_tokens": meta.get("output_tokens"),
            "total_tokens": meta.get("total_tokens"),
            "cached_tokens": meta.get("cached_tokens"),
            "reasoning_tokens": meta.get("reasoning_tokens"),
            "status": meta.get("status"),
            "incomplete_reason": meta.get("incomplete_reason"),
            "refusal": meta.get("refusal"),
            "latency_ms": meta.get("latency_ms"),
            "output_chars": output_chars,
        })

    def log_novelty(record: dict) -> None:
        """Structured repetition-guard record. Emitted IN ADDITION to the formatted
        thinking-log strings, which two offline tests parse and must keep working."""
        _nov_seq["n"] += 1
        # seq, not turn_idx: no chat row is written for a dropped turn, so consecutive
        # drops would otherwise share one index (and land on a user row).
        _append_jsonl(session.get("novelty_fp"),
                      {"chat_room_id": room_id, "time": now_local_iso(),
                       "seq": _nov_seq["n"], **record})

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
                call_kind="memory_distill",
                agent_key=agent_key,
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

        # The generic task above is keyed on (state, mode, decision_style), so all
        # agents get one of the same SHAPE. This line is keyed on STANCE, and is
        # what makes the three voices produce structurally different content
        # instead of three phrasings of the same evaluation dimension.
        if HAVE_STANCE:
            focus = get_stance_phase_focus(
                scenario_type, agent_configs.get(agent_key, {}).get("stance"),
                lookup_state, lang)
            if focus:
                lines.append(f"What only YOU should be putting on the table this turn: {focus}")

        budget = QUESTION_BUDGET.get(lookup_state)
        if budget and not s.get("stall"):
            lines.append(budget)
        if known_context or domain_background:
            # The examples have to match the scenario (CLI-faithful): a fixed
            # employment wording pointed parent_child sessions at details that
            # do not exist in their KNOWN USER CONTEXT.
            anchor_examples = ANCHOR_EXAMPLES.get(
                scenario_type, "a stated constraint, the deadline, a named option, a ranked priority")
            lines.append(
                "Anchor this message to the user's actual case: name at least one specific detail "
                f"from KNOWN USER CONTEXT ({anchor_examples}). A statement that would read the same for "
                "any user is not a contribution. "
                "Do not re-ask for anything already listed there as filled in. "
                "If DOMAIN BACKGROUND is present, use it only to support analysis; it does not "
                "replace understanding the user's actual, specific situation, and it must not be "
                "treated as a source of concrete numbers or facts beyond what it states."
            )
        recent = [ln for ln in transcript_lines[-6:] if not ln.lower().startswith("user:")]
        if len(recent) >= 4 and not any(has_disagreement(ln) for ln in recent):
            lines.append(
                "CONSENSUS WARNING: the last several messages contained no real disagreement. "
                "Before adding anything, state plainly where your stance differs from where the "
                "group is heading, and what that direction costs the interest you represent. "
                "If you genuinely agree, name the specific sacrifice you are accepting to get there."
            )
        if HAVE_STANCE and s.get("state") == "Convergence":
            stance = agent_configs.get(agent_key, {}).get("stance")
            weight_hint = get_convergence_weight_hint(scenario_type, intake_data, stance, lang)
            if weight_hint:
                lines.append(f"Stance weighting for this closing stage: {weight_hint}")

        # Stance Knowledge — DYNAMIC channel + related_cards A-OR-B expand
        # (repeat hit of same card, or Convergence / Concluded).
        if HAVE_STANCE_KNOWLEDGE and stance_knowledge_data:
            stance = agent_configs.get(agent_key, {}).get("stance")
            li = last_user_index(transcript_lines)
            last_user_message = (
                transcript_lines[li].split(":", 1)[1].strip() if li is not None else ""
            )
            # A phase context can be rebuilt after a dropped/retried turn. Clear
            # any earlier candidate first so a future message never inherits a
            # stale badge from a generation that was not emitted.
            pending_knowledge_matches.pop(agent_key, None)
            sk_block = resolve_dynamic_stance_knowledge(
                scenario_type=scenario_type,
                stance=stance,
                last_user_message=last_user_message,
                lang=lang,
                knowledge=stance_knowledge_data,
                hit_history=session["agent_knowledge_hit_history"],
                agent_key=agent_key,
                deliberation_state=s.get("state", "Exploration"),
                on_match=lambda hit: pending_knowledge_matches.__setitem__(agent_key, hit),
            )
            if sk_block:
                lines.append(sk_block)
        return "\n".join(lines)

    def append_agent(agent: "ChatAgent", txt: str, options: Optional[list] = None) -> None:
        txt = sanitize_single_message(txt, agent.name, all_agent_names)
        opts = options if isinstance(options, list) and len(options) >= 2 else None
        msg_id = f"m-{uuid.uuid4().hex[:12]}"
        msg = {
            "id": msg_id,
            "chat_room_id": room_id,
            "time": now_local_iso(),
            "character": agent.name,
            "txt": txt,
        }
        if opts:
            msg["options"] = opts
        knowledge = pending_knowledge_matches.pop(agent.key, None)
        if knowledge:
            msg["knowledge"] = knowledge
        session.setdefault("history", []).append(msg)
        _append_jsonl(session.get("chat_fp"), msg)
        if persist_chat:
            persist_chat(msg)
        transcript_lines.append(f"{agent.name}: {txt}")
        resp = {
            "agent_key": agent.key,
            "agent": agent.name,
            "message": txt,
            "message_id": msg_id,
        }
        if opts:
            resp["options"] = opts
        if knowledge:
            resp["knowledge"] = knowledge
        responses.append(resp)
        session.setdefault("has_spoken", {})[agent.key] = True
        agent.spoke += 1
        session.setdefault("spoke_counts", {})[agent.key] = agent.spoke

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
        raw = create(client_admin, msgs, 0.0, 300,
                     call_kind="admin3_moderator", agent_key="admin3")
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

        # Convergence gate (deterministic, not asked of the LLM — CLI-faithful):
        # the group must not close before some substantive disagreement is on
        # record; otherwise it is held at Structuring with an explicit
        # instruction to surface the conflict.
        if parsed["state"] == "Convergence" and prev_state not in ("Convergence", CONCLUDED_STATE):
            agent_lines = [ln for ln in transcript_lines if not ln.lower().startswith("user:")]
            if not any(has_disagreement(ln) for ln in agent_lines):
                log_moderator(
                    "admin3_convergence_gated",
                    f"{prev_state} -> Convergence withheld: no substantive disagreement "
                    f"on record yet across {len(agent_lines)} agent turns.",
                )
                parsed = dict(parsed)
                parsed["state"] = "Structuring"
                parsed["goal"] = (
                    "Before closing: no one has actually disagreed yet. Each agent must "
                    "name where its own stance conflicts with where the group is heading, "
                    "and what that direction costs the interest it represents."
                )

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

    def enforce_novelty(
        agent: "ChatAgent",
        messages: List[dict],
        parsed: dict,
        temp: float,
        *,
        named_by_user: bool = False,
    ) -> dict:
        """Two-scope novelty guard (CLI-faithful): group (vs the recent window,
        all speakers) and self (vs this agent's OWN last N messages). Failing
        EITHER triggers one corrective retry; the retry must clear BOTH scopes
        or the turn is dropped. nov_th <= 0 is the master off switch for the
        whole guard; self_nov_th <= 0 turns off only the self scope.

        named_by_user: the user @-mentioned this agent, so the retry still runs
        (a fresher answer is better) but a failing retry is KEPT rather than
        dropped. Silence from an agent the user called on by name reads as the
        product ignoring them — measured in the roll-call baseline, where only
        1 of 3 named agents ever answered."""
        txt = parsed.get("message") or ""
        if nov_th <= 0 or not transcript_lines or not txt:
            return parsed

        own_prefix = f"{agent.name}: "

        def _scores(message: str, src_parsed: Optional[dict] = None) -> tuple:
            """(group, own, group_raw, own_raw, quote_target, quote_excluded).

            group/own exclude the reply-target's last message (the [MOVE]
            @target, falling back to body @mentions) so that engaging a claim
            is not scored as repeating it; *_raw keep the pre-exclusion
            semantics for cross-room comparability. self_ratio is 1.0 until
            this agent has spoken at least once."""
            if not message:
                return 0.0, 0.0, 0.0, 0.0, None, 0
            window = transcript_lines[-novelty_window:]
            own_lines = [ln[len(own_prefix):] for ln in transcript_lines
                         if ln.startswith(own_prefix)][-self_novelty_window:]
            group_raw = novelty_ratio(message, window)
            own_raw = novelty_ratio(message, own_lines) if own_lines else 1.0
            exclude: set = set()
            target = resolve_reply_target(
                (src_parsed or {}).get("move_detail") or "", message,
                mention_patterns, agent.key)
            if target:
                t_text = last_message_of(name_map.get(target, target), transcript_lines)
                if t_text:
                    exclude = _content_tokens(t_text)
            if not exclude:
                return group_raw, own_raw, group_raw, own_raw, None, 0
            group = novelty_ratio(message, window, exclude_tokens=exclude)
            own = (novelty_ratio(message, own_lines, exclude_tokens=exclude)
                   if own_lines else 1.0)
            return group, own, group_raw, own_raw, target, len(exclude)

        def _failing(group: float, own: float):
            """Which scope (if any) this message fails, as a short label."""
            if nov_th > 0 and group < nov_th:
                return "group"
            if self_nov_th > 0 and own < self_nov_th:
                return "self"
            return None

        def _failing_drop(group: float, own: float):
            """Same, against the (much lower) bar for discarding a retry."""
            if drop_th > 0 and group < drop_th:
                return "group"
            if drop_th > 0 and own < drop_th:
                return "self"
            return None

        def _nov_base(group: float, own: float, group_raw: float, own_raw: float,
                      quote_target, quote_excluded: int) -> dict:
            """Per-scope booleans and the RESOLVED thresholds, not a single label and not
            module constants. _failing tests group first, so a message failing BOTH scopes
            reports only "group"; and the HTTP and CLI defaults for these thresholds
            disagree, so a stored ratio is uninterpretable without the bar it was judged
            against. *_raw are the pre-quote-exclusion scores: group_ratio changed meaning
            when exclusion landed, so cross-period comparisons must use the raw fields."""
            return {
                "agent": agent.key,
                "agent_name": agent.name,
                "group_ratio": round(group, 4),
                "self_ratio": round(own, 4),
                "group_ratio_raw": round(group_raw, 4),
                "self_ratio_raw": round(own_raw, 4),
                "quote_target": quote_target,
                "quote_excluded": quote_excluded,
                "group_threshold": nov_th,
                "self_threshold": self_nov_th,
                "drop_threshold": drop_th,
                "group_window": novelty_window,
                "self_window": self_novelty_window,
                "group_failed": bool(nov_th > 0 and group < nov_th),
                "self_failed": bool(self_nov_th > 0 and own < self_nov_th),
                "named_by_user": bool(named_by_user),
            }

        ratio, self_ratio, ratio_raw, self_ratio_raw, quote_target, quote_excluded = \
            _scores(txt, parsed)
        _base = _nov_base(ratio, self_ratio, ratio_raw, self_ratio_raw,
                          quote_target, quote_excluded)
        scope = _failing(ratio, self_ratio)
        if scope is None:
            # A normally-published turn re-arms the defer exit (see below).
            session.setdefault("novelty_defer_streak", {})[agent.key] = 0
            log_novelty({**_base, "retried": False,
                         "kept": True, "dropped": False, "reason": "pass"})
            return parsed

        log_thinking(
            "novelty_retry",
            f"{agent.key}: novelty group={ratio:.2f}/{nov_th:.2f} "
            f"self={self_ratio:.2f}/{self_nov_th:.2f} — failed on {scope}, retrying once",
        )
        log_novelty({**_base, "retried": True, "kept": None,
                     "dropped": False, "reason": f"trigger:{scope}"})

        # Name the actual failure, so the retry fixes the right problem: the
        # generic "the group already has this" reads as wrong (and gets
        # ignored) when what the agent really did was repeat ITSELF.
        if scope == "self":
            diagnosis = ("That message re-states a point YOU have already made earlier in this "
                         "conversation, just worded differently. Rephrasing your own earlier "
                         "argument is not a contribution. Replace it entirely.\n")
        else:
            diagnosis = ("That message restates points the group already has on the table and adds "
                         "nothing new. Replace it entirely.\n")

        retry_messages = messages + [
            {"role": "assistant", "content": txt},
            {
                "role": "user",
                "content": (
                    diagnosis +
                    "Contribute exactly one of: a concrete comparison of two named options along one "
                    "dimension, an elimination with its reason, a direct challenge to a specific claim "
                    "someone made, a specific fact from KNOWN USER CONTEXT that nobody has cited yet, or "
                    "— only if the concrete options are not yet on the table — a new evaluation "
                    "dimension.\n"
                    "If you genuinely have nothing new, reply with ONE short sentence saying so and "
                    "naming whose point you are deferring to, and tag it [MOVE] concede @TheirName. "
                    "Either way, do not ask a question this time. "
                    # The full format, [MOVE] included: retried turns used to come back
                    # without a move self-report, which left their map edges unlabelled
                    # AND made the deferral exit above structurally unreachable.
                    "Keep the FULL required output format: [MOVE], then [RATIONALE], then [MESSAGE]."
                ),
            },
        ]
        retry_raw = create(client_chat, retry_messages, min(temp + 0.15, 1.4), max_output_tokens,
                           call_kind="novelty_retry", agent_key=agent.key, retry_index=1)
        retry_parsed = parse_agent_turn(retry_raw)
        (retry_ratio, retry_self, retry_ratio_raw, retry_self_raw,
         retry_quote_target, retry_quote_excluded) = \
            _scores(retry_parsed.get("message") or "", retry_parsed)
        _retry_base = _nov_base(retry_ratio, retry_self, retry_ratio_raw, retry_self_raw,
                                retry_quote_target, retry_quote_excluded)

        # The retry is judged against the DROP bar, not the trigger that asked
        # for it. Measured: with the two equal, 21 of 28 retries were discarded
        # and the agent simply vanished from those turns.
        retry_scope = _failing_drop(retry_ratio, retry_self)
        _retry_empty = not (retry_parsed.get("message") or "").strip()
        if retry_scope is None:
            session.setdefault("novelty_defer_streak", {})[agent.key] = 0
            log_thinking(
                "novelty_retry",
                f"{agent.key}: retry novelty group={retry_ratio:.2f} self={retry_self:.2f} (kept)",
            )
            log_novelty({**_retry_base, "retried": True, "kept": True,
                         "dropped": False, "reason": "retry_cleared_drop_bar",
                         "first_group_ratio": round(ratio, 4),
                         "first_self_ratio": round(self_ratio, 4)})
            return retry_parsed
        if named_by_user:
            log_thinking(
                "novelty_retry",
                f"{agent.key}: retry still failing {retry_scope}, but the user named this "
                f"agent — kept anyway (answering beats silence)",
            )
            log_novelty({**_retry_base, "retried": True, "kept": True,
                         "dropped": False, "reason": f"kept_named_by_user:{retry_scope}",
                         "first_group_ratio": round(ratio, 4),
                         "first_self_ratio": round(self_ratio, 4)})
            return retry_parsed
        # Explicit short deferral: [MOVE] concede @Target within the length cap.
        # Scored a deferral would always fail — it quotes the point it yields
        # to — so the check is structural, after named_by_user (full answers
        # beat hand-offs) and before the drop. The streak cap stops "always
        # concede" from becoming the universal escape hatch: a second
        # consecutive deferral by the same agent drops like before.
        defer_target = is_defer_turn(retry_parsed, mention_patterns, agent.key)
        _streaks = session.setdefault("novelty_defer_streak", {})
        if defer_target and _streaks.get(agent.key, 0) < NOVELTY_DEFER_MAX_STREAK:
            _streaks[agent.key] = _streaks.get(agent.key, 0) + 1
            log_thinking(
                "novelty_retry",
                f"{agent.key}: retry still failing {retry_scope}, but it is an explicit "
                f"deferral to {defer_target} — published as a hand-off",
            )
            log_novelty({**_retry_base, "retried": True, "kept": True,
                         "dropped": False, "reason": f"kept_defer:{retry_scope}",
                         "defer_target": defer_target,
                         "first_group_ratio": round(ratio, 4),
                         "first_self_ratio": round(self_ratio, 4)})
            return retry_parsed
        log_thinking(
            "novelty_retry",
            f"{agent.key}: retry novelty group={retry_ratio:.2f} self={retry_self:.2f}, "
            f"still failing {retry_scope} — turn dropped",
        )
        # An empty or unparseable retry scores (0.0, 0.0) via the _scores short-circuit and
        # would otherwise be filed as repetition. It is a generation failure; say so.
        _reason = "dropped:empty_retry" if _retry_empty else f"dropped:{retry_scope}"
        log_novelty({**_retry_base, "retried": True, "kept": False,
                     "dropped": True, "reason": _reason,
                     "first_group_ratio": round(ratio, 4),
                     "first_self_ratio": round(self_ratio, 4)})
        # drop_reason discriminates this from the refusal guard, which returns an identical
        # sentinel -- rationale.jsonl's turn_dropped rows could not tell them apart.
        return {"message": "", "rationale": "", "dropped": True,
                "drop_reason": _reason,
                "drop_group_ratio": round(retry_ratio, 4),
                "drop_self_ratio": round(retry_self, 4)}

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
                f"{history}{board_prompt_note()}"
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
                        stance_labels=stance_labels,
                    )
                    + get_memory_context(burst_agent.key),
                },
                {"role": "user", "content": user_prompt},
            ]
            raw = create(client_chat, messages, stall_temp, max_output_tokens,
                         call_kind="stall_burst", agent_key=burst_agent.key)
            parsed = parse_agent_turn(raw)
            txt = (parsed.get("message") or "").strip()
            if not txt:
                # Same silent-turn rule as agent_turn: no [MESSAGE] block means nothing to
                # say, and a "…" bubble reads as broken. Skip to the next burst agent.
                log_agent_event(burst_agent.key, "turn_dropped",
                                "generation carried no MESSAGE block; agent stayed silent this turn")
                continue
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
            chips = process_agent_options(
                burst_agent.key, burst_agent.name, parsed.get("options")
            )
            append_agent(burst_agent, txt, options=chips)
            # Self-reported move -> {room}_rationale.jsonl, written IMMEDIATELY after
            # the chat row. map_facts.py joins the two on (timestamp, speaker) at
            # one-second granularity, so anything between these two writes risks
            # straddling a second boundary and orphaning the event.
            if parsed.get("move"):
                log_agent_event(burst_agent.key, "move", parsed.get("move_detail") or parsed["move"])
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
        # Board goes in front of the intro note so "options on the table" reads
        # as context, not as part of the formatting instruction.
        extra = board_prompt_note() + extra
        # The turn directive comes LAST — closest to generation, after all
        # context blocks — and rides in both the mention and regular branches.
        if turn_directive:
            extra += turn_directive
        effective_temp = temperature
        if stall_triggered:
            effective_temp = min(temperature + 0.25, 1.4)
        phase_context = get_phase_context(agent.key)
        if mention_trigger:
            # Co-named agents: without this every agent in a roll-call answers
            # as if asked alone, so three near-identical replies come back and
            # the novelty guard eats two of them.
            others = [
                key_to_agent[k].name
                for k in (session.get("mention_named") or [])
                if k != agent.key and k in key_to_agent
            ]
            group_note = (
                f"The user named {len(others) + 1} of you in that message: "
                f"you and {', '.join(others)}. Give YOUR own angle — do not "
                f"restate what the others would obviously say.\n"
                if others
                else ""
            )
            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "Each line is formatted as: Speaker: message\n"
                "The user just mentioned YOU by name in their last message. "
                "Respond to the user directly first — address what they asked or said to you — "
                "before anything else. Stay in character.\n"
                f"{group_note}\n"
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
                    stance_labels=stance_labels,
                )
                + get_memory_context(agent.key),
            },
            {"role": "user", "content": user_prompt},
        ]
        raw = create(client_chat, messages, effective_temp, max_output_tokens,
                     call_kind="agent_turn", agent_key=agent.key)
        parsed = parse_agent_turn(raw)
        parsed = enforce_no_refusal(
            agent,
            messages,
            parsed,
            effective_temp,
            create_fn=lambda msgs, t, mt: create(client_chat, msgs, t, mt,
                                                 call_kind="refusal_retry",
                                                 agent_key=agent.key, retry_index=1),
            model=model,
            max_output_tokens=max_output_tokens,
            log_event=log_agent_event,
            log_think=log_thinking,
        )
        if not parsed.get("dropped"):
            parsed = enforce_novelty(
                agent, messages, parsed, effective_temp, named_by_user=mention_trigger
            )
        if parsed.get("dropped"):
            # The refusal guard and the novelty guard return identical sentinels, so this
            # row used to say "refusal or novelty" and leave the cause unrecoverable.
            # drop_reason is set only by the novelty path; its absence means refusal.
            _dr = parsed.get("drop_reason")
            if _dr:
                detail = (
                    f"novelty guard rejected the turn ({_dr}, "
                    f"group={parsed.get('drop_group_ratio')} self={parsed.get('drop_self_ratio')}); "
                    "agent stayed silent this turn"
                )
            else:
                detail = "refusal guard rejected the turn; agent stayed silent this turn"
            log_agent_event(agent.key, "turn_dropped", detail)
            maybe_run_moderator()
            return
        txt = (parsed.get("message") or "").strip()
        if not txt:
            # The call succeeded but carried no [MESSAGE] block — the model wrote only its
            # private RATIONALE and never spoke. parse_agent_turn strips private blocks, so
            # nothing visible survives. This used to publish a "…" placeholder, which read
            # to participants as a broken turn (2 of 72 logged agent messages, ~2.8%).
            # Staying silent matches how the refusal and novelty guards already drop a turn.
            log_agent_event(agent.key, "turn_dropped",
                            "generation carried no MESSAGE block; agent stayed silent this turn")
            maybe_run_moderator()
            return
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
        chips = process_agent_options(
            agent.key, agent.name, parsed.get("options"), force_intro=force_intro
        )
        append_agent(agent, txt, options=chips)
        # Self-reported move -> {room}_rationale.jsonl, written IMMEDIATELY after
        # the chat row. map_facts.py joins the two on (timestamp, speaker) at
        # one-second granularity, so anything between these two writes risks
        # straddling a second boundary and orphaning the event.
        if parsed.get("move"):
            log_agent_event(agent.key, "move", parsed.get("move_detail") or parsed["move"])
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
        admin1_out = create(client_admin, admin1_messages, 0.2, 260,
                            call_kind="admin1", agent_key="admin1")
        log_thinking("admin1", admin1_out or "")
        admin2_messages = [
            {"role": "system", "content": admin2_system},
            {"role": "user", "content": admin1_out or ""},
        ]
        admin2_out = (create(client_admin, admin2_messages, 0.0, MIN_OUTPUT_TOKENS,
                             call_kind="admin2", agent_key="admin2") or "").strip().upper()
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

    if turn_directive:
        # One row per affected user turn: the study-side filter for "was the
        # low-content contract active here". Old rooms have no such row.
        log_thinking("turn_directive", "low_content contract active for this turn")

    if moderator_state.get("state") == CONCLUDED_STATE:
        moderator_state["state"] = "Convergence"
        moderator_state["goal"] = ""
        log_moderator(
            "admin3_reopened",
            "User spoke after Concluded — back to Convergence for re-classification.",
        )

    mentioned = parse_mentions(user_message or "", mention_patterns)
    # Roll-call roster for this user turn: each named agent is told who else
    # was named, so they angle their answers instead of colliding.
    session["mention_named"] = list(mentioned)
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
            # CLI-faithful: queued mentions are honored even if the moderator
            # latched to Concluded mid-burst — the loop re-checks the queue
            # first, and only an EMPTY queue lets Concluded stop the burst.
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
    ap.add_argument("--max_output_tokens", type=int, default=520,
                    help="One generation carries four blocks: MOVE, RATIONALE, MESSAGE, OPTIONS. "
                         "Raised 220 -> 320 in logs/316347, then 320 -> 520 after room 001999, "
                         "where messages alone measured 174-317 tokens and every turn past ~250 "
                         "lost its trailing block (4 of 6). MOVE and RATIONALE now lead the format "
                         "so a squeeze truncates prose rather than metadata, but the budget also "
                         "has to fit the prose. Watch for TRUNCATED in the rationale log if you "
                         "lower it. Default 520")
    ap.add_argument("--max_history_chars", type=int, default=12000)
    ap.add_argument("--log_dir", default="logs", help="Directory to write jsonl logs")
    ap.add_argument("--prefer_agents", type=float, default=0.85,
                    help="Probability to override Admin output to an agent when it picks U (0..1). Default 0.85")
    ap.add_argument("--max_user_gap", type=int, default=12,
                    help="Force U if user hasn't spoken in this many transcript lines. Default 12")

    # ---- Message quality guards ----
    ap.add_argument("--novelty_threshold", type=float, default=0.4,
                    help="If a reply's share of content words unseen in the recent transcript falls "
                         "below this, the agent gets one corrective retry (one extra API call); if "
                         "the retry still misses the bar the turn is DROPPED and the agent stays "
                         "silent. 0 disables the check. Calibrated on logs/442575: clear "
                         "restatements scored 0.19-0.44, genuine contributions 0.55-0.69. Raised "
                         "from 0.35 to 0.5 after logs/316347. Note the bigger change is the drop "
                         "rule: retries used to be kept merely for scoring better than the "
                         "original (0.52 > 0.00 was 'kept'), independently of this threshold. "
                         "Default 0.5")
    ap.add_argument("--novelty_drop_threshold", type=float, default=0.25,
                    help="A retried reply is DISCARDED (the agent stays silent) only below this "
                         "much lower bar. Measured over 7 rooms: when the drop bar equalled the "
                         "retry trigger (0.5), 21 of 28 retries were discarded — agents went "
                         "silent on three quarters of the turns they were asked to redo, and 11 "
                         "of 28 retries scored WORSE than the first attempt because engaging with "
                         "a specific claim necessarily reuses that claim's words. At 0.25 only 3 "
                         "of those 28 are discarded: silence now requires near-verbatim repetition, "
                         "not merely a middling score. 0 disables dropping entirely.")
    ap.add_argument("--novelty_window", type=int, default=10,
                    help="How many recent transcript lines the novelty check compares against. Short "
                         "enough that a deliberate callback to something said 20 turns ago isn't "
                         "penalized. Default 10")
    ap.add_argument("--self_novelty_threshold", type=float, default=0.35,
                    help="Second novelty scope: how much of a reply must be new relative to THIS "
                         "agent's own recent messages (not the whole room). Catches cross-turn "
                         "self-repetition, which --novelty_threshold structurally cannot: with 3 "
                         "agents an agent's own turns are only every third line, so a 10-line "
                         "all-speaker window holds just 2-3 of them and anything older could be "
                         "re-served in new wording unflagged. Lower than --novelty_threshold on "
                         "purpose — scoring one voice against its own accumulated vocabulary yields "
                         "structurally lower ratios. 0 disables this scope; --novelty_threshold 0 "
                         "still disables the whole guard including this one. Default 0.35")
    ap.add_argument("--self_novelty_window", type=int, default=6,
                    help="How many of the agent's OWN past messages the self-novelty scope compares "
                         "against. Bounded so an agent isn't scored against an ever-growing pile of "
                         "its own vocabulary (which would eventually reject everything). Default 6")

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
            allow_soft=True,  # a setup hint is short by design ("跳槽", "手机")
        ) if hint else ""

    # Short "represents X" phrase per agent, for the generated cast list in the
    # prompt roster. Empty for scenarios that use no stances.
    stance_labels: Dict[str, str] = {}
    if HAVE_STANCE:
        for key in agent_keys:
            label = get_stance_label(args.scenario_type,
                                     agent_configs.get(key, {}).get("stance"), args.lang)
            if label:
                stance_labels[key] = label

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

        # The generic task above is keyed on (state, mode, decision_style), so all
        # agents get one of the same SHAPE. This line is keyed on STANCE, and is
        # what makes the three voices produce structurally different content
        # instead of three phrasings of the same evaluation dimension.
        if HAVE_STANCE:
            focus = get_stance_phase_focus(
                args.scenario_type, agent_configs.get(agent_key, {}).get("stance"),
                lookup_state, args.lang)
            if focus:
                lines.append(f"What only YOU should be putting on the table this turn: {focus}")

        budget = QUESTION_BUDGET.get(lookup_state)
        if budget and not s["stall"]:
            lines.append(budget)

        if known_context or domain_background:
            # The examples have to match the scenario. They used to be hardcoded
            # to the employment case ("salary/level/location, the career stage"),
            # which in a parent_child session pointed the model at details that
            # do not exist in its KNOWN USER CONTEXT.
            anchor_examples = ANCHOR_EXAMPLES.get(
                args.scenario_type, "a stated constraint, the deadline, a named option, a ranked priority")
            lines.append(
                "Anchor this message to the user's actual case: name at least one specific detail "
                f"from KNOWN USER CONTEXT ({anchor_examples}). A statement that would read the same for "
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

        # Convergence gate (deterministic, not asked of the LLM): three agents
        # holding three opposed stances must not close before they have actually
        # disagreed even once. Without this the group "converges" on turn 5 by
        # agreeing with each other — which is the premature-convergence failure,
        # and also what precedes the model refusing a turn outright once the chat
        # slides into telling the user what to do about an already-settled choice.
        # Held at Structuring with an explicit instruction to surface the conflict.
        if parsed["state"] == "Convergence" and prev_state not in ("Convergence", CONCLUDED_STATE):
            agent_lines = [ln for ln in transcript_lines if not ln.startswith("user:")]
            if not any(has_disagreement(ln) for ln in agent_lines):
                log_moderator("admin3_convergence_gated",
                              f"{prev_state} -> Convergence withheld: no substantive disagreement "
                              f"on record yet across {len(agent_lines)} agent turns.")
                parsed = dict(parsed)
                parsed["state"] = "Structuring"
                parsed["goal"] = ("Before closing: no one has actually disagreed yet. Each agent must "
                                  "name where its own stance conflicts with where the group is heading, "
                                  "and what that direction costs the interest it represents.")

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
                    preloaded_knowledge_text=agent_configs[burst_agent.key].get("preloaded_knowledge", ""),
                    stance_labels=stance_labels)
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
            # Self-reported move -> {room}_rationale.jsonl, written IMMEDIATELY after
            # the chat row. map_facts.py joins the two on (timestamp, speaker) at
            # one-second granularity, so anything between these two writes risks
            # straddling a second boundary and orphaning the event.
            if parsed.get("move"):
                log_agent_event(burst_agent.key, "move", parsed.get("move_detail") or parsed["move"])
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
                    preloaded_knowledge_text=agent_configs[agent.key].get("preloaded_knowledge", ""),
                    stance_labels=stance_labels)
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
            # Self-reported move -> {room}_rationale.jsonl, written IMMEDIATELY after
            # the chat row. map_facts.py joins the two on (timestamp, speaker) at
            # one-second granularity, so anything between these two writes risks
            # straddling a second boundary and orphaning the event.
            if parsed.get("move"):
                log_agent_event(agent.key, "move", parsed.get("move_detail") or parsed["move"])
            maybe_distill_snippet(agent.key, txt, stall_active=stall_triggered)

            # After the triggering agent speaks, run the burst for remaining agents
            if stall_triggered:
                stall_burst(trigger_key=agent.key)

            maybe_run_moderator()
            return True

        # Per-agent defer streak (CLI has no session dict; HTTP keeps its own
        # in session["novelty_defer_streak"]).
        novelty_defer_streak: Dict[str, int] = {}

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

            TWO SCOPES, because one was not enough. The original check compared
            only against transcript_lines[-novelty_window:] — the last N lines
            from ALL speakers. With three agents taking turns, an agent's own
            previous message is roughly every third line, so a 10-line window
            held only its own last 2-3 turns. Anything it had argued before that
            fell out of the window and could be re-served in new wording without
            ever being flagged — the observed "cross-turn self-repetition". So a
            message is now scored twice:
              group : vs the recent window, all speakers  -> echoing the room
              self  : vs this agent's OWN last N messages -> repeating yourself
            Failing EITHER triggers the corrective retry. The self scope needs
            its own, lower threshold: it compares against a single voice's
            accumulated vocabulary, so its scores run structurally lower than the
            group scope's and reusing the same number would silence everyone.
            """
            txt = parsed["message"]
            if not transcript_lines or not txt:
                return parsed
            # --novelty_threshold 0 stays the documented master off switch for the
            # whole guard (both scopes), so existing "disable novelty" invocations
            # keep meaning that. --self_novelty_threshold 0 turns off only the
            # self scope.
            if args.novelty_threshold <= 0:
                return parsed

            own_prefix = f"{agent.name}: "

            def _scores(message: str, src_parsed: Optional[dict] = None) -> tuple:
                """(group, own, group_raw, own_raw, quote_target, quote_excluded).
                Same quote-exclusion semantics as the HTTP twin: the reply-target's
                last message does not count against novelty; *_raw keep the old
                meaning. self_ratio is 1.0 until this agent has spoken."""
                if not message:
                    return 0.0, 0.0, 0.0, 0.0, None, 0
                window = transcript_lines[-args.novelty_window:]
                own_lines = [ln[len(own_prefix):] for ln in transcript_lines
                             if ln.startswith(own_prefix)][-args.self_novelty_window:]
                group_raw = novelty_ratio(message, window)
                own_raw = novelty_ratio(message, own_lines) if own_lines else 1.0
                exclude: set = set()
                target = resolve_reply_target(
                    (src_parsed or {}).get("move_detail") or "", message,
                    mention_patterns, agent.key)
                if target:
                    t_text = last_message_of(name_map.get(target, target), transcript_lines)
                    if t_text:
                        exclude = _content_tokens(t_text)
                if not exclude:
                    return group_raw, own_raw, group_raw, own_raw, None, 0
                group = novelty_ratio(message, window, exclude_tokens=exclude)
                own = (novelty_ratio(message, own_lines, exclude_tokens=exclude)
                       if own_lines else 1.0)
                return group, own, group_raw, own_raw, target, len(exclude)

            def _failing(group: float, own: float):
                """Which scope (if any) this message fails, as a short label."""
                if args.novelty_threshold > 0 and group < args.novelty_threshold:
                    return "group"
                if args.self_novelty_threshold > 0 and own < args.self_novelty_threshold:
                    return "self"
                return None

            def _failing_drop(group: float, own: float):
                """Same, against the much lower bar for DISCARDING a retry."""
                bar = args.novelty_drop_threshold
                if bar > 0 and group < bar:
                    return "group"
                if bar > 0 and own < bar:
                    return "self"
                return None

            ratio, self_ratio, _g_raw, _s_raw, _q_target, _q_excluded = _scores(txt, parsed)
            scope = _failing(ratio, self_ratio)
            if scope is None:
                novelty_defer_streak[agent.key] = 0
                return parsed

            log_thinking("novelty_retry",
                         f"{agent.key}: novelty group={ratio:.2f}/{args.novelty_threshold:.2f} "
                         f"self={self_ratio:.2f}/{args.self_novelty_threshold:.2f} — "
                         f"failed on {scope}, retrying once"
                         # Appended, never inserted: test_self_novelty matches prefix substrings.
                         f" (raw group={_g_raw:.2f} quote_target={_q_target} excluded={_q_excluded})")

            # Name the actual failure, so the retry fixes the right problem: the
            # generic "the group already has this" reads as wrong (and gets
            # ignored) when what the agent really did was repeat ITSELF.
            if scope == "self":
                diagnosis = ("That message re-states a point YOU have already made earlier in this "
                             "conversation, just worded differently. Rephrasing your own earlier "
                             "argument is not a contribution. Replace it entirely.\n")
            else:
                diagnosis = ("That message restates points the group already has on the table and adds "
                             "nothing new. Replace it entirely.\n")

            retry_messages = messages + [
                {"role": "assistant", "content": txt},
                {"role": "user", "content": (
                    diagnosis +
                    "Contribute exactly one of: a concrete comparison of two named options along one "
                    "dimension, an elimination with its reason, a direct challenge to a specific claim "
                    "someone made, a specific fact from KNOWN USER CONTEXT that nobody has cited yet, or "
                    "— only if the concrete options are not yet on the table — a new evaluation "
                    "dimension.\n"
                    "If you genuinely have nothing new, reply with ONE short sentence saying so and "
                    "naming whose point you are deferring to, and tag it [MOVE] concede @TheirName. "
                    "Either way, do not ask a question this time. "
                    "Keep the FULL required output format: [MOVE], then [RATIONALE], then [MESSAGE]."
                )},
            ]
            meta: dict = {}
            retry_raw = create_response(args.model, retry_messages,
                                        min(temp + 0.15, 1.4), args.max_output_tokens, meta=meta)
            log_generation_meta(agent.key, meta, note="novelty retry")
            retry_parsed = parse_agent_turn(retry_raw)
            retry_ratio, retry_self, _rg_raw, _rs_raw, _rq_target, _rq_excluded = \
                _scores(retry_parsed["message"], retry_parsed)

            # The retry is the last chance: it must clear BOTH scopes on its own,
            # or the agent says nothing at all. The old rule kept a retry whenever
            # it merely scored HIGHER than the original — in logs/316347 that
            # published 0.50 and 0.52 rewrites of 0.00 turns, i.e. content the
            # guard itself had flagged as recycled, promoted purely for being less
            # bad. Silence is an allowed turn (the system prompt says so
            # explicitly); a rephrased restatement is not.
            # …but the bar for throwing the retry AWAY is far lower than the one
            # that asked for it. Measured over 7 rooms with the two equal: 21 of
            # 28 retries discarded, and 11 of 28 scored worse than the original
            # because engaging a specific claim reuses that claim's words.
            retry_scope = _failing_drop(retry_ratio, retry_self)
            if retry_scope is None:
                novelty_defer_streak[agent.key] = 0
                log_thinking("novelty_retry",
                             f"{agent.key}: retry novelty group={retry_ratio:.2f} "
                             f"self={retry_self:.2f} (kept)")
                return retry_parsed
            # Same structural defer exit as the HTTP twin: a short explicit
            # [MOVE] concede @Target hand-off publishes instead of vanishing,
            # at most once in a row per agent.
            defer_target = is_defer_turn(retry_parsed, mention_patterns, agent.key)
            if defer_target and novelty_defer_streak.get(agent.key, 0) < NOVELTY_DEFER_MAX_STREAK:
                novelty_defer_streak[agent.key] = novelty_defer_streak.get(agent.key, 0) + 1
                log_thinking("novelty_retry",
                             f"{agent.key}: retry still failing {retry_scope}, but it is an "
                             f"explicit deferral to {defer_target} — kept as a hand-off")
                return retry_parsed
            log_thinking("novelty_retry",
                         f"{agent.key}: retry novelty group={retry_ratio:.2f} self={retry_self:.2f}, "
                         f"still failing {retry_scope} — turn dropped")
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


def create_response_with_client(client, model: str, messages: List[dict], temperature: float,
                                max_output_tokens: int, meta: Optional[dict] = None) -> str:
    """meta: filled in-place, same contract as create_response.

    This is the branch the HTTP server actually takes in production -- app.py always
    supplies create_response_with_client and get_openai_clients() always returns a live
    client. Wiring metadata only into create_response would leave the product path silent
    while still looking correct in tests that omit the client.
    """
    max_output_tokens = max(int(max_output_tokens), MIN_OUTPUT_TOKENS)
    if meta is None:
        meta = {}
    _t0 = time.perf_counter()
    resp = client.responses.create(
        model=model, input=messages,
        max_output_tokens=max_output_tokens,
        **_sampling_params(model, temperature),
    )
    meta["latency_ms"] = int((time.perf_counter() - _t0) * 1000)
    _collect_meta_sdk(resp, meta)
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
