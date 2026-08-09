# -*- coding: utf-8 -*-
"""Knowledge-base integrity for BOTH scenarios, run as part of the offline suite.

Mirrors validate_kb.py so a bad edit to either build_*_kb.py cannot land
silently. The check that actually caught real bugs during both expansions is the
keyword self-match test: matching returns the FIRST card whose keyword appears in
the message, so a broad keyword on an earlier card shadows a specific phrase on a
later one. Two such cases are on record:

  * parent_child — `parent_interparental_conflict` ("we argue", "fighting in
    front of the kids") must stay ahead of `parent_power_struggle` ("argue",
    "fight", "conflict"), or the interparental card is unreachable in English.
  * employment  — `life_burnout_signals` originally used the bare word
    "drained", which swallowed `life_work_intensity_health`'s "physically
    drained"; it is now "emotionally drained".

Any change to a build script must keep this green. Excluded-topic lists are kept
PER SCENARIO on purpose (parenting and employment exclude different things) and
must not be merged.
"""
import json
import os
import re
import shutil

from _harness import bootstrap, Checker

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bootstrap("agentwake_kb_")
shutil.copytree(os.path.join(BACKEND, "background_templates"), "background_templates")

_ck = Checker(); check = _ck.check
CJK = re.compile(r"[一-鿿]")

# Expected shape per scenario. The counts are asserted, not merely reported, so a
# silently dropped card or keyword fails the suite.
SCENARIOS = {
    "parent_child": {
        "stances": ["child_centered", "parent_centered", "relationship_centered"],
        "split": [9, 10, 9],
        "cards": 28,
        "keywords": 319,
        "edges": 66,
        "cross_stance": 36,
        "banned": ["霸凌", "bully", "拒学", "school refusal", "多动", "ADHD", "自闭",
                   "autism", "学习障碍", "learning disability", "体罚",
                   "corporal punishment", "打孩子"],
        # (must come first, would otherwise be shadowed by)
        "ordering": [("parent_centered", "parent_interparental_conflict",
                      "parent_power_struggle")],
    },
    # employment carries ONE fork-local card on top of the upstream 29
    # (growth_academia_vs_industry_comp, see build_employment_kb.py). Upstream
    # @987c0b0 asserts 29 / [9,10,10] / 323 kw / 61 edges / 22 cross — every
    # number below is that value plus this card's contribution, so a future
    # upstream sync can diff the delta rather than re-derive the totals:
    #   cards       29 -> 30   (+1)
    #   split    [9,10,10] -> [10,10,10]   (the card is growth_centered)
    #   keywords   323 -> 341  (+18: 10 en + 4 original spaced zh + 4 unspaced zh;
    #                           en >= zh is enforced by the parity check below)
    #   edges       61 -> 63   (+2 out-refs; edges are out-degree sums, NOT
    #                           symmetric, so no reverse refs were added)
    #   cross       22 -> 23   (+1: stability_financial_buffer is cross-stance;
    #                           growth_startup_vs_corporate is intra-growth)
    "employment": {
        "stances": ["growth_centered", "stability_centered", "life_centered"],
        "split": [10, 10, 10],
        "cards": 30,
        "keywords": 341,
        "edges": 63,
        "cross_stance": 23,
        "banned": ["歧视", "discrimination", "性骚扰", "harassment", "签证", "visa",
                   "移民", "immigration", "抑郁症", "depression diagnosis", "仲裁",
                   "lawsuit", "劳动仲裁", "sue "],
        # Local addition. Both cards carry 企业; keeping the firm-type card first
        # means a bare 企业 hint binds there rather than to the pay-comparison
        # card. Upstream's list is empty for employment.
        "ordering": [("growth_centered", "growth_startup_vs_corporate",
                      "growth_academia_vs_industry_comp")],
    },
}


def _match(msg, pool):
    low = msg.lower()
    for c in pool:
        for kw in c["keywords"]:
            if kw.lower() in low:
                return c
    return None


