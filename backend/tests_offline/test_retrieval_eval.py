# -*- coding: utf-8 -*-
"""Retrieval evaluation: what the scored pass changed, measured, not asserted.

Two things live here.

1. A BEFORE/AFTER table over labelled corpora. BEFORE is upstream pass 1 alone
   (exact case-folded substring, first card wins); AFTER is the shipped matcher.
   Every fire is printed so the numbers can be audited by eye rather than
   trusted, because "did it retrieve the RIGHT card" is a judgement no assertion
   can make.

2. Regression guards on the properties that must not drift: gold recall may not
   fall, and cross-scenario contamination may not gain a new offender.

Corpora bundled here are all team-authored (the 8 scripted teaser turns from
DUMMY_SESSIONS.md, the two DEMO01 turns, and the app's own suggested prompts).
Real participant messages are deliberately NOT committed — point
AGORA_RETRIEVAL_EVAL_CORPUS at an exported _replay.json to include them:

    AGORA_RETRIEVAL_EVAL_CORPUS=/path/to/_replay.json python tests_offline/test_retrieval_eval.py

Run from backend/ (load_stance_knowledge uses a relative default path).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stance_knowledge as sk  # noqa: E402

KB = sk.load_stance_knowledge()
EMP = ["growth_centered", "stability_centered", "life_centered"]
PC = ["child_centered", "parent_centered", "relationship_centered"]

FAILURES = []


def check(label, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def before(message, cards):
    """Upstream pass 1, verbatim: exact case-folded containment, first card wins."""
    low = (message or "").lower().strip()
    if not low:
        return None
    for card in cards:
        for keyword in card.get("keywords", []):
            if keyword.lower() in low:
                return card
    return None


def after(message, cards, lang="en"):
    return sk._match_topic_card(message, cards, lang, allow_soft=False)


# --------------------------------------------------------------------------- #
# corpora
# --------------------------------------------------------------------------- #
# DUMMY_SESSIONS.md A4, with that file's own "→ card" annotations as gold.
# Turns 5 and 8 carry no annotation: they exist to drive the option board and
# the closing question, and no card in any pool is about them.
SCRIPTED = [
    ("I finish my PhD in March and I have three offers on the table. I keep going "
     "back and forth — I am afraid I will regret whichever one I pick.",
     {"growth_affective_forecasting"}),
    ("If I take the Singapore research scientist job, can I ever come back to "
     "academia? Or is that a one-way door?",
     {"stability_reversibility", "growth_academia_vs_industry_comp"}),
    ("@B I want to hear you specifically on the contract side — the 3-year lab "
     "contract and the 2-year visa. Which one actually leaves me more exposed?",
     {"stability_contract_pitfalls"}),
    ("My partner has her own design career in Tokyo. Moving to Singapore means we "
     "live apart for at least two years.",
     {"life_relocation_family_impact", "life_partner_career"}),
    ("Compare the Kyoto one against the Shibuya one for me. What does each "
     "actually cost me?", set()),
    ("@A you keep pushing the PI track, but I have watched people stay postdocs "
     "for six years. What makes you think that will not be me?",
     {"growth_promotion_plateau"}),
    ("Honestly the salary gap is 4.7 million yen a year. Am I being naive putting "
     "research autonomy above that?",
     {"life_income_adaptation", "stability_financial_buffer"}),
    ("Say I go with the postdoc, the way I am leaning right now. What am I giving "
     "up that I will not be able to get back?", set()),
]

# The two real turns of the DEMO01 teaser session (room 596389). Same gold as
# scripted turns 1 and 2 — the participant typed the script verbatim.
DEMO = SCRIPTED[:2]

# The app's own opener chips (frontend/src/app/data/agents.ts,
# backend/scenes/*_prompts_en.json). A chip that can never retrieve anything is
# a chip that guarantees an unsourced first turn, so these are measured too.
SUGGESTED = {
    ("employment", "en"): None,
    ("employment", "zh"): None,
    ("parent_child", "en"): None,
    ("parent_child", "zh"): None,
}


def _load_suggested():
    """Read the prompts from the shipped files rather than restating them, so
    the eval cannot silently drift out of sync with what users are shown."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ts = os.path.join(os.path.dirname(here), "frontend", "src", "app", "data", "agents.ts")
    out = {}
    if not os.path.exists(ts):
        return out
    with open(ts, "r", encoding="utf-8") as f:
        text = f.read()
    for const, lang in (("SCENE_SUGGESTED_PROMPTS", "en"),
                        ("SCENE_SUGGESTED_PROMPTS_ZH", "zh")):
        start = text.find(f"export const {const}")
        if start < 0:
            continue
        for scenario in ("employment", "parent_child"):
            key = text.find(f"  {scenario}: [", start)
            if key < 0:
                continue
            end = text.find("],", key)
            body = text[key:end]
            out[(scenario, lang)] = [
                line.strip().strip(",").strip('"')
                for line in body.splitlines()[1:]
                if line.strip().startswith('"')
            ]
    return out


