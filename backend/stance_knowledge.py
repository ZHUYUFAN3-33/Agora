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

  LOCAL BLOCK 1 (helpers, just below the imports) — includes the scored
                 retrieval pass (`rank_topic_cards`, `_scored_topic_card` and
                 their tokenizer/index helpers)
  LOCAL BLOCK 2 (preview_matched_card, at the end of the module)
  _match_topic_card  — gained `allow_soft`, default False, AND a scored pass.
                       It is no longer byte-for-byte upstream on either branch:
                       allow_soft=False now falls through to BM25 instead of
                       returning None, and allow_soft=True still runs the local
                       pass 2. Only pass 1 itself is upstream.

The `allow_soft` chain (_match_topic_card -> peek_matched_card_id /
get_stance_knowledge_hit -> get_stance_knowledge_block) is threaded so the
runtime prompt path can stay pass-1 pure while the UI hint preview opts in.
Re-syncing means: take upstream wholesale, then re-apply those two blocks and
re-thread `allow_soft`.
=============================================================================
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import List, Optional

from lang_utils import normalize_lang, pick, header

# Resolved against THIS FILE, not the process CWD. The cards are package data
# that ships next to the module, so the caller's working directory has no say in
# whether they load. It used to be the bare relative path, and load_stance_knowledge()
# returns {} for a missing directory without raising or logging — so starting the
# server from the repo root instead of backend/ silently produced a session with
# no knowledge base at all. Measured on a real local run: 10 agent turns, every
# retrieval "skipped", zero cards, no error anywhere. Production only escaped it
# because the Dockerfile does COPY backend/ ./ with WORKDIR /app, which makes the
# CWD happen to be the backend directory.
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
STANCE_KNOWLEDGE_DIR_DEFAULT = os.path.join(
    _PACKAGE_DIR, "background_templates", "stance_knowledge")


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


# --- scored retrieval, used only by the per-turn runtime path ----------------
#
# Pass 1 (exact substring) is precise but only fires when the user reproduces a
# hand-written keyword verbatim, and users do not. Measured on production logs:
# 2 hits in 43 agent turns across 5 participants / 12 rooms, and 0 in the 10
# turns of the DEMO01 teaser session. The misses are not exotic — "I will
# regret" misses the keyword "will I regret" on word order alone, and "can I
# ever come back" misses "can I go back" on one inserted adverb.
#
# So pass 1.5 scores every card in the pool with BM25 over its keywords and
# takes the top one — which is also what sections/4-system.tex has always
# claimed this module does. Two properties matter more than the ranking itself:
#
#   BILINGUAL TOKENS. 11 of the 12 real rooms are Chinese, and Chinese has no
#   whitespace, so an English word tokenizer produces nothing at all on them.
#   Tokens are therefore English word stems plus Chinese character bigrams.
#
#   ABSTAINING. A wrong card is worse than no card, and roughly a third of real
#   user turns are meta requests ("compare these two for me") or topics the
#   corpus does not cover at all, where the correct output is nothing.
#   _BM25_MIN_MATCHED_TOKENS is what buys that: every false fire measured on the
#   real corpus rested on a SINGLE shared token — "offer" pulling in a contract
#   card, "salary" pulling in an income card — while every correct fire shared
#   at least two. Requiring two distinct query tokens removed all of them and
#   cost no correct hit. A runner-up margin was also tried and only ever lost
#   correct hits, so there is deliberately no such knob.
#
# Parameters were swept against four labelled corpora (real participant turns,
# the 8 scripted teaser turns, the DEMO01 session, and the app's own suggested
# prompts). tests_offline/test_retrieval_eval.py pins the outcome.

_BM25_K1 = 1.5
_BM25_B = 0.75
_BM25_MIN_SCORE = 2.0
_BM25_MIN_MATCHED_TOKENS = 2
# Scored retrieval is for whole user messages. A two-or-three character query is
# a setup hint, and binding one is the failure test_kb_integrity.py pins: "跳槽时"
# tokenizes to 跳槽 + 槽时, both of which sit inside the keyword 跳槽时机, so
# without this floor a bare hint would clear the two-token guard on its own.
# The shortest real participant message seen in production yields 5 tokens.
_BM25_MIN_QUERY_TOKENS = 4

