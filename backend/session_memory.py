# -*- coding: utf-8 -*-
"""
session_memory.py

Cross-session memory: carry a short summary of the last few sessions into the
next one, so the agents "remember" where the discussion left off without the
user having to re-explain anything. This is implicit auto-carry, NOT a
user-facing history query.

Storage: memory/{user_id}__{scenario_type}.jsonl — one JSON record per line,
append-only (a new session adds a line, never rewrites the file):
    {
      "session_id": "...",
      "date": "...",
      "summary": "3-5 sentence recap of what was discussed / user leaning / "
                 "what was left unresolved",
      "open_threads": ["topic not yet explored", ...]
    }

Reading is deliberately trivial — just the last few lines of jsonl. No
retrieval, no vectorization (a user runs ~3 sessions a week; the data is tiny).

The single extra LLM call this feature adds (the end-of-session summary) reuses
the caller's existing create_response(); this module never builds its own API
client. Pass create_response in via summarize_session().
"""
from __future__ import annotations

import json
import os
from typing import Callable, List, Optional

from lang_utils import normalize_lang

MEMORY_DIR_DEFAULT = "memory"


def memory_path(user_id: str, scenario_type: str, dir_path: str = MEMORY_DIR_DEFAULT) -> str:
    """memory/{user_id}__{scenario_type}.jsonl — double underscore separates the
    two keys so a normal user_id/scenario_type (no '__') round-trips cleanly."""
    return os.path.join(dir_path, f"{user_id or 'anonymous'}__{scenario_type}.jsonl")


# ---------------------------------------------------------------- read side
def load_recent_sessions(
    user_id: str,
    scenario_type: str,
    limit: int = 3,
    dir_path: str = MEMORY_DIR_DEFAULT,
) -> List[dict]:
    """Return up to `limit` most-recent session records (oldest -> newest).

    Empty list when there is no user_id/scenario_type or no file yet (first-ever
    session for this pair). Malformed lines are skipped, not fatal.
    """
    if not user_id or not scenario_type:
        return []
    path = memory_path(user_id, scenario_type, dir_path)
    if not os.path.exists(path):
        return []
    records: List[dict] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records[-limit:] if limit and limit > 0 else records


def build_session_memory_text(records: List[dict], lang: str = "zh") -> str:
    """Concatenate recent session summaries into one injectable block, or "" if
    there are none. Injected at the same level as KNOWN USER CONTEXT /
    DOMAIN BACKGROUND, and clearly labeled as prior-session recap, not new input.
    """
    if not records:
        return ""
    lang = normalize_lang(lang)
    if lang == "zh":
        header = "=== 上次会话记忆（前几次讨论的摘要，非本次用户输入）==="
        threads_label = "尚未讨论"
        sep = "；"
    else:
        header = "=== PREVIOUS SESSION MEMORY (summary of last session(s), not new user input) ==="
        threads_label = "Open threads"
        sep = "; "
    parts = [header]
    for r in records:
        summary = (r.get("summary") or "").strip()
        threads = [t for t in (r.get("open_threads") or []) if str(t).strip()]
        date = str(r.get("date", "")).strip()
        if summary:
            parts.append(f"[{date}] {summary}" if date else summary)
        if threads:
            joiner = "：" if lang == "zh" else ": "
            parts.append(f"{threads_label}{joiner}{sep.join(str(t).strip() for t in threads)}")
    return "\n".join(parts)


# ---------------------------------------------------------------- write side
def _build_summary_messages(transcript_text: str, lang: str) -> List[dict]:
    # Prompt AND output are always English, regardless of the session language.
    # `lang` is kept in the signature for API stability / future use.
    system = (
        "You are a conversation-archival assistant. Below is the full transcript of a "
        "multi-agent deliberation. Output ONLY one JSON object, with no extra text or code "
        "fences, with these fields:\n"
        '  "summary": 3-5 sentences recapping the core of the discussion — where it got to, '
        "what the user leaned toward, and what was left unresolved;\n"
        '  "open_threads": an array of strings listing topics raised but not yet explored or '
        "concluded (empty array if none).\n"
        'Write the values of "summary" and each item of "open_threads" in English.\n'
        "Write the summary as an objective recap of the previous session for the next one to "
        "reference, not as advice to the user."
    )
    user = f"Full transcript:\n\n{transcript_text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _parse_summary_output(raw: str) -> dict:
    """Pull {summary, open_threads} out of the model's reply. Tolerates a stray
    code fence or surrounding prose by grabbing the outermost {...}."""
    text = (raw or "").strip()
    if not text:
        return {"summary": "", "open_threads": []}
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            summary = str(obj.get("summary", "")).strip()
            threads = obj.get("open_threads", [])
            if not isinstance(threads, list):
                threads = [str(threads)] if threads else []
            threads = [str(t).strip() for t in threads if str(t).strip()]
            return {"summary": summary, "open_threads": threads}
        except json.JSONDecodeError:
            pass
    # Fallback: keep the raw text as the summary so nothing is silently lost.
    return {"summary": text, "open_threads": []}


def summarize_session(
    transcript_text: str,
    lang: str,
    create_response: Callable,
    model: str,
    max_output_tokens: int = 400,
    temperature: float = 0.3,
) -> dict:
    """One LLM call (via the caller's create_response) that turns the full
    transcript into {"summary": str, "open_threads": [str, ...]}.

    create_response is expected to have the same signature the main script uses:
        create_response(model, messages, temperature, max_output_tokens) -> str
    """
    if not (transcript_text or "").strip():
        return {"summary": "", "open_threads": []}
    messages = _build_summary_messages(transcript_text, lang)
    raw = create_response(model, messages, temperature, max_output_tokens)
    return _parse_summary_output(raw)


def append_session_record(
    user_id: str,
    scenario_type: str,
    session_id: str,
    date: str,
    summary: str,
    open_threads: List[str],
    dir_path: str = MEMORY_DIR_DEFAULT,
) -> Optional[dict]:
    """Append one record to memory/{user_id}__{scenario_type}.jsonl (creating the
    dir/file as needed). Returns the record, or None if there is nothing to save.
    """
    if not user_id or not scenario_type:
        return None
    if not (summary or "").strip() and not open_threads:
        return None
    os.makedirs(dir_path, exist_ok=True)
    record = {
        "session_id": session_id,
        "date": date,
        "summary": summary,
        "open_threads": open_threads or [],
    }
    with open(memory_path(user_id, scenario_type, dir_path), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
