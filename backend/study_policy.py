# -*- coding: utf-8 -*-
"""Which scenarios and which experiment modes a participant may choose.

Both shards run the same image (one Dockerfile, one frontend bundle), so a
per-deployment split has to live in env rather than in code -- see
fly.shard2.toml. Two knobs, both empty by default, so shard 1 and every local
run keep the old behaviour of "everything is selectable":

    AGORA_ALLOWED_SCENARIOS = "employment"
        Scenario ids a participant may actually start. The others still appear
        in the picker, greyed out: a scene that silently vanishes reads as a
        bug to a participant who was told the study has two of them.

    AGORA_MODE_POLICY = "P33-P44=full;P45-P56=single"
        Per-participant mode assignment. `<first>-<last>=<mode>[|<mode>...]`,
        both ends inclusive, entries separated by ';' or ','. Ids are matched
        as letter prefix + number, so P5 and P05 are the same participant. A
        single id ("P40=single") is a one-element range. A participant no rule
        names keeps every mode, which is what shard 1 relies on.

Modes use the internal names ("full", "limited", "single"); "multi" and
"multi2" are accepted as aliases for the first two, because that is what the
sidebar calls them.

Admins bypass the mode policy -- Multi-2 is an operator tool and the operator
has to be able to reach it. They do NOT bypass the scenario list: a researcher
checking the deployment should see exactly what a participant sees.

Enforcement is in both directions on purpose. The frontend greys the options
out so nobody can pick them, and /api/start rejects them so a stale bundle or a
hand-rolled request cannot put a participant in the wrong condition -- which
would be invisible in the logs until analysis.
"""

import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ALL_MODES: Tuple[str, ...] = ("full", "limited", "single")

SCENARIOS_ENV = "AGORA_ALLOWED_SCENARIOS"
MODE_POLICY_ENV = "AGORA_MODE_POLICY"

_MODE_ALIASES: Dict[str, str] = {
    "full": "full",
    "multi": "full",
    "multi_agent": "full",
    "multiagent": "full",
    "limited": "limited",
    "multi2": "limited",
    "multi_2": "limited",
    "single": "single",
    "single_agent": "single",
    "singleagent": "single",
}

# "P33" -> ("P", 33). Zero padding is dropped so P05 and P5 match the same rule.
_USER_ID_RE = re.compile(r"^([A-Za-z]*?)0*(\d+)$")

_Rule = Tuple[str, int, int, List[str]]


def _env(name: str, env: Optional[Dict[str, str]] = None) -> str:
    src = os.environ if env is None else env
    return (src.get(name) or "").strip()


def _split(raw: str) -> List[str]:
    return [p.strip() for p in re.split(r"[;,]", raw or "") if p.strip()]


def _parse_user_id(user_id: Optional[str]) -> Optional[Tuple[str, int]]:
    m = _USER_ID_RE.match((user_id or "").strip())
    if not m:
        return None
    return m.group(1).upper(), int(m.group(2))


def _normalize_mode(raw: str) -> Optional[str]:
    key = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _MODE_ALIASES.get(key)


def parse_mode_policy(raw: str) -> List[_Rule]:
    """`"P33-P44=full;P45-P56=single"` -> [("P", 33, 44, ["full"]), ...].

    Unparseable entries are dropped rather than raised: a typo in a fly secret
    must not take the whole app down mid-study. Dropping one leaves that range
    unrestricted, which is the same as not having written the rule at all.
    """
    rules: List[_Rule] = []
    for part in _split(raw):
        if "=" not in part:
            continue
        span, _, modes_raw = part.partition("=")
        modes = [m for m in (_normalize_mode(x) for x in modes_raw.split("|")) if m]
        if not modes:
            continue
        lo_raw, _, hi_raw = span.strip().partition("-")
        lo = _parse_user_id(lo_raw)
        hi = _parse_user_id(hi_raw) if hi_raw.strip() else lo
        if not lo or not hi or lo[0] != hi[0]:
            continue
        rules.append((lo[0], min(lo[1], hi[1]), max(lo[1], hi[1]), modes))
    return rules


def allowed_modes(
    user_id: Optional[str],
    is_admin: bool = False,
    env: Optional[Dict[str, str]] = None,
) -> List[str]:
    if is_admin:
        return list(ALL_MODES)
    rules = parse_mode_policy(_env(MODE_POLICY_ENV, env))
    if not rules:
        return list(ALL_MODES)
    parsed = _parse_user_id(user_id)
    if not parsed:
        return list(ALL_MODES)
    prefix, num = parsed
    for rule_prefix, lo, hi, modes in rules:
        if rule_prefix == prefix and lo <= num <= hi:
            return list(modes)
    return list(ALL_MODES)


def allowed_scenarios(
    all_scenarios: Sequence[str],
    env: Optional[Dict[str, str]] = None,
) -> List[str]:
    wanted = {s.lower() for s in _split(_env(SCENARIOS_ENV, env))}
    if not wanted:
        return list(all_scenarios)
    keep = [s for s in all_scenarios if s.lower() in wanted]
    # An env that names nothing this build ships is a misconfiguration, and
    # locking every participant out of every scene is worse than ignoring it.
    return keep or list(all_scenarios)


def scenario_allowed(
    scenario_type: Optional[str],
    all_scenarios: Sequence[str],
    env: Optional[Dict[str, str]] = None,
) -> bool:
    if not scenario_type:
        return True
    if scenario_type not in all_scenarios:
        return True  # legacy scenes are not part of the Agora-2 roster
    return scenario_type in allowed_scenarios(all_scenarios, env=env)


def policy_for(
    user_id: Optional[str],
    is_admin: bool,
    all_scenarios: Iterable[str],
    env: Optional[Dict[str, str]] = None,
) -> dict:
    """What the client needs to render the pickers, in one payload."""
    scenarios = list(all_scenarios)
    allowed_s = allowed_scenarios(scenarios, env=env)
    allowed_m = allowed_modes(user_id, is_admin=is_admin, env=env)
    return {
        "user_id": user_id,
        "is_admin": bool(is_admin),
        "allowed_scenarios": allowed_s,
        "allowed_modes": allowed_m,
        "scenarios_restricted": len(allowed_s) < len(scenarios),
        "modes_restricted": len(allowed_m) < len(ALL_MODES),
    }
