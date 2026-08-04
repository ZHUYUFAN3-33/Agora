# -*- coding: utf-8 -*-
"""
Offline verification for the five pacing/quality fixes derived from logs/316347:
  1. phase progression tracks USER turns, not agent chatter
  2. Convergence has a terminal state and stops proactive agent turns
  3. stall_burst is exempt from the consecutive-turn valve and really emits
  4. novelty failures are dropped, not published
  5. generation metadata (refusal / truncation) reaches the log
All LLM calls are stubbed — no API key, no network.
"""
import builtins, io, json, os, sys, tempfile

from _harness import bootstrap, Checker

# Dummy key + sys.path + throwaway temp dir; see tests_offline/_harness.py.
aw = bootstrap("agentwake_pacing_")

_ck = Checker()
check = _ck.check  # keep the familiar check(name, cond, detail) call site

os.makedirs("roles", exist_ok=True)
for k in "ABC":
    with open(f"roles/{k}.txt", "w", encoding="utf-8") as f:
        f.write(f"Role {k}.")
with open("info3.jsonl", "w", encoding="utf-8") as f:
    json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)


def run_session(inputs, agent_reply, moderator_states, argv_extra=(), meta_for_agent=None):
    """Drive one full session with stubbed LLM. agent_reply may be a callable
    (nth_call -> raw string) or a constant string. Returns parsed logs."""
    state_iter = iter(moderator_states)
    last_state = {"v": moderator_states[0] if moderator_states else "Exploration"}
    counts = {"agent": 0}

    def fake(model, messages, temperature, max_output_tokens, meta=None):
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        user_c = messages[-1]["content"]
        if meta is not None:
            meta["status"] = "completed"
        if sys_c.startswith("You are Admin-2"):
            return "A"
        if sys_c.startswith("You are Admin-1"):
            return "analysis. NEXT = A"
        if "deliberation moderator" in sys_c:
            try:
                last_state["v"] = next(state_iter)
            except StopIteration:
                pass
            # a trailing "!" in the scripted state means "report stall: true"
            st = last_state["v"]
            stall = "true" if st.endswith("!") else "false"
            return (f"[Moderator]\nmode: S\nstate: {st.rstrip('!')}\n"
                    f"stall: {stall}\ngoal: g\n[/Moderator]")
        if messages[0]["role"] == "user" and "Distill" in user_c:
            return "stub stance."
        counts["agent"] += 1
        if meta is not None and meta_for_agent:
            meta.update(meta_for_agent)
        return agent_reply(counts["agent"]) if callable(agent_reply) else agent_reply

    aw.create_response = fake
    it = iter(inputs)
    builtins.input = lambda prompt="": next(it)
    logdir = tempfile.mkdtemp(prefix="logs_")
    sys.argv = (["x", "--info", "info3.jsonl", "--roles-dir", "roles", "--start_order", "ABC",
                 "--prefer_agents", "0", "--log_dir", logdir] + list(argv_extra))
    cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    out = cap.getvalue()
    room = [l for l in out.splitlines() if l.startswith("Chat room id:")][0].split()[-1]

    def load(suffix):
        p = os.path.join(logdir, f"{room}{suffix}.jsonl")
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    return {"out": out, "chat": load(""), "mod": load("_moderator"),
            "rat": load("_rationale"), "think": load("_thinking")}


GOOD = "[MESSAGE]\n{}\n[/MESSAGE]\n[RATIONALE]\nwhy\n[/RATIONALE]"

# ---- 1. phase progression is gated on USER turns -------------------------
# Three agent greetings with no user input must NOT advance the phase.
r = run_session(
    inputs=["/exit"],
    agent_reply=lambda n: GOOD.format(f"unique alpha{n} bravo{n} charlie{n} delta{n}"),
    moderator_states=["Structuring", "Narrowing", "Convergence"],
    argv_extra=["--novelty_threshold", "0"],
)
changes = [m for m in r["mod"] if m["character"] == "admin3_state_change"]
check("1a: agent-only greetings do not advance the phase", len(changes) == 0,
      f"{len(changes)} state changes: {[m['txt'] for m in changes]}")

# With 2 user turns, at most one advance.
r = run_session(
    inputs=["first user line", "second user line", "/exit"],
    agent_reply=lambda n: GOOD.format(f"unique alpha{n} bravo{n} charlie{n} delta{n}"),
    moderator_states=["Structuring", "Narrowing", "Convergence", "Convergence"],
    argv_extra=["--novelty_threshold", "0"],
)
changes = [m for m in r["mod"] if m["character"] == "admin3_state_change"]
check("1b: two user turns advance the phase at most once", len(changes) <= 1,
      f"{len(changes)} changes: {[m['txt'] for m in changes]}")

