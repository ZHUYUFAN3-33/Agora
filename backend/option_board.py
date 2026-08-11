# -*- coding: utf-8 -*-
"""
option_board.py — the room-level Option Board.

"Which options are on the table" is ROOM STATE with a lifecycle — proposed,
endorsed, superseded, chosen — not a per-message payload. Before this module
that state only existed implicitly: every agent turn was allowed to publish
its own [OPTIONS] chips (agents cannot see each other's chips, so they re-offer
the same set in new wording), and decision_map.build_structured_option_layer
had to reconstruct identity at read time with alias tables and five fallback
matching passes.

The board inverts that: agent [OPTIONS] output is a PROPOSAL that is reconciled
into the board at write time; what the user sees (canonical chips), what agents
see (a serialized board block in their prompt), and what the map renders all
come from the same normalized state. A repeated proposal is not noise to drop —
it is recorded as an endorsement.

Structure — a board is a list of AXES (mutually-exclusive option groups):
one axis answers one decision question ("Sony vs Honda"), a differently-shaped
question ("startup vs big company") is a different axis. Options arriving in
one [OPTIONS] group are siblings by definition and are never merged with each
other; matching only happens across proposals.

    {room}_option_board.json
    {
      "room_id", "version": 1,
      "axes": [{
        "id": "ax1",
        "created_index": int,        # message index that opened the axis
        "last_new_index": int,       # newest index that ADDED an option
        "displayed_index": int|null, # newest index chips were rendered on
        "chosen_option_id": str|null,
        "options": [{
          "id": "ax1-o1", "label": canonical, "aliases": [..],
          "first_index": int|null, "proposed_by": str,
          "endorsed_by": [{"by": str, "index": int, "label": raw}],
          "status": "open|chosen|rejected|retired"
        }]
      }],
      "updated_at": iso
    }

Everything here is deterministic string work — no LLM, no network.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

BOARD_VERSION = 1
# Generous cap: intake entries are written as full sentences ("Stay at BigTech
# Co (stable, high salary, slower growth)") and a mid-word cut loses meaning.
LABEL_MAX = 72
MAX_AXIS_OPTIONS = 12   # accumulation cap per axis (display cap is tighter)
MAX_DISPLAY = 6

# Merge when similarity clears this. Calibrated on room 732594's real labels
# ("Choose Sony for stability" vs "Sony for balance" → 0.5) — see tests.
SIM_THRESHOLD = 0.5
# "Board stable" display trigger: no new option for this many messages.
STABLE_TURNS = 3
# Don't render chips again within this many messages of any chip render,
# unless the user explicitly asked to choose.
COOLDOWN_MSGS = 3

# Choose-verbs and function words carry no option identity. Directional verbs
# (stay/leave/keep) are NOT stopped — "stay at Sony" vs "leave Sony" differ.
_STOPWORDS = {
    "choose", "choosing", "chose", "pick", "picking", "select", "selecting",
    "explore", "exploring", "consider", "considering", "try", "trying",
    "option", "options", "go", "going", "take", "taking", "opt",
    "the", "a", "an", "for", "with", "despite", "of", "to", "and", "or",
    "in", "on", "at", "is", "be", "it", "its", "your", "my", "our",
    "vs", "versus", "more", "most",
}
# Substrings stripped from CJK text before feature extraction (choose-words).
_CJK_STRIP = ("选择", "选项", "方案", "選択", "選ぶ", "を選ぶ", "プラン", "选")

_CJK_RUN_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]+")
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9]+")

# "The user is asking to choose" — deliberately short, high-precision lists.
_CHOOSE_INTENT_RE = re.compile(
    "|".join([
        # zh
        r"选哪个", r"怎么选", r"该选", r"帮我选", r"哪个好", r"哪个更",
        r"如何选", r"给我.{0,4}选项",
        # en
        r"\bwhich (one|option|way)\b", r"\bshould i (choose|pick|take|go|do)\b",
        r"\bwhat should i\b", r"\bhelp me (choose|decide|pick)\b",
        r"\bgive me( the)? options\b", r"\brecommend\b",
        # ja
        r"どっち", r"どれが", r"選べば", r"決めら?れ", r"おすすめ", r"オススメ",
    ]),
    re.IGNORECASE,
)


def board_path(log_dir: str, room_id: str) -> str:
    return os.path.join(log_dir, f"{room_id}_option_board.json")


def empty_board(room_id: str) -> dict:
    return {"room_id": room_id, "version": BOARD_VERSION, "axes": []}


def load_board(log_dir: str, room_id: str) -> dict:
    path = board_path(log_dir, room_id)
    if not os.path.exists(path):
        return empty_board(room_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("axes"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return empty_board(room_id)


def save_board(log_dir: str, room_id: str, board: dict) -> None:
    os.makedirs(log_dir, exist_ok=True)
    board["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = board_path(log_dir, room_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(board, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def board_has_content(board: Optional[dict]) -> bool:
    return bool(board and any(ax.get("options") for ax in board.get("axes") or []))


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _features(label: str) -> set:
    """Latin content words + CJK char bigrams (single char if a run is length 1)."""
    norm = _norm(label)
    feats: set = set()
    for tok in _LATIN_TOKEN_RE.findall(norm):
        if tok not in _STOPWORDS:
            feats.add(tok)
    cjk_text = "".join(_CJK_RUN_RE.findall(label or ""))
    for strip in _CJK_STRIP:
        cjk_text = cjk_text.replace(strip, "")
    for run in _CJK_RUN_RE.findall(cjk_text):
        if len(run) == 1:
            feats.add(run)
        else:
            for i in range(len(run) - 1):
                feats.add(run[i : i + 2])
    return feats


def _cjk_prefix_len(a: str, b: str) -> int:
    """Common leading CJK chars — zh/ja option labels usually lead with the
    entity ("索尼稳定" / "索尼求稳"), so a shared prefix is a strong signal
    where bigram overlap alone dilutes ("华为手机" vs "苹果手机" share only
    the generic suffix and must NOT merge)."""
    def _stripped(s: str) -> str:
        for strip in _CJK_STRIP:
            s = s.replace(strip, "")
        return s

    ra = _CJK_RUN_RE.findall(_stripped(a or ""))
    rb = _CJK_RUN_RE.findall(_stripped(b or ""))
    if not ra or not rb:
        return 0
    x, y = ra[0], rb[0]
    n = 0
    for ca, cb in zip(x, y):
        if ca != cb:
            break
        n += 1
    return n


def similarity(a: str, b: str) -> float:
    """0..1. Deterministic, language-mixed safe. ≥ SIM_THRESHOLD means
    "same option, different wording"."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    fa, fb = _features(a), _features(b)
    coeff = 0.0
    if fa and fb:
        coeff = len(fa & fb) / min(len(fa), len(fb))
    if coeff < SIM_THRESHOLD and _cjk_prefix_len(a, b) >= 2:
        coeff = max(coeff, SIM_THRESHOLD)
    return coeff


