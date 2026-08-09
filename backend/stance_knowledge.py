# -*- coding: utf-8 -*-
"""
stance_knowledge.py

Simplest possible version of the "keyword-triggered knowledge under a fixed
stance" feature discussed for the parent_child scenario:

  1. If the user's message matches a keyword in the CURRENT SPEAKING AGENT'S
     stance-specific topic cards -> use that card.
  2. Otherwise -> use that stance's generic fallback card.

Both paths are static, local dict lookups. No network calls, no vector
search, no LLM call — this is intentional: it keeps latency at zero and
keeps every possible output fully pre-written and auditable (same
"assignment-layer determinism" principle as PHASE_PROMPTS / STANCE_PROMPTS).

Data files: background_templates/stance_knowledge/{scenario_type}.json
(one file per scenario, e.g. parent_child.json, employment.json)
Each file's structure (no outer scenario_type key — the filename IS the
scenario type, matching the same convention already used for
scenario_templates/ and background_templates/):
  {
    "<stance>": {
      "topic_cards": [
        {
          "id": "...", "tag": {"zh":..., "en":...}, "keywords": [...],
          "text": {"zh":..., "en":...},
          "source": "...", "source_type": "academic|government|institutional",
          "related_cards": ["<other card id>", ...]
        }, ...
      ],
      "generic_fallback": {"zh":..., "en":..., "tag": {"zh":..., "en":...},
                           "source": "...", "source_type": "..."}
    }, ...
  }

`tag` is the card's curated short NAME. It exists so a frontend can label a
hit with what the card is about; the `keywords` are match triggers and must
never be shown as if they were the card's name.

Current coverage:
  parent_child.json: 28 topic cards + 3 fallbacks  (build_parent_child_kb.py)
  employment.json:   30 topic cards + 3 fallbacks  (build_employment_kb.py)
                     = 29 upstream + 1 fork-local card

=== FORK NOTE (read before syncing with agora2/backend-dev) ==================
Upstream baseline: agora2/backend-dev @ 987c0b0.

Every function below is upstream VERBATIM except for the two clearly banner-ed
LOCAL blocks and one upstream function that gained a single opt-in parameter:

  LOCAL BLOCK 1 (helpers, just below the imports)
  LOCAL BLOCK 2 (preview_matched_card, at the end of the module)
  _match_topic_card  — gained `allow_soft`, default False. With the default it
                       is byte-for-byte upstream behaviour; the local pass 2
                       only runs when a caller opts in.

The `allow_soft` chain (_match_topic_card -> peek_matched_card_id /
get_stance_knowledge_hit -> get_stance_knowledge_block) is threaded so the
runtime prompt path can stay pass-1 pure while the UI hint preview opts in.
Re-syncing means: take upstream wholesale, then re-apply those two blocks and
re-thread `allow_soft`.
=============================================================================
"""
from __future__ import annotations

import json
import os
import re
from typing import List, Optional

from lang_utils import normalize_lang, pick, header

STANCE_KNOWLEDGE_DIR_DEFAULT = os.path.join("background_templates", "stance_knowledge")


# =============================================================================
# LOCAL BLOCK 1 — fork-only helpers (no upstream counterpart)
#
# These back the agent-customizer UI, where the user types a SHORT setup hint
# ("跳槽", "手机") rather than a full sentence. Upstream only ever matches whole
# user messages, so it needs none of this.
# =============================================================================

_CJK_RE = re.compile(r"[一-鿿]")
_STANCE_ID_PREFIXES = (
    "growth_",
    "stability_",
    "life_",
    "child_",
    "parent_",
    "relationship_",
)

