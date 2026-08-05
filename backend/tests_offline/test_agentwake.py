# -*- coding: utf-8 -*-
"""Offline verification for the six agentwake_new.py changes: unit tests for the
pure functions, startup-error paths, and a full stubbed dry run (no API calls)."""
import builtins
import io
import json
import os
import sys
from contextlib import redirect_stderr

from _harness import bootstrap, Checker

# Sets the dummy key, puts agora_backend on sys.path, and chdir's into a fresh
# temp dir so repeated runs never pollute the repo. See tests_offline/_harness.py.
aw = bootstrap("agentwake_test_")

_ck = Checker()
check = _ck.check  # keep the familiar check(name, cond, detail) call site

# ---------------------------------------------------------------- unit tests
# 1. parse_agent_turn
p = aw.parse_agent_turn("[MESSAGE]\nhello there\n[/MESSAGE]\n[RATIONALE]\nbecause reasons\n[/RATIONALE]")
# "options" is a product-side extension (option chips); empty list when the
# generation carries no [OPTIONS] block.
check("parse: tagged", p == {"message": "hello there", "rationale": "because reasons", "options": []}, repr(p))

p = aw.parse_agent_turn("no tags at all, just text")
check("parse: untagged fallback", p["message"] == "no tags at all, just text" and p["rationale"] == "", repr(p))

p = aw.parse_agent_turn("[MESSAGE]\nonly message half open")  # broken output
check("parse: broken tags no crash, no tag leak",
      "[MESSAGE]" not in p["message"] and p["message"] == "only message half open", repr(p))

long_rat = " ".join(f"w{i}" for i in range(40))
p = aw.parse_agent_turn(f"[MESSAGE]m[/MESSAGE][RATIONALE]{long_rat}[/RATIONALE]")
check("parse: rationale capped at 30 words + ellipsis",
      len(p["rationale"].split()) == 30 and p["rationale"].endswith("...")
      and "w30" not in p["rationale"], repr(p["rationale"]))

p = aw.parse_agent_turn("")
check("parse: empty input no crash", p == {"message": "", "rationale": "", "options": []}, repr(p))

# 2. mention helpers
keys5 = ["A", "B", "C", "D", "E"]
nm5 = {k: f"Chatbot{k}" for k in keys5}
pats = aw.build_mention_patterns(keys5, nm5)
check("mentions: basic order", aw.parse_mentions("@A @B what do you two think?", pats) == ["A", "B"])
check("mentions: unknown ignored", aw.parse_mentions("@Z hello @B", pats) == ["B"])
check("mentions: name + case insensitive", aw.parse_mentions("@chatbota and @b", pats) == ["A", "B"])
check("mentions: dedupe", aw.parse_mentions("@A @A @ChatbotA @B", pats) == ["A", "B"])
check("mentions: cap at 4", aw.parse_mentions("@A @B @C @D @E", pats) == ["A", "B", "C", "D"])
check("mentions: empty text", aw.parse_mentions("", pats) == [])

# 3. build_admin_prompts
a1, a2 = aw.build_admin_prompts(["A", "B"], 4)
check("admin prompts: 2-key content",
      "A or B or U" in a1 and "after 4 consecutive" in a1 and "A or B or U" in a2, a1)
check("admin prompts: no stale A/B/C wording", "A or B or C" not in a1 and "A or B or C" not in a2)
a1, _ = aw.build_admin_prompts(keys5, 7)
check("admin prompts: 5-key content", "A or B or C or D or E or U" in a1 and "after 7 consecutive" in a1)

# ------------------------------------------------------- startup error paths
def run_main_expect_exit(argv, want_in_stderr):
    sys.argv = ["agentwake_new.py"] + argv
    err = io.StringIO()
    code = None
    try:
        with redirect_stderr(err):
            aw.main()
    except SystemExit as e:
        code = e.code
    return code, err.getvalue(), want_in_stderr in err.getvalue()

with open("info5.jsonl", "w", encoding="utf-8") as f:
    json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in keys5}}, f)
with open("info2.jsonl", "w", encoding="utf-8") as f:
    json.dump({"agents": {"A": {"decision": "Rational", "emotion": "Joy"},
                          "B": {"decision": "Avoidant", "emotion": "Fear"}}}, f)

code, err, ok = run_main_expect_exit(["--info", "info5.jsonl"], "--roles-dir")
check("startup: 5 keys w/o roles dir -> clean error naming --roles-dir", code == 2 and ok, err)

os.makedirs("roles_partial", exist_ok=True)
open(os.path.join("roles_partial", "A.txt"), "w", encoding="utf-8").write("role A")
code, err, ok = run_main_expect_exit(
    ["--info", "info5.jsonl", "--roles-dir", "roles_partial"], "do not exist")
check("startup: explicit roles-dir with missing files -> lists them",
      code == 2 and ok and "B.txt" in err, err)

