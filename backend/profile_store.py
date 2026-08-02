# -*- coding: utf-8 -*-
"""
profile_store.py

Implements the two-layer information model discussed for Agora AI:

  User Profile     — persists across sessions, rarely changes
                      (profiles/{user_id}.json)
  Scenario Intake   — collected fresh every session, scenario-specific
                      (appended into the same file's session_history)

Both layers are driven by scenario_templates/{scenario_type}.json, and every
question / label used here is bilingual (zh/en) via lang_utils.pick().

This module only handles collection + storage + formatting into the
"KNOWN USER CONTEXT" prompt block. Matching that context to domain
background text is scenario_background.py's job.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from lang_utils import normalize_lang, pick, header, SECTION_HEADERS

PROFILES_DIR_DEFAULT = "profiles"


# -------------------------------------------------------------------------
# Template loading
# -------------------------------------------------------------------------

def load_scenario_template(scenario_type: str, templates_dir: str = "scenario_templates") -> dict:
    """Loads scenario_templates/{scenario_type}.json — one file per scenario."""
    path = os.path.join(templates_dir, f"{scenario_type}.json")
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


# -------------------------------------------------------------------------
# Profile persistence
# -------------------------------------------------------------------------

def _profile_path(user_id: str, profiles_dir: str = PROFILES_DIR_DEFAULT) -> str:
    os.makedirs(profiles_dir, exist_ok=True)
    safe_id = "".join(c for c in user_id if c.isalnum() or c in ("-", "_")) or "anonymous"
    return os.path.join(profiles_dir, f"{safe_id}.json")


def load_profile(user_id: str, profiles_dir: str = PROFILES_DIR_DEFAULT) -> dict:
    path = _profile_path(user_id, profiles_dir)
    if not os.path.exists(path):
        return {"profile": {}, "session_history": []}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("profile", {})
    data.setdefault("session_history", [])
    return data


def save_profile(user_id: str, data: dict, profiles_dir: str = PROFILES_DIR_DEFAULT) -> None:
    path = _profile_path(user_id, profiles_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -------------------------------------------------------------------------
# Interactive collection (CLI). Swap the _ask_* functions for your own
# frontend / form handler if this isn't run in a terminal.
# -------------------------------------------------------------------------

def _format_options_line(field: dict, lang: str) -> str:
    opts = field.get("options") or []
    labels = [f"{o['value']}={pick(o['label'], lang)}" for o in opts]
    return " / ".join(labels)


def _option_values(field: dict) -> list:
    return [o["value"] for o in (field.get("options") or [])]


def _coerce_option(field: dict, raw: str):
    """
    Maps whatever the user typed onto the option's stored `value`, accepting
    either the value itself ("joint") or the displayed label in either language
    ("共同决定" / "Joint decision"), case-insensitively.

    Storing a label instead of the value would break every downstream lookup
    keyed on the value — e.g. stance._PARENT_CHILD_OWNER_HINTS would silently
    miss and the Convergence weight hint would just vanish — so an unrecognized
    answer returns None and the caller re-asks rather than saving it as-is.
    """
    raw_norm = raw.strip().lower()
    for o in field.get("options") or []:
        if raw_norm == str(o["value"]).strip().lower():
            return o["value"]
        label = o.get("label")
        if isinstance(label, dict):
            for text in label.values():
                if text and raw_norm == str(text).strip().lower():
                    return o["value"]
        elif label and raw_norm == str(label).strip().lower():
            return o["value"]
    return None


def _ask_field(field: dict, lang: str, existing_value=None) -> object:
    q = pick(field["question"], lang)
    optional_note = ""
    if field.get("optional"):
        optional_note = " [Enter=skip]" if lang == "en" else " [直接回车可跳过]"

    is_select = field.get("type") == "select"
    # Shown in both branches: previously a returning user editing a select field
    # got no list of legal values at all.
    opt_line = _format_options_line(field, lang) if is_select else ""

    while True:
        if existing_value not in (None, "", []):
            confirm_prompt = f"{q}{optional_note}\n"
            if opt_line:
                confirm_prompt += f"  ({opt_line})\n"
            confirm_prompt += (
                f"  Current: {existing_value}\n  Press Enter to keep, or type a new value: "
                if lang == "en"
                else f"  当前记录：{existing_value}\n  回车保持不变，或输入新值："
            )
            raw = input(confirm_prompt).strip()
            if raw == "":
                return existing_value
        else:
            if is_select:
                raw = input(f"{q}{optional_note}\n  ({opt_line}) > ").strip()
            else:
                raw = input(f"{q}{optional_note} > ").strip()
            if raw == "" and field.get("optional"):
                return None

        if is_select:
            coerced = _coerce_option(field, raw)
            if coerced is None:
                allowed = ", ".join(_option_values(field))
                print(f"  Not a valid choice. Please enter one of: {allowed}" if lang == "en"
                      else f"  输入无效，请输入以下取值之一：{allowed}")
                continue
            return coerced

        value = raw
        break

    if field.get("type") == "number":
        try:
            return int(value)
        except ValueError:
            return value  # keep raw string rather than crash on odd input
    if field.get("type") == "list":
        return [v.strip() for v in value.split(",") if v.strip()]
    return value


def collect_or_confirm_profile(user_id: str, scenario_type: str, template: dict,
                                lang: str = "zh",
                                profiles_dir: str = PROFILES_DIR_DEFAULT,
                                auto_confirm: bool = False) -> dict:
    """
    First-time users: full form.
    Returning users: show current values, let them confirm/update per field
    instead of re-answering everything from scratch.

    auto_confirm=True: for testing / automated runs. Any field that already
    has a saved value is used silently with no prompt. Fields still missing
    (e.g. an incomplete example profile) fall back to a normal prompt —
    auto_confirm can't invent a value for something that was never provided.
    """
    lang = normalize_lang(lang)
    data = load_profile(user_id, profiles_dir)
    profile = data["profile"]
    fields = template["profile_fields"]

    is_new = not profile
    banner = (
        "\n--- Setting up your profile (first time) ---\n" if lang == "en" and is_new else
        "\n--- 首次使用，建立你的个人画像 ---\n" if is_new else
        "\n--- Confirm your saved profile ---\n" if lang == "en" else
        "\n--- 确认已保存的个人信息 ---\n"
    )
    if not auto_confirm:
        print(banner)

    for field in fields:
        key = field["key"]
        existing = profile.get(key)
        if auto_confirm:
            if existing not in (None, "", []):
                continue  # already have a value — use it silently, no prompt
            if field.get("optional"):
                continue  # optional and still empty — leave blank, no prompt
            # required and missing: auto_confirm can't invent a value, falls through to prompt
        answer = _ask_field(field, lang, existing_value=existing)
        if answer is not None:
            profile[key] = answer

    profile["last_updated"] = _now_iso()
    data["profile"] = profile
    save_profile(user_id, data, profiles_dir)
    return profile


def load_intake_from_file(path: str) -> dict:
    """
    Loads a pre-filled Scenario Intake from a flat JSON object, e.g.
    {"decision_field": "结构工程", "options": ["Company A", "Company B"], ...}.
    No validation against the template — used for testing/demo runs where
    you want to skip the interactive questions entirely.
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def collect_scenario_intake(scenario_type: str, template: dict, lang: str = "zh") -> dict:
    """Scenario Intake is always collected fresh — it's expected to change every session."""
    lang = normalize_lang(lang)
    fields = template["scenario_fields"]
    intake: Dict[str, object] = {}

    banner = "\n--- This session's details ---\n" if lang == "en" else "\n--- 本次决策的具体信息 ---\n"
    print(banner)

    for field in fields:
        answer = _ask_field(field, lang, existing_value=None)
        if answer is not None:
            intake[field["key"]] = answer

    return intake


