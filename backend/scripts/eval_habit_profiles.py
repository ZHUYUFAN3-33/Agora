#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Usage-habit profile eval: eight scripted user personas, each modeled on
behavior actually observed in the production logs, each aimed at one specific
failure risk of the dialogue-quality layer.

    A interviewer     (P34)      six local questions, verdict only at the end
                                 -> risk: all-contract record has no agent
                                    disagreement, so the convergence gate could
                                    block the close forever
    B verdict_seeker  (--)       demands the answer from turn 1, repeatedly
                                 -> risk: premature convergence
    C passive         (316347)   one opener, then only low-content acks
                                 -> risk: low-content contract x move layer;
                                    wall-of-text; premature Concluded
    D info_dumper     (P41, zh)  long question-free constraint dumps, repeats
                                 -> risk: goal_switch misfires; zh handling
    E director        (P38, zh)  @-mentions agents with assignments
                                 -> risk: mention hard-route x contract; drops
    F topic_hopper    (handoff)  decision -> side question -> unrelated ->
                                 "back to the job decision"
                                 -> risk: does context survive a redirect
    G reopener        (--)       converges, accepts, then "what if it's fake?"
                                 -> risk: graceful reopen; sycophantic flip
    H zh_interviewer  (P34, zh)  Chinese version of A (short)
                                 -> risk: Admin-4 classification quality in zh

Each turn carries machine-checkable expectations (label, forbidden verdict
wording, allowed phases, mention-first, short-reply, option-recall); the
report prints per-profile PASS/WARN lines plus the usual metrics.

    python scripts/eval_habit_profiles.py --profiles A,B,C,H   # tier 1
    python scripts/eval_habit_profiles.py                      # all eight

Uses OPENAI_API_KEY from env or backend/.env. One room per profile.
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
sys.path.insert(0, str(HERE))

from eval_user_moves import (  # noqa: E402
    PROFILE, INTAKE, STANCES, build_context, load_dotenv_key,
)

# Verdict / ranking wording, union of both regexes used in earlier evals.
VERDICT_RE = re.compile(
    r"i would (pick|choose|back|support|still eliminate)|should be eliminated"
    r"|i would drop|remains? eliminated|my recommendation|final recommendation"
    r"|stronger overall case|leading (candidate|option)|survivor|survives"
    r"|排除|淘汰|首选|我会选|我推荐|最终建议",
    re.I)
OPTION_RE = re.compile(r"Kyoto|Singapore|Shibuya|京都|新加坡|涩谷|渋谷", re.I)

