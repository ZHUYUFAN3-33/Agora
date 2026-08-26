#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live-API eval for the user-move layer (Admin-4).

Drives run_user_turn() directly (no Flask needed) with the DEMO01 employment
scenario from DUMMY_SESSIONS.md and a fixed script of user turns, each with the
move label a careful human would assign. Run it twice — once per arm — and
compare:

    python scripts/eval_user_moves.py --arm off   # AGORA_USER_MOVE_LAYER=0
    python scripts/eval_user_moves.py --arm on    # AGORA_USER_MOVE_LAYER=1

What it reports, per arm, from the room's own logs:
  - Admin-4 label per user turn vs the expected label (accuracy; on-arm only)
  - ranking-frame rate: share of agent messages carrying ranking/elimination
    wording ("leading candidate", "remains eliminated", ...), split into
    contract turns vs phase turns. The hypothesis: contract turns drop to ~0
    while phase turns stay high (the phase machinery is untouched).
  - [MOVE] distribution (does `clarify` finally appear on contract turns?)
  - dropped turns (novelty/refusal) — the guard must not eat the burst when
    three agents answer the same bounded question
  - phase timeline (redirect visible for the goal_switch turn on the on-arm)

Costs one real session per arm (~6 user turns × up to 3 agent turns each, plus
admin calls). Uses OPENAI_API_KEY from the environment or backend/.env.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

# ---------------------------------------------------------------------------
# The scripted session. Expected labels are what a careful human would assign;
# turns marked expected=None are genuinely ambiguous and excluded from the
# accuracy count (but still run, because agents must behave sensibly on them).
# Turn 3 is the exact live failure this layer exists for: room 434276's
# contract question, which got answered wrapped in a fresh round of rankings.
# ---------------------------------------------------------------------------
SCRIPT = [
    {"user": "Five years from now, will I regret whichever one I turn down?",
     "expected": None, "note": "opener; ambiguous between progress/local/request"},
    {"user": "What should I check in the contract and probation period before I decide?",
     "expected": "local_question", "note": "the room-434276 failure case"},
    {"user": "@ChatbotB I think you are overweighting the contract end date — a fixed term is also a clean exit point.",
     "expected": "challenge", "note": "user pushes back on stability agent"},
    {"user": "One thing I did not mention: my partner may get a Kyoto offer of their own next year.",
     "expected": "new_criterion", "note": "new fact that reweighs the comparison"},
    {"user": "So which one would you pick, all things considered?",
     "expected": "request_recommendation", "note": "phase machinery should run"},
    {"user": "Set the job choice aside for now — my visa renewal just got complicated, what should I sort out first?",
     "expected": "goal_switch", "note": "paper's Redirecting case"},
]

# Same frame as the log analysis that motivated the layer (54% of agent
# messages across 15 rooms matched this).
RANK_RE = re.compile(
    r"stronger overall case|leading (candidate|option)|eliminat|should be dropped"
    r"|rule out|remains? (eliminated|dropped)|survivor|survives|排除|淘汰|首选"
    r"|最该先排除|不建议|leading candidate|drop (it|one|the)",
    re.I)

PROFILE = {
    "age": 31,
    "education": "PhD candidate (D3) in Human-Computer Interaction; MA in Industrial Design",
    "industry_experience": "4 years as a product designer in consumer electronics, then 3 years back in academia",
    "career_stage": "job_change",
    "family_situation": "Partner works as a designer in Tokyo and does not want to relocate. No children.",
    "long_term_goal": "To keep doing research I choose myself, and to still be doing it in ten years",
    "risk_tolerance": "medium",
}
INTAKE = {
    "decision_field": "Where to go after finishing the PhD next March — research track or industry",
    "options": [
        "Kyoto national lab postdoc — 3-year contract, JPY 4.8M, PI track",
        "US tech firm research scientist — JPY 9.5M, relocate to Singapore",
        "Shibuya startup UX lead — JPY 7.2M plus equity, stay in Tokyo",
    ],
    "deadline": "The lab needs an answer by mid-March; the startup offer expires in two weeks",
    "current_status": "pending_grad",
    "priority_ranking": ["Research autonomy", "My partner's career", "Long-term stability", "Salary"],
    "comparison_anchor": "I lean toward the postdoc, but I am not confident it is the right call",
}
STANCES = {"A": "growth_centered", "B": "stability_centered", "C": "life_centered"}