def append_session_history(
    user_id: str,
    scenario_type: str,
    intake: dict,
    profiles_dir: str = PROFILES_DIR_DEFAULT,
    session_id: Optional[str] = None,
) -> str:
    """Records this session's intake so future sessions can offer it as a default hint.

    Dual-writes JSON profile session_history + SQLite session_intake when possible.
    Prefer passing room_id as session_id so DB joins stay stable.
    """
    data = load_profile(user_id, profiles_dir)
    sid = (session_id or "").strip() or f"{scenario_type}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    data["session_history"].append({
        "session_id": sid,
        "scenario_type": scenario_type,
        "intake": intake,
        "date": _now_iso(),
    })
    save_profile(user_id, data, profiles_dir)
    try:
        from user_store import get_user_store
        get_user_store().upsert_session_intake(sid, user_id, scenario_type, intake or {})
    except Exception:
        pass
    return sid


def most_recent_intake(user_id: str, scenario_type: str,
                        profiles_dir: str = PROFILES_DIR_DEFAULT) -> Optional[dict]:
    """Used to prefill defaults, e.g. 'last time deadline was 2 weeks, same this time?'."""
    try:
        from user_store import get_user_store
        db_intake = get_user_store().most_recent_session_intake(user_id, scenario_type)
        if db_intake:
            return db_intake
    except Exception:
        pass
    data = load_profile(user_id, profiles_dir)
    for entry in reversed(data.get("session_history", [])):
        if entry["scenario_type"] == scenario_type:
            return entry["intake"]
    return None