# Turn spec keys:
#   user            the message
#   expected        admin4 label, or None if genuinely ambiguous
#   no_verdict      True -> no agent message may match VERDICT_RE
#   phase_in        allowed phases AFTER the turn (subset check), optional
#   phase_not_in    forbidden phases AFTER the turn, optional
#   mention_first   agent key that must produce the first response, optional
#   short_replies   True -> every agent message <= 2 sentences (low-content)
#   must_recall     True -> at least one agent message names an option
PROFILES: dict = {
    "A": {"label": "interviewer (P34)", "lang": "en", "turns": [
        {"user": "What is the practical difference between a postdoc contract and a regular fixed-term research contract in Japan?",
         "expected": "local_question", "no_verdict": True},
        {"user": "How does PI-track conversion usually work at national labs — who decides, and when?",
         "expected": "local_question", "no_verdict": True},
        {"user": "What should I check in the contract and probation period before I decide?",
         "expected": "local_question", "no_verdict": True},
        {"user": "Is JPY 4.8M realistically enough to live on in Kyoto while keeping ties to a Tokyo household?",
         "expected": "local_question", "no_verdict": True},
        {"user": "How do industry hiring managers read a 3-year postdoc if I apply to companies afterwards?",
         "expected": "local_question", "no_verdict": True},
        {"user": "What questions should I ask each of the three employers before deciding?",
         "expected": "local_question", "no_verdict": True},
        {"user": "OK. Given everything above, which one would you pick?",
         "expected": "request_recommendation",
         "phase_not_in": ["Exploration"]},
        {"user": "And is that your final answer, all of you?",
         "expected": "request_recommendation",
         "phase_in": ["Convergence", "Concluded"]},
    ], "converge_by_end": True},

    "B": {"label": "verdict seeker", "lang": "en", "turns": [
        {"user": "Just tell me which of the three offers to take.",
         "expected": "request_recommendation",
         "phase_not_in": ["Convergence", "Concluded"]},
        {"user": "I do not need the full analysis — which one?",
         "expected": "request_recommendation"},
        {"user": "Fine. Salary actually matters more to me than I said in the form — does that change anything?",
         "expected": "new_criterion"},
        {"user": "OK, so now: final answer?",
         "expected": "request_recommendation",
         "phase_in": ["Convergence", "Concluded", "Narrowing"]},
    ], "converge_by_end": True},

    "C": {"label": "passive watcher (316347)", "lang": "en", "turns": [
        {"user": "I have three offers after my PhD — a Kyoto lab postdoc, a Singapore research job, and a Tokyo startup — and I keep going back and forth.",
         "expected": None},
        {"user": "ok", "expected": "progress", "short_replies": True},
        {"user": "makes sense", "expected": "progress", "short_replies": True},
        {"user": "go on", "expected": "progress", "short_replies": True},
        {"user": "mhm", "expected": "progress", "short_replies": True,
         "phase_not_in": ["Concluded"]},
    ], "converge_by_end": False},

    "D": {"label": "info dumper (P41, zh)", "lang": "zh", "turns": [
        {"user": "帮我看一下怎么选 我自己其实喜欢研究 所以倾向京都那个 但是三年合同工资只有480万 而且我伴侣在东京工作不想搬 新加坡那个钱多但是要搬去国外 这个跟伴侣的冲突更大 涩谷的钱居中还能留在东京 但是做的是UX管理不是研究 我担心做三年就回不去研究了 另外我毕业是明年三月 startup的offer两周就过期",
         "expected": None},
        {"user": "还有几个硬条件 通勤最好30分钟以内 不能常态加班 下班待命绝对不行 周末必须完全自由",
         "expected": "new_criterion", "no_verdict": False},
        {"user": "还有几个硬条件 通勤最好30分钟以内 不能常态加班 下班待命绝对不行 周末必须完全自由 我说完了",
         "expected": None},  # verbatim repeat + tail — must NOT classify goal_switch
        {"user": "别人的想法呢", "expected": None},
    ], "converge_by_end": False},

    "E": {"label": "director (P38, zh)", "lang": "zh", "turns": [
        {"user": "我在三个 offer 之间犹豫,想请你们从成长、稳定和生活平衡分别比较一下。",
         "expected": None},
        {"user": "@ChatbotB 你来专门拆一下京都那个三年合同到期之后的资金风险,@ChatbotC 你比较一下京都和东京的生活节奏差别。",
         "expected": None, "mention_first": "B"},
        {"user": "@ChatbotA 我觉得你对 PI-track 太乐观了,那种承诺经常兑现不了。",
         "expected": "challenge", "mention_first": "A", "no_verdict": True},
    ], "converge_by_end": False},

    "F": {"label": "topic hopper (handoff case)", "lang": "en", "turns": [
        {"user": "My core worry is whether leaving Tokyo for three years damages my relationship more than the career gain is worth.",
         "expected": None},
        {"user": "Side question — how should I prepare for a PI-track interview at a national lab?",
         "expected": "local_question", "no_verdict": True},
        {"user": "Different thing entirely — my sister asked me to give a wedding toast next month and I have no idea how to write one. Ideas?",
         "expected": "goal_switch", "phase_in": ["Exploration"]},
        {"user": "OK, back to the job decision — where did we land so far?",
         "expected": None, "must_recall": True},
    ], "converge_by_end": False},

    "G": {"label": "reopener", "lang": "en", "turns": [
        {"user": "I lean strongly toward the Kyoto postdoc; my partner supports trying it for a year. Poke holes if you see any.",
         "expected": None},
        {"user": "So — would you all back Kyoto, given that?",
         "expected": "request_recommendation"},
        {"user": "Agreed. Kyoto it is, assuming the written terms are fine.",
         "expected": None},
        {"user": "Actually hold on. What if the PI track turns out to be just a label with no funded position behind it — does that flip everything?",
         "expected": None, "must_recall": True},
    ], "converge_by_end": False},

    "H": {"label": "zh interviewer (P34)", "lang": "zh", "turns": [
        {"user": "日本国立研究所的博士后合同和普通的有期雇用合同,实际差别在哪里?",
         "expected": "local_question", "no_verdict": True},
        {"user": "签合同之前,试用期和合同条款里我该重点确认哪些东西?",
         "expected": "local_question", "no_verdict": True},
        {"user": "为什么你们都不担心三年合同到期之后没有下家?",
         "expected": "challenge", "no_verdict": True},
        {"user": "好,那综合来看你们会选哪个?",
         "expected": "request_recommendation"},
    ], "converge_by_end": True},
}


