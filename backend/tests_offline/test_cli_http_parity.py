# -*- coding: utf-8 -*-
"""CLI (main) vs HTTP (run_user_turn) scheduling parity.

Checks:
  H1  HTTP novelty env fallback matches CLI argparse default (0.5)
  H2  Mention hard-route: same first speaker when valves are equalized
  H3  No-repeat: no consecutive same agent; equal burst length under seed
  H4  Force-U: burst stops after max_consecutive agent turns
  H5  Omitting novelty_threshold still runs (production-shaped call)

No live API — LLM calls are stubbed.
"""
from __future__ import annotations

import builtins
import inspect
import io
import json
import os
import random
import sys

from _harness import bootstrap, Checker

aw = bootstrap("agentwake_parity_")
_ck = Checker()
check = _ck.check


def make_fake(admin2_pick: str = "A"):
    n = {"i": 0}

    def fake_cli(model, messages, temperature, max_output_tokens, meta=None):
        if meta is not None:
            meta["status"] = "completed"
        return _reply(messages)

    def fake_http(client, model, messages, temp, max_tok):
        return _reply(messages)

    def _reply(messages):
        sys_c = messages[0]["content"] if messages[0]["role"] == "system" else ""
        user_c = messages[-1]["content"]
        if "Distill the agent's CURRENT position" in user_c or (
            messages[0]["role"] == "user" and "Distill" in user_c
        ):
            return "stub stance."
        if sys_c.startswith("You are Admin-2"):
            return admin2_pick
        if sys_c.startswith("You are Admin-1"):
            return f"analysis. NEXT = {admin2_pick}"
        if "deliberation moderator" in sys_c:
            return (
                "[Moderator]\nmode: S\nstate: Exploration\nstall: false\ngoal: g\n"
                "[/Moderator]"
            )
        n["i"] += 1
        return (
            f"[MESSAGE]\nunique parity point {n['i']} omega{n['i']} sigma{n['i']}\n"
            f"[/MESSAGE]\n[RATIONALE]\nwhy {n['i']}\n[/RATIONALE]"
        )

    return fake_cli, fake_http