for scenario, exp in SCENARIOS.items():
    path = os.path.join("background_templates", "stance_knowledge", f"{scenario}.json")
    with open(path, encoding="utf-8") as f:
        D = json.load(f)
    cards = [c for cfg in D.values() for c in cfg["topic_cards"]]
    all_ids = {c["id"]: st for st, cfg in D.items() for c in cfg["topic_cards"]}
    P = f"{scenario}:"

    # ---- shape ----------------------------------------------------------
    check(f"{P} {exp['cards']} topic cards", len(cards) == exp["cards"], str(len(cards)))
    check(f"{P} stance split is {'/'.join(map(str, exp['split']))}",
          [len(D[s]["topic_cards"]) for s in exp["stances"]] == exp["split"],
          str({s: len(c["topic_cards"]) for s, c in D.items()}))

    REQUIRED = {"id", "tag", "keywords", "text", "source", "source_type", "related_cards"}
    bad = [c["id"] for c in cards if REQUIRED - set(c)]
    check(f"{P} every card has the required fields (incl. tag)", not bad, str(bad))
    bad = [c["id"] for c in cards
           if not {"zh", "en"} <= set(c["tag"]) or not {"zh", "en"} <= set(c["text"])]
    check(f"{P} tag and text are bilingual on every card", not bad, str(bad))
    bad = [s for s, cfg in D.items()
           if not {"zh", "en", "source", "tag"} <= set(cfg["generic_fallback"])]
    check(f"{P} every generic_fallback has zh/en/source/tag", not bad, str(bad))

    # ---- keyword parity -------------------------------------------------
    bad = [c["id"] for c in cards
           if len([k for k in c["keywords"] if not CJK.search(k)])
           < len([k for k in c["keywords"] if CJK.search(k)])]
    check(f"{P} English keywords at least at parity with Chinese", not bad, str(bad))

    # ---- related_cards graph --------------------------------------------
    broken = [(c["id"], r) for c in cards for r in c["related_cards"] if r not in all_ids]
    check(f"{P} no broken related_cards references", not broken, str(broken))
    thin = [(c["id"], len(c["related_cards"])) for c in cards if len(c["related_cards"]) < 2]
    check(f"{P} every card has >= 2 related edges", not thin, str(thin))
    edges = sum(len(c["related_cards"]) for c in cards)
    cross = sum(1 for st, cfg in D.items() for c in cfg["topic_cards"]
                for r in c["related_cards"] if all_ids.get(r) not in (None, st))
    check(f"{P} {exp['edges']} total edges", edges == exp["edges"], str(edges))
    check(f"{P} {exp['cross_stance']} cross-stance edges",
          cross == exp["cross_stance"], str(cross))

    # ---- content constraints --------------------------------------------
    bad = [c["id"] for c in cards if "一般性" not in c["text"]["zh"]]
    check(f"{P} every zh card carries the disclaimer sentence", not bad, str(bad))
    hits = [(c["id"], b) for c in cards for b in exp["banned"]
            if b.lower() in (c["text"]["zh"] + c["text"]["en"]
                             + " ".join(c["keywords"])).lower()]
    check(f"{P} no excluded sensitive topics (scenario-specific list)", not hits, str(hits))

    # ---- keyword self-match (the ordering guard) ------------------------
    total, fails = 0, []
    for stance, cfg in D.items():
        for c in cfg["topic_cards"]:
            for kw in c["keywords"]:
                total += 1
                msg = f"关于{kw}我想聊聊" if CJK.search(kw) else f"I want to talk about {kw}"
                hit = _match(msg, cfg["topic_cards"])
                if not hit or hit["id"] != c["id"]:
                    fails.append((c["id"], kw, hit["id"] if hit else None))
    check(f"{P} every keyword matches its own card ({total - len(fails)}/{total})",
          not fails, "shadowed: " + str(fails[:5]))
    check(f"{P} keyword count is {exp['keywords']} (guards against silent loss)",
          total == exp["keywords"], str(total))

    # ---- documented ordering dependencies -------------------------------
    for stance, first, second in exp["ordering"]:
        order = [c["id"] for c in D[stance]["topic_cards"]]
        check(f"{P} {first} precedes {second}",
              order.index(first) < order.index(second), str(order[:3]))


# ---- the specific shadowing that was fixed in employment ----------------
import stance_knowledge as sk
kb = sk.load_stance_knowledge()
check("employment: 'physically drained' still reaches life_work_intensity_health",
      sk.peek_matched_card_id("employment", "life_centered", "I feel physically drained",
                              "en", knowledge=kb) == "life_work_intensity_health")
check("employment: 'emotionally drained' reaches life_burnout_signals",
      sk.peek_matched_card_id("employment", "life_centered", "I am emotionally drained",
                              "en", knowledge=kb) == "life_burnout_signals")