_WORD_RE = re.compile(r"[a-z0-9']+")
_HAN_RUN_RE = re.compile(r"[一-鿿]+")
# U+2019 is what iOS/macOS smart punctuation and most IMEs emit, so "can’t"
# would otherwise tokenize to nothing (`can` is a stopword, `t` is one char)
# while the keyword "can't" keeps its token. 20 shipped keywords across 15 cards
# depend on that token.
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "´": "'"})

# Function words that must not, on their own, satisfy the two-matched-token
# acceptance bar. These are NOT dropped from the index or the query — `back` has
# to stay indexable for the keyword "can I go back", and `keep` for "keeping the
# door open" — they simply do not COUNT as topical evidence.
#
# Without this the bar is satisfiable by two pure function words, which is not a
# theoretical concern: "stay put for another year" matched {put, year} against
# the keyword "put in so many years" and was handed the sunk-cost card, and
# "I keep going back and forth" matched {back, keep} against
# stability_reversibility. Both are exactly the single-token failure the bar was
# introduced to stop, with a second function word making up the count.
_EN_WEAK_TOKENS = frozenset("""
about all am being back come every first long make many more most much new now
off only other over own people put right say still thing think through want way
keep last take give get go come know look see thing year years time
""".split())

# Pools are rebuilt from disk on every /api/message, but their card ids are
# stable, so the postings can be keyed off identity rather than recomputed.
# Bounded by the number of distinct (scenario, stance) pools — six today.
_INDEX_CACHE: dict = {}


def _stem(word: str) -> str:
    """Crude suffix strip, applied to a FIXPOINT.

    Both sides go through this — the keyword when the index is built and the
    user's own words when the query is tokenized — so the only property that
    actually matters is that the two agree. A single pass does not give that,
    because one suffix can mask another: `savings` lost its `s` and stopped,
    while the user's `saving` went on to lose `ing`, and the two never met. The
    same masking split `stress`/`stressed` and `siblings`/`sibling`. Looping
    until nothing more strips makes the function idempotent, which is what
    closes the gap.

    Plain `s` is stripped before `ing`/`ed` for the same reason, guarded on `ss`
    so `stress` and `business` keep theirs. An earlier version tried `es` before
    `s`, which cut the stem-final `e` off every silent-e plural — `rules` became
    `rul` while `rule` stayed `rule`, so a message saying "rule" could not reach
    the keyword "different rules".

    Irregulars are still missed (`hire`/`hiring`, `move`/`moved`). Closing those
    needs a real stemmer, which is a dependency this module does not have; what
    is fixed here is the class where BOTH sides are regular and only disagreed
    because the stripping was order-dependent.
    """
    previous = None
    while word != previous and len(word) > 3:
        previous = word
        if word.endswith("sses") and len(word) > 5:
            word = word[:-2]          # businesses -> business, passes -> pass
            continue
        if word.endswith("ss"):
            break
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s"):
            word = word[:-1]
        elif word.endswith("ing") and len(word) > 5:
            word = word[:-3]
        elif word.endswith("ed") and len(word) > 4:
            word = word[:-2]
        else:
            break
    return word


def _tokenize(text: str) -> List[str]:
    """English stems + CJK character bigrams, both lowercased.

    Bigrams rather than a word segmenter because segmentation would be another
    dependency and would still have to agree with how the keywords were written;
    overlapping bigrams match 加班 inside 并且加班多 without either.
    """
    text = (text or "").lower().translate(_APOSTROPHES)
    tokens = [_stem(w) for w in _WORD_RE.findall(text)
              if len(w) > 1 and w not in _EN_STOPWORDS]
    for run in _HAN_RUN_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
            continue
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def _pool_index(topic_cards: list):
    """(docs, document frequency, N, average length) for one stance pool.

    docs holds POSITIONS, never the card dicts. The pool is re-read from disk on
    every turn, so a cached card object is a card as it was when the index was
    first built — returning one would hand the prompt a stale body while pass 1,
    reading the fresh list, returned the current one for the same card id.

    The cache key is the keyword content itself for the same reason: keying on
    (id, keyword count) is stable across any edit that preserves the count, so an
    edited keyword list would go on being scored by its old postings.
    """
    key = tuple((c.get("id") or "", tuple(c.get("keywords") or [])) for c in topic_cards)
    cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    docs = []
    for position, card in enumerate(topic_cards):
        tokens = _tokenize(" ".join(card.get("keywords") or []))
        docs.append((position, len(tokens), _count(tokens)))
    n_docs = len(docs)
    doc_freq: dict = {}
    for _pos, _len, freqs in docs:
        for token in freqs:
            doc_freq[token] = doc_freq.get(token, 0) + 1
    avg_len = (sum(length for _p, length, _f in docs) / n_docs) if n_docs else 0.0
    index = (docs, doc_freq, n_docs, avg_len)
    _INDEX_CACHE[key] = index
    return index


