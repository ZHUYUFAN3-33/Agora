# -*- coding: utf-8 -*-
"""Acceptance for the per-deployment study policy (backend/study_policy.py):

  1. default    -> with no env set, every scene and every mode stays selectable,
                   which is what shard 1 and every local run depend on.
  2. scenarios  -> AGORA_ALLOWED_SCENARIOS narrows the roster, and a scene it
                   drops is reported unavailable rather than deleted.
  3. modes      -> AGORA_MODE_POLICY assigns a mode by participant id range,
                   inclusive on both ends, zero-padding-insensitive.
  4. shard 2    -> the exact strings fly.shard2.toml ships put P33-P44 in multi
                   and P45-P56 in single, and leave nobody in between.
  5. bad input  -> a malformed rule is ignored instead of locking people out.

No API key or network: this is pure string parsing.
"""
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from _harness import Checker  # noqa: E402

import study_policy as sp  # noqa: E402

_ck = Checker(); check = _ck.check

ALL_SCENES = ["employment", "parent_child"]

# ------------------------------------------------------------- default (2)
check("no env -> every scene", sp.allowed_scenarios(ALL_SCENES, env={}) == ALL_SCENES)
check("no env -> every mode", sp.allowed_modes("P33", env={}) == list(sp.ALL_MODES))

# ----------------------------------------------------------- scenarios (3)
only_job = {"AGORA_ALLOWED_SCENARIOS": "employment"}
check("env narrows the roster", sp.allowed_scenarios(ALL_SCENES, env=only_job) == ["employment"])
check("named scene stays allowed", sp.scenario_allowed("employment", ALL_SCENES, env=only_job))
check("dropped scene is blocked", not sp.scenario_allowed("parent_child", ALL_SCENES, env=only_job))
check("legacy scenes untouched", sp.scenario_allowed("scene4", ALL_SCENES, env=only_job))
check(
    "an env naming nothing we ship is ignored",
    sp.allowed_scenarios(ALL_SCENES, env={"AGORA_ALLOWED_SCENARIOS": "typo"}) == ALL_SCENES,
)

# --------------------------------------------------------------- modes (6)
shard2 = {"AGORA_MODE_POLICY": "P33-P44=multi;P45-P56=single"}
for uid in ("P33", "P39", "P44"):
    check(f"{uid} is multi only", sp.allowed_modes(uid, env=shard2) == ["full"], uid)
for uid in ("P45", "P50", "P56"):
    check(f"{uid} is single only", sp.allowed_modes(uid, env=shard2) == ["single"], uid)
check("P32 (shard 1) is unrestricted", sp.allowed_modes("P32", env=shard2) == list(sp.ALL_MODES))
check("P57 (past the roster) is unrestricted", sp.allowed_modes("P57", env=shard2) == list(sp.ALL_MODES))
check("zero padding matches", sp.allowed_modes("P045", env=shard2) == ["single"])
check("admin bypasses the policy", sp.allowed_modes("P45", is_admin=True, env=shard2) == list(sp.ALL_MODES))
check(
    "a single id is a one-element range",
    sp.allowed_modes("P40", env={"AGORA_MODE_POLICY": "P40=single"}) == ["single"],
)
check(
    "a rule may name several modes",
    sp.allowed_modes("P40", env={"AGORA_MODE_POLICY": "P33-P44=multi|single"}) == ["full", "single"],
)

# ------------------------------------------------------------ payload (3)
both = dict(only_job); both.update(shard2)
pol = sp.policy_for("P33", is_admin=False, all_scenarios=ALL_SCENES, env=both)
check("payload allows only the job scene", pol["allowed_scenarios"] == ["employment"])
check("payload allows only multi", pol["allowed_modes"] == ["full"])
check("payload flags both restrictions", pol["scenarios_restricted"] and pol["modes_restricted"])
unrestricted = sp.policy_for("P01", is_admin=False, all_scenarios=ALL_SCENES, env={})
check("unrestricted payload flags nothing",
      not unrestricted["scenarios_restricted"] and not unrestricted["modes_restricted"])

# ---------------------------------------------------------- bad input (3)
check("a rule with no '=' is dropped", sp.parse_mode_policy("P33-P44") == [])
check("an unknown mode is dropped", sp.parse_mode_policy("P33-P44=telepathy") == [])
check("mismatched prefixes are dropped", sp.parse_mode_policy("P33-Q44=single") == [])
check(
    "one bad rule does not sink the good one",
    sp.allowed_modes("P50", env={"AGORA_MODE_POLICY": "garbage;P45-P56=single"}) == ["single"],
)
check("a non-participant id is unrestricted", sp.allowed_modes("admin", env=shard2) == list(sp.ALL_MODES))
check("a missing id is unrestricted", sp.allowed_modes(None, env=shard2) == list(sp.ALL_MODES))

_ck.finish("ALL CHECKS PASSED")