# ---- structured accessors, both scenarios ------------------------------
check("loader discovers both scenarios by filename",
      set(kb) == {"parent_child", "employment"}, str(sorted(kb)))

hit = sk.get_stance_knowledge_hit("parent_child", "parent_centered",
                                  "我们夫妻吵架当着孩子面", "zh", knowledge=kb)
check("pc hit: specific card returns id + tag",
      hit and hit["id"] == "parent_interparental_conflict" and hit["tag"] == "父母间冲突",
      str(hit and (hit["id"], hit["tag"])))

hit_e = sk.get_stance_knowledge_hit("employment", "stability_centered",
                                    "公司最近在裁员", "zh", knowledge=kb)
check("emp hit: specific card returns id + tag",
      hit_e and hit_e["id"] == "stability_layoff_signals" and hit_e["tag"] == "裁员信号",
      str(hit_e and (hit_e["id"], hit_e["tag"])))
check("emp hit: related entries carry id and tag",
      hit_e["related"] and all(r["id"] and r["tag"] for r in hit_e["related"]),
      str([(r["id"], r["tag"]) for r in hit_e["related"]]))
check("emp hit: cross-stance related resolves",
      any(r["id"].startswith(("growth_", "life_"))
          for r in sk.get_stance_knowledge_hit("employment", "growth_centered",
                                               "跳槽时机", "zh", knowledge=kb)["related"]))

fb = sk.get_stance_knowledge_hit("employment", "growth_centered",
                                 "今天天气不错", "zh", knowledge=kb)
check("emp: no keyword -> fallback with id None but a tag",
      fb and fb["id"] is None and fb["tag"] and fb["is_fallback"] is True, str(fb))
check("emp: no stance -> None",
      sk.get_stance_knowledge_hit("employment", None, "x", knowledge=kb) is None)

for scenario, n in (("parent_child", 28), ("employment", 30)):  # employment: 29 upstream + 1 local
    tm_zh = sk.get_tag_map(scenario, "zh", knowledge=kb)
    tm_en = sk.get_tag_map(scenario, "en", knowledge=kb)
    check(f"get_tag_map({scenario}) covers every card", len(tm_zh) == n, str(len(tm_zh)))
    check(f"get_tag_map({scenario}) is language-aware",
          tm_zh != tm_en and set(tm_zh) == set(tm_en))

# ---- the prompt-facing block is unchanged by the tag work ---------------
blk = sk.get_stance_knowledge_block("employment", "stability_centered",
                                    "公司最近在裁员", "zh", knowledge=kb)
check("block renders exactly header + body + source (no extra tag line)",
      blk == f"=== 背景知识（仅供参考） ===\n{hit_e['text']}\n(来源: {hit_e['source']})",
      repr(blk[:120]))
check("block with include_header=False is the bare body",
      sk.get_stance_knowledge_block("employment", "stability_centered", "公司最近在裁员",
                                    "zh", knowledge=kb, include_header=False) == hit_e["text"])
check("block with include_related=True appends the related section",
      "[相关背景]" in sk.get_stance_knowledge_block(
          "employment", "stability_centered", "公司最近在裁员", "zh",
          knowledge=kb, include_related=True))

# =============================================================================
# LOCAL (fork-only) — the opt-in soft matcher.
#
# Upstream's _match() helper above is pure pass-1, so nothing it asserts says
# anything about this fork's pass 2. Pass 2 exists for the agent customizer,
# where the user types a short hint rather than a sentence, and it is the one
# place where a card reorder inside build_*_kb.py can silently change answers.
#
# The rules under test (stance_knowledge._soft_keyword_hit / _match_topic_card):
#   - off unless the caller passes allow_soft=True
#   - CJK fragments must be ANCHORED (prefix/suffix) in the keyword
#   - English fragments need >= 2 tokens, >= 5 chars, >= 1 non-stopword
#   - abstain entirely when more than one card soft-matches
# =============================================================================
PC = kb["parent_child"]
EMP = kb["employment"]


def _soft(scenario_cfg, stance, msg, lang="zh"):
    cards = scenario_cfg[stance]["topic_cards"]
    c = sk._match_topic_card(msg, cards, lang, allow_soft=True)
    return c["id"] if c else None