def _display_field_value(field: dict, value: Any, lang: str, unfilled: str) -> str:
    """Resolve select codes to labels; leave lists/text as-is."""
    if value in (None, "", []):
        return unfilled
    if field.get("type") == "select" and isinstance(value, str):
        for opt in field.get("options") or []:
            if str(opt.get("value")) == value:
                lab = opt.get("label")
                if isinstance(lab, dict):
                    return pick(lab, lang) or value
                if lab:
                    return str(lab)
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if field.get("type") == "multi_select" or field.get("options"):
                matched = None
                for opt in field.get("options") or []:
                    if str(opt.get("value")) == str(item):
                        lab = opt.get("label")
                        matched = pick(lab, lang) if isinstance(lab, dict) else (str(lab) if lab else str(item))
                        break
                parts.append(matched or str(item))
            else:
                parts.append(str(item))
        return ", ".join(parts)
    return str(value)


# -------------------------------------------------------------------------
# Prompt formatting — turns profile + intake into the KNOWN USER CONTEXT block
# -------------------------------------------------------------------------

def format_known_context(scenario_type: str, profile: dict, intake: dict,
                          template: dict, lang: str = "zh") -> str:
    """
    Builds the full "KNOWN USER CONTEXT" block for injection into
    ChatAgent.system_prompt(). Missing fields are explicitly marked
    (not omitted) so agents know what's genuinely still unknown and
    should be the target of Exploration-phase questions.
    """
    lang = normalize_lang(lang)
    cfg = template
    unfilled = pick(SECTION_HEADERS["unfilled"], lang)
    reported_by_parent = pick(SECTION_HEADERS["reported_by_parent"], lang)

    lines = [header("known_context", lang)]

    profile_label = "Profile" if lang == "en" else "用户画像"
    scenario_label = "This decision" if lang == "en" else "本次场景"
    lines.append(f"[{profile_label}]")
    for field in cfg.get("profile_fields") or []:
        key = field["key"]
        label = pick(field["question"], lang)
        value = profile.get(key)
        lines.append(f"- {label} -> {_display_field_value(field, value, lang, unfilled)}")

    lines.append(f"[{scenario_label}]")
    for field in cfg.get("scenario_fields") or []:
        key = field["key"]
        label = pick(field["question"], lang)
        value = intake.get(key)
        suffix = ""
        # Special-case: parent_child's child_stated_preference is always
        # a parent's account, never the child's own words — flag it inline.
        if scenario_type == "parent_child" and key == "child_stated_preference" and value not in (None, "", []):
            suffix = f" {reported_by_parent}"
        display = _display_field_value(field, value, lang, unfilled)
        lines.append(f"- {label} -> {display}{suffix}")

    # Free-text setup hint (not a template field) — always surface when present
    hint = (intake.get("hint") or profile.get("hint") or "").strip()
    if hint:
        hint_label = "Setup hint" if lang == "en" else "开场补充"
        lines.append(f"- {hint_label} -> {hint}")

    return "\n".join(lines)


# -------------------------------------------------------------------------
# End-to-end convenience entry point
# -------------------------------------------------------------------------

def run_intake_flow(user_id: str, scenario_type: str, lang: str = "zh",
                     templates_dir: str = "scenario_templates",
                     profiles_dir: str = PROFILES_DIR_DEFAULT,
                     auto_confirm_profile: bool = False,
                     intake_file: Optional[str] = None) -> Dict[str, dict]:
    """
    Full flow used before a session starts:
      1) load/confirm persistent Profile (or auto-confirm silently, for testing)
      2) collect fresh Scenario Intake (or load it from a file, for testing)
      3) persist intake into session_history
      4) return both, plus the formatted KNOWN USER CONTEXT block
    """
    template = load_scenario_template(scenario_type, templates_dir)
    profile = collect_or_confirm_profile(user_id, scenario_type, template, lang, profiles_dir,
                                          auto_confirm=auto_confirm_profile)
    if intake_file:
        intake = load_intake_from_file(intake_file)
    else:
        intake = collect_scenario_intake(scenario_type, template, lang)
    append_session_history(user_id, scenario_type, intake, profiles_dir)
    known_context = format_known_context(scenario_type, profile, intake, template, lang)
    return {"profile": profile, "intake": intake, "known_context": known_context}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Run the Profile + Scenario Intake collection flow standalone.")
    ap.add_argument("--user_id", required=True)
    ap.add_argument("--scenario_type", required=True, choices=["employment", "parent_child"])
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    args = ap.parse_args()

    result = run_intake_flow(args.user_id, args.scenario_type, args.lang)
    print("\n" + result["known_context"])