def load_dotenv_key() -> None:
    if os.getenv("OPENAI_API_KEY"):
        return
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENAI_API_KEY=") :
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
                return


def build_context(lang: str):
    from profile_store import load_scenario_template, format_known_context
    from scenario_background import load_background_template, get_scenario_background
    template = load_scenario_template("employment", str(BACKEND / "scenario_templates"))
    known = format_known_context("employment", PROFILE, INTAKE, template, lang)
    bg_cfg = load_background_template("employment", str(BACKEND / "background_templates"))
    background = get_scenario_background("employment", {**PROFILE, **INTAKE}, bg_cfg, lang)
    return known, background


def run_arm(arm: str, model: str, log_dir: Path, lang: str) -> dict:
    os.environ["AGORA_USER_MOVE_LAYER"] = "1" if arm == "on" else "0"
    os.chdir(BACKEND)  # module-relative data dirs (KB, presets) expect this
    import agentwake_new as aw
    from agent_assembly import build_all_agent_specs

    known_context, domain_background = build_context(lang)
    room_id = f"eval{arm}{int(time.time()) % 100000}"
    log_dir.mkdir(parents=True, exist_ok=True)

    cfg = {k: {"decision": "Rational", "emotion": "Joy", "stance": s}
           for k, s in STANCES.items()}
    specs = build_all_agent_specs(cfg, scenario_type="employment", lang=lang)
    agents = {k: aw.ChatAgent(k, f"Chatbot{k}", specs[k]["role_text"]) for k in "ABC"}
    agent_list = [agents[k] for k in "ABC"]

    fps = {}
    for key, suffix in (("chat_fp", ""), ("think_fp", "_thinkinglog"),
                        ("moderator_fp", "_moderator"), ("rationale_fp", "_rationale"),
                        ("memory_fp", "_memory"), ("generation_fp", "_generation"),
                        ("novelty_fp", "_novelty"), ("retrieval_fp", "_retrieval")):
        fps[key] = open(log_dir / f"{room_id}{suffix}.jsonl", "a", encoding="utf-8")

    session = {
        "room_id": room_id,
        "history": [],
        "moderator_state": {"mode": None, "state": "Exploration", "stall": False, "goal": ""},
        "has_spoken": {k: False for k in "ABC"},
        "mention_queue": [],
        "agent_runtime_config": cfg,
        "memory_snippets": {k: [] for k in "ABC"},
        "turns_since_distill": {k: 0 for k in "ABC"},
        "latest_rationale": {k: "" for k in "ABC"},
        "latest_snippet_id": {k: None for k in "ABC"},
        "snippet_counters": {k: 0 for k in "ABC"},
        **fps,
    }

    per_turn = []
    for i, step in enumerate(SCRIPT):
        msg = {"chat_room_id": room_id, "time": aw.now_local_iso(),
               "character": "user", "txt": step["user"]}
        session["history"].append(msg)
        fps["chat_fp"].write(json.dumps(msg, ensure_ascii=False) + "\n"); fps["chat_fp"].flush()
        print(f"\n=== user turn {i+1}/{len(SCRIPT)} [{step['note']}] ===\n  U: {step['user']}")
        t0 = time.time()
        r = aw.run_user_turn(
            session=session,
            user_message=step["user"],
            agents=agents,
            agent_list=agent_list,
            all_agent_names=[a.name for a in agent_list],
            client_chat=None,           # falls through to create_response (real API)
            client_admin=None,
            scene="Group decision chat: three advisors help the user decide between job offers.",
            known_context=known_context,
            domain_background=domain_background,
            intake_data=INTAKE,
            scenario_type="employment",
            lang=lang,
            model=model,
        )
        for resp in r.get("responses") or []:
            print(f"  {resp['agent']}: {resp['message'][:160].replace(chr(10), ' ')}…")
        per_turn.append({
            "i": i, "user": step["user"], "expected": step["expected"],
            "got_move": r.get("user_move"), "phase_after": r.get("phase"),
            "n_agents": len(r.get("responses") or []),
            "agent_msgs": [resp["message"] for resp in r.get("responses") or []],
            "latency_s": round(time.time() - t0, 1),
        })
    for fp in fps.values():
        fp.close()
    return {"arm": arm, "room_id": room_id, "turns": per_turn, "log_dir": str(log_dir)}