def _hard(scenario_cfg, stance, msg, lang="zh"):
    cards = scenario_cfg[stance]["topic_cards"]
    c = sk._match_topic_card(msg, cards, lang)  # allow_soft defaults to False
    return c["id"] if c else None


check("soft matching is OFF by default (runtime prompt path is upstream-pure)",
      _hard(PC, "parent_centered", "孩子") is None
      and _hard(EMP, "growth_centered", "跳槽时") is None)

# --- direction 1: generic hints must bind NOTHING -----------------------------
# Every entry here is a term a user could plausibly type that cannot discriminate
# between the cards of its own scenario: pronouns, time/degree adverbs, modal and
# negation stubs, and the scenario's own subject nouns (孩子/父母, 工作/公司).
# Binding one of these means an agent silently carries a research card the user
# never asked for, for the whole session.
GENERIC = {
    ("parent_child", "parent_centered"): ["孩子", "父母", "家长", "应该", "总是", "什么", "已经",
                              "现在", "时间", "自己", "一个", "这样", "东西", "的事"],
    ("parent_child", "child_centered"): ["孩子", "自己", "什么", "一下", "东西", "以后", "别人"],
    ("parent_child", "relationship_centered"): ["什么", "父母", "时间", "这样", "再说", "以前", "一样"],
    ("employment", "growth_centered"): ["工作", "公司", "企业", "行业", "什么", "现在", "以后",
                               "感觉", "时候", "自己", "一点"],
    ("employment", "stability_centered"): ["工作", "公司", "最近", "已经", "几年", "个人", "比较"],
    ("employment", "life_centered"): ["工作", "生活", "时间", "两个", "安排", "没有", "一个"],
}
_leaked = [(st, g, _soft(kb[sc], st, g)) for (sc, st), gs in GENERIC.items()
           for g in gs if _soft(kb[sc], st, g)]
check(f"no generic hint binds a card ({sum(len(v) for v in GENERIC.values())} probed)",
      not _leaked, str(_leaked[:5]))

# --- direction 2: every card stays reachable ----------------------------------
# A stoplist that is too aggressive is just as broken as one that is too loose,
# so pin the other side too: one natural hint per card, all 58 cards.
REACH = {
    ("employment", "growth_centered"): {
        "growth_job_change_timing": "跳槽", "growth_skill_obsolescence": "技能过时",
        "growth_industry_outlook": "夕阳", "growth_promotion_plateau": "晋升",
        "growth_startup_vs_corporate": "创业", "growth_learning_environment": "团队",
        "growth_specialist_generalist": "专精", "growth_network_effects": "人脉",
        "growth_affective_forecasting": "后悔",
        # the fork-local card: 学术/高校/薪酬/读博 are the natural zh hints for it
        "growth_academia_vs_industry_comp": "学术",
    },
    ("employment", "stability_centered"): {
        "stability_layoff_signals": "裁员", "stability_financial_buffer": "存款",
        "stability_sunk_cost": "浪费", "stability_risk_tolerance_state": "冒险",
        "stability_reversibility": "退路", "stability_industry_cyclical_risk": "周期",
        "stability_side_job_balance": "副业", "stability_contract_pitfalls": "试用期",
        "stability_loss_framing": "失去", "stability_job_insecurity_perception": "踏实",
    },
    ("employment", "life_centered"): {
        "life_burnout_signals": "倦怠", "life_commute_cost": "通勤",
        "life_income_adaptation": "涨薪", "life_meaning_orientation": "饭碗",
        "life_nonwork_identity": "爱好", "life_partner_career": "伴侣",
        "life_recovery_time": "待命", "life_relocation_family_impact": "换城市",
        "life_remote_hybrid_tradeoffs": "远程", "life_work_intensity_health": "身体",
    },
    ("parent_child", "child_centered"): {
        "child_device_dependency": "手机", "child_social_withdrawal": "朋友",
        "child_learning_motivation": "厌学", "child_sleep": "睡眠", "child_eating": "吃饭",
        "child_personal_jurisdiction": "隐私", "child_participation_voice": "被决定",
        "child_defiance": "顶嘴", "child_emotional_outburst": "发脾气",
    },
    ("parent_child", "parent_centered"): {
        "parent_power_struggle": "总是吵架", "parent_screen_time": "屏幕",
        "parent_academic_pressure": "补习", "parent_interparental_conflict": "夫妻",
        "parent_burnout": "精力", "parent_intensive_norms": "别人家",
        "parent_own_upbringing": "我爸", "parent_work_family": "加班",
        "parent_financial_stress": "经济", "parent_sibling_comparison": "老大",
    },
    ("parent_child", "relationship_centered"): {
        "relationship_communication_breakdown": "沟通",
        "relationship_trust_disclosure": "信任",
        "relationship_adolescent_distancing": "青春", "relationship_repair_timing": "冷静",
        "relationship_shared_time": "陪伴", "relationship_warmth_structure": "太严",
        "relationship_conflict_normativity": "正常",
        "relationship_inconsistent_styles": "唱红脸",
        "relationship_psychological_control": "内疚",
    },
}
_probed = sum(len(v) for v in REACH.values())
_unreachable = [(cid, hint, _soft(kb[sc], st, hint))
                for (sc, st), cards in REACH.items()
                for cid, hint in cards.items() if _soft(kb[sc], st, hint) != cid]
