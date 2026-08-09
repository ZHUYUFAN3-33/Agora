# -*- coding: utf-8 -*-
"""
lang_utils.py
Small helpers shared by profile_store.py and scenario_background.py
to keep zh / en / ja behavior consistent everywhere.
"""
from __future__ import annotations
import re
from typing import Union

SUPPORTED_LANGS = ("zh", "en", "ja")
DEFAULT_LANG = "zh"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_KANA_RE = re.compile(r"[\u3040-\u30ff]")


def normalize_lang(lang: str) -> str:
    """Fold any input into a supported lang code, defaulting to zh."""
    if not lang:
        return DEFAULT_LANG
    lang = lang.strip().lower()
    if lang.startswith("zh"):
        return "zh"
    if lang.startswith("en"):
        return "en"
    if lang.startswith("ja"):
        return "ja"
    return DEFAULT_LANG


def detect_lang(text: str) -> str:
    """
    Lightweight heuristic for fallback when --lang is unset.
    Kana → ja; otherwise CJK ratio → zh; else en.
    """
    if not text:
        return DEFAULT_LANG
    stripped = re.sub(r"\s+", "", text)
    if not stripped:
        return DEFAULT_LANG
    if _KANA_RE.search(stripped):
        return "ja"
    cjk_count = len(_CJK_RE.findall(stripped))
    ratio = cjk_count / len(stripped)
    return "zh" if ratio > 0.15 else "en"


def pick(bilingual: Union[dict, str], lang: str) -> str:
    """
    Fetch the right string out of a {"zh": "...", "en": "..."} object.
    Falls back to whichever language IS present if the requested one is
    missing, and passes plain strings through unchanged (so callers don't
    have to special-case legacy non-bilingual fields).
    """
    lang = normalize_lang(lang)
    if isinstance(bilingual, str):
        return bilingual
    if not isinstance(bilingual, dict):
        return ""
    if bilingual.get(lang):
        return bilingual[lang]
    # fallback to the other language rather than returning nothing
    for other in SUPPORTED_LANGS:
        if bilingual.get(other):
            return bilingual[other]
    return ""


SECTION_HEADERS = {
    "known_context": {
        "zh": "=== 已知用户信息（用户提供，勿重复询问）===",
        "en": "=== KNOWN USER CONTEXT (provided by user, do not re-ask) ===",
        "ja": "=== 既知のユーザー情報（ユーザー提供。再質問しない）===",
    },
    "domain_background": {
        "zh": "=== 领域背景（系统提供，非用户所说，仅供参考）===",
        "en": "=== DOMAIN BACKGROUND (system-provided, not the user's own words, for reference only) ===",
        "ja": "=== 分野背景（システム提供。ユーザー本人の発言ではない。参考のみ）===",
    },
    "domain_background_caveat": {
        "zh": "（注意：以上是该类情况的一般性背景知识，不是对用户具体情况的判断，也不能替代对用户实际输入信息的了解。讨论时不要引用其中未出现的具体数字或事实。）",
        "en": "(Note: the above is general background knowledge for this type of situation, not a judgment about the user's specific case, and it does not substitute for understanding what the user has actually said. Do not cite specific numbers or facts beyond what is written here.)",
        "ja": "（注：以上はその種の状況向けの一般的背景であり、ユーザー個別事情への判断ではない。ここに無い具体数字や事実を引用しないこと。）",
    },
    "unfilled": {
        "zh": "（未填写）",
        "en": "(not provided)",
        "ja": "（未記入）",
    },
    "reported_by_parent": {
        "zh": "（家长转述，非孩子本人输入）",
        "en": "(as reported by the parent, not the child's own input)",
        "ja": "（保護者による代理入力。子ども本人の入力ではない）",
    },
}


def header(key: str, lang: str) -> str:
    return pick(SECTION_HEADERS[key], lang)