def report(result: dict) -> None:
    arm, turns = result["arm"], result["turns"]
    print(f"\n{'=' * 70}\nARM: {arm}   room {result['room_id']}   logs: {result['log_dir']}")
    contract_moves = {"local_question", "challenge", "new_criterion", "goal_switch"}
    scored = [t for t in turns if t["expected"]]
    if arm == "on":
        hits = sum(1 for t in scored if t["got_move"] == t["expected"])
        print(f"Admin-4 accuracy on unambiguous turns: {hits}/{len(scored)}")
        for t in scored:
            mark = "ok " if t["got_move"] == t["expected"] else "MISS"
            print(f"  [{mark}] turn {t['i']+1}: expected {t['expected']:<24} got {t['got_move']}")
    rank_contract = rank_phase = n_contract = n_phase = 0
    for t in turns:
        # On the off-arm nothing is a contract turn; bucket by the EXPECTED
        # label so the same turns are compared across arms.
        is_contract = (t["expected"] in contract_moves)
        for m in t["agent_msgs"]:
            if is_contract:
                n_contract += 1
                rank_contract += bool(RANK_RE.search(m))
            else:
                n_phase += 1
                rank_phase += bool(RANK_RE.search(m))
    print(f"ranking-frame rate on would-be contract turns: {rank_contract}/{n_contract}")
    print(f"ranking-frame rate on phase turns:            {rank_phase}/{n_phase}")
    # moves + drops from the logs
    logdir, room = Path(result["log_dir"]), result["room_id"]
    moves, drops = {}, 0
    for line in open(logdir / f"{room}_rationale.jsonl", encoding="utf-8"):
        o = json.loads(line)
        if o.get("event") == "move":
            k = (o.get("detail") or "").split()[0] or "?"
            moves[k] = moves.get(k, 0) + 1
        if o.get("event") == "turn_dropped":
            drops += 1
    print(f"[MOVE] distribution: {moves}   dropped turns: {drops}")
    states = [json.loads(l) for l in open(logdir / f"{room}_moderator.jsonl", encoding="utf-8")]
    timeline = [f"{s['character']}:{s['txt'][:40]}" for s in states
                if s["character"] in ("admin3_state_change", "admin3_redirected", "admin4_usermove")]
    print("moderator timeline:")
    for t in timeline:
        print(f"  {t}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", choices=["on", "off", "both"], default="both")
    ap.add_argument("--model", default=os.getenv("AGORA_MODEL") or "gpt-5.6-terra")
    ap.add_argument("--lang", default="en", choices=["en", "zh"])
    ap.add_argument("--log_dir", default=str(BACKEND / "logs_eval"))
    args = ap.parse_args()

    load_dotenv_key()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set (env or backend/.env)")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = []
    for arm in (["on", "off"] if args.arm == "both" else [args.arm]):
        results.append(run_arm(arm, args.model, Path(args.log_dir) / f"{stamp}-{arm}", args.lang))
    for r in results:
        report(r)
    out = Path(args.log_dir) / f"{stamp}-summary.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nfull summary written to {out}")


if __name__ == "__main__":
    main()
