# -*- coding: utf-8 -*-
"""Two failures seen together in one live zh parent_child session.

1. REFUSAL. An agent replied "I'm sorry, I can't assist with that." — a bare
   content refusal, returned as ordinary COMPLETED content so no generation
   metadata flags it. Published verbatim it breaks the persona, tells the user
   nothing, and pollutes the transcript that later turns, the novelty scores and
   the session summary all read. It must now be reframed once and, if it holds,
   the turn dropped (silence is already an allowed turn).

2. ENGLISH DRIFT FROM THE PRESETS. The same session had an agent answer wholly
   in English with:
       "Option A is the strongest. ... Recommendation: Choose A, ... and act now."
   which is decision/Spontaneous.txt's STRUCTURAL EXAMPLES block:
       "Option B is clearly stronger. ... Recommendation: Choose B and act now."
   reproduced almost verbatim. Those worked examples are now stripped at splice
   time, so the model is not handed an English output template.
"""
import builtins, io, json, os, shutil, sys

from _harness import bootstrap, Checker

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
aw = bootstrap("agentwake_refusal_")
for _d in ("background_templates", "scenes", "decision", "emotion", "stance_templates"):
    shutil.copytree(os.path.join(BACKEND, _d), _d)

_ck = Checker(); check = _ck.check

REFUSAL = "I'm sorry, I can't assist with that."
GOOD = "我认为这个方案低估了接送成本，@U 你提到过下周就要截止。"

# ---------------------------------------------------- unit: refusal detection
for t in (REFUSAL, "Sorry, I cannot help with that.",
          "I'm unable to assist with this request.",
          "抱歉，我不能协助处理这个请求。"):
    check(f"detected as refusal: {t[:34]!r}", aw.looks_like_refusal(t))

# A turn that ARGUES it cannot back an option is a real contribution, not a refusal.
for t in ("我不同意选项A，因为它牺牲了孩子的自主性。",
          "I can't back Option A because the commute alone eats two evenings a week, "
          "which is the very thing you said worried you.",
          "Option A is the strongest given the deadline."):
    check(f"not a refusal: {t[:34]!r}", not aw.looks_like_refusal(t))


# ------------------------------------- unit: decision presets lose the examples
import agent_assembly as aa
for name in ("Spontaneous", "Rational", "Dependent", "Intuitive", "Avoidant"):
    raw = aa.load_decision_text(name)
    spliced = aa.assemble_role_text(name, "Joy")
    check(f"{name}: STRUCTURAL EXAMPLES present in the source file",
          "STRUCTURAL EXAMPLES" in raw)
    check(f"{name}: worked example is stripped from the spliced role_text",
          "STRUCTURAL EXAMPLES" not in spliced, spliced[:200])
    check(f"{name}: structural requirements survive the strip",
          "CONTRIBUTION REQUIREMENT" in spliced and "CONSTRAINTS" in spliced)
check("the English 'act now' template no longer reaches role_text",
      "act now" not in aa.assemble_role_text("Spontaneous", "Joy"))


# ------------------------------------------ integration: refusal never publishes
def _run(agent_replies):
    """agent_replies: callable(nth_agent_call, is_retry) -> body text."""
    calls = {"n": 0}
    def fake(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        sysc = messages[0]["content"] if messages[0]["role"] == "system" else ""
        if sysc.startswith("You are Admin-2"):
            return "A"
        if sysc.startswith("You are Admin-1"):
            return "NEXT = A"
        if "deliberation moderator" in sysc:
            return "[Moderator]\nmode: S\nstate: Structuring\nstall: false\ngoal: g\n[/Moderator]"
        last = messages[-1]["content"]
        if messages[0]["role"] == "user" and "Distill" in last:
            return "stub."
        is_retry = "That was a refusal" in last
        if not is_retry:
            calls["n"] += 1
        body = agent_replies(calls["n"], is_retry)
        return f"[MESSAGE]\n{body}\n[/MESSAGE]\n[RATIONALE]\nr\n[/RATIONALE]"
    aw.create_response = fake

    with open("info3.jsonl", "w", encoding="utf-8") as f:
        json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)
    inputs = iter(["我们再聊聊这个决定", "/exit"])
    builtins.input = lambda prompt="": next(inputs)
    sys.argv = ["x", "--info", "info3.jsonl", "--prefer_agents", "0",
                "--novelty_threshold", "0", "--log_dir", "lg"]
    cap = io.StringIO(); real = sys.stdout; sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    out = cap.getvalue()
    room = [l for l in out.splitlines() if l.startswith("Chat room id:")][0].split()[-1]
    chat = [json.loads(l) for l in open(f"lg/{room}.jsonl", encoding="utf-8")]
    rat = [json.loads(l) for l in open(f"lg/{room}_rationale.jsonl", encoding="utf-8")]
    return out, chat, rat


# every first attempt refuses; the reframed retry succeeds -> retry is published
out, chat, rat = _run(lambda n, retry: GOOD if retry else REFUSAL)
published = [r["txt"] for r in chat if r["character"] != "user"]
check("refusal is never published when the retry recovers",
      published and not any(aw.looks_like_refusal(t) for t in published),
      str(published[:2]))
check("the reframed reply is what reaches the chat",
      any(GOOD in t for t in published), str(published[:2]))
check("the refusal is recorded for diagnosis",
      any(r["event"] == "refusal_detected" for r in rat),
      str({r["event"] for r in rat}))

# refusal survives the retry -> the turn is dropped, nothing published
out, chat, rat = _run(lambda n, retry: REFUSAL)
published = [r["txt"] for r in chat if r["character"] != "user"]
check("an unrecoverable refusal is dropped, not published",
      not any(aw.looks_like_refusal(t) for t in published), str(published[:3]))
check("the drop is logged",
      any(r["event"] == "turn_dropped" for r in rat),
      str({r["event"] for r in rat}))


# ------------------------------------------- prompt restates the language rule
_sp = aw.ChatAgent("A", "ChatbotA", "(role)").system_prompt(
    scene="(s)", name_map={"A": "ChatbotA"}, lang="zh")
check("language directive is restated at the end of the prompt",
      _sp.count("Write every message in Chinese") >= 2, str(_sp.count("Write every message in Chinese")))

_ck.finish("REFUSAL / LANGUAGE CHECKS PASSED")