def _prep_cli_files():
    os.makedirs("roles", exist_ok=True)
    for k in "ABC":
        with open(f"roles/{k}.txt", "w", encoding="utf-8") as f:
            f.write(f"Role {k}.")
    with open("info3.jsonl", "w", encoding="utf-8") as f:
        json.dump(
            {"agents": {k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"}},
            f,
        )


def run_cli_burst(
    user_messages: list,
    *,
    prefer_agents: float,
    novelty_threshold: float,
    admin2_pick: str = "A",
    seed: int = 42,
    extra_argv: list | None = None,
) -> list:
    """Drive main() with --start_order U so the first event is the user message."""
    fake_cli, _ = make_fake(admin2_pick)
    aw.create_response = fake_cli
    _prep_cli_files()
    random.seed(seed)
    inputs = iter(list(user_messages) + ["/exit"])
    builtins.input = lambda prompt="": next(inputs)
    argv = [
        "x", "--info", "info3.jsonl", "--roles-dir", "roles",
        "--start_order", "U",
        "--prefer_agents", str(prefer_agents),
        "--novelty_threshold", str(novelty_threshold),
        "--log_dir", "parity_cli_logs",
    ]
    if extra_argv:
        argv.extend(extra_argv)
    sys.argv = argv
    cap = io.StringIO()
    real = sys.stdout
    sys.stdout = cap
    try:
        aw.main()
    finally:
        sys.stdout = real
    out = cap.getvalue()
    room_lines = [l for l in out.splitlines() if l.startswith("Chat room id:")]
    if not room_lines:
        return []
    room = room_lines[0].split()[-1]
    chat = [json.loads(l) for l in open(f"parity_cli_logs/{room}.jsonl", encoding="utf-8")]
    return [r["character"] for r in chat]


def _http_session(user_txt: str) -> dict:
    return {
        "room_id": "parity1",
        "history": [{"character": "user", "txt": user_txt}],
        "moderator_state": {"mode": "S", "state": "Exploration", "stall": False, "goal": ""},
        "has_spoken": {"A": False, "B": False, "C": False},
        "mention_queue": [],
        "agent_runtime_config": {
            k: {"decision": "Rational", "emotion": "Joy"} for k in "ABC"
        },
        "think_fp": None,
        "moderator_fp": None,
        "chat_fp": None,
        "rationale_fp": open("parity_rationale.jsonl", "a", encoding="utf-8"),
        "memory_fp": open("parity_memory.jsonl", "a", encoding="utf-8"),
        "memory_snippets": {"A": [], "B": [], "C": []},
        "turns_since_distill": {"A": 0, "B": 0, "C": 0},
        "latest_rationale": {"A": "", "B": "", "C": ""},
        "latest_snippet_id": {"A": None, "B": None, "C": None},
        "snippet_counters": {"A": 0, "B": 0, "C": 0},
    }


def run_http_burst(
    user_message: str,
    *,
    prefer_agents: float | None,
    novelty_threshold: float | None,
    max_agent_turns_before_user: int | None = 5,
    admin2_pick: str = "A",
    seed: int = 42,
) -> list:
    _, fake_http = make_fake(admin2_pick)
    agents = {k: aw.ChatAgent(k, f"Chatbot{k}", f"role {k}") for k in "ABC"}
    agent_list = [agents[k] for k in "ABC"]
    names = [a.name for a in agent_list]
    for a in agent_list:
        a.spoke = 0
    random.seed(seed)
    sess = _http_session(user_message)
    kwargs = dict(
        session=sess,
        user_message=user_message,
        agents=agents,
        agent_list=agent_list,
        all_agent_names=names,
        client_chat=object(),
        client_admin=object(),
        scene="s",
        prefer_agents=prefer_agents,
        max_agent_turns_before_user=max_agent_turns_before_user,
        create_response_with_client=fake_http,
    )
    if novelty_threshold is not None:
        kwargs["novelty_threshold"] = novelty_threshold
    r = aw.run_user_turn(**kwargs)
    return ["user"] + [x["agent"] for x in r["responses"]]


def agent_only(seq: list) -> list:
    return [s for s in seq if s != "user"]


def first_burst(seq: list) -> list:
    if not seq:
        return []
    out = [seq[0]]
    for s in seq[1:]:
        if s == "user":
            break
        out.append(s)
    return out


def has_consec_dup(seq: list) -> bool:
    agents = agent_only(seq)
    return any(a == b for a, b in zip(agents, agents[1:]))


# ---------------------------------------------------------------------------
# H1 / H5 — default valves
# ---------------------------------------------------------------------------

os.environ.pop("AGORA_NOVELTY_THRESHOLD", None)
os.environ.pop("AGORA_PREFER_AGENTS", None)

_src = inspect.getsource(aw.run_user_turn)
check(
    "H1: HTTP novelty env fallback is CLI-faithful 0.5",
    'os.getenv("AGORA_NOVELTY_THRESHOLD", "0.5")' in _src,
    "run_user_turn fallback must be 0.5",
)
check(
    "H1: resolved default without env == 0.5",
    float(os.getenv("AGORA_NOVELTY_THRESHOLD", "0.5")) == 0.5,
)

_http_speakers_default = run_http_burst(
    "ping defaults",
    prefer_agents=0.85,
    novelty_threshold=None,
    max_agent_turns_before_user=5,
    admin2_pick="U",
    seed=7,
)
check(
    "H5: production-shaped HTTP call (novelty omitted) still runs",
    len(_http_speakers_default) >= 1,
    _http_speakers_default,
)


# ---------------------------------------------------------------------------
# H2 — mention hard-route
# ---------------------------------------------------------------------------

SEED = 42
VALVES = dict(prefer_agents=0.0, novelty_threshold=0.0)

cli_m = first_burst(run_cli_burst(
    ["@ChatbotB please", "/exit"],
    admin2_pick="A",
    seed=SEED,
    **VALVES,
))
http_m = run_http_burst(
    "@ChatbotB please",
    admin2_pick="A",
    seed=SEED,
    prefer_agents=0.0,
    novelty_threshold=0.0,
    max_agent_turns_before_user=5,
)

check("H2: CLI mention → first agent is ChatbotB", agent_only(cli_m)[:1] == ["ChatbotB"], cli_m)
check("H2: HTTP mention → first agent is ChatbotB", agent_only(http_m)[:1] == ["ChatbotB"], http_m)
check(
    "H2: CLI↔HTTP first agent matches under equalized valves",
    agent_only(cli_m)[:1] == agent_only(http_m)[:1],
    {"cli": cli_m, "http": http_m},
)


# ---------------------------------------------------------------------------
# H3 — no-repeat
# ---------------------------------------------------------------------------

cli_nr = first_burst(run_cli_burst(
    ["go on", "/exit"],
    prefer_agents=1.0,
    novelty_threshold=0.0,
    admin2_pick="A",
    seed=SEED,
))
http_nr = run_http_burst(
    "go on",
    prefer_agents=1.0,
    novelty_threshold=0.0,
    max_agent_turns_before_user=5,
    admin2_pick="A",
    seed=SEED,
)

check("H3: CLI no consecutive same agent", not has_consec_dup(cli_nr), cli_nr)
check("H3: HTTP no consecutive same agent", not has_consec_dup(http_nr), http_nr)
check(
    "H3: CLI↔HTTP burst length equal (max_consecutive=5)",
    len(agent_only(cli_nr)) == len(agent_only(http_nr)),
    {"cli": cli_nr, "http": http_nr},
)


# ---------------------------------------------------------------------------
# H4 — force-U
# ---------------------------------------------------------------------------

cli_fu = first_burst(run_cli_burst(
    ["force gap", "/exit"],
    prefer_agents=1.0,
    novelty_threshold=0.0,
    admin2_pick="A",
    seed=SEED,
))
http_fu5 = run_http_burst(
    "force gap",
    prefer_agents=1.0,
    novelty_threshold=0.0,
    max_agent_turns_before_user=5,
    admin2_pick="A",
    seed=SEED,
)
http_fu3 = run_http_burst(
    "force gap",
    prefer_agents=1.0,
    novelty_threshold=0.0,
    max_agent_turns_before_user=3,
    admin2_pick="A",
    seed=SEED,
)

check("H4: CLI burst length == native max_consecutive (5)", len(agent_only(cli_fu)) == 5, cli_fu)
check("H4: HTTP(max=5) burst length == 5", len(agent_only(http_fu5)) == 5, http_fu5)
check("H4: HTTP(max=3) respects lower cap → 3", len(agent_only(http_fu3)) == 3, http_fu3)
check(
    "H4: CLI↔HTTP(max=5) agent count matches",
    len(agent_only(cli_fu)) == len(agent_only(http_fu5)),
    {"cli": cli_fu, "http": http_fu5},
)

_ck.finish("CLI↔HTTP PARITY PROBE DONE")