def _count(tokens: List[str]) -> dict:
    freqs: dict = {}
    for token in tokens:
        freqs[token] = freqs.get(token, 0) + 1
    return freqs


def _rank_pool(user_message: str, topic_cards: list) -> List[tuple]:
    """[(score, strong_matched_count, card), ...] best first, or [] if the query
    is too short to be a real user message.

    The count returned is of TOPICAL matched tokens — matches on _EN_WEAK_TOKENS
    still contribute to the score but are not counted as evidence, because the
    acceptance bar downstream is expressed in that count.
    """
    if not user_message or not topic_cards:
        return []
    docs, doc_freq, n_docs, avg_len = _pool_index(topic_cards)
    if not n_docs or not avg_len:
        return []
    # Generic CJK stubs are dropped from the QUERY only: a card whose keyword
    # genuinely contains 工作 should still be findable by a more specific token.
    query = {t for t in _tokenize(user_message) if t not in _CJK_GENERIC_HINTS}
    if len(query) < _BM25_MIN_QUERY_TOKENS:
        return []
    scored = []
    for position, length, freqs in docs:
        score = 0.0
        matched = 0
        for token in query:
            freq = freqs.get(token, 0)
            if not freq:
                continue
            if token not in _EN_WEAK_TOKENS:
                matched += 1
            idf = math.log(1 + (n_docs - doc_freq[token] + 0.5) / (doc_freq[token] + 0.5))
            score += idf * freq * (_BM25_K1 + 1) / (
                freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * length / avg_len)
            )
        scored.append((score, matched, topic_cards[position]))
    # id as the tie-break so equal scores do not silently depend on JSON order.
    scored.sort(key=lambda r: (-r[0], r[2].get("id") or ""))
    return scored


def rank_topic_cards(user_message: str, topic_cards: list, limit: int = 3) -> List[dict]:
    """The ranking as plain data — [{"id", "score", "matched_tokens"}, ...].

    Public because the runtime logs the top few candidates for every retrieval
    ATTEMPT, hit or miss. Before that existed a miss left no trace anywhere, so a
    whole session could retrieve nothing with nothing in any log looking wrong.
    """
    ranked = _rank_pool(user_message, topic_cards)
    rows = [{"id": card.get("id"), "score": round(score, 4), "matched_tokens": matched}
            for score, matched, card in ranked]
    return rows[:limit] if limit else rows


def _surface_words(text: str) -> set:
    """Stemmed words INCLUDING function words, single letters dropped.

    _tokenize throws stopwords away, which is right for scoring and wrong for
    deciding whether the user reproduced a keyword PHRASE. "can I go back" and
    "decided for me" both reduce to one content token, but the first survives
    here as {can, go, back} against a message saying "can I ever come back",
    while the second keeps only {decid} against "before deciding".
    """
    text = (text or "").lower().translate(_APOSTROPHES)
    return {_stem(w) for w in _WORD_RE.findall(text) if len(w) > 1}


