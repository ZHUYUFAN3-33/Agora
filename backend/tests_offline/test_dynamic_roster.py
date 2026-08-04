# -*- coding: utf-8 -*-
"""Dynamic start roster: stance cycle + /api/start agents[] slot_keys (2/4/6 + default 3)."""
import os
import sys

backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
if backend not in sys.path:
    sys.path.insert(0, backend)

from stance import assign_stance, list_stances
from agent_assembly import build_all_agent_specs

failures = []


def check(ok: bool, label: str, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(label)


# --- stance cycle for D/E/F ---
emp = list_stances("employment")
slots4 = ["A", "B", "C", "D"]
check(assign_stance("employment", "A") == emp[0], "A keeps growth stance")
check(assign_stance("employment", "D", agent_keys=slots4) == emp[3 % 3], "D cycles to growth", assign_stance("employment", "D", agent_keys=slots4))
check(assign_stance("employment", "E", agent_keys=["A", "B", "C", "D", "E"]) == emp[4 % 3], "E cycles to stability")
check(assign_stance("employment", "F", agent_keys=["A", "B", "C", "D", "E", "F"]) == emp[5 % 3], "F cycles to life")

pc = list_stances("parent_child")
check(
    assign_stance("parent_child", "D", agent_keys=["A", "B", "C", "D"]) == pc[0],
    "parent_child D cycles child_centered",
)

# --- assemble N agents gets stance on each ---
cfg4 = {
    "A": {"decision": "Rational", "emotion": "Joy"},
    "B": {"decision": "Rational", "emotion": "Fear"},
    "C": {"decision": "Avoidant", "emotion": "Disgust"},
    "D": {"decision": "Dependent", "emotion": "Surprise"},
}
specs = build_all_agent_specs(cfg4, scenario_type="employment", lang="en")
check(set(specs.keys()) == {"A", "B", "C", "D"}, "assemble 4 keys")
check(all(specs[k].get("stance") for k in cfg4), "every agent has stance", {k: specs[k].get("stance") for k in cfg4})
check(specs["D"]["stance"] == emp[0], "assembled D stance cycles", specs["D"]["stance"])

# stance override + per-agent hint preload
cfg_override = {
    "A": {"decision": "Rational", "emotion": "Joy", "stance": "life_centered"},
    "B": {
        "decision": "Rational",
        "emotion": "Fear",
        "stance": "growth_centered",
        "hint": "job change timing",
    },
}
specs_o = build_all_agent_specs(cfg_override, scenario_type="employment", lang="en")
check(specs_o["A"]["stance"] == "life_centered", "stance override on A", specs_o["A"]["stance"])
check(bool(specs_o["B"].get("preloaded_knowledge")), "hint preload on B", bool(specs_o["B"].get("preloaded_knowledge")))
check(not specs_o["A"].get("preloaded_knowledge"), "no hint → no preload on A")

from stance_knowledge import preview_matched_card
prev = preview_matched_card("employment", "growth_centered", "job change timing", "en")
check(prev.get("matched") is True and len(prev.get("tags") or []) > 0, "knowledge preview tags")

# --- parse + session helpers from app (Flask may init) ---
try:
    import app as flask_app

    keys2, names2, rt2 = flask_app._parse_start_agents_payload(
        {
            "agents": [
                {"key": "A", "name": "Mia", "decision": "Rational", "emotion": "joy", "stance": "growth_centered", "hint": "x"},
                {"key": "B", "name": "Ethan", "decision": "Intuitive", "emotion": "fear"},
            ]
        },
        "full",
        scenario_type="employment",
    )
    check(rt2["A"].get("stance") == "growth_centered" and rt2["A"].get("hint") == "x", "parse stance+hint")
    check(keys2 == ["A", "B"], "parse 2 agents", keys2)
    check(names2["A"] == "Mia" and rt2["B"]["decision"] == "Intuitive", "parse names/runtime")

    keys6, _, _ = flask_app._parse_start_agents_payload(
        {
            "agents": [
                {"key": k, "name": f"Bot{k}", "decision": "Rational", "emotion": "Joy"}
                for k in "ABCDEF"
            ]
        },
        "full",
    )
    check(keys6 == list("ABCDEF"), "parse 6 agents")

    try:
        flask_app._parse_start_agents_payload(
            {"agents": [{"key": "A", "name": "Only", "decision": "Rational", "emotion": "Joy"}]},
            "full",
        )
        check(False, "reject 1 agent in full mode")
    except ValueError:
        check(True, "reject 1 agent in full mode")

    try:
        flask_app._parse_start_agents_payload(
            {
                "agents": [
                    {"key": k, "name": f"Bot{k}", "decision": "Rational", "emotion": "Joy"}
                    for k in "ABCDEFG"
                ]
            },
            "full",
        )
        check(False, "reject 7 agents")
    except ValueError:
        check(True, "reject 7 agents")

    none_keys, _, _ = flask_app._parse_start_agents_payload({}, "full")
    check(none_keys is None, "missing agents → default path")

    # init_session + apply slot keys + _make_session_agents
    sess = flask_app.init_session("testroom")
    flask_app._apply_slot_keys_to_session(sess, ["A", "B", "C", "D"])
    sess["agent_display_names"] = {k: f"Name{k}" for k in "ABCD"}
    sess["agent_runtime_config"] = {
        k: {"decision": "Rational", "emotion": "Joy"} for k in "ABCD"
    }
    sess["slot_to_profile"] = {k: k for k in "ABCD"}
    amap, alist, anames = flask_app._make_session_agents(sess)
    check(list(amap.keys()) == ["A", "B", "C", "D"], "session agents map 4")
    check(anames == ["NameA", "NameB", "NameC", "NameD"], "display names applied", anames)
    check(set(sess["has_spoken"]) == {"A", "B", "C", "D"}, "has_spoken dynamic")

    # default 3-slot session
    sess3 = flask_app.init_session("testroom3")
    check(flask_app._session_slot_keys(sess3) == ["A", "B", "C"], "default slot_keys ABC")

except Exception as e:
    check(False, "app.py roster helpers", str(e))

if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nALL CHECKS PASSED")