def run_corpus(name, items, scenario, lang, stances):
    """items: [(message, gold_ids)] — returns (before, after) summary dicts."""
    summary = {}
    for tag, matcher in (("before", before), ("after", lambda m, c: after(m, c, lang))):
        fires = gold_ok = gold_chances = 0
        rows = []
        for message, gold in items:
            for stance in stances:
                pool = KB[scenario][stance]["topic_cards"]
                ids = {c.get("id") for c in pool}
                wanted = gold & ids
                gold_chances += bool(wanted)
                card = matcher(message, pool)
                if not card:
                    continue
                fires += 1
                verdict = ("GOLD" if card["id"] in wanted
                           else ("WRONG-ON-GOLD" if wanted else "fire (no gold in pool)"))
                gold_ok += card["id"] in wanted
                rows.append((message[:58], stance, card["id"], verdict))
        summary[tag] = {"fires": fires, "gold_ok": gold_ok,
                        "gold_chances": gold_chances, "rows": rows}
    print(f"\n--- {name} ---")
    b, a = summary["before"], summary["after"]
    print(f"    fires        {b['fires']:3}  ->  {a['fires']:3}"
          f"   (of {len(items) * len(stances)} chances)")
    print(f"    gold on top  {b['gold_ok']:3}  ->  {a['gold_ok']:3}"
          f"   (of {a['gold_chances']} pairs where a gold card exists in that pool)")
    if a["rows"]:
        print("    every fire AFTER:")
        for msg, stance, cid, verdict in a["rows"]:
            print(f"      {stance[:9]:9} {cid:36} {verdict:24} {msg!r}")
    return b, a


