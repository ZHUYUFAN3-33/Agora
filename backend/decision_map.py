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

IBIS_EDGE_TYPES = frozenset({"emerged_from", "supports", "opposes"})
ISSUE_STATUSES = frozenset({"open", "leaning", "settled"})

LABEL_MAX = 48

IBIS_PROMPT = {
    "zh": (
        "你在从一场决策讨论中抽取 IBIS 风格决策地图。只根据原文，禁止编造。\n"
        "严格输出一个 JSON 对象（不要代码块）：\n"
        "{\n"
        '  "issues": [{"id":"issue_1","label":"短标题","parent_id":null,'
        '"status":"open|leaning|settled","winning_claim_id":null,"phase":"Exploration|Structuring|Narrowing|Convergence|null","summary":"一句话题意"}],\n'
        '  "claims": [{"id":"claim_1","issue_id":"issue_1","speaker":"user或角色名",'
        '"text":"可核对的主张一句","badge":null,"message_indexes":[0]}],\n'
        '  "edges": [{"id":"e1","type":"emerged_from|supports|opposes","from":"…","to":"…"}],\n'
        '  "room_leaning": {"direction":"全场倾向一句或空","strength":"明确|倾向|未定|clear|leaning|undecided"}\n'
        "}\n"
        "规则：\n"
        "1) 每条 claim 至少 1 个 message_indexes（原文行号，从 0 起），禁止无依据主张。\n"
        "2) 同一 speaker 对同一 issue 的重复表态合并为一条，indexes 取并集。\n"
        "3) issues 通常 1–4 个；旁支用 parent_id + emerged_from 边。\n"
        "4) supports/opposes 只连 claim→claim，且原文有明显附和/反驳才连；不确定宁可不连。\n"
        "5) settled 需有收敛信号，否则 open/leaning。\n"
        "6) badge 可填人设立场名，但 text 必须来自发言。\n"
        "7) 若提供已有地图摘要，尽量复用已有 id，只更新变化。\n"
    ),
    "en": (
        "Extract an IBIS-style decision map from this deliberation. Use only the text; invent nothing.\n"
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


def load_latest_extract(log_dir: str, room_id: str) -> Optional[dict]:
    path = extract_log_path(log_dir, room_id)
    if not os.path.exists(path):
        return None
    latest = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    latest = json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return None
    if not isinstance(latest, dict):
        return None
    if isinstance(latest.get("map"), dict):
        return latest["map"]
    return latest


def append_extract(log_dir: str, room_id: str, payload: dict) -> None:
    os.makedirs(log_dir, exist_ok=True)
    path = extract_log_path(log_dir, room_id)
    row = {"time": datetime.now().isoformat(timespec="seconds"), "map": payload}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def empty_map(room_id: str, lang: str = "en", *, insufficient: bool = False) -> dict:
    return {
        "room_id": room_id,
        "lang": normalize_lang(lang),
        "issues": [],
        "claims": [],
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
    """Clean LLM / cached payload into IBIS schema."""
    data = data if isinstance(data, dict) else {}
    issues_in = data.get("issues") or data.get("topics") or []
    claims_in = data.get("claims") or data.get("stances") or []
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
            "phase": t.get("phase"),
            "summary": _truncate(str(t.get("summary") or ""), 80) or None,
        })
        issue_ids.add(iid)

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
        # Drop claims with no evidence when we know msg_count
        if msg_count and not indexes:
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
        else:
            if frm not in claim_ids or to not in claim_ids:
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
    lines = []
    for i, m in enumerate(msgs[:max_messages]):
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
) -> dict:
    """Assemble API payload. Caller decides whether to LLM; this never invents claims."""
    lang = normalize_lang(lang)
    insufficient = not enough_messages(msgs)
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
        "edges": [],
        "room_leaning": None,
    }
    merged = merge_ibis_maps(base, cached, msg_count=len(msgs))
    if fresh:
        merged = merge_ibis_maps(merged, fresh, msg_count=len(msgs))
    merged = apply_overall_leaning(merged, overall)

    return {
        "room_id": room_id,
        "lang": lang,
        "issues": merged.get("issues") or [],
        "claims": merged.get("claims") or [],
        "edges": merged.get("edges") or [],
        "annotations": annotations,
        "phase_spine": phase_spine,
        "room_leaning": merged.get("room_leaning"),
        "agents": [{"key": a.get("key"), "name": a.get("name"), "stance": a.get("stance")} for a in (agents or [])],
        "insufficient": False,
        "extracted": bool(cached or fresh),
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
