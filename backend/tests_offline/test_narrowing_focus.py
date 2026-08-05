# -*- coding: utf-8 -*-
"""Template completeness: every stance has a phase_focus for every phase.

The Narrowing entries were missing entirely — during exactly the phase where
options get eliminated, the three voices lost their stance-specific brief and
fell back to the shared (state, decision) task, i.e. converged structurally.
This locks all 4 phases x all stances x both languages in both templates, via
the same accessor the prompt assembly uses.
"""
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND)  # stance.py resolves stance_templates/ relative to cwd

from _harness import Checker  # noqa: E402
import stance  # noqa: E402

_ck = Checker(); check = _ck.check

PHASES = ("Exploration", "Structuring", "Narrowing", "Convergence")

for scenario in ("employment", "parent_child"):
    stances = stance.list_stances(scenario)
    check(f"{scenario}: template defines stances", bool(stances))
    for st in stances:
        for phase in PHASES:
            for lang in ("zh", "en"):
                focus = stance.get_stance_phase_focus(scenario, st, phase, lang)
                check(f"{scenario}/{st}/{phase}/{lang}: phase focus present",
                      bool(focus and focus.strip()), repr(focus))

_ck.finish("PHASE FOCUS COMPLETENESS CHECKS PASSED")
