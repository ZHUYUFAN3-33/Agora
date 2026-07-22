# -*- coding: utf-8 -*-
"""
agent_assembly.py

The assembly interface: takes the three dimensions discussed for Agora AI —
Decision Style, Emotion, Stance — and glues them into ONE fixed agent spec
per agent (A/B/C), replacing the old workflow of hand-pasting emotion.txt +
decision.txt content into chatbot1/2/3.txt yourself.

-------------------------------------------------------------------------
PRESET SLOTS (root-level folders — this is what "留预设位置" means):

    decision/            <- one txt file per decision style
        Rational.txt
        Intuitive.txt
        Dependent.txt
        Spontaneous.txt
        Avoidant.txt

    emotion/              <- one txt file per emotion
        Joy.txt
        Anger.txt
        Fear.txt
        Sadness.txt
        Disgust.txt
        Surprise.txt
        (add more later, e.g. Anxious.txt — no code change needed, as
         long as info.jsonl's "emotion" value matches the filename)

Both folders already ship populated with the txt files you originally
uploaded — nothing to fill in unless you add a NEW decision style or
emotion later, in which case just drop a same-named txt file into the
matching folder.
-------------------------------------------------------------------------

WHY STANCE ISN'T BAKED INTO THE SAME STATIC TEXT AS DECISION+EMOTION:

Decision + Emotion are genuinely static — same text every turn, same text
regardless of scenario. Stance is ALSO static for a given scenario (it
doesn't change turn to turn either), but it depends on scenario_type,
which decision/emotion don't. And the Convergence weight hint that rides
along with stance (see stance.py) depends on Scenario Intake data that
isn't known until the pre-session intake flow runs — i.e. after role_text
would normally be assembled.

So this module exposes ONE function, build_agent_spec(), that hands back
everything needed to construct a fixed agent in a single call:
  - role_text     : Decision + Emotion, spliced, ready to use as-is forever
  - stance        : the stance name (or None)
  - stance_text   : the stance instruction text (or "") — fixed for the
                    scenario, meant to be injected as its own prompt block
                    (ChatAgent.system_prompt(..., stance_text=...)) rather
                    than folded into role_text, so agentwake_new.py doesn't
                    end up with the same stance text appearing twice.
"""
from __future__ import annotations

import os
from typing import Dict, Optional, TypedDict

DECISION_DIR_DEFAULT = "decision"
EMOTION_DIR_DEFAULT = "emotion"

try:
    from stance import assign_stance, get_stance_text, stance_enabled
    HAVE_STANCE = True
except ImportError:
    HAVE_STANCE = False


class AgentSpec(TypedDict):
    agent_key: str
    decision: str
    emotion: str
    role_text: str
    stance: Optional[str]
    stance_text: str


# -------------------------------------------------------------------------
# Preset-slot readers
# -------------------------------------------------------------------------

def _read_preset(dir_path: str, name: str) -> str:
    """
    Reads {dir_path}/{name}.txt from the preset-slot folder. Returns a
    visible placeholder (not a silent empty string, not a crash) if the
    file hasn't been dropped in yet, so a missing preset is obvious in
    the assembled prompt rather than failing quietly.
    """
    if not name:
        return ""
    path = os.path.join(dir_path, f"{name}.txt")
    if not os.path.exists(path):
        return f"[MISSING PRESET: {path} — add this file to enable the '{name}' option]"
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def load_decision_text(name: str, decision_dir: str = DECISION_DIR_DEFAULT) -> str:
    """Preset slot: decision/{name}.txt"""
    return _read_preset(decision_dir, name)


def load_emotion_text(name: str, emotion_dir: str = EMOTION_DIR_DEFAULT) -> str:
    """Preset slot: emotion/{name}.txt"""
    return _read_preset(emotion_dir, name)


