# -*- coding: utf-8 -*-
"""
decision_map.py — IBIS Decision Map (LLM-first)

Canvas schema:
  {
    room_id, lang,
    issues: [{id, label, parent_id?, status, winning_claim_id?, phase?, summary?}],
    claims: [{id, issue_id, speaker, text, badge?, message_indexes}],
    edges: [{id, type: emerged_from|supports|opposes, from, to}],
    annotations, phase_spine, room_leaning,
    insufficient: bool, extracted: bool
  }

Open map → smart extract. Too few messages → insufficient (no LLM, no fake graph).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from lang_utils import normalize_lang

MIN_USER_MSGS = 2
MIN_AGENT_MSGS = 3
MIN_TOTAL_MSGS = 6

IBIS_EDGE_TYPES = frozenset({"emerged_from", "supports", "opposes", "chooses"})
ISSUE_STATUSES = frozenset({"open", "leaning", "settled"})
OPTION_STATUSES = frozenset({"open", "leaning", "chosen", "rejected"})

LABEL_MAX = 48

ISSUE_FALLBACK_LABEL = {
    "zh": "当前抉择",
    "en": "Current choice",
    "ja": "いまの選択",
}

IBIS_PROMPT = {
    "zh": (
        "你在从一场决策讨论中抽取 IBIS 风格决策地图。只根据原文，禁止编造。\n"
        "【语言】所有面向用户的字段必须用中文撰写：issues.label、issues.summary、"
        "claims.text、room_leaning.direction、room_leaning.strength。"
        "即使原文是英文/日文，也要用中文概括（不要照抄英文）。"
        "speaker 可保留原角色名；status / edge.type / phase 枚举值保持英文代码。\n"
        "严格输出一个 JSON 对象（不要代码块）：\n"
        "{\n"
        '  "issues": [{"id":"issue_1","label":"短标题","parent_id":null,'
        '"status":"open|leaning|settled","winning_claim_id":null,"phase":"Exploration|Structuring|Narrowing|Convergence|null","summary":"一句话题意"}],\n'
        '  "claims": [{"id":"claim_1","issue_id":"issue_1","speaker":"user或角色名",'
        '"text":"可核对的主张一句（中文）","badge":null,"message_indexes":[0]}],\n'
        '  "edges": [{"id":"e1","type":"emerged_from|supports|opposes","from":"…","to":"…"}],\n'
        '  "room_leaning": {"direction":"全场倾向一句（中文）或空","strength":"明确|倾向|未定"}\n'
        "}\n"
        "规则：\n"
        "1) 每条 claim 至少 1 个 message_indexes（原文行号，从 0 起），禁止无依据主张。\n"
        "2) 同一 speaker 对同一 issue 的重复表态合并为一条，indexes 取并集。\n"
        "3) issues 通常 1–4 个；旁支用 parent_id + emerged_from 边。\n"
        "4) supports/opposes 只连 claim→claim，且原文有明显附和/反驳才连；不确定宁可不连。\n"
        "5) settled 需有收敛信号，否则 open/leaning。\n"
        "6) badge 可填人设立场名，但 text 必须来自发言（用中文表述）。\n"
        "7) 若提供已有地图摘要，尽量复用已有 id，只更新变化；字段仍须中文。\n"
        "8) 不要编造 options 或 chooses；选项与手选由系统结构化层提供。\n"
    ),
    "en": (
        "Extract an IBIS-style decision map from this deliberation. Use only the text; invent nothing.\n"
        "LANGUAGE: Write all user-facing fields in English "
        "(issues.label, issues.summary, claims.text, room_leaning.direction, room_leaning.strength). "
        "Even if the transcript is Chinese/Japanese, summarize in English. "
        "Keep speaker names as-is; keep status / edge.type / phase enum codes in English.\n"
        "Output strictly one JSON object (no fences):\n"
        "{\n"
        '  "issues": [{"id":"issue_1","label":"short title","parent_id":null,'
        '"status":"open|leaning|settled","winning_claim_id":null,"phase":"Exploration|Structuring|Narrowing|Convergence|null","summary":"one-line issue sense"}],\n'
        '  "claims": [{"id":"claim_1","issue_id":"issue_1","speaker":"user or agent name",'
        '"text":"one verifiable claim","badge":null,"message_indexes":[0]}],\n'
        '  "edges": [{"id":"e1","type":"emerged_from|supports|opposes","from":"…","to":"…"}],\n'
        '  "room_leaning": {"direction":"room leaning or empty","strength":"clear|leaning|undecided"}\n'
        "}\n"
        "Rules:\n"
        "1) Every claim needs ≥1 message_indexes (0-based). No invented positions.\n"
        "2) Merge repeat claims by same speaker on same issue; union indexes.\n"
        "3) Usually 1–4 issues; branches use parent_id + emerged_from.\n"
        "4) supports/opposes only claim→claim when text clearly agrees/disagrees; skip if unsure.\n"
        "5) settled only with convergence signals; else open/leaning.\n"
        "6) badge may be a persona stance id; text must come from speech.\n"
        "7) If a prior map summary is provided, reuse ids and patch changes.\n"
        "8) Do not invent options or chooses; structured selection is supplied separately.\n"
    ),
    "ja": (
        "この熟議から IBIS 風の意思決定マップを抽出する。原文のみに依拠し、捏造禁止。\n"
        "【言語】ユーザー向けフィールドはすべて日本語で書く："
        "issues.label、issues.summary、claims.text、room_leaning.direction、room_leaning.strength。"
        "原文が中国語／英語でも日本語で要約する。"
        "speaker は元の名前のままでよい。status / edge.type / phase の列挙コードは英語のまま。\n"
        "厳密に JSON オブジェクト1つだけを出力（コードフェンスなし）：\n"
        "{\n"
        '  "issues": [{"id":"issue_1","label":"短い標題","parent_id":null,'
        '"status":"open|leaning|settled","winning_claim_id":null,"phase":"Exploration|Structuring|Narrowing|Convergence|null","summary":"議題の一言"}],\n'
        '  "claims": [{"id":"claim_1","issue_id":"issue_1","speaker":"userまたは役名",'
        '"text":"検証可能な主張一句（日本語）","badge":null,"message_indexes":[0]}],\n'
        '  "edges": [{"id":"e1","type":"emerged_from|supports|opposes","from":"…","to":"…"}],\n'
        '  "room_leaning": {"direction":"場の傾向一句（日本語）または空","strength":"明確|傾向|未定"}\n'
        "}\n"
        "規則：\n"
        "1) 各 claim に message_indexes を1つ以上（0始まり）。根拠のない主張は禁止。\n"
        "2) 同一 speaker・同一 issue の繰り返しはマージし indexes を和集合。\n"
        "3) issues はだいたい 1–4。枝は parent_id + emerged_from。\n"
        "4) supports/opposes は原文に明確な賛否がある claim→claim のみ。\n"
        "5) settled は収束の根拠がある時だけ。なければ open/leaning。\n"
        "6) badge にスタンス名可。text は発言由来で日本語。\n"
        "7) 既存マップ要約があれば id を再利用し差分更新。フィールドは日本語。\n"
        "8) options や chooses を捏造しない（構造化選択は別レイヤ）。\n"
    ),
}


def _truncate(text: str, max_len: int = LABEL_MAX) -> str:
    one = re.sub(r"\s+", " ", (text or "")).strip()
    if len(one) <= max_len:
        return one
    return one[: max_len - 1].rstrip() + "…"


def _parse_time_ms(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp() * 1000.0
    if isinstance(value, (int, float)):
        v = float(value)
        return v if v > 1e12 else v * 1000.0
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000.0
    except (TypeError, ValueError):
        return None


def _msg_text(m: dict) -> str:
    return (m.get("txt") or m.get("content") or m.get("message") or "").strip()


def _msg_character(m: dict) -> str:
    return (m.get("character") or m.get("speaker") or m.get("role") or "").strip()


def _is_user_msg(m: dict) -> bool:
    ch = _msg_character(m).lower()
    if ch in ("user", "u", "@u"):
        return True
    return m.get("role") == "user"


def _is_agent_msg(m: dict) -> bool:
    if _is_user_msg(m):
        return False
    ch = _msg_character(m)
    if not ch:
        return False
    low = ch.lower()
    if low.startswith("admin") or "moderator" in low or low == "system":
        return False
    return True


def count_messages(msgs: List[dict]) -> Tuple[int, int, int]:
    user_n = sum(1 for m in msgs if _is_user_msg(m) and _msg_text(m))
    agent_n = sum(1 for m in msgs if _is_agent_msg(m) and _msg_text(m))
    total = sum(1 for m in msgs if _msg_text(m))
    return user_n, agent_n, total


def enough_messages(msgs: List[dict]) -> bool:
    user_n, agent_n, total = count_messages(msgs)
    if user_n >= MIN_USER_MSGS and agent_n >= MIN_AGENT_MSGS:
        return True
    return total >= MIN_TOTAL_MSGS


def _nearest_message_index(msgs: List[dict], time_value: Any) -> Optional[int]:
    target = _parse_time_ms(time_value)
    if target is None or not msgs:
        return None
    best_i = None
    best_dist = float("inf")
    for i, m in enumerate(msgs):
        mt = _parse_time_ms(m.get("time") or m.get("timestamp") or m.get("created_at"))
        if mt is None:
            continue
        dist = abs(mt - target)
        if dist < best_dist:
            best_dist = dist
            best_i = i
    return best_i


def build_phase_spine(msgs: List[dict], phase_changes: Optional[List[dict]]) -> List[dict]:
    spine = []
    for ch in phase_changes or []:
        idx = _nearest_message_index(msgs, ch.get("time"))
        t = ch.get("time")
        spine.append({
            "from": ch.get("from"),
            "to": ch.get("to"),
            "time": t.isoformat() if hasattr(t, "isoformat") else t,
            "message_index": idx,
        })
    return spine


def summary_meta_path(log_dir: str, room_id: str) -> str:
    return os.path.join(log_dir, f"{room_id}_summary_meta.json")


def extract_log_path(log_dir: str, room_id: str) -> str:
    return os.path.join(log_dir, f"{room_id}_decision_map.jsonl")


def annotations_path(log_dir: str, room_id: str) -> str:
    return os.path.join(log_dir, f"{room_id}_decision_map_annotations.json")


def load_summary_overall(log_dir: str, room_id: str) -> Optional[dict]:
    path = summary_meta_path(log_dir, room_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        overall = data.get("overall")
        return overall if isinstance(overall, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def save_summary_overall(log_dir: str, room_id: str, overall: Optional[dict], lang: str = "en") -> None:
    if not overall:
        return
    os.makedirs(log_dir, exist_ok=True)
    path = summary_meta_path(log_dir, room_id)
    payload = {
        "room_id": room_id,
        "lang": normalize_lang(lang),
        "overall": overall,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_user_annotations(log_dir: str, room_id: str) -> List[dict]:
    path = annotations_path(log_dir, room_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("annotations") if isinstance(data, dict) else data
        return [a for a in (items or []) if isinstance(a, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def save_user_annotations(log_dir: str, room_id: str, annotations: List[dict]) -> None:
    os.makedirs(log_dir, exist_ok=True)
    path = annotations_path(log_dir, room_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"annotations": annotations}, f, ensure_ascii=False, indent=2)


def add_user_annotation(
    log_dir: str,
    room_id: str,
    text: str,
    target_id: Optional[str] = None,
    message_indexes: Optional[List[int]] = None,
    kind: str = "user",
) -> dict:
    annotations = load_user_annotations(log_dir, room_id)
    item = {
        "id": f"ann-{uuid.uuid4().hex[:10]}",
        "text": (text or "").strip(),
        "kind": kind if kind in ("user", "system", "layer") else "user",
        "target_id": target_id,
        "message_indexes": list(message_indexes or []),
    }
    annotations.append(item)
    save_user_annotations(log_dir, room_id, annotations)
    return item


def delete_user_annotation(log_dir: str, room_id: str, annotation_id: str) -> bool:
    annotations = load_user_annotations(log_dir, room_id)
    next_items = [a for a in annotations if a.get("id") != annotation_id]
    if len(next_items) == len(annotations):
        return False
    save_user_annotations(log_dir, room_id, next_items)
    return True


def promote_layer_annotations(
    layer_items: List[dict],
    *,
    only_decision: bool = True,
) -> List[dict]:
    out: List[dict] = []
    for item in layer_items or []:
        layer = (item.get("layer") or "").strip().lower()
        if only_decision and layer != "decision":
            continue
        excerpt = (item.get("excerpt") or item.get("text") or "").strip()
        if not excerpt:
            continue
        idx = item.get("message_index")
        indexes = [int(idx)] if isinstance(idx, int) or (isinstance(idx, str) and str(idx).isdigit()) else []
        out.append({
            "id": f"layer-{item.get('id') or uuid.uuid4().hex[:8]}",
            "text": _truncate(excerpt, 80),
            "kind": "layer",
            "target_id": item.get("target_id"),
            "message_indexes": indexes,
        })
    return out


def transcript_fingerprint(msgs: List[dict]) -> str:
    """Stable short hash of transcript content — used to skip re-extract when unchanged."""
    h = hashlib.sha256()
    h.update(str(len(msgs or [])).encode("utf-8"))
    for m in msgs or []:
        h.update(b"\0")
        h.update(_msg_character(m).encode("utf-8", errors="ignore"))
        h.update(b"\0")
        h.update(_msg_text(m).encode("utf-8", errors="ignore"))
    return h.hexdigest()[:20]


def load_latest_extract_meta(
    log_dir: str,
    room_id: str,
    *,
    lang: Optional[str] = None,
) -> Optional[dict]:
    """
    Newest extract row as:
      {map, lang, fingerprint, msg_count, time}
    If lang is set, only return a row saved for that UI lang.
    """
    path = extract_log_path(log_dir, room_id)
    if not os.path.exists(path):
        return None
    want = normalize_lang(lang) if lang else None
    latest_any = None
    latest_match = None
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
                if not isinstance(row, dict):
                    continue
                payload = row.get("map") if isinstance(row.get("map"), dict) else row
                if not isinstance(payload, dict):
                    continue
                meta = {
                    "map": payload,
                    "lang": row.get("lang") or payload.get("lang"),
                    "fingerprint": row.get("fingerprint") or payload.get("fingerprint"),
                    "msg_count": row.get("msg_count")
                    if row.get("msg_count") is not None
                    else payload.get("msg_count"),
                    "time": row.get("time"),
                }
                latest_any = meta
                row_lang = meta.get("lang")
                if want and row_lang and normalize_lang(str(row_lang)) == want:
                    latest_match = meta
    except OSError:
        return None
    if want:
        return latest_match
    return latest_any


def load_latest_extract(
    log_dir: str,
    room_id: str,
    *,
    lang: Optional[str] = None,
) -> Optional[dict]:
    """Return the newest extract map. If lang is set, prefer a row saved for that UI lang."""
    meta = load_latest_extract_meta(log_dir, room_id, lang=lang)
    return meta["map"] if meta else None


def extract_cache_fresh(meta: Optional[dict], msgs: List[dict]) -> bool:
    """True when cached extract still matches current transcript."""
    if not meta or not isinstance(meta.get("map"), dict):
        return False
    fp = transcript_fingerprint(msgs)
    cached_fp = meta.get("fingerprint")
    if cached_fp and str(cached_fp) == fp:
        return True
    # Legacy rows without fingerprint: treat same message count as unchanged.
    if not cached_fp and meta.get("msg_count") is not None:
        try:
            return int(meta["msg_count"]) == len(msgs or [])
        except (TypeError, ValueError):
            return False
    return False


def append_extract(
    log_dir: str,
    room_id: str,
    payload: dict,
    lang: Optional[str] = None,
    *,
    msgs: Optional[List[dict]] = None,
    fingerprint: Optional[str] = None,
    msg_count: Optional[int] = None,
) -> None:
    os.makedirs(log_dir, exist_ok=True)
    path = extract_log_path(log_dir, room_id)
    lang_n = normalize_lang(lang) if lang else None
    body = dict(payload) if isinstance(payload, dict) else {"raw": payload}
    if lang_n:
        body["lang"] = lang_n
    fp = fingerprint or (transcript_fingerprint(msgs) if msgs is not None else None)
    n = msg_count if msg_count is not None else (len(msgs) if msgs is not None else None)
    if fp:
        body["fingerprint"] = fp
    if n is not None:
        body["msg_count"] = n
    row = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "lang": lang_n,
        "fingerprint": fp,
        "msg_count": n,
        "map": body,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def empty_map(room_id: str, lang: str = "en", *, insufficient: bool = False) -> dict:
    return {
        "room_id": room_id,
        "lang": normalize_lang(lang),
        "issues": [],
        "claims": [],
        "options": [],
        "edges": [],
        "annotations": [],
        "phase_spine": [],
        "room_leaning": None,
        "agents": [],
        "insufficient": bool(insufficient),
        "extracted": False,
        # legacy empty keys so old clients don't crash
        "topics": [],
        "stances": [],
        "conclusions": [],
    }


def choices_log_path(log_dir: str, room_id: str) -> str:
    return os.path.join(log_dir, f"{room_id}_choices.jsonl")


def load_choices(log_dir: str, room_id: str) -> List[dict]:
    path = choices_log_path(log_dir, room_id)
    if not os.path.exists(path):
        return []
    out: List[dict] = []
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
                if isinstance(row, dict) and row.get("option_id"):
                    out.append(row)
    except OSError:
        return []
    return out


def append_choice(log_dir: str, room_id: str, choice: dict) -> dict:
    os.makedirs(log_dir, exist_ok=True)
    path = choices_log_path(log_dir, room_id)
    row = {
        "id": str(choice.get("id") or f"ch-{uuid.uuid4().hex[:10]}"),
        "time": datetime.now().isoformat(timespec="seconds"),
        "choice_group_id": str(choice.get("choice_group_id") or ""),
        "option_id": str(choice.get("option_id") or ""),
        "label": _truncate(str(choice.get("label") or ""), 48),
        "proposed_by": choice.get("proposed_by"),
        "message_index": choice.get("message_index"),
        "selection_message_index": choice.get("selection_message_index"),
        "options": choice.get("options") if isinstance(choice.get("options"), list) else None,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def choice_for_group(choices: List[dict], group_id: str) -> Optional[dict]:
    gid = str(group_id or "")
    if not gid:
        return None
    for c in reversed(choices or []):
        if str(c.get("choice_group_id") or "") == gid:
            return c
    return None


def _msg_options(m: dict) -> List[dict]:
    """Read options from a chat history row (jsonl or DB clarifying_question)."""
    raw = m.get("options")
    if not raw and isinstance(m.get("clarifying_question"), dict):
        raw = m["clarifying_question"].get("options")
    if not isinstance(raw, list):
        return []
    out = []
    for i, item in enumerate(raw):
        if isinstance(item, str) and item.strip():
            out.append({"id": f"o{i + 1}", "label": _truncate(item.strip(), 48)})
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("text") or "").strip()
            if not label:
                continue
            oid = str(item.get("id") or f"o{i + 1}").strip() or f"o{i + 1}"
            out.append({"id": oid, "label": _truncate(label, 48)})
    return out if len(out) >= 2 else []


def build_structured_option_layer(
    msgs: List[dict],
    choices: List[dict],
    *,
    lang: str = "en",
    intake_options: Optional[List[Any]] = None,
) -> dict:
    """
    Deterministic Option + chooses layer from chat chips / choice log / intake.
    Does not invent claims.
    """
    lang = normalize_lang(lang)
    issue_id = "issue_choice"
    issue_label = ISSUE_FALLBACK_LABEL.get(lang) or ISSUE_FALLBACK_LABEL["en"]
    options: List[dict] = []
    opt_ids: set = set()
    edges: List[dict] = []
    claims: List[dict] = []
    chosen_ids: set = set()
    # Cross-message dedup: agents re-offer the same chips every few turns, and
    # each message used to mint a fresh namespaced node ("Offer A" × N). One
    # canonical node per normalized label; later groups alias into it.
    label_to_id: Dict[str, str] = {}   # normalized label -> canonical option id
    alias: Dict[str, str] = {}         # "{group}:{oid}" -> canonical option id
    group_members: Dict[str, List[str]] = {}  # group_id -> canonical ids in that chip group

    def _norm_label(s: str) -> str:
        return re.sub(r"\s+", "", (s or "")).strip().lower()

    def add_option(
        oid: str,
        label: str,
        *,
        proposed_by: str,
        indexes: List[int],
        status: str = "open",
        group_id: Optional[str] = None,
    ) -> None:
        if oid in opt_ids:
            # Upgrade status if newly chosen
            if status == "chosen":
                for o in options:
                    if o["id"] == oid:
                        o["status"] = "chosen"
                        chosen_ids.add(oid)
            return
        st = status if status in OPTION_STATUSES else "open"
        options.append({
            "id": oid,
            "issue_id": issue_id,
            "label": _truncate(label, 40),
            "summary": None,
            "proposed_by": proposed_by,
            "status": st,
            "message_indexes": indexes,
            "choice_group_id": group_id,
        })
        opt_ids.add(oid)
        if st == "chosen":
            chosen_ids.add(oid)

    # Intake seeds (map-only; proposed_by=intake)
    for i, item in enumerate(intake_options or []):
        if isinstance(item, str) and item.strip():
            oid, label = f"intake_{i + 1}", item.strip()
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("text") or item.get("name") or "").strip()
            if not label:
                continue
            oid = str(item.get("id") or f"intake_{i + 1}")
        else:
            continue
        add_option(oid, label, proposed_by="intake", indexes=[])
        label_to_id.setdefault(_norm_label(label), oid)
        alias[oid] = oid

    # Agent message option groups (deduped by label across messages)
    for mi, m in enumerate(msgs or []):
        opts = _msg_options(m)
        if not opts:
            continue
        group_id = str(m.get("id") or f"msg-{mi}")
        speaker = _msg_character(m) or "agent"
        members: List[str] = []
        for o in opts:
            full = f"{group_id}:{o['id']}"
            key = _norm_label(o["label"])
            canon = label_to_id.get(key)
            if canon:
                # Same option re-offered in a later message: one node, union indexes.
                alias[full] = canon
                for existing in options:
                    if existing["id"] == canon:
                        if mi not in existing["message_indexes"]:
                            existing["message_indexes"] = [*existing["message_indexes"], mi]
                        break
                members.append(canon)
                continue
            add_option(full, o["label"], proposed_by=speaker, indexes=[mi], group_id=group_id)
            label_to_id[key] = full
            alias[full] = full
            members.append(full)
        group_members[group_id] = members

    # Apply hand selections (truth source)
    for ch in choices or []:
        gid = str(ch.get("choice_group_id") or "")
        oid_raw = str(ch.get("option_id") or "")
        label = str(ch.get("label") or "").strip()
        if not oid_raw:
            continue
        # Resolution order: alias (handles label-deduped groups) → exact
        # namespaced id → label match → suffix scan → recreate from payload.
        cand = f"{gid}:{oid_raw}" if gid else oid_raw
        full_id = alias.get(cand) or (cand if cand in opt_ids else None)
        if not full_id and label:
            full_id = label_to_id.get(_norm_label(label))
        if not full_id:
            # Match by suffix or recreate from choice payload options
            for o in options:
                if o["id"].endswith(f":{oid_raw}") or o["id"] == oid_raw:
                    full_id = o["id"]
                    break
        if not full_id and isinstance(ch.get("options"), list):
            for o in ch["options"]:
                if isinstance(o, dict) and str(o.get("id")) == oid_raw:
                    full_id = f"{gid}:{oid_raw}" if gid else oid_raw
                    add_option(
                        full_id,
                        str(o.get("label") or label or oid_raw),
                        proposed_by=str(ch.get("proposed_by") or "agent"),
                        indexes=_coerce_indexes([ch.get("message_index")], len(msgs)) if msgs else [],
                        group_id=gid or None,
                    )
                    break
        if not full_id:
            full_id = f"{gid}:{oid_raw}" if gid else oid_raw
            add_option(
                full_id,
                label or oid_raw,
                proposed_by=str(ch.get("proposed_by") or "agent"),
                indexes=_coerce_indexes([ch.get("message_index")], len(msgs)) if msgs else [],
                status="chosen",
                group_id=gid or None,
            )
            label_to_id.setdefault(_norm_label(label or full_id), full_id)
            alias[full_id] = full_id
        else:
            add_option(
                full_id,
                label or full_id,
                proposed_by="user",
                indexes=_coerce_indexes([ch.get("message_index")], len(msgs)) if msgs else [],
                status="chosen",
                group_id=gid or None,
            )

        sel_idx = ch.get("selection_message_index")
        indexes = _coerce_indexes(
            [sel_idx if sel_idx is not None else ch.get("message_index")],
            len(msgs),
        ) if msgs else []
        sel_id = f"sel-{ch.get('id') or full_id}"
        claims.append({
            "id": sel_id,
            "issue_id": issue_id,
            "speaker": "user",
            "text": label or full_id,
            "badge": "selection",
            "message_indexes": indexes,
        })
        edges.append({
            "id": f"e-chooses-{sel_id}-{full_id}",
            "type": "chooses",
            "from": sel_id,
            "to": full_id,
        })

    # Mark non-chosen siblings in a chosen group as rejected (still visible).
    # Two paths: group_members covers choices made on a later (label-aliased)
    # chip group; the choice_group_id scan is the legacy fallback for options
    # that directly carry the chosen group id.
    rejected_ids: set = set()
    for ch in choices or []:
        gid = str(ch.get("choice_group_id") or "")
        members = group_members.get(gid) or []
        if any(mid in chosen_ids for mid in members):
            rejected_ids.update(mid for mid in members if mid not in chosen_ids)
    chosen_groups = {
        o.get("choice_group_id")
        for o in options
        if o.get("status") == "chosen" and o.get("choice_group_id")
    }
    for o in options:
        if o.get("status") == "chosen":
            continue
        if o["id"] in rejected_ids or (
            o.get("choice_group_id") and o["choice_group_id"] in chosen_groups
        ):
            o["status"] = "rejected"

    if not options and not claims:
        return {"issues": [], "options": [], "claims": [], "edges": []}

    winning = next((o["id"] for o in options if o.get("status") == "chosen"), None)
    status = "settled" if winning else "open"
    return {
        "issues": [{
            "id": issue_id,
            "label": issue_label,
            "parent_id": None,
            "status": status,
            "winning_claim_id": None,
            "winning_option_id": winning,
            "phase": None,
            "summary": None,
        }],
        "options": options[:12],
        "claims": claims[:24],
        "edges": edges,
        "room_leaning": None,
    }


def _coerce_indexes(raw: Any, msg_count: int) -> List[int]:
    out: List[int] = []
    if not isinstance(raw, list):
        return out
    for x in raw:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= i < msg_count:
            out.append(i)
    return list(dict.fromkeys(out))


def normalize_ibis(data: Optional[dict], *, msg_count: int = 0) -> dict:
    """Clean LLM / cached / structured payload into IBIS schema."""
    data = data if isinstance(data, dict) else {}
    issues_in = data.get("issues") or data.get("topics") or []
    claims_in = data.get("claims") or data.get("stances") or []
    options_in = data.get("options") or []
    edges_in = data.get("edges") or []

    issues: List[dict] = []
    issue_ids: set = set()
    for t in issues_in:
        if not isinstance(t, dict):
            continue
        iid = str(t.get("id") or "").strip() or f"issue_{uuid.uuid4().hex[:8]}"
        status = str(t.get("status") or "open").strip().lower()
        if status in ("active", "concluded", "parked", "unclear"):
            status = {"active": "open", "concluded": "settled", "parked": "open", "unclear": "open"}.get(status, "open")
        if status not in ISSUE_STATUSES:
            status = "open"
        issues.append({
            "id": iid,
            "label": _truncate(str(t.get("label") or t.get("summary") or iid), 40),
            "parent_id": t.get("parent_id"),
            "status": status,
            "winning_claim_id": t.get("winning_claim_id"),
            "winning_option_id": t.get("winning_option_id"),
            "phase": t.get("phase"),
            "summary": _truncate(str(t.get("summary") or ""), 80) or None,
        })
        issue_ids.add(iid)

    options: List[dict] = []
    option_ids: set = set()
    for o in options_in:
        if not isinstance(o, dict):
            continue
        oid = str(o.get("id") or "").strip() or f"opt_{uuid.uuid4().hex[:8]}"
        issue_id = o.get("issue_id")
        if issue_id and issue_id not in issue_ids and issues:
            issue_id = issues[0]["id"]
        if not issue_id:
            continue
        label = (o.get("label") or o.get("text") or "").strip()
        if not label:
            continue
        status = str(o.get("status") or "open").strip().lower()
        if status not in OPTION_STATUSES:
            status = "open"
        indexes = (
            _coerce_indexes(o.get("message_indexes"), msg_count)
            if msg_count
            else list(o.get("message_indexes") or [])
        )
        options.append({
            "id": oid,
            "issue_id": issue_id,
            "label": _truncate(label, 40),
            "summary": _truncate(str(o.get("summary") or ""), 80) or None,
            "proposed_by": str(o.get("proposed_by") or "agent"),
            "status": status,
            "message_indexes": indexes,
            "choice_group_id": o.get("choice_group_id"),
        })
        option_ids.add(oid)

    claims: List[dict] = []
    claim_ids: set = set()
    for c in claims_in:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip() or f"claim_{uuid.uuid4().hex[:8]}"
        issue_id = c.get("issue_id") or c.get("topic_id")
        if issue_id and issue_id not in issue_ids and issues:
            issue_id = issues[0]["id"]
        if not issue_id:
            continue
        text = (c.get("text") or c.get("summary") or "").strip()
        if not text:
            continue
        indexes = _coerce_indexes(c.get("message_indexes"), msg_count) if msg_count else list(c.get("message_indexes") or [])
        # Selection claims may have empty indexes; keep them. Other claims need evidence when msg_count known.
        is_selection = (c.get("badge") == "selection") or str(cid).startswith("sel-")
        if msg_count and not indexes and not is_selection:
            continue
        claims.append({
            "id": cid,
            "issue_id": issue_id,
            "speaker": str(c.get("speaker") or "unknown"),
            "text": _truncate(text, 120),
            "badge": c.get("badge") or c.get("stance_id"),
            "message_indexes": indexes,
        })
        claim_ids.add(cid)

    edges: List[dict] = []
    seen_e = set()
    for e in edges_in:
        if not isinstance(e, dict):
            continue
        et = str(e.get("type") or "").strip()
        if et == "challenges":
            et = "opposes"
        if et == "extends":
            et = "supports"
        if et not in IBIS_EDGE_TYPES:
            continue
        frm, to = e.get("from"), e.get("to")
        if not frm or not to or frm == to:
            continue
        # Validate endpoints
        if et == "emerged_from":
            if frm not in issue_ids or to not in issue_ids:
                continue
        elif et == "chooses":
            if frm not in claim_ids or to not in option_ids:
                continue
        elif et in ("supports", "opposes"):
            # claim→claim or claim→option
            if frm not in claim_ids:
                continue
            if to not in claim_ids and to not in option_ids:
                continue
        else:
            continue
        eid = str(e.get("id") or f"e-{et}-{frm}-{to}")
        if eid in seen_e:
            continue
        seen_e.add(eid)
        edges.append({"id": eid, "type": et, "from": frm, "to": to})

    # Auto emerged_from from parent_id
    for iss in issues:
        pid = iss.get("parent_id")
        if pid and pid in issue_ids:
            eid = f"e-emerged_from-{iss['id']}-{pid}"
            if eid not in seen_e:
                edges.append({"id": eid, "type": "emerged_from", "from": iss["id"], "to": pid})
                seen_e.add(eid)

    leaning = data.get("room_leaning")
    if not isinstance(leaning, dict):
        # Legacy conclusions
        conclusions = data.get("conclusions") or []
        room_c = next((c for c in conclusions if isinstance(c, dict) and c.get("scope") == "room"), None)
        if room_c:
            leaning = {
                "direction": room_c.get("direction") or "",
                "strength": room_c.get("strength") or "",
            }
        else:
            leaning = None

    return {
        "issues": issues[:6],
        "claims": claims[:24],
        "options": options[:12],
        "edges": edges,
        "room_leaning": leaning,
    }


def merge_ibis_maps(base: dict, overlay: Optional[dict], *, msg_count: int = 0) -> dict:
    """Merge overlay IBIS onto base; overlay wins on id for labels; union indexes."""
    b = normalize_ibis(base, msg_count=msg_count)
    if not overlay:
        return b
    o = normalize_ibis(overlay, msg_count=msg_count)

    def merge_list(key: str) -> List[dict]:
        by_id = {str(i["id"]): dict(i) for i in b.get(key) or []}
        for item in o.get(key) or []:
            iid = str(item["id"])
            if iid in by_id:
                merged = {**by_id[iid], **{k: v for k, v in item.items() if v is not None}}
                if "message_indexes" in by_id[iid] or "message_indexes" in item:
                    a = list(by_id[iid].get("message_indexes") or [])
                    bb = list(item.get("message_indexes") or [])
                    merged["message_indexes"] = list(dict.fromkeys([*a, *bb]))
                by_id[iid] = merged
            else:
                by_id[iid] = item
        return list(by_id.values())

    edges = list(b.get("edges") or [])
    eids = {e["id"] for e in edges}
    for e in o.get("edges") or []:
        if e["id"] not in eids and e.get("type") in IBIS_EDGE_TYPES:
            edges.append(e)
            eids.add(e["id"])

    leaning = o.get("room_leaning") or b.get("room_leaning")
    return {
        "issues": merge_list("issues"),
        "claims": merge_list("claims"),
        "options": merge_list("options"),
        "edges": edges,
        "room_leaning": leaning,
    }


def _prior_summary_for_prompt(prior: Optional[dict]) -> str:
    if not prior:
        return ""
    n = normalize_ibis(prior)
    compact = {
        "issues": [{"id": i["id"], "label": i["label"], "parent_id": i.get("parent_id"), "status": i.get("status")} for i in n["issues"]],
        "claims": [{"id": c["id"], "issue_id": c["issue_id"], "speaker": c["speaker"], "text": c["text"]} for c in n["claims"][:16]],
        "edges": n["edges"][:20],
    }
    return json.dumps(compact, ensure_ascii=False)


def extract_ibis_llm(
    msgs: List[dict],
    lang: str,
    create_response: Callable[..., str],
    *,
    prior: Optional[dict] = None,
    model: str = "gpt-4o-mini",
    max_messages: int = 50,
) -> Optional[dict]:
    lang = normalize_lang(lang)
    # Window over the NEWEST messages — the most recent turns are what the map
    # must reflect. Indexes stay GLOBAL (offset enumerate) so message_indexes
    # remain valid against the full history.
    start = max(0, len(msgs) - max_messages)
    lines = []
    for i, m in enumerate(msgs[start:], start=start):
        text = _msg_text(m)
        if not text:
            continue
        lines.append(f"[{i}] {_msg_character(m) or '?'}: {text}")
    if not lines:
        return None
    body = "\n".join(lines)
    if len(body) > 14000:
        body = body[-14000:]
    prior_s = _prior_summary_for_prompt(prior)
    if prior_s:
        body = f"PRIOR_MAP (reuse ids when possible):\n{prior_s}\n\nTRANSCRIPT:\n{body}"
    system = IBIS_PROMPT.get(lang) or IBIS_PROMPT["en"]
    try:
        raw = create_response(
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": body}],
            0.25,
            1600,
        )
    except Exception:
        return None
    try:
        from transcript_summary import _extract_json
        data = _extract_json(raw)
    except Exception:
        data = None
        try:
            data = json.loads(raw)
        except Exception:
            start, end = (raw or "").find("{"), (raw or "").rfind("}")
            if start != -1 and end > start:
                try:
                    data = json.loads(raw[start : end + 1])
                except Exception:
                    data = None
    if not isinstance(data, dict):
        return None
    return normalize_ibis(data, msg_count=len(msgs))


# Back-compat alias used by older callers / tests
def extract_decision_map_llm(msgs, lang, create_response, **kwargs):
    return extract_ibis_llm(msgs, lang, create_response, **kwargs)


def merge_decision_maps(base: dict, overlay: Optional[dict], *, msg_count: int = 0) -> dict:
    """Back-compat name → IBIS merge, preserving envelope fields from base."""
    merged = merge_ibis_maps(base, overlay, msg_count=msg_count)
    out = dict(base)
    out.update(merged)
    # Clear legacy fake graph fields from deterministic builder era
    out["topics"] = []
    out["stances"] = []
    out["conclusions"] = []
    if merged.get("room_leaning"):
        out["conclusions"] = [{
            "id": "conclusion-room",
            "scope": "room",
            "direction": merged["room_leaning"].get("direction") or "",
            "strength": merged["room_leaning"].get("strength") or "",
            "status": "leaning",
            "why": [],
            "against": [],
        }]
    return out


def apply_overall_leaning(map_data: dict, overall: Optional[dict]) -> dict:
    if not overall or not isinstance(overall, dict):
        return map_data
    direction = (overall.get("direction") or "").strip()
    strength = (overall.get("strength") or "").strip()
    if not direction and not strength:
        return map_data
    out = dict(map_data)
    out["room_leaning"] = {
        "direction": direction or (out.get("room_leaning") or {}).get("direction") or "",
        "strength": strength or (out.get("room_leaning") or {}).get("strength") or "",
    }
    # Nudge primary issue status
    issues = list(out.get("issues") or [])
    if issues:
        s = strength.lower()
        status = "settled" if ("明确" in strength or "clear" in s) else ("leaning" if ("倾向" in strength or "lean" in s) else issues[0].get("status") or "open")
        issues[0] = {**issues[0], "status": status if status in ISSUE_STATUSES else issues[0].get("status")}
        out["issues"] = issues
    return out


def assemble_smart_map(
    *,
    room_id: str,
    msgs: List[dict],
    phase_changes: Optional[List[dict]] = None,
    lang: str = "en",
    overall: Optional[dict] = None,
    user_annotations: Optional[List[dict]] = None,
    cached: Optional[dict] = None,
    fresh: Optional[dict] = None,
    agents: Optional[List[dict]] = None,
    choices: Optional[List[dict]] = None,
    intake_options: Optional[List[Any]] = None,
) -> dict:
    """Assemble API payload. Caller decides whether to LLM; this never invents claims."""
    lang = normalize_lang(lang)
    # Structured options/choices can render even before LLM threshold.
    structured = build_structured_option_layer(
        msgs or [],
        choices or [],
        lang=lang,
        intake_options=intake_options,
    )
    has_structured = bool(structured.get("options") or structured.get("claims"))
    insufficient = not enough_messages(msgs) and not has_structured
    phase_spine = build_phase_spine(msgs, phase_changes)
    annotations = list(user_annotations or [])

    if insufficient:
        m = empty_map(room_id, lang, insufficient=True)
        m["phase_spine"] = phase_spine
        m["annotations"] = annotations
        m["agents"] = [{"key": a.get("key"), "name": a.get("name"), "stance": a.get("stance")} for a in (agents or [])]
        user_n, agent_n, total = count_messages(msgs)
        m["counts"] = {"user": user_n, "agent": agent_n, "total": total}
        return m

    base = {
        "room_id": room_id,
        "lang": lang,
        "issues": [],
        "claims": [],
        "options": [],
        "edges": [],
        "room_leaning": None,
    }
    # LLM layer: the newest extract REPLACES the previous one rather than
    # unioning with it. Union let re-numbered ids duplicate every node and kept
    # LLM-deleted claims alive forever; continuity lives in the PRIOR_MAP block
    # of the extraction prompt, not in a client-side union.
    merged = merge_ibis_maps(base, fresh or cached, msg_count=len(msgs))
    # Structured hand-choices win over LLM for options / chooses / selection claims.
    if has_structured:
        merged = merge_ibis_maps(merged, structured, msg_count=len(msgs))
        # Never let LLM overwrite chosen status on structured options
        chosen = {
            o["id"]
            for o in (structured.get("options") or [])
            if o.get("status") == "chosen"
        }
        if chosen:
            opts = []
            for o in merged.get("options") or []:
                if o["id"] in chosen:
                    opts.append({**o, "status": "chosen"})
                else:
                    opts.append(o)
            merged["options"] = opts
            for iss in merged.get("issues") or []:
                if iss.get("id") == "issue_choice" or not iss.get("winning_option_id"):
                    iss["winning_option_id"] = next(iter(chosen), None)
                    if iss.get("winning_option_id"):
                        iss["status"] = "settled"
    merged = apply_overall_leaning(merged, overall)

    return {
        "room_id": room_id,
        "lang": lang,
        "issues": merged.get("issues") or [],
        "claims": merged.get("claims") or [],
        "options": merged.get("options") or [],
        "edges": merged.get("edges") or [],
        "annotations": annotations,
        "phase_spine": phase_spine,
        "room_leaning": merged.get("room_leaning"),
        "agents": [{"key": a.get("key"), "name": a.get("name"), "stance": a.get("stance")} for a in (agents or [])],
        "insufficient": False,
        "extracted": bool(cached or fresh or has_structured),
        "topics": [],
        "stances": [],
        "conclusions": [],
        "counts": dict(zip(("user", "agent", "total"), count_messages(msgs))),
    }


# Legacy no-op builder kept for tests that import the name — returns empty IBIS shell + phases only
def build_decision_map(
    *,
    room_id: str,
    msgs: List[dict],
    phase_changes: Optional[List[dict]] = None,
    agents: Optional[List[dict]] = None,
    scenario_type: Optional[str] = None,
    lang: str = "en",
    overall: Optional[dict] = None,
    knowledge: Optional[dict] = None,
    user_annotations: Optional[List[dict]] = None,
    layer_annotations: Optional[List[dict]] = None,
) -> dict:
    anns = list(user_annotations or [])
    anns.extend(promote_layer_annotations(layer_annotations or []))
    return assemble_smart_map(
        room_id=room_id,
        msgs=msgs,
        phase_changes=phase_changes,
        lang=lang,
        overall=overall,
        user_annotations=anns,
        cached=None,
        fresh=None,
        agents=agents,
    )


def strength_to_status(strength: Optional[str]) -> str:
    s = (strength or "").strip().lower()
    if s in ("明确", "clear", "settled", "strong") or "明确" in (strength or "") or "clear" in s:
        return "settled"
    if s in ("倾向", "leaning", "lean") or "倾向" in (strength or "") or "lean" in s:
        return "leaning"
    return "open"
