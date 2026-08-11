# -*- coding: utf-8 -*-
"""
map_facts.py — the DETERMINISTIC fact layer under the decision map.

Reads two logs that already exist for every room and derives the reply graph
without a single LLM call:

    {room}.jsonl            one row per published chat message
    {room}_rationale.jsonl  per-turn structured events: move / agent_mention /
                            rationale (the [MOVE] and [RATIONALE] self-reports)

Output (see load_room_facts):
    turns[]      one node per chat row, in file order — X axis of the map
    relations[]  directed edges "this turn responds to that turn", each with a
                 kind (challenge/extend/clarify/mention) and a deterministic
                 sign: challenge -> "opposes", everything else -> "neutral".
                 "supports" NEVER originates here — colouring a neutral edge
                 green requires the pair-classification pass (map_llm), which
                 is gated on measured precision.

WHY NOT normalize_move(): it scans AGENT_MOVES in tuple order rather than text
position, so 'extend @ChatbotB, not a challenge' resolves to 'challenge'. The
first-whitespace-token rule below parses 88/88 real records correctly.

WHY concede IS NOT AN EDGE: 6 of 7 observed concede records carry no target.
It becomes a "softened_by" marker on the conceder's OWN most recent prior turn
("this speaker later walked this back"), which is what it actually means.

WHY "answers" EXISTS: an agent replying to the user almost always self-reports
new_point — from the agent's side it IS raising a new point — so the move layer
alone leaves the user's turns completely unconnected (measured in room 001999:
4 of 6 moves were new_point, every one of them addressing @U). A turn whose
text explicitly addresses the user therefore earns one backward edge to the
user's latest prior turn. One primary target per turn: a turn that already
resolved an agent target keeps that edge instead, so the map shows the
argument, not a duplicate of the backbone.

Join contract (measured over rooms 641306/778329/205171/209915/021808/078400/
236995): a move event and its chat row are written in the same call path and
share the same second-resolution timestamp; the minimum same-speaker gap is
12s against 1s granularity, so (time, speaker) is unambiguous. Rows lacking an
id (user rows, legacy logs, CLI logs) get the stable fallback id
"u-{room}-{index}".
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# Kinds we accept from the [MOVE] self-report. Mirrors AGENT_MOVES in
# agentwake_new.py; duplicated as data (not imported) so this module never
# drags in the 3800-line agent runtime.
MOVE_KINDS = ("challenge", "extend", "new_point", "concede", "clarify")

# kind -> deterministic edge sign. supports is deliberately absent.
KIND_SIGN = {
    "challenge": "opposes",
    "extend": "neutral",
    "clarify": "neutral",
    "mention": "neutral",
    "answers": "neutral",
}

_AT_TOKEN_RE = re.compile(r"@([\w\-]+)")
# The turn addresses the user directly. Agents write "@U" in the log; the UI
# swaps it for the reader's nickname at render time, so the log form is what
# matters here.
_AT_USER_RE = re.compile(r"@(?:U|user|you|用户|您|あなた)\b", re.IGNORECASE)
_MENTION_LIST_RE = re.compile(r"mentioned\s*\[([^\]]*)\]")
_MENTION_KEY_RE = re.compile(r"'([^']+)'")


def _rows(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    out: List[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def _is_user(character: str) -> bool:
    return (character or "").strip().lower() in ("user", "u", "@u")


def parse_move_detail(detail: str) -> Tuple[str, List[str]]:
    """(kind, [@target tokens]) from a move event's detail field.

    Kind = FIRST whitespace token only (see module docstring for why not
    normalize_move). Unknown first tokens yield ("", []) so a garbled record
    degrades to nothing instead of a wrong edge.
    """
    text = (detail or "").strip()
    if not text:
        return "", []
    first = text.split()[0].strip().lower().rstrip(",.;:!?")
    kind = first.replace("-", "_").replace(" ", "_")
    if kind not in MOVE_KINDS:
        return "", []
    targets = [t.rstrip(",.;:!?") for t in _AT_TOKEN_RE.findall(text)]
    return kind, targets


def parse_mention_keys(detail: str) -> List[str]:
    """Agent keys out of "A mentioned ['B', 'C'] (soft cue, ...)"."""
    m = _MENTION_LIST_RE.search(detail or "")
    if not m:
        return []
    return _MENTION_KEY_RE.findall(m.group(1))


class _Roster:
    """Speaker bookkeeping: display name <-> agent key, learned from the join
    itself (no Chatbot{K} assumption, so limited-mode names work too)."""

    def __init__(self) -> None:
        self.key_to_name: Dict[str, str] = {}
        self.name_to_key: Dict[str, str] = {}

    def learn(self, key: str, name: str) -> None:
        if key and name and key not in self.key_to_name:
            self.key_to_name[key] = name
            self.name_to_key[name.lower()] = key

    def resolve_token(self, token: str) -> Optional[str]:
        """@-token -> canonical display name, "user", or None."""
        low = (token or "").strip().lower()
        if not low:
            return None
        if low in ("u", "user", "你", "用户"):
            return "user"
        if low in self.name_to_key:  # exact display name
            for name in self.key_to_name.values():
                if name.lower() == low:
                    return name
        if low.upper() in self.key_to_name:  # bare key: @B
            return self.key_to_name[low.upper()]
        return None


def load_room_facts(log_dir: str, room_id: str) -> Dict[str, Any]:
    chat = _rows(os.path.join(log_dir, f"{room_id}.jsonl"))
    events = _rows(os.path.join(log_dir, f"{room_id}_rationale.jsonl"))

    roster = _Roster()

    # ---- turns[] -----------------------------------------------------------
    turns: List[dict] = []
    for i, m in enumerate(chat):
        character = str(m.get("character") or "").strip()
        turns.append({
            "id": str(m.get("id") or f"u-{room_id}-{i}"),
            "index": i,
            "speaker": character,
            "is_user": _is_user(character),
            "time": m.get("time"),
            "txt": str(m.get("txt") or ""),
            "rationale": None,
            "move_kind": None,
            "move_detail": None,
            "softened_by": None,
        })

    by_time: Dict[str, List[int]] = {}
    for t in turns:
        by_time.setdefault(str(t["time"]), []).append(t["index"])

    def last_index_by_speaker(name: str, before: int) -> Optional[int]:
        for j in range(before - 1, -1, -1):
            if name == "user":
                if turns[j]["is_user"]:
                    return j
            elif turns[j]["speaker"] == name:
                return j
        return None

    # ---- join move / rationale / agent_mention events to chat rows ---------
    consumed: set = set()

    def join_event(ev: dict) -> Optional[int]:
        """Chat-row index for one rationale event: same second, agent row,
        not already bound to another event of the same type."""
        t = str(ev.get("time") or "")
        key = str(ev.get("agent") or "")
        cands = [i for i in by_time.get(t, []) if not turns[i]["is_user"]]
        if not cands:
            return None
        if len(cands) > 1:
            # Prefer a row we already learned belongs to this key.
            known = roster.key_to_name.get(key)
            narrowed = [i for i in cands if known and turns[i]["speaker"] == known]
            cands = narrowed or cands
        idx = cands[0]
        roster.learn(key, turns[idx]["speaker"])
        return idx

    relations: List[dict] = []
    seen_pairs: set = set()
    stats = {
        "moves": 0, "moves_joined": 0, "targets_resolved": 0,
        "at_u_recovered": 0, "mention_extras": 0,
        "dangling_dropped": 0, "concede_badges": 0,
    }
    # Turn indexes that already produced an outgoing edge — the "one primary
    # target per turn" rule for the answers-the-user pass below.
    sourced: set = set()

    def add_relation(src: int, dst: int, kind: str, source: str) -> None:
        pair = (turns[src]["id"], turns[dst]["id"])
        if pair in seen_pairs or src == dst:
            return
        seen_pairs.add(pair)
        sourced.add(src)
        relations.append({
            "id": f"r-{turns[src]['id']}-{turns[dst]['id']}",
            "from_id": turns[src]["id"],
            "from_index": src,
            "to_id": turns[dst]["id"],
            "to_index": dst,
            "kind": kind,
            "sign": KIND_SIGN.get(kind, "neutral"),
            "source": source,
        })

    # First pass: rationale text + move self-reports.
    move_rows: List[Tuple[int, str, List[str]]] = []  # (turn index, kind, targets)
    for ev in events:
        etype = ev.get("event")
        if etype == "rationale":
            idx = join_event(ev)
            if idx is not None and turns[idx]["rationale"] is None:
                turns[idx]["rationale"] = str(ev.get("detail") or "")
            continue
        if etype == "move":
            stats["moves"] += 1
            idx = join_event(ev)
            if idx is None:
                continue
            stats["moves_joined"] += 1
            kind, targets = parse_move_detail(str(ev.get("detail") or ""))
            if not kind:
                continue
            turns[idx]["move_kind"] = kind
            turns[idx]["move_detail"] = str(ev.get("detail") or "")[:80]
            move_rows.append((idx, kind, targets))
            continue
        if etype == "agent_mention":
            idx = join_event(ev)
            if idx is None:
                continue
            extras = parse_mention_keys(str(ev.get("detail") or ""))
            turns[idx].setdefault("_mention_keys", []).extend(extras)

    # Second pass: turn moves into relations (roster is now fully learned).
    for idx, kind, targets in move_rows:
        if kind == "new_point":
            continue  # a new line starts here; no backward edge by definition
        if kind == "concede":
            own_prev = last_index_by_speaker(turns[idx]["speaker"], idx)
            if own_prev is not None:
                turns[own_prev]["softened_by"] = turns[idx]["id"]
                stats["concede_badges"] += 1
            continue
        for tok in targets:
            name = roster.resolve_token(tok)
            if not name:
                continue
            dst = last_index_by_speaker(name, idx)
            if dst is None:
                stats["dangling_dropped"] += 1
                continue
            add_relation(idx, dst, kind, "move")
            stats["targets_resolved"] += 1

    # Answers-the-user pass: every agent turn whose TEXT addresses the user and
    # which has no edge yet points back at the user's latest prior turn. Runs
    # over all agent turns, not just parsed moves, so a garbled [MOVE] still
    # keeps the backbone intact (see the module docstring for why new_point
    # cannot be trusted to mean "not a reply" here).
    for t in turns:
        if t["is_user"] or t["index"] in sourced:
            continue
        if not _AT_USER_RE.search(t["txt"]):
            continue
        dst = last_index_by_speaker("user", t["index"])
        if dst is None:
            continue
        before = len(relations)
        add_relation(t["index"], dst, "answers", "at_user")
        if len(relations) > before:
            stats["at_u_recovered"] += 1

    # Third pass: soft mentions recover the co-addressed targets MOVE's single
    # @slot truncated away. Neutral by construction.
    for t in turns:
        keys = t.pop("_mention_keys", None)
        # new_point means "not aimed at anyone" and concede is badge-only —
        # but a turn whose MOVE was garbled (move_kind None) still earns its
        # neutral mention edges: the @ in the text is real even when the tag
        # wasn't parseable.
        if not keys or t["move_kind"] in ("new_point", "concede"):
            continue
        for k in keys:
            name = roster.key_to_name.get(str(k))
            if not name:
                continue
            dst = last_index_by_speaker(name, t["index"])
            if dst is None:
                continue
            before = len(relations)
            add_relation(t["index"], dst, "mention", "agent_mention")
            if len(relations) > before:
                stats["mention_extras"] += 1
    # Clean helper key off untouched turns too.
    for t in turns:
        t.pop("_mention_keys", None)

    return {
        "room_id": room_id,
        "turns": turns,
        "relations": relations,
        "roster": dict(roster.key_to_name),
        "stats": stats,
    }


if __name__ == "__main__":
    import sys
    log_dir = sys.argv[1] if len(sys.argv) > 1 else "logs"
    rooms = sys.argv[2:] or ["641306", "778329", "205171", "209915", "021808", "078400", "236995"]
    grand = 0
    for r in rooms:
        f = load_room_facts(log_dir, r)
        kinds: Dict[str, int] = {}
        opp = 0
        for rel in f["relations"]:
            kinds[rel["kind"]] = kinds.get(rel["kind"], 0) + 1
            opp += rel["sign"] == "opposes"
        grand += len(f["relations"])
        print(f"{r}: turns={len(f['turns'])} relations={len(f['relations'])} "
              f"(opposes={opp}) kinds={kinds} stats={f['stats']}")
    print(f"TOTAL relations = {grand}")