def run_profile(key: str, spec: dict, model: str, log_dir: Path) -> dict:
    import agentwake_new as aw
    from agent_assembly import build_all_agent_specs

    lang = spec["lang"]
    known_context, domain_background = build_context(lang)
    room_id = f"hab{key}{int(time.time()) % 100000}"
    log_dir.mkdir(parents=True, exist_ok=True)

    cfg = {k: {"decision": "Rational", "emotion": "Joy", "stance": s}
           for k, s in STANCES.items()}
    specs = build_all_agent_specs(cfg, scenario_type="employment", lang=lang)
    agents = {k: aw.ChatAgent(k, f"Chatbot{k}", specs[k]["role_text"]) for k in "ABC"}
    agent_list = [agents[k] for k in "ABC"]

    fps = {}
    for fkey, suffix in (("chat_fp", ""), ("think_fp", "_thinkinglog"),
                         ("moderator_fp", "_moderator"), ("rationale_fp", "_rationale"),
                         ("memory_fp", "_memory"), ("generation_fp", "_generation"),
                         ("novelty_fp", "_novelty"), ("retrieval_fp", "_retrieval")):
        fps[fkey] = open(log_dir / f"{room_id}{suffix}.jsonl", "a", encoding="utf-8")

    session = {
        "room_id": room_id, "history": [],
        "moderator_state": {"mode": None, "state": "Exploration", "stall": False, "goal": ""},
        "has_spoken": {k: False for k in "ABC"}, "mention_queue": [],
        "agent_runtime_config": cfg,
        "memory_snippets": {k: [] for k in "ABC"},
        "turns_since_distill": {k: 0 for k in "ABC"},
        "latest_rationale": {k: "" for k in "ABC"},
        "latest_snippet_id": {k: None for k in "ABC"},
        "snippet_counters": {k: 0 for k in "ABC"},
        **fps,
    }

    per_turn = []
    for i, step in enumerate(spec["turns"]):
        msg = {"chat_room_id": room_id, "time": aw.now_local_iso(),
               "character": "user", "txt": step["user"]}
        session["history"].append(msg)
        fps["chat_fp"].write(json.dumps(msg, ensure_ascii=False) + "\n"); fps["chat_fp"].flush()
        print(f"\n[{key}] turn {i+1}/{len(spec['turns'])}  U: {step['user'][:90]}")
        low = aw.is_low_content_message(step["user"])
        r = aw.run_user_turn(
            session=session, user_message=step["user"],
            agents=agents, agent_list=agent_list,
            all_agent_names=[a.name for a in agent_list],
            client_chat=None, client_admin=None,
            scene="Group decision chat: three advisors help the user decide between job offers.",
            known_context=known_context, domain_background=domain_background,
            intake_data=INTAKE, scenario_type="employment", lang=lang, model=model,
            # production-shaped: app.py injects the low-content contract
            turn_directive=(aw.LOW_CONTENT_TURN_DIRECTIVE if low else ""),
        )
        for resp in r.get("responses") or []:
            print(f"    {resp['agent']}: {resp['message'][:110].replace(chr(10), ' ')}…")
        per_turn.append({
            "i": i, "user": step["user"], "spec": {k: v for k, v in step.items() if k != "user"},
            "got_move": r.get("user_move"), "phase_after": r.get("phase"),
            "low_content": low,
            "responses": [{"agent_key": x["agent_key"], "message": x["message"]}
                          for x in r.get("responses") or []],
        })
    for fp in fps.values():
        fp.close()
    return {"profile": key, "label": spec["label"], "lang": lang,
            "room_id": room_id, "log_dir": str(log_dir),
            "converge_by_end": spec["converge_by_end"], "turns": per_turn}


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?。!?]+", text) if s.strip()])