def main():
    print("=" * 96)
    print("RETRIEVAL BEFORE/AFTER   (before = upstream pass 1 only, after = shipped matcher)")
    print("=" * 96)

    b_s, a_s = run_corpus("scripted teaser turns (DUMMY_SESSIONS.md A4)",
                          SCRIPTED, "employment", "en", EMP)
    b_d, a_d = run_corpus("DEMO01 session 596389 (the 2 real turns)",
                          DEMO, "employment", "en", EMP)

    prompts = _load_suggested()
    b_p = a_p = 0
    p_total = 0
    print("\n--- app suggested prompts (as shipped to users) ---")
    for (scenario, lang), items in sorted(prompts.items()):
        stances = EMP if scenario == "employment" else PC
        for message in items:
            for stance in stances:
                pool = KB[scenario][stance]["topic_cards"]
                p_total += 1
                b_p += bool(before(message, pool))
                hit = after(message, pool, lang)
                a_p += bool(hit)
                if hit:
                    print(f"      {scenario:12} {lang} {stance[:9]:9} "
                          f"{hit['id']:34} {message[:46]!r}")
    print(f"    fires        {b_p:3}  ->  {a_p:3}   (of {p_total} chances)")

    # Cross-scenario contamination: every fire here is a false positive by
    # construction — employment prompts against parent_child pools and back.
    #
    # This cannot happen at runtime: the pool is chosen by scenario before
    # retrieval is attempted. It sits here as a PROXY for spurious matching, so
    # what it guards is the SET of offenders rather than a count — a higher count
    # that adds no new offender is noise; a new offender is a regression.
    print("\n--- cross-scenario contamination (every fire is a false positive) ---")
    b_c = a_c = c_total = 0
    pairs = []
    for (scenario, lang), items in sorted(prompts.items()):
        other, o_stances = (("parent_child", PC) if scenario == "employment"
                            else ("employment", EMP))
        for message in items:
            for stance in o_stances:
                pool = KB[other][stance]["topic_cards"]
                c_total += 1
                b_c += bool(before(message, pool))
                hit = after(message, pool, lang)
                a_c += bool(hit)
                if hit:
                    pairs.append((scenario, stance, hit["id"], message[:44]))
    for src, stance, cid, msg in pairs:
        print(f"      {src:12} -> {stance[:12]:12} {cid:34} {msg!r}")
    print(f"    fires        {b_c:3}  ->  {a_c:3}   (of {c_total} chances)")

    real = os.environ.get("AGORA_RETRIEVAL_EVAL_CORPUS")
    if real and os.path.exists(real):
        turns = json.load(open(real, encoding="utf-8")).get("turns", [])
        seen = {}
        for t in turns:
            if t.get("has_pool") and t.get("query"):
                seen[(t["room_id"], t["query"], t["stance"])] = t
        b_r = a_r = 0
        for (_room, query, stance), t in seen.items():
            pool = KB[t["scenario"]][stance]["topic_cards"]
            b_r += bool(before(query, pool))
            a_r += bool(after(query, pool, t.get("lang", "zh")))
        print(f"\n--- real participant turns ({real}) ---")
        print(f"    fires        {b_r:3}  ->  {a_r:3}   (of {len(seen)} distinct lookups)")
    else:
        print("\n--- real participant turns: not loaded "
              "(set AGORA_RETRIEVAL_EVAL_CORPUS to include them) ---")

    print()
    check("scripted: gold recall did not fall", a_s["gold_ok"] >= b_s["gold_ok"],
          f"{b_s['gold_ok']} -> {a_s['gold_ok']} of {a_s['gold_chances']}")
    check("DEMO01: gold recall did not fall", a_d["gold_ok"] >= b_d["gold_ok"],
          f"{b_d['gold_ok']} -> {a_d['gold_ok']} of {a_d['gold_chances']}")
    check("suggested prompts: retrievability did not fall", a_p >= b_p, f"{b_p} -> {a_p}")
    # Documented, deliberately not tuned around. See the comment above.
    known = {
        # Pass 1, and older than the scored pass: the parent_child keyword 分居
        # (a couple separating) is a literal substring of 两地分居 (partners
        # living in different cities for work). A corpus flaw — fixing it means
        # editing the keyword, which is card curation, not retrieval.
        "parent_interparental_conflict",
        # Scored pass. "Five years from now, will I regret whichever one I turn
        # down?" shares two generic tokens with 'every conversation turns into a
        # fight', and scores 3.74 doing it — higher than several CORRECT fires,
        # so no score threshold separates the two. Left standing and named.
        "relationship_communication_breakdown",
    }
    new_offenders = sorted({cid for _s, _st, cid, _m in pairs} - known)
    check("cross-scenario contamination introduced no new offender",
          not new_offenders, f"{b_c} -> {a_c} fires; new: {new_offenders or 'none'}")
    # Tokenizer invariants. Both sides of the match — the keyword at index time
    # and the user's own words at query time — run through _stem, so the only
    # property that matters is that they agree. Each of these pinned a real
    # measured miss: `rules` indexed as `rul` while `rule` stayed `rule`, and
    # `savings` indexed as `saving` while `saving` stemmed on to `sav`.
    vocabulary = {w for scenario in KB.values() for stance in scenario.values()
                  for card in stance.get("topic_cards", [])
                  for keyword in card.get("keywords", [])
                  for w in sk._WORD_RE.findall(keyword.lower())}
    unstable = sorted(w for w in vocabulary if sk._stem(sk._stem(w)) != sk._stem(w))
    check("_stem is idempotent over the shipped keyword vocabulary",
          not unstable, f"unstable: {unstable or 'none'}")
    disagreeing = [(a, b) for a, b in [
        ("rules", "rule"), ("savings", "saving"), ("battles", "battle"),
        ("siblings", "sibling"), ("stress", "stressed"), ("grades", "grade"),
        ("scores", "score"), ("choices", "choice"), ("business", "businesses"),
    ] if sk._stem(a) != sk._stem(b)]
    check("_stem agrees across inflections of the same shipped word",
          not disagreeing, f"disagreeing: {disagreeing or 'none'}")

    plain = "Two years ago we didn't have this problem; now it is constant."
    smart = plain.replace("'", "’")
    pool = KB["parent_child"]["relationship_centered"]["topic_cards"]
    check("a typographic apostrophe retrieves the same card as a plain one",
          (after(plain, pool, "en") or {}).get("id") == (after(smart, pool, "en") or {}).get("id"),
          f"{(after(plain, pool, 'en') or {}).get('id')} vs {(after(smart, pool, 'en') or {}).get('id')}")

    check("scored pass never fires on a short setup hint",
          after("跳槽时", KB["employment"]["growth_centered"]["topic_cards"], "zh") is None
          and after("孩子", KB["parent_child"]["parent_centered"]["topic_cards"], "zh") is None)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("All retrieval-eval checks passed.")


if __name__ == "__main__":
    main()
