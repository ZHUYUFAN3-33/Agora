# -*- coding: utf-8 -*-
"""
turn_summaries.py — per-turn incremental summaries for the decision map.

The old map ran ONE whole-transcript extraction per open: a single LLM call
was responsible for the entire graph, so one lazy generation emptied the whole
map (observed live: a 10-turn deliberation reduced to 1 issue + 1 claim).
This module inverts the contract: each TURN gets its own one-line summary,
keywords and an optional stance reading, generated in one batched call for
whatever turns are still missing, and cached permanently — a published chat
row never changes, so its summary never has to be recomputed.

Failure model: everything degrades per-turn. A malformed row in the LLM
answer, a failed call, a missing file — the map renders that turn with a
truncated raw-text fallback instead of a summary. The map can no longer go
empty because of one bad generation.

Cache: {room}_turn_summaries.jsonl, append-only. One row per turn:
  {turn_id, index, text_hash, schema, lang, summary, keywords[],
   stances:[{option_id, sign, quote}], model, time}
Newest row per (turn_id, lang) wins; text_hash guards against transcript
rewrites and `schema` against contract changes (both re-annotate rather than
lie about what an old row means).

WHY stances IS A LIST: it used to be a single {option_id, sign} and the prompt
said "one specific option; otherwise null" — which silenced precisely the turns
doing the comparison work. Measured on room 001999: 4 of 4 turns whose summary
reads "…of both options" carried a null stance, leaving 3 of 10 turns with any
position at all. A turn that weighs two options now emits one entry per option,
which is what makes a per-option case-for/case-against ledger fillable.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from lang_utils import normalize_lang

SUMMARY_MODEL = "gpt-4o"
MAX_BATCH_TURNS = 40          # per LLM call; long rooms take several calls
SUMMARY_MAX_WORDS = 24        # hard trim on our side, prompt asks for ≤18
QUOTE_MAX_WORDS = 20
MAX_STANCES_PER_TURN = 4

# Bump when the row contract changes: cached rows written under an older
# schema are re-annotated instead of being silently reinterpreted.
SCHEMA_VERSION = 3

LANG_NAME = {"en": "English", "zh": "Chinese (中文)", "ja": "Japanese (日本語)"}

STANCE_SIGNS = ("support", "concern")

# Summaries that describe what a turn is ABOUT instead of what it SAYS.
# Measured: 6 of 6 agent summaries in room 001999 opened with one of these
# ("ChatbotB analyzes financial security of both options" tells the reader
# nothing), which is a wasted card on every single turn.
META_VERBS = (
    "discusses", "analyzes", "analyses", "examines", "explores", "addresses",
    "compares", "highlights", "considers", "evaluates", "reviews", "outlines",
    "talks about", "describes", "mentions that", "elaborates",
    "讨论", "分析", "探讨", "评估", "阐述", "介绍", "谈到", "比较了",
)


def summaries_path(log_dir: str, room_id: str) -> str:
    return os.path.join(log_dir, f"{room_id}_turn_summaries.jsonl")


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def load_summaries(log_dir: str, room_id: str, *, lang: Optional[str] = None) -> Dict[str, dict]:
    """Newest cached row per turn_id (optionally only rows for `lang`)."""
    path = summaries_path(log_dir, room_id)
    if not os.path.exists(path):
        return {}
    want = normalize_lang(lang) if lang else None
    out: Dict[str, dict] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict) or not row.get("turn_id"):
                    continue
                if want and normalize_lang(str(row.get("lang") or "")) != want:
                    continue
                out[str(row["turn_id"])] = row
    except OSError:
        return {}
    return out


def _append_rows(log_dir: str, room_id: str, rows: List[dict]) -> None:
    if not rows:
        return
    os.makedirs(log_dir, exist_ok=True)
    with open(summaries_path(log_dir, room_id), "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _trim(text: str, max_words: int, max_chars: int) -> str:
    one = " ".join((text or "").split())
    words = one.split(" ")
    if len(words) > max_words:
        one = " ".join(words[:max_words]) + "…"
    return one[:max_chars]


def _trim_summary(text: str) -> str:
    return _trim(text, SUMMARY_MAX_WORDS, 160)


def is_meta_summary(text: str) -> bool:
    """True when the summary describes the turn instead of stating it."""
    low = (text or "").strip().lower()
    if not low:
        return False
    return any(v in low for v in META_VERBS)


def _batch_prompt(
    turns: List[dict],
    need_indexes: List[int],
    options: List[dict],
    lang: str,
) -> List[dict]:
    lang_name = LANG_NAME.get(lang, "English")
    opt_lines = "\n".join(
        f'- id "{o["id"]}": {o["label"]}' for o in options
    ) or "(none yet)"
    transcript = "\n".join(
        f"[{t['index']}] {t['speaker']}: {t['txt']}" for t in turns if (t.get("txt") or "").strip()
    )
    need = ", ".join(str(i) for i in need_indexes)
    system = (
        "You annotate decision-deliberation transcripts, one annotation per turn. "
        "Output strictly a JSON array, no code fences, no commentary."
    )
    user = (
        f"OPTIONS ON THE TABLE:\n{opt_lines}\n\n"
        f"TRANSCRIPT:\n{transcript}\n\n"
        f"Annotate ONLY these turn indexes: [{need}]\n"
        "For each, output an object:\n"
        '{"index": <int>, "summary": "what this turn actually says, ≤18 words", '
        '"keywords": ["3-4 short keywords naming what THIS speaker argues, never the option they argue against"], '
        '"stances": [{"option_id": "<id from OPTIONS>", "sign": "support|concern", '
        '"quote": "the specific point about THIS option, ≤15 words"}]}\n'
        "Rules:\n"
        f"1) summary, keywords and quotes in {lang_name}. Factual, no invention, no praise filler.\n"
        "2) summary states the SUBSTANCE — the claim, trade-off, question or decision. "
        "NEVER write what the turn is 'about'. Banned openings: discusses / analyzes / "
        "examines / explores / addresses / compares / highlights / considers / evaluates. "
        "Write 'BigTech pays more but grows you slower', not 'discusses growth and pay'. "
        "Say what THIS speaker is arguing. Only name both options when the speaker "
        "genuinely gave them equal weight — do not force every summary into the same "
        "'X offers A; Y offers B' shape.\n"
        "3) stances: ONE ENTRY PER OPTION this turn takes a position on. A turn that argues "
        "both sides of two options emits TWO entries — one per option — not zero. "
        "sign=support when the point is a reason to pick that option, sign=concern when it is "
        "a cost, risk or doubt about it. quote is that specific point, standing on its own. "
        "Use [] only for pure procedure (greetings, 'let me look into that') with no substance.\n"
        "4) One object per requested index. No extra indexes.\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _parse_batch(raw: str) -> List[dict]:
    body = (raw or "").strip()
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
    return data if isinstance(data, list) else []


def ensure_turn_summaries(
    log_dir: str,
    room_id: str,
    turns: List[dict],
    *,
    lang: str,
    options: Optional[List[dict]] = None,
    create_response: Optional[Callable[..., str]] = None,
    model: str = SUMMARY_MODEL,
) -> Dict[str, dict]:
    """Return {turn_id: summary_row} covering as many turns as possible.

    Generates summaries for turns that have none cached (or whose text
    changed), one batched call per MAX_BATCH_TURNS. With create_response=None
    (or on any failure) it returns whatever the cache already has — callers
    always fall back to raw text for the rest.
    """
    lang = normalize_lang(lang)
    cached = load_summaries(log_dir, room_id, lang=lang)
    option_ids = {str(o.get("id")) for o in (options or [])}

    need: List[dict] = []
    for t in turns:
        txt = (t.get("txt") or "").strip()
        if not txt:
            continue
        row = cached.get(str(t["id"]))
        fresh = (
            row
            and row.get("text_hash") == _text_hash(txt)
            and int(row.get("schema") or 1) >= SCHEMA_VERSION
            and (row.get("summary") or "").strip()
        )
        if fresh:
            continue
        need.append(t)

    if not need or create_response is None:
        return cached

    for start in range(0, len(need), MAX_BATCH_TURNS):
        chunk = need[start : start + MAX_BATCH_TURNS]
        need_indexes = [t["index"] for t in chunk]
        by_index = {t["index"]: t for t in chunk}
        try:
            raw = create_response(
                model,
                _batch_prompt(turns, need_indexes, options or [], lang),
                0.2,
                2400,
            )
        except Exception:
            break  # keep whatever we have; map falls back to raw text
        rows_out: List[dict] = []
        for item in _parse_batch(raw):
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            turn = by_index.get(idx)
            if turn is None:
                continue
            summary = _trim_summary(str(item.get("summary") or ""))
            if not summary:
                continue
            keywords = [
                str(k).strip()[:24]
                for k in (item.get("keywords") or [])
                if isinstance(k, (str, int)) and str(k).strip()
            ][:4]
            # One entry per option; a repeat option in the same turn keeps the
            # first reading rather than letting a turn vote twice.
            stances: List[dict] = []
            seen_opts: set = set()
            raw_stances = item.get("stances")
            if isinstance(item.get("stance"), dict) and not raw_stances:
                raw_stances = [item["stance"]]  # tolerate the old singular key
            for s in raw_stances or []:
                if not isinstance(s, dict):
                    continue
                oid = str(s.get("option_id") or "")
                sign = str(s.get("sign") or "").strip().lower()
                if oid not in option_ids or sign not in STANCE_SIGNS or oid in seen_opts:
                    continue
                seen_opts.add(oid)
                stances.append({
                    "option_id": oid,
                    "sign": sign,
                    "quote": _trim(str(s.get("quote") or ""), QUOTE_MAX_WORDS, 140) or None,
                })
                if len(stances) >= MAX_STANCES_PER_TURN:
                    break
            row = {
                "turn_id": str(turn["id"]),
                "index": idx,
                "text_hash": _text_hash(turn.get("txt") or ""),
                "schema": SCHEMA_VERSION,
                "lang": lang,
                "summary": summary,
                "keywords": keywords,
                "stances": stances,
                "meta_summary": is_meta_summary(summary),
                "model": model,
                "time": datetime.now().isoformat(timespec="seconds"),
            }
            rows_out.append(row)
            cached[row["turn_id"]] = row
        _append_rows(log_dir, room_id, rows_out)
    return cached