# ---------------------------------------------------------------- dry run
os.makedirs("roles2", exist_ok=True)
open(os.path.join("roles2", "A.txt"), "w", encoding="utf-8").write("Role text for A.")
open(os.path.join("roles2", "B.txt"), "w", encoding="utf-8").write("Role text for B.")

STATES = ["Structuring", "Narrowing", "Convergence", "Convergence", "Convergence"]
mod_calls = {"n": 0}

def fake_create_response(model, messages, temperature, max_output_tokens, meta=None):
    if meta is not None:
        meta["status"] = "completed"
    sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
    user_c = messages[-1]["content"]
    if sys_c.startswith("You are Admin-2"):
        return "U"
    if sys_c.startswith("You are Admin-1"):
        return "analysis text. NEXT = U"
    if "deliberation moderator" in sys_c:
        state = STATES[min(mod_calls["n"], len(STATES) - 1)]
        mod_calls["n"] += 1
        return f"[Moderator]\nmode: S\nstate: {state}\nstall: false\ngoal: stub goal\n[/Moderator]"
    if messages[0]["role"] == "user" and "Distill the agent's CURRENT position" in user_c:
        return "Stub distilled stance."
    # agent turn — includes a soft @ToOtherBot cue
    return ("[MESSAGE]\n@U here is my view. @ChatbotB do you see a risk?\n[/MESSAGE]\n"
            "[RATIONALE]\nMy persona pushes for a quick concrete option in this phase.\n[/RATIONALE]")

aw.create_response = fake_create_response

INPUTS = iter([
    "@A @B what do you two think?",
    "@B follow up",
    "@A @B more thoughts",
    "@Z @B one",
    "@B two",
    "/exit",
])
builtins.input = lambda prompt="": next(INPUTS)

sys.argv = ["agentwake_new.py", "--info", "info2.jsonl", "--roles-dir", "roles2",
            "--start_order", "AB", "--prefer_agents", "0", "--novelty_threshold", "0",
            "--log_dir", "dry_logs"]
stdout_cap = io.StringIO()
_real_stdout = sys.stdout
class Tee:
    def write(self, s):
        stdout_cap.write(s)
        _real_stdout.write(s)
    def flush(self):
        _real_stdout.flush()
sys.stdout = Tee()
try:
    aw.main()
finally:
    sys.stdout = _real_stdout

# locate the logs of this run
room = [ln for ln in stdout_cap.getvalue().splitlines() if ln.startswith("Chat room id:")][0].split()[-1]

def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]

chat = load(os.path.join("dry_logs", f"{room}.jsonl"))
rationale = load(os.path.join("dry_logs", f"{room}_rationale.jsonl"))
memory = load(os.path.join("dry_logs", f"{room}_memory.jsonl"))
thinking = load(os.path.join("dry_logs", f"{room}_thinking.jsonl"))

check("dry: no tag leak into chat log",
      all("[MESSAGE]" not in r["txt"] and "[RATIONALE]" not in r["txt"] for r in chat))
check("dry: only configured agents + user ever speak",
      {r["character"] for r in chat} <= {"ChatbotA", "ChatbotB", "user"},
      str({r["character"] for r in chat}))
events = {r["event"] for r in rationale}
check("dry: rationale log has all event types",
      {"rationale", "agent_mention", "mention_override", "mention_dispatch"} <= events, str(events))
check("dry: thinking log untouched by new events",
      all(set(r) == {"chat_room_id", "time", "character", "txt"} for r in thinking))

# hard-route order: first user mention turn must dispatch A then B, back to back
dispatches = [r["agent"] for r in rationale if r["event"] == "mention_dispatch"]
check("dry: '@A @B' dispatches A then B in order", dispatches[:2] == ["A", "B"], str(dispatches))
check("dry: '@Z @B' ignored unknown, dispatched only B",
      "Z" not in dispatches and dispatches.count("B") >= 3, str(dispatches))

# memory chain: per-agent linear parent links
by_agent = {}
for s in memory:
    by_agent.setdefault(s["agent_key"], []).append(s)
chain_ok = True
for k, snips in by_agent.items():
    if snips[0]["parent_id"] is not None:
        chain_ok = False
    for prev, cur in zip(snips, snips[1:]):
        if cur["parent_id"] != prev["id"]:
            chain_ok = False
check("dry: memory chains link parent_id -> previous id", chain_ok and len(memory) > 0,
      json.dumps(by_agent, ensure_ascii=False))
check("dry: some agent has a chain of >= 2 snippets",
      any(len(s) >= 2 for s in by_agent.values()),
      str({k: len(v) for k, v in by_agent.items()}))
check("dry: snippet triggers are the deterministic three",
      all(s["trigger"] in {"phase_change", "stall", "periodic"} for s in memory),
      str([s["trigger"] for s in memory]))
check("dry: not every agent turn produced a snippet",
      len(memory) < sum(1 for r in chat if r["character"].startswith("Chatbot")),
      f"{len(memory)} snippets vs agent msgs")

_ck.finish("ALL CHECKS PASSED")