# English function words that must not, on their own, justify a soft match.
# Without this an input like "of it" reverse-matches the keyword "sick of it"
# and binds a burnout card. Measured on the 987c0b0 knowledge base: 56 such
# all-stopword fragments fired before this list existed.
_EN_STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from go got had has
have he her him his how i i'd i'm if in into is it it's its just like me my no
not of on or our out she should so than that the their them then there these
they this to too up us was we were what when which who whom why will with would
you your
""".split())

# The Chinese counterpart. It has to be an explicit list rather than a computed
# rule, because none of the structural signals actually separate these from real
# topic terms — all of the following were tried and measured on the 987c0b0 base
# and all of them fail:
#
#   fragment/keyword length ratio  — measures how long the KEYWORD is, not how
#       specific the hint is. It admits 工作 (⊂ 工作忙, 0.67) while rejecting
#       学术 (⊂ 学术界还是产业界, 0.25): wrong in both directions.
#   corpus document frequency     — 工作/孩子/应该 occur in 1-2 keywords each,
#       exactly like 跳槽/学术/裁员. No separation at all.
#   prefix-only anchoring         — Chinese compounds are head-final, so this
#       does drop 孩子 ⊂ 别人家的孩子, but it also drops 手机 ⊂ 抱着手机.
#
# What actually distinguishes them is lexical: these are pronouns, time and
# degree adverbs, modal/negation stubs, and the scenario's own subject nouns
# (孩子/父母 in parent_child, 工作/公司 in employment). A scenario's subject noun
# cannot discriminate between that scenario's own cards by construction.
#
# Rejecting means the preview shows no chip, which is the honest outcome: the
# hint was too generic to bind anything in particular. tests_offline/
# test_kb_integrity.py pins both directions (these stay unbound; every card
# stays reachable by some natural hint).
_CJK_GENERIC_HINTS = frozenset("""
一下 一个 一样 一点 一起 一条 上去 下去 两个 东西 事情 从小 以前 以后 会不
但是 何时 依然 你们 值不 做到 别人 别的 到时 前面 可以 只是 后面 咱们 哪来
因为 在的 多久 大家 头上 好家 如果 存在 安排 定规 家长 对着 已经 常吵 平时
几年 应该 开始 得不 得少 得说 心里 忙了 怎么 总是 感觉 应当 我们 我的 我能
什么 现在 再说 那时 起来 出来 过来 下来 上来 回来 一定 到底 究竟 反正
我说 我这 所以 才能 打算 时候 时间 是不 最近 有的 本来 来吗 标准 样子 比较
没有 父母 生活 电话 的人 的事 相关 看不 真的 知道 硬是 确实 而且 能不 自己
至于 觉得 该不 谁说 这个 这样 那个 那样 里面 问我 随时 需要 顺便 骤然
孩子 子女 家庭 工作 公司 企业 行业 职业 位置 个人 方向 环境 情况 问题 内容
经常 白天 试试 试看 考不 说不 让他 理他 理我 谁迁 凭什 为什 么事 么管 么久
还有 还能 关你 不了 不用 不算 不得 不去 不来 上要 上话 在忙 干了 走了 行了
""".split())


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _keyword_for_lang(kw: str, lang: str) -> bool:
    """Split bilingual keyword lists for UI: en → Latin-ish, zh → CJK-containing."""
    kw = (kw or "").strip()
    if not kw:
        return False
    cjk = _has_cjk(kw)
    if normalize_lang(lang) == "zh":
        return cjk
    return not cjk


def _soft_keyword_hit(msg_lower: str, kw_lower: str) -> bool:
    """Allow a short hint to match a longer keyword phrase.

    Hard match remains `kw in msg`. Soft match is the reverse (`msg in kw`) with
    guardrails, because reverse containment is enormously more permissive: on the
    987c0b0 knowledge base an unguarded version fires on 1,941 distinct fragments
    (4.6x the old, smaller base), including pure noise.

    Two guardrails, each fixing a measured failure class:

      CJK  — >= 2 chars, ANCHORED (prefix or suffix of the keyword), and not a
             generic term. Anchoring alone is not enough: 孩子 is a clean suffix
             of 别人家的孩子, so a bare "孩子" hint bound an intensive-parenting
             card. Anchoring kills the medial junk (我的 ⊂ 带我的人,
             个人 ⊂ 我这个人比较保守); _CJK_GENERIC_HINTS kills the rest. See that
             list for why this is lexical rather than computed.
      EN   — needs >= 2 tokens, >= 5 chars, and at least one token that is not a
             function word. Anchoring does NOT work here ("of it" is a genuine
             suffix of "sick of it"), so content-word presence is the test.
    """
    if not msg_lower or not kw_lower or msg_lower not in kw_lower:
        return False
    if _has_cjk(msg_lower):
        if len(msg_lower) < 2 or msg_lower in _CJK_GENERIC_HINTS:
            return False
        return kw_lower.startswith(msg_lower) or kw_lower.endswith(msg_lower)
    tokens = [t for t in re.split(r"\s+", msg_lower) if t]
    if len(tokens) < 2 or len(msg_lower) < 5:
        return False
    return any(t.strip(".,!?;:'\"") not in _EN_STOPWORDS for t in tokens)


def _humanize_card_id(card_id: str) -> str:
    title = card_id or ""
    for prefix in _STANCE_ID_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix):]
            break
    return title.replace("_", " ").strip()


# =============================================================================
# END LOCAL BLOCK 1 — everything below is upstream unless banner-ed otherwise
# =============================================================================


def load_stance_knowledge(dir_path: str = STANCE_KNOWLEDGE_DIR_DEFAULT) -> dict:
    """
    Loads background_templates/stance_knowledge/{scenario_type}.json — one
    file per scenario (parent_child.json, employment.json), matching the
    same split-file convention already used for scenario_templates/ and
    background_templates/. Missing scenario files are skipped silently
    (that scenario just has no knowledge base, same as before).

    Returns the same merged shape the rest of this module expects:
        {"<scenario_type>": {"<stance>": {...}, ...}, ...}
    """
    knowledge = {}
    if not os.path.isdir(dir_path):
        return knowledge
    for fname in os.listdir(dir_path):
        if not fname.endswith(".json"):
            continue
        scenario_type = fname[:-5]  # strip ".json"
        with open(os.path.join(dir_path, fname), "r", encoding="utf-8-sig") as f:
            knowledge[scenario_type] = json.load(f)
    return knowledge


def _match_topic_card(user_message: str, topic_cards: list, lang: str,
                      allow_soft: bool = False) -> Optional[dict]:
    """Upstream pass-1 matching, plus an opt-in fork-local pass 2.

    allow_soft=False (the default, and what every runtime prompt path uses) is
    byte-for-byte upstream behaviour.

    allow_soft=True adds the reverse-containment pass for SHORT setup hints. It
    is opt-in rather than always-on because pass 2 is only correct when the input
    is a hint; on a real user turn a terse message like "孩子" would soft-hit a
    specific research card that pass 1 would (correctly) have missed, sending the
    agent a card the user never asked about.

    Pass 2 ABSTAINS when more than one card soft-matches. Without that, the
    answer silently depends on card order inside the generated json — 38 such
    ambiguous inputs exist on the 987c0b0 base (e.g. "工作" soft-matches 5
    life_centered cards). Returning None there falls through to the generic
    fallback, which is the honest answer.
    """
    if not user_message:
        return None
    msg_lower = user_message.lower().strip()
    # Pass 1: classic "keyword appears in the message". Upstream behaviour.
    for card in topic_cards:
        for kw in card.get("keywords", []):
            if kw.lower() in msg_lower:
                return card
    if not allow_soft:
        return None
    # Pass 2 (LOCAL): short hint against a longer keyword; unique match only.
    soft_hits = []
    for card in topic_cards:
        for kw in card.get("keywords", []):
            if _soft_keyword_hit(msg_lower, kw.lower()):
                soft_hits.append(card)
                break
    return soft_hits[0] if len(soft_hits) == 1 else None


def _find_card_by_id(scenario_cfg: dict, card_id: str) -> Optional[dict]:
    """Searches all stances within a scenario for a topic card with this id
    (related_cards can point across stances, not just within the same one)."""
    for stance_cfg in scenario_cfg.values():
        for c in stance_cfg.get("topic_cards", []):
            if c.get("id") == card_id:
                return c
    return None


def peek_matched_card_id(
    scenario_type: str,
    stance: Optional[str],
    user_message: str,
    lang: str = "zh",
    knowledge: Optional[dict] = None,
    knowledge_dir: str = STANCE_KNOWLEDGE_DIR_DEFAULT,
    allow_soft: bool = False,
) -> Optional[str]:
    """Lightweight probe: return the id of the topic card `user_message` WOULD
    hit for this scenario/stance, or None (no keyword match, or no
    scenario/stance/knowledge base). Builds no text and never falls back to the
    generic card — it uses the exact same matcher as get_stance_knowledge_block,
    so callers can cheaply decide *whether* to expand related cards (and track
    repeat hits) before paying to assemble the full block.

    allow_soft must be passed the SAME value as the get_stance_knowledge_block
    call it gates, or the two disagree about what matched.
    """
    if not stance or not user_message:
        return None
    lang = normalize_lang(lang)
    if knowledge is None:
        knowledge = load_stance_knowledge(knowledge_dir)
    stance_cfg = knowledge.get(scenario_type, {}).get(stance)
    if not stance_cfg:
        return None
    card = _match_topic_card(user_message, stance_cfg.get("topic_cards", []), lang,
                             allow_soft=allow_soft)
    return card.get("id") if card else None


def get_stance_knowledge_hit(
    scenario_type: str,
    stance: Optional[str],
    user_message: str,
    lang: str = "zh",
    knowledge: Optional[dict] = None,
    knowledge_dir: str = STANCE_KNOWLEDGE_DIR_DEFAULT,
    allow_soft: bool = False,
) -> Optional[dict]:
    """Structured lookup result for the CURRENT speaking agent, or None.

    Returns:
        {
          "id":       card id, or None for the generic fallback
          "tag":      short display label in `lang` (frontends label the hit with this)
          "text":     the card body in `lang`
          "source":   citation string
          "related":  [{"id", "tag", "text", "source"}, ...] — one hop, may be empty
          "is_fallback": True when no keyword matched and the per-stance
                         generic card was used instead
        }
      None when there is no stance, no knowledge base for this
      scenario/stance, or no fallback defined.

    This is the structured counterpart of get_stance_knowledge_block(): the
    block flattens everything into one string, which a frontend cannot parse a
    `tag` back out of. `id` is the stable, language-independent key — use it for
    filtering and counting; use `tag[lang]` only for display.
    """
    if not stance:
        return None
    lang = normalize_lang(lang)

    if knowledge is None:
        knowledge = load_stance_knowledge(knowledge_dir)

    scenario_cfg = knowledge.get(scenario_type, {})
    stance_cfg = scenario_cfg.get(stance)
    if not stance_cfg:
        return None

    card = _match_topic_card(user_message, stance_cfg.get("topic_cards", []), lang,
                             allow_soft=allow_soft)
    if card is None:
        fallback = stance_cfg.get("generic_fallback")
        if not fallback:
            return None
        return {
            "id": None,
            "tag": pick(fallback.get("tag", {}), lang),
            "text": pick({"zh": fallback.get("zh", ""), "en": fallback.get("en", "")}, lang),
            "source": fallback.get("source", ""),
            "related": [],
            "is_fallback": True,
        }

    related = []
    for rel_id in card.get("related_cards", []):
        rel = _find_card_by_id(scenario_cfg, rel_id)
        if rel:
            related.append({
                "id": rel.get("id"),
                "tag": pick(rel.get("tag", {}), lang),
                "text": pick(rel["text"], lang),
                "source": rel.get("source", ""),
            })

    return {
        "id": card.get("id"),
        "tag": pick(card.get("tag", {}), lang),
        "text": pick(card["text"], lang),
        "source": card.get("source", ""),
        "related": related,
        "is_fallback": False,
    }


def get_stance_knowledge_block(
    scenario_type: str,
    stance: Optional[str],
    user_message: str,
    lang: str = "zh",
    knowledge: Optional[dict] = None,
    knowledge_dir: str = STANCE_KNOWLEDGE_DIR_DEFAULT,
    include_header: bool = True,
    include_related: bool = False,
    allow_soft: bool = False,
) -> str:
    """
    Returns a ready-to-inject text block for the CURRENT speaking agent
    (identified by its stance), or "" if this scenario/stance has no
    knowledge base defined (e.g. employment, or stances not yet covered).

    knowledge: pass a pre-loaded dict to avoid re-reading the file every
    turn (recommended — load once in main(), reuse across the session).

    include_related: when True and a specific topic card was matched
    (not the generic fallback), also appends the one-hop related cards
    listed in that card's `related_cards` field — a lightweight stand-in
    for GraphRAG's multi-hop retrieval, implemented as plain dict lookups
    with zero added latency. Off by default; turn on only when you want
    to go a level deeper (e.g. the same topic keeps coming up across turns).

    Formatting only: the lookup itself lives in get_stance_knowledge_hit(), so
    the two can never disagree about what was matched. Output is byte-identical
    to the pre-`tag` behaviour, since every existing caller injects this string
    into a prompt.
    """
    hit = get_stance_knowledge_hit(scenario_type, stance, user_message, lang,
                                   knowledge=knowledge, knowledge_dir=knowledge_dir,
                                   allow_soft=allow_soft)
    if hit is None:
        return ""

    body = hit["text"]
    if not include_header:
        return body

    lang = normalize_lang(lang)
    label = "背景知识（仅供参考）" if lang == "zh" else "BACKGROUND KNOWLEDGE (for reference only)"
    src_label = "来源" if lang == "zh" else "Source"
    block = f"=== {label} ===\n{body}\n({src_label}: {hit['source']})"

    if include_related and not hit["is_fallback"] and hit["related"]:
        related_label = "相关背景" if lang == "zh" else "Related background"
        related_parts = [f"- {r['text']} ({src_label}: {r['source']})" for r in hit["related"]]
        block += f"\n\n[{related_label}]\n" + "\n".join(related_parts)

    return block


def get_tag_map(
    scenario_type: str,
    lang: str = "zh",
    knowledge: Optional[dict] = None,
    knowledge_dir: str = STANCE_KNOWLEDGE_DIR_DEFAULT,
) -> dict:
    """{card_id: tag} for every topic card in a scenario, across all stances.

    For frontends that render the related_cards graph: `related` entries carry
    ids, and resolving them to display labels otherwise means parsing the whole
    JSON client-side. Fallback cards have no id and are not included.
    """
    if knowledge is None:
        knowledge = load_stance_knowledge(knowledge_dir)
    lang = normalize_lang(lang)
    return {
        c["id"]: pick(c.get("tag", {}), lang)
        for stance_cfg in knowledge.get(scenario_type, {}).values()
        for c in stance_cfg.get("topic_cards", [])
        if c.get("id")
    }


# =============================================================================
# LOCAL BLOCK 2 — fork-only, no upstream counterpart
#
# Backs POST /api/knowledge-preview (app.py), which the agent customizer calls
# as the user types a setup hint, to show which knowledge card that hint binds.
# =============================================================================


def preview_matched_card(
    scenario_type: str,
    stance: Optional[str],
    hint: str,
    lang: str = "en",
    knowledge: Optional[dict] = None,
    knowledge_dir: str = STANCE_KNOWLEDGE_DIR_DEFAULT,
) -> dict:
    """
    Preview which topic card a setup hint would bind for UI tags.
    Does NOT use generic_fallback (matches assemble preload: miss → empty).

    Soft matching is ON here (allow_soft=True) and only here among the public
    entry points: this is the one caller whose input is a short hint by design.

    Tags are topic identity (+ optional source_type), not match-keyword
    synonyms. The label is the card's curated `tag`; a keyword is now only a
    last resort. It used to be the DEFAULT, which is why typing "we argue a lot"
    produced a chip reading "conflict" — a raw trigger word — instead of the
    card's actual subject, "Struggle over authority".
    """
    hint = (hint or "").strip()
    lang = normalize_lang(lang)
    if not scenario_type or not stance or not hint:
        return {"matched": False, "fallback": False, "tags": [], "card": None}

    if knowledge is None:
        knowledge = load_stance_knowledge(knowledge_dir)
    scenario_cfg = (knowledge or {}).get(scenario_type, {}) or {}
    stance_cfg = scenario_cfg.get(stance) if isinstance(scenario_cfg, dict) else None
    if not isinstance(stance_cfg, dict):
        return {"matched": False, "fallback": False, "tags": [], "card": None}

    card = _match_topic_card(hint, stance_cfg.get("topic_cards", []) or [], lang,
                             allow_soft=True)
    if not card:
        return {"matched": False, "fallback": False, "tags": [], "card": None}

    keywords = list(card.get("keywords") or [])
    lang_keywords = [kw for kw in keywords if _keyword_for_lang(kw, lang)]
    display_keywords = lang_keywords or keywords

    # Cards carry zh/en only. lang_utils.pick walks ("zh","en","ja") in order, so
    # pick(tag, "ja") silently returns the CHINESE label while _keyword_for_lang
    # hands a ja UI the ENGLISH keywords — label and keywords would contradict
    # each other. Resolve ja to en so the chip stays internally consistent.
    _tag_obj = card.get("tag") or {}
    tag_label = (pick(_tag_obj, "en") if lang == "ja" else pick(_tag_obj, lang)).strip()

    # Label priority: curated tag -> humanized id -> keyword -> raw id. Every
    # generated card has a tag, so the later rungs only catch a hand-added card
    # that predates the field.
    humanized = _humanize_card_id(str(card.get("id") or ""))
    topic_label = (
        tag_label
        or humanized
        or (lang_keywords[0] if lang_keywords else "")
        or (keywords[0] if keywords else "")
        or str(card.get("id") or "")
    )
    tags: List[dict] = [{"id": f"topic:{card.get('id')}", "label": topic_label}]
    source_type = (card.get("source_type") or "").strip()
    if source_type:
        tags.append({"id": f"source:{source_type}", "label": source_type})

    return {
        "matched": True,
        "fallback": False,
        "tags": tags,
        "card": {
            "id": card.get("id"),
            # None distinguishes "this card has no curated name yet" (fix the KB)
            # from "the name happens to equal the derived title".
            "tag": tag_label or None,
            "title": topic_label,
            "keywords": display_keywords,
            "keywords_all": keywords,
            "source_type": source_type or card.get("source_type"),
        },
    }


# =============================================================================
# END LOCAL BLOCK 2
# =============================================================================


if __name__ == "__main__":
    knowledge = load_stance_knowledge()

    print("--- hit a topic card (parent_child) ---")
    print(get_stance_knowledge_block(
        "parent_child", "parent_centered", "我们俩总是有冲突", lang="zh", knowledge=knowledge))

    print("\n--- no keyword match -> generic fallback (parent_child) ---")
    print(get_stance_knowledge_block(
        "parent_child", "child_centered", "他说想学做饭", lang="zh", knowledge=knowledge))

    print("\n--- English, topic card (parent_child) ---")
    print(get_stance_knowledge_block(
        "parent_child", "relationship_centered", "I don't think he trusts me anymore",
        lang="en", knowledge=knowledge))

    print("\n--- employment scenario now has content too ---")
    print(get_stance_knowledge_block(
        "employment", "stability_centered", "我担心公司要裁员了", lang="zh", knowledge=knowledge))

    print("\n--- one-hop related_cards expansion ---")
    print(get_stance_knowledge_block(
        "employment", "growth_centered", "感觉这份工作技能都要跟不上了", lang="zh",
        knowledge=knowledge, include_related=True))

    print("\n--- UI hint preview (soft matching ON, label is the card's tag) ---")
    print(preview_matched_card("parent_child", "parent_centered", "吵架", lang="zh",
                               knowledge=knowledge))