def _best_similarity(label: str, option: dict) -> float:
    cands = [option.get("label") or ""] + list(option.get("aliases") or [])
    return max((similarity(label, c) for c in cands), default=0.0)


# ---------------------------------------------------------------------------
# Reconcile — agent [OPTIONS] proposals merge into the board
# ---------------------------------------------------------------------------

def _cut(label: str) -> str:
    label = re.sub(r"\s+", " ", label).strip()
    if len(label) <= LABEL_MAX:
        return label
    return label[: LABEL_MAX - 1].rstrip() + "…"


def _dedupe_group(options: List[dict]) -> List[dict]:
    seen: set = set()
    out: List[dict] = []
    for o in options or []:
        label = _cut(str((o or {}).get("label") or ""))
        if not label:
            continue
        key = _norm(label)
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": str(o.get("id") or f"o{len(out) + 1}"), "label": label})
    return out


def _new_axis_id(board: dict) -> str:
    return f"ax{len(board.get('axes') or []) + 1}"


def _endorse(option: dict, speaker: str, msg_index: Optional[int], raw_label: str) -> bool:
    """Record one endorsement per speaker per option. Returns True if recorded."""
    speaker = (speaker or "").strip() or "agent"
    if speaker == option.get("proposed_by"):
        return False
    for e in option.get("endorsed_by") or []:
        if e.get("by") == speaker:
            return False
    option.setdefault("endorsed_by", []).append({
        "by": speaker,
        "index": msg_index if isinstance(msg_index, int) else None,
        "label": raw_label[:LABEL_MAX],
    })
    return True


