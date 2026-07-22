# -*- coding: utf-8 -*-
"""
agora_context.py

Single entry point agentwake_new.py should call. Wraps profile_store.py
and scenario_background.py so main() only needs one function call to get
everything needed for the KNOWN USER CONTEXT + DOMAIN BACKGROUND blocks.
"""
from __future__ import annotations

from typing import Dict, Tuple

from lang_utils import normalize_lang, detect_lang
from profile_store import (
    load_scenario_template,
    run_intake_flow,
)
from scenario_background import (
    load_background_template,
    get_scenario_background,
)


def prepare_session_context(
    user_id: str,
    scenario_type: str,
    lang: str = "zh",
    templates_dir: str = "scenario_templates",
    background_dir: str = "background_templates",
    profiles_dir: str = "profiles",
    auto_confirm_profile: bool = False,
    intake_file: str = None,
) -> Dict[str, str]:
    """
    Runs the full pre-session flow:
      1) Profile confirm/collect + Scenario Intake collect (interactive,
         unless auto_confirm_profile / intake_file are set for testing)
      2) Domain Background matched against the collected intake
    Returns the two prompt blocks ready to be handed to ChatAgent.system_prompt().
    """
    lang = normalize_lang(lang)

    intake_result = run_intake_flow(
        user_id=user_id,
        scenario_type=scenario_type,
        lang=lang,
        templates_dir=templates_dir,
        profiles_dir=profiles_dir,
        auto_confirm_profile=auto_confirm_profile,
        intake_file=intake_file,
    )

    bg_cfg = load_background_template(scenario_type, background_dir)
    # match_field (e.g. employment's decision_field, parent_child's child_age) may live
    # in either layer — decision_field is a Scenario Intake field, but child_age is a
    # Profile field. Merge both so matching works regardless of which layer it's in;
    # intake wins on overlap since it's the fresher, session-specific value.
    match_context = {**intake_result["profile"], **intake_result["intake"]}
    domain_background = get_scenario_background(
        scenario_type=scenario_type,
        intake=match_context,
        cfg=bg_cfg,
        lang=lang,
    )

    return {
        "known_context": intake_result["known_context"],
        "domain_background": domain_background,
        "profile": intake_result["profile"],
        "intake": intake_result["intake"],
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Run the full context-prep flow standalone (for testing).")
    ap.add_argument("--user_id", required=True)
    ap.add_argument("--scenario_type", required=True, choices=["employment", "parent_child"])
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--auto_confirm_profile", action="store_true",
                    help="Skip prompts for any profile field that already has a saved value")
    ap.add_argument("--intake_file", default=None,
                    help="Load Scenario Intake from this JSON file instead of asking interactively")
    args = ap.parse_args()

    ctx = prepare_session_context(args.user_id, args.scenario_type, args.lang,
                                   auto_confirm_profile=args.auto_confirm_profile,
                                   intake_file=args.intake_file)
    print("\n" + ctx["known_context"])
    print("\n" + ctx["domain_background"])
