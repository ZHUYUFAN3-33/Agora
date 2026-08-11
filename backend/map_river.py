# -*- coding: utf-8 -*-
"""
map_river.py — assemble the River payload: the decision map's main view.

One structure instead of two disconnected ones. The old map split content and
structure across an LLM-guessed claim canvas (content, no time) and a reply
strip (time, no content); neither was readable alone. The river fuses them:

    turns[]      every chat turn in time order, carrying its CONTENT
                 (per-turn summary from turn_summaries.py, raw-text fallback),
                 its MOVE self-report + rationale, and milestone badges
    relations[]  who-answered-whom edges (map_facts.py, deterministic)
    phases[]     phase spine for background bands
    options[]    the Option Board, flattened
    verdict      chosen option + which turns argued for it + stance tallies

Everything here is deterministic assembly — the only LLM involvement happened
earlier, per-turn, in turn_summaries.py. A missing summary degrades that one
card, never the map.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

FALLBACK_TEXT_LEN = 110


def flat_board_options(board: Optional[dict]) -> List[dict]:
    out: List[dict] = []
    for axis in (board or {}).get("axes") or []:
        for o in axis.get("options") or []:
            if o.get("status") == "retired":
                continue
            out.append({
                "id": o["id"],
                "axis_id": axis.get("id"),
                "label": o.get("label") or "",
                "status": o.get("status") or "open",
                "proposed_by": o.get("proposed_by") or "agent",
                "endorsed_by": [e.get("by") for e in o.get("endorsed_by") or [] if e.get("by")],
                "first_index": o.get("first_index"),
            })
    return out


def _latest_choice(choices: List[dict]) -> Optional[dict]:
    for ch in reversed(choices or []):
        if ch.get("option_id"):
            return ch
    return None


def _choice_turn_index(ch: dict) -> Optional[int]:
    for key in ("selection_message_index", "message_index"):
        v = ch.get(key)
        if isinstance(v, int) and v >= 0:
            return v
    return None


GUIDANCE_KEYS = ("why", "against", "would_change", "your_call", "strength_reason", "your_role")


def extract_guidance(overall: Optional[dict]) -> dict:
    """The session summary's reasoning fields, which the map used to discard.

    transcript_summary asks the model for why / against / would_change /
    your_call — the honest parts, including reasons that were never answered
    in the discussion — and apply_overall_leaning kept only direction and
    strength. Everything else went on the floor."""
    if not isinstance(overall, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in GUIDANCE_KEYS:
        v = overall.get(k)
        if isinstance(v, list):
            items = [str(x).strip() for x in v if str(x or "").strip()]
            if items:
                out[k] = items[:5]
        elif isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def build_river(
    *,
    facts: Dict[str, Any],
    board: Optional[dict],
    choices: List[dict],
    summaries: Dict[str, dict],
    phase_spine: List[dict],
    lang: str = "en",
    guidance: Optional[dict] = None,
) -> dict:
    fact_turns = facts.get("turns") or []
    relations = facts.get("relations") or []
    options = flat_board_options(board)
    opt_by_id = {o["id"]: o for o in options}

    # Which turn indexes carry milestone badges
    shown_by_index: Dict[int, List[str]] = {}
    for axis in (board or {}).get("axes") or []:
        di = axis.get("displayed_index")
        if isinstance(di, int) and di >= 0:
            shown_by_index.setdefault(di, []).append(axis.get("id"))
    choice_by_index: Dict[int, dict] = {}
    for ch in choices or []:
        idx = _choice_turn_index(ch)
        if idx is not None:
            choice_by_index[idx] = {
                "option_id": str(ch.get("option_id") or ""),
                "label": str(
                    ch.get("label")
                    or opt_by_id.get(str(ch.get("option_id") or ""), {}).get("label")
                    or ""
                ),
            }

    related_indexes: set = set()
    for r in relations:
        related_indexes.add(r.get("from_index"))
        related_indexes.add(r.get("to_index"))

    turns: List[dict] = []
    counts: Dict[str, Dict[str, int]] = {}
    for t in fact_turns:
        row = summaries.get(str(t["id"])) or {}
        # schema 2 stores a list; tolerate the old singular key on stale rows.
        raw_stances = row.get("stances")
        if raw_stances is None and isinstance(row.get("stance"), dict):
            raw_stances = [row["stance"]]
        stances = [
            s for s in (raw_stances or [])
            if isinstance(s, dict) and s.get("option_id") in opt_by_id
        ]
        for s in stances:
            c = counts.setdefault(s["option_id"], {"support": 0, "concern": 0})
            sign = s.get("sign")
            if sign in c:
                c[sign] += 1
        # The river's own card border still shows one stance; the ledger uses
        # the full list.
        stance = stances[0] if stances else None
        badges: Dict[str, Any] = {}
        if t["index"] in shown_by_index:
            badges["options_shown"] = shown_by_index[t["index"]]
        if t["index"] in choice_by_index:
            badges["choice"] = choice_by_index[t["index"]]
        txt = (t.get("txt") or "").strip()
        summary = (row.get("summary") or "").strip() or None
        turn = {
            "id": t["id"],
            "index": t["index"],
            "speaker": t.get("speaker") or "?",
            "is_user": bool(t.get("is_user")),
            "time": t.get("time"),
            "summary": summary,
            "has_summary": bool(summary),
            "fallback_text": txt[:FALLBACK_TEXT_LEN] + ("…" if len(txt) > FALLBACK_TEXT_LEN else ""),
            "keywords": list(row.get("keywords") or []),
            "stance": stance,
            "stances": stances,
            "move_kind": t.get("move_kind"),
            "move_detail": t.get("move_detail"),
            "rationale": t.get("rationale"),
            "softened_by": t.get("softened_by"),
            "badges": badges,
        }
        turn["key"] = bool(
            turn["is_user"]
            or turn["index"] in related_indexes
            or stances
            or turn["softened_by"]
            or badges
        )
        turns.append(turn)

    # ---- verdict -----------------------------------------------------------
    latest = _latest_choice(choices)
    chosen_id: Optional[str] = None
    if latest and str(latest.get("option_id")) in opt_by_id:
        chosen_id = str(latest["option_id"])
    if not chosen_id:
        chosen_id = next((o["id"] for o in options if o.get("status") == "chosen"), None)
    chosen = opt_by_id.get(chosen_id) if chosen_id else None

    def _points(option_id: str, sign: str) -> List[dict]:
        """Sentences arguing one way about one option, best first.

        Ranked by reply-graph membership (a point made under fire survived a
        reply, so it carries more weight than an unchallenged aside) and then
        by recency, which is the same rule the old single-column `why` used."""
        out = []
        for t in turns:
            # The "Chose: X" confirmation is the decision, not a reason for it.
            # Listing it under "said for it" answers "why did you pick this?"
            # with "because you picked it".
            if t.get("badges", {}).get("choice"):
                continue
            for s in t.get("stances") or []:
                if s.get("option_id") != option_id or s.get("sign") != sign:
                    continue
                out.append({
                    "turn_id": t["id"],
                    "index": t["index"],
                    "speaker": t["speaker"],
                    "is_user": t["is_user"],
                    "text": s.get("quote") or t.get("summary") or t.get("fallback_text") or "",
                })
        out.sort(key=lambda p: (p["index"] in related_indexes, p["index"]), reverse=True)
        return out[:4]

    # The ledger: one card per option, the two cases side by side. Unlike a
    # criteria x options matrix this needs no stable criterion vocabulary and
    # introduces no concept the reader has to learn — it is a pros/cons list.
    ledger: List[dict] = []
    for o in options:
        c = counts.get(o["id"]) or {"support": 0, "concern": 0}
        ledger.append({
            "option_id": o["id"],
            "label": o["label"],
            "status": o["status"],
            "proposed_by": o["proposed_by"],
            "endorsed_by": o["endorsed_by"],
            "case_for": _points(o["id"], "support"),
            "case_against": _points(o["id"], "concern"),
            "counts": c,
        })
    # Chosen first, then rejected last, then by weight of discussion.
    ledger.sort(
        key=lambda l: (
            l["status"] != "chosen",
            l["status"] == "rejected",
            -(l["counts"]["support"] + l["counts"]["concern"]),
        )
    )

    why_ids = [p["turn_id"] for p in _points(chosen_id, "support")][:3] if chosen_id else []

    verdict = {
        "chosen_option_id": chosen_id,
        "chosen_label": (chosen or {}).get("label"),
        "decided_index": _choice_turn_index(latest) if latest else None,
        "why_turn_ids": why_ids,
        "counts": counts,
        "undecided": chosen_id is None,
    }

    return {
        "lang": lang,
        "turns": turns,
        "relations": relations,
        "phases": [
            p for p in (phase_spine or [])
            if isinstance(p, dict)
        ],
        "options": options,
        "ledger": ledger,
        "guidance": guidance or {},
        "verdict": verdict,
    }