def reconcile(
    board: dict,
    options: List[dict],
    *,
    speaker: str,
    msg_index: Optional[int],
) -> dict:
    """Merge one proposed [OPTIONS] group into the board.

    Axis choice: the axis whose existing options fuzzy-match the most incoming
    labels (each board option consumes at most one incoming option). No match
    anywhere → the group opens a new axis. Matched incoming options become
    endorsements (+ alias when the wording is new); unmatched ones are added to
    the winning axis as new alternatives.
    """
    incoming = _dedupe_group(options)
    result = {"axis": None, "mapping": {}, "added": [], "endorsed": []}
    if not incoming:
        return result

    axes = board.setdefault("axes", [])
    best_axis: Optional[dict] = None
    best_matches: Dict[str, tuple] = {}
    for axis in axes:
        used: set = set()
        matches: Dict[str, tuple] = {}
        for opt in incoming:
            best = None
            for bo in axis.get("options") or []:
                if bo["id"] in used or bo.get("status") == "retired":
                    continue
                s = _best_similarity(opt["label"], bo)
                if s >= SIM_THRESHOLD and (best is None or s > best[1]):
                    best = (bo, s)
            if best:
                matches[opt["id"]] = best
                used.add(best[0]["id"])
        if len(matches) > len(best_matches):
            best_axis, best_matches = axis, matches

    idx = msg_index if isinstance(msg_index, int) else None
    if best_axis is None or not best_matches:
        axis = {
            "id": _new_axis_id(board),
            "created_index": idx,
            "last_new_index": idx if idx is not None else -1,
            "displayed_index": None,
            "chosen_option_id": None,
            "options": [],
        }
        axes.append(axis)
        matches = {}
    else:
        axis = best_axis
        matches = best_matches

    result["axis"] = axis
    for opt in incoming:
        hit = matches.get(opt["id"])
        if hit:
            bo = hit[0]
            raw = opt["label"]
            if _endorse(bo, speaker, idx, raw):
                result["endorsed"].append(bo["id"])
            aliases = bo.setdefault("aliases", [])
            if _norm(raw) != _norm(bo.get("label") or "") and all(
                _norm(raw) != _norm(al) for al in aliases
            ):
                aliases.append(raw)
            result["mapping"][opt["id"]] = bo["id"]
            continue
        if len(axis["options"]) >= MAX_AXIS_OPTIONS:
            continue
        bo = {
            "id": f"{axis['id']}-o{len(axis['options']) + 1}",
            "label": opt["label"],
            "aliases": [],
            "first_index": idx,
            "proposed_by": (speaker or "").strip() or "agent",
            "endorsed_by": [],
            "status": "open",
        }
        axis["options"].append(bo)
        axis["last_new_index"] = idx if idx is not None else axis.get("last_new_index", -1)
        result["mapping"][opt["id"]] = bo["id"]
        result["added"].append(bo["id"])
    return result


def seed_intake(board: dict, intake_options: List[Any]) -> None:
    """Room-creation options accumulate silently (proposed_by=intake, no index)."""
    group = []
    for i, item in enumerate(intake_options or []):
        if isinstance(item, str) and item.strip():
            group.append({"id": f"intake_{i + 1}", "label": item.strip()})
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("text") or item.get("name") or "").strip()
            if label:
                group.append({"id": str(item.get("id") or f"intake_{i + 1}"), "label": label})
    if len(group) >= 2:
        reconcile(board, group, speaker="intake", msg_index=None)


# ---------------------------------------------------------------------------
# Display policy — WHEN chips render is a board policy, not a message property
# ---------------------------------------------------------------------------

def user_asked_to_choose(user_message: Optional[str]) -> bool:
    return bool(_CHOOSE_INTENT_RE.search(user_message or ""))


def active_axis(board: dict) -> Optional[dict]:
    """The axis a bare "which should I pick?" refers to.

    Needed because the prompt block tells agents NOT to re-propose known
    options — so an existing axis is often never "touched" again, and a
    user-ask must be able to render it without a fresh proposal. Undecided,
    ≥2 open options; among several, the most recently touched wins (pure
    intake axes sit at -1 and lose to anything the conversation touched)."""
    best = None
    best_key = -2
    for axis in board.get("axes") or []:
        if axis.get("chosen_option_id"):
            continue
        open_n = sum(1 for o in axis.get("options") or [] if o.get("status") == "open")
        if open_n < 2:
            continue
        key = max(
            axis.get("last_new_index") if isinstance(axis.get("last_new_index"), int) else -1,
            axis.get("created_index") if isinstance(axis.get("created_index"), int) else -1,
            axis.get("displayed_index") if isinstance(axis.get("displayed_index"), int) else -1,
        )
        if best is None or key > best_key:
            best, best_key = axis, key
    return best


def _last_display_index(board: dict) -> Optional[int]:
    vals = [
        ax.get("displayed_index")
        for ax in board.get("axes") or []
        if isinstance(ax.get("displayed_index"), int)
    ]
    return max(vals) if vals else None