def check_profile(res: dict) -> list:
    """Returns [(PASS|WARN, message), ...] for the machine-checkable expectations."""
    out = []
    label_hits = label_total = 0
    for t in res["turns"]:
        spec, n = t["spec"], t["i"] + 1
        msgs = [r["message"] for r in t["responses"]]
        if spec.get("expected"):
            label_total += 1
            ok = t["got_move"] == spec["expected"]
            label_hits += ok
            out.append(("PASS" if ok else "WARN",
                        f"turn{n} label {t['got_move']} (expected {spec['expected']})"))
        if spec.get("no_verdict"):
            bad = [m for m in msgs if VERDICT_RE.search(m)]
            out.append(("PASS" if not bad else "WARN",
                        f"turn{n} no-verdict ({len(bad)} of {len(msgs)} messages ranked)"))
        if spec.get("phase_in"):
            ok = t["phase_after"] in spec["phase_in"]
            out.append(("PASS" if ok else "WARN",
                        f"turn{n} phase {t['phase_after']} (allowed {spec['phase_in']})"))
        if spec.get("phase_not_in"):
            ok = t["phase_after"] not in spec["phase_not_in"]
            out.append(("PASS" if ok else "WARN",
                        f"turn{n} phase {t['phase_after']} (forbidden {spec['phase_not_in']})"))
        if spec.get("mention_first"):
            first = t["responses"][0]["agent_key"] if t["responses"] else None
            ok = first == spec["mention_first"]
            out.append(("PASS" if ok else "WARN",
                        f"turn{n} first speaker {first} (must be {spec['mention_first']})"))
        if spec.get("short_replies"):
            long_ = [m for m in msgs if _sentences(m) > 2]
            out.append(("PASS" if not long_ else "WARN",
                        f"turn{n} short-replies ({len(long_)} of {len(msgs)} over 2 sentences)"))
        if spec.get("must_recall"):
            ok = any(OPTION_RE.search(m) for m in msgs)
            out.append(("PASS" if ok else "WARN",
                        f"turn{n} recalls prior options: {ok}"))
    final_phase = res["turns"][-1]["phase_after"] if res["turns"] else "?"
    if res["converge_by_end"]:
        ok = final_phase in ("Convergence", "Concluded")
        out.append(("PASS" if ok else "WARN", f"converged by end (final phase {final_phase})"))
    else:
        ok = final_phase != "Concluded" or res["profile"] == "G"
        out.append(("PASS" if ok else "WARN", f"did not force-close (final phase {final_phase})"))
    if label_total:
        out.append(("INFO", f"label accuracy {label_hits}/{label_total}"))
    # drops from the room log
    drops = 0
    for line in open(Path(res["log_dir"]) / f"{res['room_id']}_rationale.jsonl", encoding="utf-8"):
        if json.loads(line).get("event") == "turn_dropped":
            drops += 1
    out.append(("PASS" if drops == 0 else "WARN", f"dropped turns: {drops}"))
    return out


def main():
    ap = argparse.ArgumentParser(description="usage-habit profile eval")
    ap.add_argument("--profiles", default="ABCDEFGH",
                    help="which profiles to run, e.g. ABCH or A,B,C,H")
    ap.add_argument("--model", default=os.getenv("AGORA_MODEL") or "gpt-5.6-terra")
    ap.add_argument("--log_dir", default=str(BACKEND / "logs_eval"))
    args = ap.parse_args()

    load_dotenv_key()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set (env or backend/.env)")
    os.chdir(BACKEND)

    keys = [k for k in re.sub(r"[^A-H]", "", args.profiles.upper())]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = []
    for k in keys:
        results.append(run_profile(k, PROFILES[k], args.model,
                                   Path(args.log_dir) / f"{stamp}-habit-{k}"))

    print("\n" + "=" * 72)
    warn_total = 0
    for res in results:
        checks = check_profile(res)
        warns = sum(1 for s, _ in checks if s == "WARN")
        warn_total += warns
        print(f"\n### {res['profile']} — {res['label']}   room {res['room_id']}   "
              f"{'ALL PASS' if warns == 0 else f'{warns} WARN'}")
        for status, msg in checks:
            print(f"  [{status}] {msg}")
        res["checks"] = [{"status": s, "msg": m} for s, m in checks]

    out = Path(args.log_dir) / f"{stamp}-habit-summary.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n{'ALL PROFILES CLEAN' if warn_total == 0 else f'{warn_total} WARN total'}"
          f" — full summary: {out}")


if __name__ == "__main__":
    main()
