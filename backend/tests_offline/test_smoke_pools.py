# -*- coding: utf-8 -*-
"""Smoke: 5-agent pool runs with no code change; legacy A/B/C bot1/2/3 path intact."""
import builtins, io, json, os, sys

from _harness import bootstrap

# Dummy key + sys.path + throwaway temp dir; see tests_offline/_harness.py.
aw = bootstrap("agentwake_smoke_")

def fake_create_response(model, messages, temperature, max_output_tokens, meta=None):
    if meta is not None:
        meta["status"] = "completed"
    sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
    user_c = messages[-1]["content"]
    if sys_c.startswith("You are Admin-2"):
        return "U"
    if sys_c.startswith("You are Admin-1"):
        return "analysis. NEXT = U"
    if "deliberation moderator" in sys_c:
        return "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n[/Moderator]"
    if messages[0]["role"] == "user" and "Distill" in user_c:
        return "stub stance."
    return "[MESSAGE]\nhello from stub\n[/MESSAGE]\n[RATIONALE]\nstub why\n[/RATIONALE]"

aw.create_response = fake_create_response
failures = []

# --- 5-key pool: roles dir with all files, default start_order ABCU ---
keys5 = ["A", "B", "C", "D", "E"]
os.makedirs("roles5", exist_ok=True)
for k in keys5:
    with open(os.path.join("roles5", f"{k}.txt"), "w", encoding="utf-8") as f:
        f.write(f"Role text {k}.")
with open("info5.jsonl", "w", encoding="utf-8") as f:
    json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in keys5}}, f)

inputs = iter(["@D @E your turn", "/exit"])
builtins.input = lambda prompt="": next(inputs)
sys.argv = ["x", "--info", "info5.jsonl", "--roles-dir", "roles5",
            "--start_order", "ABCDEU", "--prefer_agents", "0",
            "--novelty_threshold", "0", "--log_dir", "dry_logs5"]
cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
try:
    aw.main()
finally:
    sys.stdout = real
out = cap.getvalue()
room = [l for l in out.splitlines() if l.startswith("Chat room id:")][0].split()[-1]
chat = [json.loads(l) for l in open(f"dry_logs5/{room}.jsonl", encoding="utf-8")]
rat = [json.loads(l) for l in open(f"dry_logs5/{room}_rationale.jsonl", encoding="utf-8")]
speakers = {r["character"] for r in chat}
dispatches = [r["agent"] for r in rat if r["event"] == "mention_dispatch"]
ok = speakers == {f"Chatbot{k}" for k in keys5} | {"user"}
print(f"[{'PASS' if ok else 'FAIL'}] 5-key pool: all five agents spoke, no code change  {speakers}")
if not ok: failures.append("5key speakers")
ok = dispatches[:2] == ["D", "E"]
print(f"[{'PASS' if ok else 'FAIL'}] 5-key pool: '@D @E' hard-routes D then E  {dispatches}")
if not ok: failures.append("5key dispatch")
ok = "E=Joy+Rational" in out
print(f"[{'PASS' if ok else 'FAIL'}] 5-key pool: startup summary prints all keys")
if not ok: failures.append("5key summary")

# --- legacy A/B/C: no --roles-dir, missing chatbot files -> placeholders, still runs ---
with open("info3.jsonl", "w", encoding="utf-8") as f:
    json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)
inputs = iter(["/exit"])
builtins.input = lambda prompt="": next(inputs)
sys.argv = ["x", "--info", "info3.jsonl", "--prefer_agents", "0",
            "--novelty_threshold", "0", "--log_dir", "dry_logs3"]
cap = io.StringIO(); sys.stdout = cap
try:
    aw.main()
finally:
    sys.stdout = real
out = cap.getvalue()
ok = "Chat room id:" in out and "ChatbotC>" in out
print(f"[{'PASS' if ok else 'FAIL'}] legacy A/B/C bot1/2/3 path still starts and runs")
if not ok: failures.append("legacy")

if failures:
    print("FAILURES:", failures); sys.exit(1)
print("SMOKE OK")