def decide_display(
    board: dict,
    axis: Optional[dict],
    *,
    force_intro: bool = False,
    phase: str = "Exploration",
    user_message: Optional[str] = None,
    msg_index: int = 0,
    user_msg_index: Optional[int] = None,
) -> Optional[List[dict]]:
    """Canonical chips for `axis` if they should render on this message, else
    None. Marks the axis displayed when it fires. The board keeps accumulating
    either way — suppression is never data loss.

    Triggers (any): the user asked to choose; the deliberation reached
    Narrowing/Convergence; the axis has been stable for STABLE_TURNS and was
    never shown. Suppressed on intro turns, on already-decided axes, when
    nothing changed since the last render, and within the global cooldown
    (user-ask overrides the last two).
    """
    if not axis or force_intro:
        return None
    if axis.get("chosen_option_id"):
        return None
    open_opts = [o for o in axis.get("options") or [] if o.get("status") == "open"]
    if len(open_opts) < 2:
        return None

    asked = user_asked_to_choose(user_message)
    last_new = axis.get("last_new_index")
    stable = (
        axis.get("displayed_index") is None
        and isinstance(last_new, int)
        and last_new >= 0
        and (msg_index - last_new) >= STABLE_TURNS
    )
    in_late_phase = phase in ("Narrowing", "Convergence")
    if not (asked or in_late_phase or stable):
        return None

    if asked and isinstance(user_msg_index, int):
        shown = axis.get("displayed_index")
        # One render per ask: the first agent answering this user message
        # stamps the chips; its roundmates don't repeat them.
        if isinstance(shown, int) and shown > user_msg_index:
            return None

    if not asked:
        shown = axis.get("displayed_index")
        if isinstance(shown, int) and (not isinstance(last_new, int) or last_new <= shown):
            return None  # nothing new since the last render of this axis
        last_any = _last_display_index(board)
        if isinstance(last_any, int) and (msg_index - last_any) < COOLDOWN_MSGS:
            return None

    axis["displayed_index"] = msg_index
    return [{"id": o["id"], "label": o["label"]} for o in open_opts[:MAX_DISPLAY]]


# ---------------------------------------------------------------------------
# Choices / prompt serialization
# ---------------------------------------------------------------------------

def find_option(board: dict, option_id: str) -> Optional[tuple]:
    oid = str(option_id or "")
    for axis in board.get("axes") or []:
        for bo in axis.get("options") or []:
            if bo["id"] == oid:
                return axis, bo
    return None


def mark_chosen(board: dict, option_id: str) -> Optional[dict]:
    """User picked an option: it becomes chosen, open siblings become rejected.
    Returns the axis, or None when the id is not on the board (legacy rooms)."""
    hit = find_option(board, option_id)
    if not hit:
        return None
    axis, chosen = hit
    for bo in axis.get("options") or []:
        if bo["id"] == chosen["id"]:
            bo["status"] = "chosen"
        elif bo.get("status") == "open":
            bo["status"] = "rejected"
    axis["chosen_option_id"] = chosen["id"]
    return axis


def board_prompt_block(board: Optional[dict]) -> str:
    """Serialized board for agent context. Empty string when nothing to show.

    This is the write-time fix for chip duplication: agents re-offered options
    because the transcript they see carries only `Speaker: text` — chips were
    invisible to them. With the board in context they can refer to options by
    canonical name instead of re-proposing them.
    """
    if not board_has_content(board):
        return ""
    lines: List[str] = []
    for axis in board.get("axes") or []:
        for bo in axis.get("options") or []:
            if bo.get("status") == "retired":
                continue
            who = bo.get("proposed_by") or "?"
            endorsers = [e.get("by") for e in bo.get("endorsed_by") or [] if e.get("by")]
            tail = f" (proposed by {who}"
            if endorsers:
                tail += "; endorsed by " + ", ".join(endorsers)
            tail += ")"
            status = bo.get("status")
            mark = f" [{status}]" if status and status != "open" else ""
            lines.append(f"- {bo.get('label')}{mark}{tail}")
            if len(lines) >= 12:
                break
        if len(lines) >= 12:
            break
    if not lines:
        return ""
    return (
        "OPTIONS ALREADY ON THE TABLE (room state):\n"
        + "\n".join(lines)
        + "\nDo NOT re-offer these as [OPTIONS] chips. Refer to them by these exact "
        "names. Only use [OPTIONS] for a genuinely new decision or a new alternative."
    )
