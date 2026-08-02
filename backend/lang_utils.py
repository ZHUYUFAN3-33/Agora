# -*- coding: utf-8 -*-
"""
lang_utils.py
Small helpers shared by profile_store.py and scenario_background.py
to keep bilingual (zh/en) behavior consistent everywhere.
"""
from __future__ import annotations
import re
from typing import Union

SUPPORTED_LANGS = ("zh", "en")
DEFAULT_LANG = "zh"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def normalize_lang(lang: str) -> str:
    """Fold any input into a supported lang code, defaulting to zh."""
    if not lang:
        return DEFAULT_LANG
    lang = lang.strip().lower()
    if lang.startswith("zh"):
        return "zh"
    if lang.startswith("en"):
        return "en"
    return DEFAULT_LANG


def detect_lang(text: str) -> str:
    """
    Lightweight heuristic: if the CJK character ratio among non-space
    characters exceeds 15%, treat as Chinese, else English.
    Used only as a fallback when the caller hasn't set --lang explicitly
    (e.g. to pick a sensible default from the first thing the user types).
    """
    if not text:
        return DEFAULT_LANG
    stripped = re.sub(r"\s+", "", text)
    if not stripped:
        return DEFAULT_LANG
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
    },
    "domain_background": {
        "zh": "=== 领域背景（系统提供，非用户所说，仅供参考）===",
        "en": "=== DOMAIN BACKGROUND (system-provided, not the user's own words, for reference only) ===",
    },
    "domain_background_caveat": {
        "zh": "（注意：以上是该类情况的一般性背景知识，不是对用户具体情况的判断，也不能替代对用户实际输入信息的了解。讨论时不要引用其中未出现的具体数字或事实。）",
        "en": "(Note: the above is general background knowledge for this type of situation, not a judgment about the user's specific case, and it does not substitute for understanding what the user has actually said. Do not cite specific numbers or facts beyond what is written here.)",
    },
    "unfilled": {
        "zh": "（未填写）",
        "en": "(not provided)",
    },
    "reported_by_parent": {
        "zh": "（家长转述，非孩子本人输入）",
        "en": "(as reported by the parent, not the child's own input)",
    },
}


def header(key: str, lang: str) -> str:
    return pick(SECTION_HEADERS[key], lang)