check(f"every card is reachable by a natural hint ({_probed} cards)",
      not _unreachable, str(_unreachable[:5]))
check("the reachability table covers every card in both scenarios",
      _probed == sum(len(cfg["topic_cards"]) for sc in (PC, EMP) for cfg in sc.values()),
      str(_probed))

# Medial CJK fragments: anchoring, not the stoplist, is what rejects these.
for stance, junk in (("growth_centered", "我的"), ("stability_centered", "这个人")):
    check(f"medial CJK fragment {junk!r} does not bind a card",
          _soft(EMP, stance, junk) is None, str(_soft(EMP, stance, junk)))

# All-stopword English fragments (anchoring cannot catch these — "of it" really
# is a suffix of "sick of it"; the non-stopword rule is what rejects them).
for stance, junk in (("life_centered", "of it"), ("life_centered", "at work")):
    check(f"all-stopword fragment {junk!r} does not bind a card",
          _soft(EMP, stance, junk, "en") is None, str(_soft(EMP, stance, junk, "en")))

# Ambiguity must abstain, not pick by json order. 吵架 is genuinely ambiguous
# between 夫妻吵架 (interparental) and 总是吵架 (parent-child); 决定 between
# 自己决定 and 被决定. Abstaining sends the user back to a sharper hint.
check("ambiguous hint '吵架' abstains rather than picking by card order",
      _soft(PC, "parent_centered", "吵架") is None,
      str(_soft(PC, "parent_centered", "吵架")))
check("ambiguous hint '决定' abstains rather than picking by card order",
      _soft(PC, "child_centered", "决定") is None,
      str(_soft(PC, "child_centered", "决定")))

# The chip label is the card's curated tag, never a raw match keyword.
# This is the regression that motivated the whole tag field: "we argue a lot"
# used to render a chip reading "conflict".
prev = sk.preview_matched_card("parent_child", "parent_centered", "we argue a lot",
                               "en", knowledge=kb)
_kws = [k.lower() for k in (prev["card"]["keywords_all"] if prev["matched"] else [])]
check("preview labels the chip with the card tag, not a keyword",
      prev["matched"] and prev["tags"][0]["label"].lower() not in _kws
      and prev["tags"][0]["label"] == prev["card"]["tag"],
      str(prev["tags"][0]["label"] if prev["matched"] else prev))
check("preview exposes card.tag so the UI can tell curated from derived",
      prev["matched"] and prev["card"]["tag"] and prev["card"]["title"] == prev["card"]["tag"])
_zh = sk.preview_matched_card("parent_child", "parent_centered", "我们俩总是有冲突",
                              "zh", knowledge=kb)
check("preview chip follows the UI language",
      _zh["matched"] and _zh["tags"][0]["label"] == "决定权争夺",
      str(_zh["tags"][0]["label"] if _zh["matched"] else _zh))
# Cards carry zh/en only; lang_utils.pick would hand a ja UI the Chinese tag
# while the keyword list stays English. preview resolves ja -> en instead.
_ja = sk.preview_matched_card("parent_child", "parent_centered", "we argue a lot",
                              "ja", knowledge=kb)
check("ja UI gets the English tag, matching its English keyword list",
      _ja["matched"] and _ja["tags"][0]["label"] == prev["tags"][0]["label"],
      str(_ja["tags"][0]["label"] if _ja["matched"] else _ja))

_ck.finish("KB INTEGRITY CHECKS PASSED")
