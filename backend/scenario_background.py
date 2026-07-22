# -*- coding: utf-8 -*-
"""
scenario_background.py

Implements Scenario Background Priming: domain knowledge that Agora AI
supplies to the agent group (not collected from the user), split into:

  - static_framework   : general knowledge about this decision type,
                          written once per scenario_type, reused always
  - targeted_entries    : matched against a field from the intake
                          (decision_field for employment / child_age for
                          parent_child), narrowing the framework to
                          something closer to the user's actual case
  - fallback_text        : used when no targeted entry matches

Every string is bilingual (zh/en); pick() resolves to the requested
language and falls back to whichever language is present.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from lang_utils import normalize_lang, pick, header, SECTION_HEADERS


def load_background_template(scenario_type: str, background_dir: str = "background_templates") -> dict:
    """Loads background_templates/{scenario_type}.json — one file per scenario."""
    path = os.path.join(background_dir, f"{scenario_type}.json")
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _match_keyword(value: str, entries: list, lang: str) -> Optional[str]:
    """Employment: decision_field free-text matched against a keyword list
    (keywords are bilingual in the data — Chinese and English terms both
    included per entry, so this works regardless of which language the
    user typed the field in)."""
    if not value:
        return None
    value_lower = str(value).lower()
    for entry in entries:
        for kw in entry.get("keywords", []):
            if kw.lower() in value_lower:
                return pick(entry["text"], lang)
    return None


def _match_age_range(value, entries: list, lang: str) -> Optional[str]:
    """Parent-child: child_age numeric value matched against inclusive ranges."""
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None
    for entry in entries:
        lo, hi = entry["range"]
        if lo <= age <= hi:
            return pick(entry["text"], lang)
    return None


def get_scenario_background(scenario_type: str, intake: dict, cfg: dict,
                             lang: str = "zh", include_header: bool = True) -> str:
    """
    Assembles the full Domain Background text for a session:
    static framework + targeted entry (or fallback), with an explicit
    "system-provided, not user-said" header and caveat so agents don't
    treat it as either a user statement or a source of hard numbers.
    """
    lang = normalize_lang(lang)
    if not cfg:
        return ""

    parts = [pick(cfg["static_framework"], lang)]

    match_type = cfg.get("match_type")
    match_field = cfg.get("match_field")
    match_value = intake.get(match_field) if match_field else None

    targeted_text = None
    if match_value not in (None, "", []):
        if match_type == "keyword":
            targeted_text = _match_keyword(match_value, cfg.get("targeted_entries", []), lang)
        elif match_type == "age_range":
            targeted_text = _match_age_range(match_value, cfg.get("targeted_entries", []), lang)

    parts.append(targeted_text if targeted_text else pick(cfg["fallback_text"], lang))

    body = "\n\n".join(p for p in parts if p)
    if not include_header:
        return body

    caveat = pick(SECTION_HEADERS["domain_background_caveat"], lang)
    return f"{header('domain_background', lang)}\n{body}\n{caveat}"


if __name__ == "__main__":
    # quick manual check
    employment_cfg = load_background_template("employment")
    parent_child_cfg = load_background_template("parent_child")

    demo_employment_zh = get_scenario_background(
        "employment", {"decision_field": "结构工程"}, employment_cfg, lang="zh")
    print(demo_employment_zh, "\n")

    demo_parent_en = get_scenario_background(
        "parent_child", {"child_age": 8}, parent_child_cfg, lang="en")
    print(demo_parent_en)
