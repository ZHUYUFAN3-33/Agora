# -*- coding: utf-8 -*-
"""Pool sizes beyond the scenario's stance set, and the guard that keeps the
extra agents from being clones.

A scenario defines a fixed set of three stances; the pool size comes from
info.jsonl. `assignment` is an ordered list indexed by the agent's position in
the sorted pool (order[i % len(order)]), so a 5-agent pool REUSES stances by
design: D gets A's stance, E gets B's. That is intended. What must not happen is
two agents sharing stance AND decision AND emotion — then every block shaping
their behaviour is identical and they can only say the same thing twice.

  1. A/B/C keep their historical stances at any pool size (nothing regressed).
  2. A 5-agent pool wraps onto the same three stances (D=A's, E=B's).
  3. Duplicated stance + duplicated decision/emotion is a hard startup error.
  4. Duplicated stance with a DIFFERENT decision/emotion starts fine, and the
     five agents' prompts are genuinely different.
  5. No stance at all (legacy, no --scenario_type) stays a warning, not an error.
"""
import builtins, io, json, os, shutil, subprocess, sys

from _harness import bootstrap, Checker

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
aw = bootstrap("agentwake_poolscale_")
for _d in ("background_templates", "scenes", "decision", "emotion", "stance_templates"):
    shutil.copytree(os.path.join(BACKEND, _d), _d)

_ck = Checker(); check = _ck.check

from stance import assign_stance, list_stances

HISTORICAL = {
    "parent_child": ["child_centered", "parent_centered", "relationship_centered"],
    "employment":   ["growth_centered", "stability_centered", "life_centered"],
}

# ---- 1 & 2: assignment semantics ------------------------------------------
for scenario, historical in HISTORICAL.items():
    check(f"{scenario}: exactly three stances", list_stances(scenario) == historical,
          str(list_stances(scenario)))
    stable = all(
        [assign_stance(scenario, k, [chr(65 + i) for i in range(n)]) for k in "ABC"] == historical
        for n in (3, 4, 5, 6)
    )
    check(f"{scenario}: A/B/C keep their historical stances at every pool size", stable)
    five = [assign_stance(scenario, k, list("ABCDE")) for k in "ABCDE"]
    check(f"{scenario}: a 5-agent pool wraps onto the same three stances",
          five == historical + historical[:2], str(five))


# ---- helper: run main() in a subprocess so sys.exit(2) is observable -------
def _run_startup(agents, scenario_type):
    """Start a session with this agent config; return (exit_code, stderr)."""
    info = "info_case.jsonl"
    with open(info, "w", encoding="utf-8") as f:
        json.dump({"agents": agents}, f, ensure_ascii=False)
    code = (
        "import builtins,sys,json\n"
        "sys.path.insert(0, r'%s')\n"
        "import agentwake_new as aw\n"
        "def fake(model,messages,temperature,max_output_tokens,meta=None):\n"
        "    if meta is not None: meta['status']='completed'\n"
        "    s=messages[0]['content'] if messages[0]['role']=='system' else ''\n"
        "    if s.startswith('You are Admin-2'): return 'A'\n"
        "    if s.startswith('You are Admin-1'): return 'NEXT = A'\n"
        "    if 'deliberation moderator' in s:\n"
        "        return '[Moderator]\\nmode: S\\nstate: Structuring\\nstall: false\\ngoal: g\\n[/Moderator]'\n"
        "    if messages[0]['role']=='user' and 'Distill' in messages[-1]['content']: return 'stub.'\n"
        "    return '[MESSAGE]\\nx\\n[/MESSAGE]\\n[RATIONALE]\\nr\\n[/RATIONALE]'\n"
        "aw.create_response=fake\n"
        "it=iter(['/exit'])\n"
        "builtins.input=lambda p='': next(it)\n"
        "sys.argv=%r\n"
        "aw.main()\n"
    ) % (BACKEND, ["x", "--info", info, "--assemble_roles", "--lang", "zh",
                   "--prefer_agents", "0", "--novelty_threshold", "0",
                   "--log_dir", "lg"]
         + (["--scenario_type", scenario_type, "--skip_intake"] if scenario_type else []))
    env = dict(os.environ, OPENAI_API_KEY="sk-test-dummy", PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, "-c", code], cwd=os.getcwd(), env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stderr or "")