# ---- 2. Convergence terminates instead of looping ------------------------
# Moderator keeps saying Convergence; after the second verdict with no user
# input the state must latch to Concluded and the floor go back to the user.
r = run_session(
    inputs=[f"u{i}" for i in range(1, 12)] + ["/exit"],
    # "i disagree" is a _DISAGREEMENT_MARKERS hit: the Convergence gate holds the
    # group at Structuring until some real disagreement is on record, so a fixture
    # that needs to REACH Convergence has to voice one (real agents are told to).
    agent_reply=lambda n: GOOD.format(f"i disagree — unique alpha{n} bravo{n} charlie{n} delta{n}"),
    moderator_states=["Convergence"] * 20,
    argv_extra=["--novelty_threshold", "0", "--max_user_gap", "3"],
)
concluded = [m for m in r["mod"] if m["character"] == "admin3_concluded"]
reopened = [m for m in r["mod"] if m["character"] == "admin3_reopened"]
check("2a: repeated Convergence latches to Concluded", len(concluded) >= 1,
      str([m["character"] for m in r["mod"]]))
check("2b: Concluded hands the floor back to the user",
      "讨论已收敛" in r["out"] or "has converged" in r["out"], r["out"][-300:])
check("2c: user input reopens a concluded discussion", len(reopened) >= 1,
      str([m["character"] for m in r["mod"]]))

# ---- 3. stall_burst actually emits ---------------------------------------
# State never changes so turns_in_current_state climbs past MODERATOR_STALL_TURNS;
# from the 3rd verdict on, the moderator reports stall: true ("!" suffix).
r = run_session(
    inputs=[f"u{i}" for i in range(1, 12)] + ["/exit"],
    agent_reply=lambda n: GOOD.format(f"unique alpha{n} bravo{n} charlie{n} delta{n}"),
    moderator_states=["Structuring", "Structuring"] + ["Structuring!"] * 20,
    argv_extra=["--novelty_threshold", "0"],
)
bursts = [t for t in r["think"] if t["character"] == "stall_burst"]
started = [t for t in bursts if t["txt"].startswith("Forcing")]
cut_short = [t for t in bursts if "cut short" in t["txt"]]
check("3a: a stall burst was triggered", len(started) >= 1, str([t["txt"] for t in bursts]))
check("3b: burst is never cut short by the consecutive-turn valve", len(cut_short) == 0,
      str([t["txt"] for t in cut_short]))
if started:
    # every burst must be followed by real chat messages from the burst agents
    burst_keys = started[0]["txt"].split()[1].split("->")
    t0 = started[0]["time"]
    after = [c for c in r["chat"] if c["time"] >= t0 and c["character"].startswith("Chatbot")]
    check("3c: burst produced at least one new message", len(after) >= 1, str(len(after)))

# ---- 4. novelty failures are dropped, not published ----------------------
# Every agent reply is the SAME text, so after the first one novelty is ~0 and
# the retry (same text again) cannot clear the bar.
r = run_session(
    inputs=["u1", "u2", "/exit"],
    agent_reply=GOOD.format("完全相同的重复内容，没有任何新东西"),
    moderator_states=["Structuring"] * 8,
    argv_extra=["--novelty_threshold", "0.5"],
)
dropped = [x for x in r["rat"] if x["event"] == "turn_dropped"]
agent_msgs = [c for c in r["chat"] if c["character"].startswith("Chatbot")]
check("4a: repeated content gets dropped", len(dropped) >= 1, str(len(dropped)))
check("4b: dropped turns never reach the chat log",
      len(agent_msgs) <= 1, f"{len(agent_msgs)} agent messages published")
check("4c: drop is announced to the user", "nothing new to add" in r["out"], r["out"][-200:])

# ---- 5. generation metadata is logged ------------------------------------
r = run_session(
    inputs=["/exit"],
    agent_reply="I'm sorry, I can't assist with that.",
    moderator_states=["Exploration"],
    argv_extra=["--novelty_threshold", "0"],
    meta_for_agent={"status": "incomplete", "incomplete_reason": "content_filter",
                    "refusal": "I'm sorry, I can't assist with that."},
)
gen = [x for x in r["rat"] if x["event"] == "generation_meta"]
check("5a: generation metadata reaches the rationale log", len(gen) >= 1, str(r["rat"][:3]))
check("5b: refusal is flagged", any("REFUSAL" in x["detail"] for x in gen),
      str([x["detail"] for x in gen]))
check("5c: reason is preserved", any("content_filter" in x["detail"] for x in gen),
      str([x["detail"] for x in gen]))

r = run_session(
    inputs=["/exit"],
    agent_reply="[MESSAGE]\ncut off mid sen",
    moderator_states=["Exploration"],
    argv_extra=["--novelty_threshold", "0"],
    meta_for_agent={"status": "incomplete", "incomplete_reason": "max_output_tokens"},
)
gen = [x for x in r["rat"] if x["event"] == "generation_meta"]
check("5d: truncation is flagged with an actionable hint",
      any("TRUNCATED" in x["detail"] for x in gen), str([x["detail"] for x in gen]))

_ck.finish("ALL PACING CHECKS PASSED")
