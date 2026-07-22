# -*- coding: utf-8 -*-
"""
transcript_report.py

Scores a saved chat log on the things that were going wrong in early runs:
information novelty, question overhead, and whether anyone actually disagreed.

Two uses:

1) Before/after comparison. Run it on a log from before the message-quality
   changes and one from after, and the difference is measurable rather than
   impressionistic.

2) Re-calibrating --novelty_threshold. The shipped default (0.35) was fitted to
   an ENGLISH transcript. With the language directive now in place, runs use
   --lang zh and scoring goes through the CJK bigram path, which has not been
   validated against real output. Run this on your first Chinese session, look
   at where the restatements actually land, and set the threshold below the
   lowest score you consider a genuine contribution.

    python transcript_report.py logs/442575.jsonl
    python transcript_report.py logs/442575.jsonl logs/998877.jsonl   # compare
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

# Reuse the scoring the live loop uses, so the report and the runtime guard can
# never drift apart.
from agentwake_new import novelty_ratio, has_disagreement, _content_tokens

NOVELTY_WINDOW = 10


def load_transcript(path: str) -> List[dict]:
    msgs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                msgs.append(json.loads(line))
    return msgs


def _questions(text: str) -> int:
    return text.count("?") + text.count("？")


def _mentions(text: str) -> int:
    return text.count("@")


def score(msgs: List[dict]) -> Dict[str, object]:
    lines = [f"{m['character']}: {m['txt']}" for m in msgs]
    rows = []
    for i, m in enumerate(msgs):
        if m["character"] == "user":
            continue
        prior = lines[max(0, i - NOVELTY_WINDOW):i]
        rows.append({
            "turn": i + 1,
            "speaker": m["character"],
            "novelty": novelty_ratio(m["txt"], prior) if prior else 1.0,
            "questions": _questions(m["txt"]),
            "mentions": _mentions(m["txt"]),
            "disagrees": has_disagreement(m["txt"]),
            "chars": len(m["txt"]),
        })
    if not rows:
        return {"rows": [], "n": 0}

    n = len(rows)
    return {
        "rows": rows,
        "n": n,
        "user_turns": sum(1 for m in msgs if m["character"] == "user"),
        "mean_novelty": sum(r["novelty"] for r in rows) / n,
        "low_novelty_share": sum(1 for r in rows if r["novelty"] < 0.35) / n,
        "questions_per_msg": sum(r["questions"] for r in rows) / n,
        "msgs_ending_in_question": sum(
            1 for i, m in enumerate(msgs)
            if m["character"] != "user" and m["txt"].rstrip().endswith(("?", "？"))
        ) / n,
        "disagreement_share": sum(1 for r in rows if r["disagrees"]) / n,
        "mean_chars": sum(r["chars"] for r in rows) / n,
    }


def print_report(path: str, s: Dict[str, object], detail: bool = True) -> None:
    print(f"\n===== {path} =====")
    if not s["n"]:
        print("  (no agent messages)")
        return
    if detail:
        print("  turn  speaker      novelty  Q  @  disagree  chars")
        for r in s["rows"]:
            flag = "  <- recycled" if r["novelty"] < 0.35 else ""
            print(f"  {r['turn']:4d}  {r['speaker']:<11} {r['novelty']:6.2f}  "
                  f"{r['questions']}  {r['mentions']}  {str(r['disagrees']):<8}  "
                  f"{r['chars']:5d}{flag}")
    print(f"\n  agent messages          {s['n']}")
    print(f"  user turns              {s['user_turns']}")
    print(f"  mean novelty            {s['mean_novelty']:.2f}   (higher is better)")
    print(f"  share below 0.35        {s['low_novelty_share']:.0%}   (lower is better)")
    print(f"  questions per message   {s['questions_per_msg']:.2f}  (lower is better)")
    print(f"  ends with a question    {s['msgs_ending_in_question']:.0%}   (lower is better)")
    print(f"  messages that disagree  {s['disagreement_share']:.0%}   (higher is better)")
    print(f"  mean length             {s['mean_chars']:.0f} chars")


def main(paths: List[str]) -> int:
    scored = []
    for p in paths:
        if not os.path.exists(p):
            print(f"ERROR: no such log: {p}", file=sys.stderr)
            return 2
        s = score(load_transcript(p))
        scored.append((p, s))
        print_report(p, s, detail=len(paths) == 1)

    if len(scored) == 2:
        (pa, a), (pb, b) = scored
        if not a["n"] or not b["n"]:
            return 0
        print(f"\n===== {os.path.basename(pa)}  ->  {os.path.basename(pb)} =====")
        for label, key, better in (
            ("mean novelty        ", "mean_novelty", "up"),
            ("share below 0.35    ", "low_novelty_share", "down"),
            ("questions per msg   ", "questions_per_msg", "down"),
            ("ends with question  ", "msgs_ending_in_question", "down"),
            ("messages disagreeing", "disagreement_share", "up"),
        ):
            delta = b[key] - a[key]
            good = (delta > 0) if better == "up" else (delta < 0)
            mark = "improved" if good and abs(delta) > 1e-9 else (
                "no change" if abs(delta) < 1e-9 else "worse")
            print(f"  {label}  {a[key]:6.2f} -> {b[key]:6.2f}  ({delta:+.2f})  {mark}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1:]))