# ---- 3: clones are rejected ------------------------------------------------
clones = {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABCDE"}   # D==A, E==B
rc, err = _run_startup(clones, "parent_child")
check("5 identical personas + stances -> startup error", rc == 2, f"rc={rc}")
check("the error names the colliding agents and what to change",
      "indistinguishable" in err and "info.jsonl" in err, err[-300:])

# ---- 4: differentiated duplicates are accepted -----------------------------
distinct = {
    "A": {"decision": "Rational",    "emotion": "Joy"},
    "B": {"decision": "Avoidant",    "emotion": "Fear"},
    "C": {"decision": "Intuitive",   "emotion": "Surprise"},
    "D": {"decision": "Dependent",   "emotion": "Sadness"},   # A's stance, other persona
    "E": {"decision": "Spontaneous", "emotion": "Anger"},     # B's stance, other persona
}
rc, err = _run_startup(distinct, "parent_child")
check("5 agents sharing stances but differing in decision/emotion -> starts fine",
      rc == 0, f"rc={rc} err={err[-300:]}")

# ---- 5: no stance at all stays a warning -----------------------------------
rc, err = _run_startup({k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}, None)
check("legacy run with no stance: duplicates warn but do not block",
      rc == 0 and "WARNING" in err, f"rc={rc} err={err[-200:]}")

# ---- 4b: those five prompts really are different ---------------------------
captured = {}
def _fake(model, messages, temperature, max_output_tokens, meta=None):
    if meta is not None:
        meta["status"] = "completed"
    sysc = messages[0]["content"] if messages[0]["role"] == "system" else ""
    if sysc.startswith("You are Admin-2"):
        return "A"
    if sysc.startswith("You are Admin-1"):
        return "NEXT = A"
    if "deliberation moderator" in sysc:
        return "[Moderator]\nmode: S\nstate: Structuring\nstall: false\ngoal: g\n[/Moderator]"
    if messages[0]["role"] == "user" and "Distill" in messages[-1]["content"]:
        return "stub."
    for k in "ABCDE":
        if sysc.startswith(f"You are Chatbot{k}"):
            captured.setdefault(k, sysc)
    return "[MESSAGE]\n我不同意\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
aw.create_response = _fake

with open("info5d.jsonl", "w", encoding="utf-8") as f:
    json.dump({"agents": distinct}, f, ensure_ascii=False)
_inputs = iter(["孩子最近很不听话", "/exit"])
builtins.input = lambda prompt="": next(_inputs)
sys.argv = ["x", "--scenario_type", "parent_child", "--skip_intake", "--lang", "zh",
            "--assemble_roles", "--info", "info5d.jsonl", "--start_order", "ABCDEU",
            "--prefer_agents", "0", "--novelty_threshold", "0", "--log_dir", "lg2"]
_c = io.StringIO(); _r = sys.stdout; sys.stdout = _c
try:
    aw.main()
finally:
    sys.stdout = _r

check("5-agent run: every agent got a prompt", len(captured) == 5, str(sorted(captured)))
check("5-agent roster labels every agent",
      all(f"- {k}: Chatbot{k} — represents " in captured["A"] for k in "ABCDE"),
      captured.get("A", "")[:400])
check("5-agent roster no longer claims a fixed count",
      not any(s in captured["A"] for s in ("三位", "A / B / C", "three AI")))
check("the five system prompts are all distinct",
      len({captured[k] for k in "ABCDE"}) == 5)
check("A and D share a stance but not a prompt",
      captured["A"] != captured["D"])

_ck.finish("STANCE POOL SCALING CHECKS PASSED")
