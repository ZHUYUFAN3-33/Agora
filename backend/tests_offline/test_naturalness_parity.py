# -*- coding: utf-8 -*-
"""The dialogue-naturalness layer reaches BOTH deliberation loops.

agentwake_new.py carries two copy-pasted deliberation loops — run_user_turn()
(web, one call per user turn) and main() (CLI, one long-running loop) — and they
have drifted from each other before. The naturalness layer was developed against
the CLI in the Agora-2 repo; the product runs the web path. A change that lands
in only one loop means the agent the user sees on the web is not the agent the
research describes.

So: drive both loops with a stubbed LLM, capture the system prompts each one
actually generates, and assert the naturalness blocks are present in both.

Also pins the one deliberate adaptation the port required: challenge_tracker is
session-scoped on the web path. run_user_turn() returns after every user turn,
so a local dict would reset the counter and both cooldowns on each HTTP call —
the consensus guard would re-fire every turn and the convergence gate would
never see a challenge. The CLI keeps a local dict because its loop never exits.
"""
import builtins
import io
import json
import sys

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_natparity_")
_ck = Checker()
check = _ck.check

# Blocks the naturalness layer adds to every agent generation, whichever loop
# produced it. Text is verbatim from the Agora-2 baseline (776f5bf).
MARKERS = {
    "CONVERSATIONAL STYLE block": "=== CONVERSATIONAL STYLE ===",
    "outcome-framed turn goal": "Your goal this turn:",
    "MOVE block in OUTPUT FORMAT": "[MOVE]",
    "MOVE honesty requirement": "Report the move honestly",
    "no-lists rule": "No bullet lists, numbered lists, or headings inside a chat message",
    "engage-the-last-speaker rule": "Open by engaging with what the LAST SPEAKER actually said",
}

AGREEABLE = "这个方向听起来不错，我也这么想"


def _agent_reply(n):
    return (f"[MESSAGE]\n{AGREEABLE} {n}\n[/MESSAGE]\n"
            f"[RATIONALE]\nr{n}\n[/RATIONALE]")


def _route(sys_c, user_c):
    """Shared stub routing: admin/moderator/distill calls vs an agent turn.

    Returns the canned reply for a non-agent call, or None to signal "this is an
    agent generation" so the caller can capture its system prompt."""
    if "Distill" in (user_c or ""):
        return "stub."
    if sys_c.startswith("You are Admin-2"):
        return "A"
    if sys_c.startswith("You are Admin-1"):
        return "NEXT = A"
    if "deliberation moderator" in sys_c:
        return "[Moderator]\nmode: S\nstate: Structuring\nstall: false\ngoal: g\n[/Moderator]"
    return None


def _is_agent_prompt(sys_c):
    return sys_c.startswith("You are Chatbot")


# ------------------------------------------------------------------ CLI path
def collect_cli_prompts():
    seen = []

    def fake(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        routed = _route(sys_c, messages[-1]["content"])
        if routed is not None:
            return routed
        if _is_agent_prompt(sys_c):
            seen.append(sys_c)
        return _agent_reply(len(seen))

    aw.create_response = fake
    with open("info_np.jsonl", "w", encoding="utf-8") as f:
        json.dump({"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}}, f)
    inputs = iter(["u1", "u2", "/exit"])
    builtins.input = lambda prompt="": next(inputs)
    sys.argv = ["x", "--info", "info_np.jsonl", "--novelty_threshold", "0",
                "--log_dir", "np_cli_logs"]
    cap, real = io.StringIO(), sys.stdout
    sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    return seen


# ----------------------------------------------------------------- HTTP path
def _session(user_txt):
    return {
        "room_id": "np1",
        "history": [{"character": "user", "txt": user_txt}],
        "moderator_state": {"mode": "S", "state": "Structuring", "stall": False, "goal": "g"},
        "has_spoken": {k: False for k in "ABC"},
        "mention_queue": [],
        "agent_runtime_config": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"},
        "think_fp": None, "moderator_fp": None, "chat_fp": None,
        "rationale_fp": None, "memory_fp": None,
        "memory_snippets": {k: [] for k in "ABC"},
        "turns_since_distill": {k: 0 for k in "ABC"},
        "latest_rationale": {k: "" for k in "ABC"},
        "latest_snippet_id": {k: None for k in "ABC"},
        "snippet_counters": {k: 0 for k in "ABC"},
    }


def collect_http_prompts(session=None, user_message="u1", move=""):
    seen = []

    def fake(client, model, messages, temp, max_tok):
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        routed = _route(sys_c, messages[-1]["content"])
        if routed is not None:
            return routed
        if _is_agent_prompt(sys_c):
            seen.append(sys_c)
        tail = f"\n[MOVE]\n{move}\n[/MOVE]" if move else ""
        n = len(seen)
        return (f"[MESSAGE]\n{AGREEABLE} {n}\n[/MESSAGE]{tail}\n"
                f"[RATIONALE]\nr{n}\n[/RATIONALE]")

    sess = session if session is not None else _session(user_message)
    if session is not None:
        sess.setdefault("history", []).append({"character": "user", "txt": user_message})
    agents = {k: aw.ChatAgent(k, f"Chatbot{k}", f"role {k}") for k in "ABC"}
    aw.run_user_turn(
        session=sess,
        user_message=user_message,
        agents=agents,
        agent_list=[agents[k] for k in "ABC"],
        all_agent_names=[f"Chatbot{k}" for k in "ABC"],
        client_chat=object(),
        client_admin=object(),
        scene="s",
        novelty_threshold=0,
        create_response_with_client=fake,
    )
    return seen, sess


cli_prompts = collect_cli_prompts()
http_prompts, _ = collect_http_prompts()

check("CLI loop produced agent prompts", len(cli_prompts) > 0, str(len(cli_prompts)))
check("HTTP loop produced agent prompts", len(http_prompts) > 0, str(len(http_prompts)))

for name, marker in MARKERS.items():
    check(f"CLI:  {name}",
          all(marker in p for p in cli_prompts),
          f"{sum(marker in p for p in cli_prompts)}/{len(cli_prompts)}")
    check(f"HTTP: {name}",
          all(marker in p for p in http_prompts),
          f"{sum(marker in p for p in http_prompts)}/{len(http_prompts)}")

# The old broadcast wording must be gone from both loops.
OLD = "no real disagreement. Before adding anything"
check("CLI:  old broadcast consensus warning is gone",
      not any(OLD in p for p in cli_prompts))
check("HTTP: old broadcast consensus warning is gone",
      not any(OLD in p for p in http_prompts))

# ------------------------------------- web adaptation: tracker survives calls
_, sess = collect_http_prompts(user_message="u1", move="challenge @ChatbotB")
tracker = sess.get("challenge_tracker")
check("HTTP: challenge_tracker is stored on the session",
      isinstance(tracker, dict), repr(tracker))
first_count = (tracker or {}).get("count", 0)
check("HTTP: self-reported challenges counted in call 1",
      first_count > 0, str(first_count))

collect_http_prompts(session=sess, user_message="u2", move="challenge @ChatbotB")
check("HTTP: counter carries across run_user_turn calls (not reset per HTTP turn)",
      sess["challenge_tracker"]["count"] > first_count,
      f'{first_count} -> {sess["challenge_tracker"]["count"]}')

_ck.finish("NATURALNESS PARITY CHECKS PASSED")