def list_available_presets(decision_dir: str = DECISION_DIR_DEFAULT,
                            emotion_dir: str = EMOTION_DIR_DEFAULT) -> Dict[str, list]:
    """Convenience: what preset names currently exist on disk, for validating info.jsonl."""
    def _names(d):
        if not os.path.isdir(d):
            return []
        return sorted(f[:-4] for f in os.listdir(d) if f.endswith(".txt"))
    return {"decision": _names(decision_dir), "emotion": _names(emotion_dir)}


# -------------------------------------------------------------------------
# Assembly
# -------------------------------------------------------------------------

def assemble_role_text(decision_name: str, emotion_name: str,
                        decision_dir: str = DECISION_DIR_DEFAULT,
                        emotion_dir: str = EMOTION_DIR_DEFAULT) -> str:
    """Splices Decision + Emotion only — this is the static role_text
    that used to be hand-pasted into chatbot1/2/3.txt."""
    emotion_text = load_emotion_text(emotion_name, emotion_dir)
    decision_text = load_decision_text(decision_name, decision_dir)

    parts = []
    if emotion_text:
        parts.append(f"--- EMOTION: {emotion_name} ---\n{emotion_text}")
    if decision_text:
        parts.append(f"--- DECISION STYLE: {decision_name} ---\n{decision_text}")
    return "\n\n".join(parts)


def build_agent_spec(agent_key: str, decision_name: str, emotion_name: str,
                      scenario_type: Optional[str] = None, lang: str = "zh",
                      decision_dir: str = DECISION_DIR_DEFAULT,
                      emotion_dir: str = EMOTION_DIR_DEFAULT) -> AgentSpec:
    """
    The single entry point: hands back everything needed to build one
    fixed agent — role_text (Decision+Emotion) plus stance/stance_text
    (kept separate on purpose, see module docstring).
    """
    role_text = assemble_role_text(decision_name, emotion_name, decision_dir, emotion_dir)

    stance = None
    stance_text = ""
    if HAVE_STANCE and scenario_type and stance_enabled(scenario_type):
        stance = assign_stance(scenario_type, agent_key)
        stance_text = get_stance_text(scenario_type, stance, lang)

    return {
        "agent_key": agent_key,
        "decision": decision_name,
        "emotion": emotion_name,
        "role_text": role_text,
        "stance": stance,
        "stance_text": stance_text,
    }


def build_all_agent_specs(agent_configs: Dict[str, dict],
                           scenario_type: Optional[str] = None, lang: str = "zh",
                           decision_dir: str = DECISION_DIR_DEFAULT,
                           emotion_dir: str = EMOTION_DIR_DEFAULT) -> Dict[str, AgentSpec]:
    """
    agent_configs: {"A": {"decision": "Rational", "emotion": "Joy"}, "B": {...}, "C": {...}}
    (this is exactly what load_agent_configs(info.jsonl) already returns in agentwake_new.py)

    Returns: {"A": AgentSpec, "B": AgentSpec, "C": AgentSpec}
    """
    return {
        key: build_agent_spec(
            agent_key=key,
            decision_name=cfg.get("decision", ""),
            emotion_name=cfg.get("emotion", ""),
            scenario_type=scenario_type,
            lang=lang,
            decision_dir=decision_dir,
            emotion_dir=emotion_dir,
        )
        for key, cfg in agent_configs.items()
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Preview one assembled agent (for testing, no API calls).")
    ap.add_argument("--agent_key", default="A", choices=["A", "B", "C"])
    ap.add_argument("--decision", required=True, help="e.g. Rational")
    ap.add_argument("--emotion", required=True, help="e.g. Joy")
    ap.add_argument("--scenario_type", default=None, choices=[None, "employment", "parent_child"])
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    args = ap.parse_args()

    print("Available presets:", list_available_presets())
    print()
    spec = build_agent_spec(args.agent_key, args.decision, args.emotion,
                             scenario_type=args.scenario_type, lang=args.lang)
    print("=== role_text (Decision + Emotion) ===")
    print(spec["role_text"])
    if spec["stance_text"]:
        print(f"\n=== stance_text ({spec['stance']}) ===")
        print(spec["stance_text"])