def _covered_keyword_ids(user_message: str, topic_cards: list) -> set:
    """Cards holding a keyword whose every content token the user said.

    The two-token floor is the right guard against a lone shared word dragging in
    an unrelated card, but on its own it also discards the single most valuable
    class of miss: the user says exactly what the keyword says, only not
    contiguously. "I will regret" against the keyword "will I regret" reduces to
    the one content token `regret`, and "can I ever come back" against
    "can I go back" reduces to `back` — both scored one matched token and were
    dropped, even though the keyword is fully contained in what the user wrote.

    So full coverage of a keyword is accepted as a second route in, with the
    degenerate case fenced off. A keyword that reduces to ONE content token has
    to clear two extra bars: that token must be unique to this card within the
    pool, AND *every* surface word of the keyword — function words included —
    must appear in the message.

    Both bars were arrived at by measurement, in that order. Pool-uniqueness
    alone let `decided for me` and `who decides` (both reducing to the
    pool-unique `decid`) fire on "What clarifying questions should I ask each
    company before deciding?". Requiring merely TWO surface words then let
    `disappointed in you` fire on "I was disappointed in how the school handled
    it" — the missing word is `you`, and `you` is the entire difference between
    a parent's disappointment in a child and in a school. Requiring all of them
    keeps `will I regret` against "I am afraid I will regret whichever one I
    pick", which is the case this route exists for, and drops both of those.

    What this route does NOT do is dispose of `just a job` — an earlier version
    of this docstring claimed it did. `_surface_words('just a job')` is
    {just, job} (the single letter is dropped, stopwords are deliberately kept),
    so any sentence with both words covers it fully. What actually rejects it is
    the pool-uniqueness bar: `job` has doc_freq 2 in the life_centered pool,
    because life_partner_career also carries "partner's job". That is worth
    knowing before curating: dropping that keyword would make
    life_meaning_orientation fire on any message containing `just` and `job`.
    """
    _docs, doc_freq, _n, _avg = _pool_index(topic_cards)
    query = {t for t in _tokenize(user_message) if t not in _CJK_GENERIC_HINTS}
    if len(query) < _BM25_MIN_QUERY_TOKENS:
        return set()
    surface = _surface_words(user_message)
    hits = set()
    for card in topic_cards:
        for keyword in card.get("keywords") or []:
            tokens = {t for t in _tokenize(keyword) if t not in _CJK_GENERIC_HINTS}
            if not tokens or not tokens <= query:
                continue
            if len(tokens) < 2:
                only = next(iter(tokens))
                # The one token carrying the whole keyword cannot be a weak one.
                # `make up` reduces to `make`, and "I want to make new rules but
                # I am not sure how to bring it up" covers both of its surface
                # words without being about making up at all.
                if only in _EN_WEAK_TOKENS or doc_freq.get(only, 0) != 1:
                    continue
                keyword_surface = _surface_words(keyword)
                if len(keyword_surface) < 2 or not keyword_surface <= surface:
                    continue
            hits.add(card.get("id"))
            break
    return hits


def _scored_topic_card(user_message: str, topic_cards: list) -> Optional[dict]:
    ranked = _rank_pool(user_message, topic_cards)
    if not ranked:
        return None
    covered = _covered_keyword_ids(user_message, topic_cards)
    # Rank order decides WHICH card; the two acceptance routes decide WHETHER
    # any card is good enough. Coverage is exempt from the score floor on
    # purpose — the floor exists to reject weak partial overlap, and a keyword
    # the user reproduced in full is not partial overlap however it scores.
    # growth_affective_forecasting on "I am afraid I will regret whichever one I
    # pick" is exactly that case: score 1.95, below the floor, keyword covered.
    for score, matched, card in ranked:
        if score <= 0:
            break
        if card.get("id") in covered:
            return card
        if score >= _BM25_MIN_SCORE and matched >= _BM25_MIN_MATCHED_TOKENS:
            return card
    return None


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
        # Pass 1.5 (LOCAL): scored retrieval — see the block above for why, and
        # why it sits here rather than before pass 1. Exact containment stays
        # first because it is the more precise signal when it fires; BM25 only
        # gets the turns that would otherwise have injected nothing at all.
        #
        # Confined to the allow_soft=False branch on purpose. allow_soft=True
        # means the input is a short SETUP HINT from the customizer UI, which
        # pass 2 already handles with hint-specific guardrails; running a
        # sentence-shaped retriever on a two-character hint would bind cards the
        # user never asked about, and would change chips the UI has always shown.
        return _scored_topic_card(user_message, topic_cards)
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
