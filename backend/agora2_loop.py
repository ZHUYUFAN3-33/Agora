# -*- coding: utf-8 -*-
"""Agora-2 turn loop callable from Flask (no Decision Board / chips).

Ports the CLI scheduling from agentwake_new.main(): user message → moderator
cadence → Admin pick → agent turns with novelty pick-better → hand back to U.
"""
from __future__ import annotations

import os
import random
from typing import Any, Callable, Dict, List, Optional

import agentwake_new as aw

CreateFn = Callable[[Any, str, List[dict], float, int], str]


def _append_jsonl(fp, obj: dict) -> None:
    if fp is None:
        return
    import json
    fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
    fp.flush()


def run_user_turn(
    *,
    session: dict,
    user_message: str,
    agents: Dict[str, aw.ChatAgent],
    agent_list: List[aw.ChatAgent],
    all_agent_names: List[str],
    client_chat,
    client_admin,
    scene: str,
    known_context: str = "",
    domain_background: str = "",
    session_memory_text: str = "",
    preloaded_knowledge_text: str = "",
    intake_data: Optional[dict] = None,
    scenario_type: Optional[str] = None,
    lang: str = "en",
    model: str = "gpt-4o",
    temperature: float = 0.8,
    max_output_tokens: int = 220,
    max_history_chars: int = 12000,
    max_user_gap: int = 12,
    max_agent_turns_before_user: int = 5,
    prefer_agents: Optional[float] = None,
    novelty_threshold: Optional[float] = None,
    novelty_window: int = 10,
    persist_chat: Optional[Callable[[dict], None]] = None,
    create_response_with_client: Optional[CreateFn] = None,
) -> Dict[str, Any]:
    """Run one user turn; mutate session; return API-shaped responses."""
    create = create_response_with_client or aw.create_response_with_client
    prefer = float(prefer_agents if prefer_agents is not None else os.getenv("AGORA_PREFER_AGENTS", "0.85"))
    nov_th = float(novelty_threshold if novelty_threshold is not None else os.getenv("AGORA_NOVELTY_THRESHOLD", "0.35"))
    intake_data = intake_data or {}

    key_to_agent = agents
    name_map = {a.key: a.name for a in agent_list}
    agent_configs = {
        slot: {
            "decision": (session.get("agent_runtime_config") or {}).get(slot, {}).get("decision", "Rational"),
            "emotion": (session.get("agent_runtime_config") or {}).get(slot, {}).get("emotion", "Joy"),
            "stance": (session.get("agent_runtime_config") or {}).get(slot, {}).get("stance"),
        }
        for slot in ("A", "B", "C")
    }

    moderator_state = session.setdefault(
        "moderator_state", {"mode": None, "state": "Exploration", "stall": False, "goal": ""}
    )
    session.setdefault("turns_in_current_state", 0)
    session.setdefault("turns_since_moderator", 0)
    session.setdefault("bots_since_user", 0)
    session.setdefault("has_spoken", {"A": False, "B": False, "C": False})

    transcript_lines = aw.history_to_transcript_lines(session.get("history") or [])
    responses: List[dict] = []

    def log_thinking(character: str, txt: str) -> None:
        rec = {"chat_room_id": session.get("room_id"), "time": aw.now_local_iso(), "character": character, "txt": txt}
        _append_jsonl(session.get("think_fp"), rec)

    def log_moderator(character: str, txt: str) -> None:
        rec = {"chat_room_id": session.get("room_id"), "time": aw.now_local_iso(), "character": character, "txt": txt}
        _append_jsonl(session.get("moderator_fp"), rec)

    def get_stance_block(agent_key: str) -> str:
        try:
            from stance import get_stance_text, stance_enabled
            if not scenario_type or not stance_enabled(scenario_type):
                return ""
            stance = agent_configs.get(agent_key, {}).get("stance")
            return get_stance_text(scenario_type, stance, lang) if stance else ""
        except Exception:
            return ""

    def get_phase_context(agent_key: str) -> str:
        s = moderator_state
        decision = agent_configs[agent_key]["decision"]
        mode = s.get("mode") or "S"
        assignment = aw.get_phase_prompt(s["state"], mode, decision, bool(s.get("stall")))
        lines = ["=== DELIBERATION STATE ==="]
        if s.get("mode"):
            lines.append(f"Mode: {'Selection' if mode == 'S' else 'Package'} | Phase: {s['state']}")
        else:
            lines.append(f"Phase: {s['state']}")
        if s.get("goal"):
            lines.append(f"Current goal: {s['goal']}")
        lines.append(f"Your task this turn: {assignment}")
        budget = aw.QUESTION_BUDGET.get(s["state"])
        if budget and not s.get("stall"):
            lines.append(budget)
        if known_context or domain_background:
            lines.append(
                "Anchor this message to the user's actual case: name at least one specific detail "
                "from KNOWN USER CONTEXT. A statement that would read the same for any user is not "
                "a contribution. Do not re-ask for anything already listed there as filled in."
            )
        recent = [ln for ln in transcript_lines[-6:] if not ln.lower().startswith("user:")]
        if len(recent) >= 4 and not any(aw.has_disagreement(ln) for ln in recent):
            lines.append(
                "CONSENSUS WARNING: the last several messages contained no real disagreement. "
                "Before adding anything, state plainly where your stance differs from where the "
                "group is heading, and what that direction costs the interest you represent."
            )
        try:
            from stance import get_convergence_weight_hint
            if s["state"] == "Convergence":
                stance = agent_configs.get(agent_key, {}).get("stance")
                weight_hint = get_convergence_weight_hint(scenario_type, intake_data, stance, lang)
                if weight_hint:
                    lines.append(f"Stance weighting for this closing stage: {weight_hint}")
        except Exception:
            pass
        return "\n".join(lines)

    def run_moderator() -> None:
        history = aw.clamp_history(transcript_lines, max_history_chars)
        roles_summary = aw.build_roles_summary(agent_list)
        stall_eligible = int(session.get("turns_in_current_state") or 0) > aw.MODERATOR_STALL_TURNS
        stall_hint = (
            f"The conversation has been in '{moderator_state['state']}' state for "
            f"{session.get('turns_in_current_state')} agent turns."
            + ("" if stall_eligible else " Do NOT set stall: true — not enough turns yet.")
        )
        msgs = [
            {"role": "system", "content": aw.ADMIN3_SYSTEM},
            {"role": "user", "content": (
                f"=== SCENE ===\n{scene}\n\n"
                f"=== AGENT PERSONALITIES ===\n{roles_summary}\n\n"
                f"=== CURRENT STATE ===\n{moderator_state['state']}\n"
                f"{stall_hint}\n\n"
                f"=== TRANSCRIPT ===\n{history}\n"
            )},
        ]
        raw = create(client_admin, model, msgs, 0.0, 300)
        log_moderator("admin3_moderator", raw or "")
        parsed = aw.parse_moderator_plan(raw or "")
        if not parsed:
            return
        prev_state = moderator_state["state"]
        moderator_state.update(parsed)
        if parsed["state"] != prev_state:
            session["turns_in_current_state"] = 0
            session["turns_since_moderator"] = 0
            log_moderator("admin3_state_change", f"{prev_state} -> {parsed['state']}  |  {parsed['goal']}")
        elif parsed["stall"] and stall_eligible:
            log_moderator(
                "admin3_stall",
                f"Stall in state={parsed['state']} after {session.get('turns_in_current_state')} turns | {parsed['goal']}",
            )
        if not stall_eligible or parsed["state"] != prev_state:
            moderator_state["stall"] = False

    def maybe_run_moderator() -> None:
        due = int(session.get("turns_since_moderator") or 0) >= aw.MODERATOR_TURN_INTERVAL
        stalling = (
            int(session.get("turns_in_current_state") or 0) > aw.MODERATOR_STALL_TURNS
            and int(session.get("turns_since_moderator") or 0) >= aw.MODERATOR_STALL_RECHECK
        )
        if due or stalling:
            session["turns_since_moderator"] = 0
            run_moderator()

    def enforce_novelty(agent: aw.ChatAgent, messages: List[dict], txt: str, temp: float) -> str:
        if nov_th <= 0 or not transcript_lines:
            return txt
        prior = transcript_lines[-novelty_window:]
        ratio = aw.novelty_ratio(txt, prior)
        if ratio >= nov_th:
            return txt
        log_thinking("novelty_retry", f"{agent.key}: novelty={ratio:.2f} < {nov_th:.2f}, retrying once")
        retry_messages = messages + [
            {"role": "assistant", "content": txt},
            {"role": "user", "content": (
                "That message restates points the group already has on the table and adds nothing new. "
                "Replace it entirely.\n"
                "Contribute exactly one of: a new evaluation dimension, a specific fact from KNOWN USER "
                "CONTEXT that nobody has cited yet, a concrete comparison of two options along one named "
                "dimension, an elimination with its reason, or a direct challenge to a specific claim "
                "someone made.\n"
                "If you genuinely have nothing new, reply with one short sentence saying so and naming "
                "whose point you are deferring to. Either way, do not ask a question this time."
            )},
        ]
        retry = create(client_chat, model, retry_messages, min(temp + 0.15, 1.4), max_output_tokens)
        retry = (retry or "").strip()
        if not retry:
            return txt
        retry_ratio = aw.novelty_ratio(retry, prior)
        log_thinking(
            "novelty_retry",
            f"{agent.key}: retry novelty={retry_ratio:.2f} ({'kept' if retry_ratio > ratio else 'discarded'})",
        )
        return retry if retry_ratio > ratio else txt

    def append_agent(agent: aw.ChatAgent, txt: str) -> None:
        txt = aw.sanitize_single_message(txt, agent.name, all_agent_names)
        msg = {
            "chat_room_id": session.get("room_id"),
            "time": aw.now_local_iso(),
            "character": agent.name,
            "txt": txt,
        }
        session.setdefault("history", []).append(msg)
        _append_jsonl(session.get("chat_fp"), msg)
        if persist_chat:
            persist_chat(msg)
        transcript_lines.append(f"{agent.name}: {txt}")
        session["has_spoken"][agent.key] = True
        agent.spoke += 1
        responses.append({
            "agent": agent.name,
            "agent_key": agent.key,
            "message": txt,
            "time": msg["time"],
        })

    def stall_burst(trigger_key: Optional[str] = None) -> None:
        stall_temp = min(temperature + 0.25, 1.4)
        burst_agents = [a for a in agent_list if a.key != trigger_key]
        log_thinking("stall_burst", f"Forcing {'->'.join(a.key for a in burst_agents)} burst at temp={stall_temp:.2f}")
        for burst_agent in burst_agents:
            if int(session.get("bots_since_user") or 0) >= max_agent_turns_before_user:
                break
            session["bots_since_user"] = int(session.get("bots_since_user") or 0) + 1
            session["turns_in_current_state"] = int(session.get("turns_in_current_state") or 0) + 1
            session["turns_since_moderator"] = int(session.get("turns_since_moderator") or 0) + 1
            history = aw.clamp_history(transcript_lines, max_history_chars)
            phase_context = get_phase_context(burst_agent.key)
            user_prompt = (
                "Below is the full group chat transcript so far.\n"
                "The moderator has flagged a stall — the group is going in circles.\n"
                "You MUST make a decisive move: propose something new, force a comparison, "
                "ask a direct question that demands an answer, or take a clear position.\n"
                "Do NOT repeat what has already been said.\n\n"
                f"{history}"
            )
            messages = [
                {"role": "system", "content": burst_agent.system_prompt(
                    scene, name_map, phase_context,
                    known_context=known_context, domain_background=domain_background,
                    stance_text=get_stance_block(burst_agent.key), lang=lang,
                    session_memory_text=session_memory_text,
                    preloaded_knowledge_text=preloaded_knowledge_text,
                )},
                {"role": "user", "content": user_prompt},
            ]
            txt = create(client_chat, model, messages, stall_temp, max_output_tokens)
            txt = (txt or "").strip() or "…"
            append_agent(burst_agent, txt)
        moderator_state["stall"] = False

    def agent_turn(agent: aw.ChatAgent, force_intro: bool = False) -> None:
        session["bots_since_user"] = int(session.get("bots_since_user") or 0) + 1
        session["turns_in_current_state"] = int(session.get("turns_in_current_state") or 0) + 1
        session["turns_since_moderator"] = int(session.get("turns_since_moderator") or 0) + 1
        stall_triggered = bool(moderator_state.get("stall"))
        history = aw.clamp_history(transcript_lines, max_history_chars)
        extra = ""
        if force_intro:
            extra = f"\n\n(Important) This is your FIRST message. Start with: Hi, I'm {agent.name}"
        effective_temp = temperature
        if stall_triggered:
            effective_temp = min(temperature + 0.25, 1.4)
        phase_context = get_phase_context(agent.key)
        user_prompt = (
            "Below is the full group chat transcript so far.\n"
            "Each line is formatted as: Speaker: message\n"
            "Continue the conversation as your character.\n"
            "Try to keep a lively group dynamic by engaging other bots (react, ask them questions, build on their points), "
            "while still keeping the user included.\n\n"
            f"{history}\n{extra}"
        )
        messages = [
            {"role": "system", "content": agent.system_prompt(
                scene, name_map, phase_context,
                known_context=known_context, domain_background=domain_background,
                stance_text=get_stance_block(agent.key), lang=lang,
                session_memory_text=session_memory_text,
                preloaded_knowledge_text=preloaded_knowledge_text,
            )},
            {"role": "user", "content": user_prompt},
        ]
        txt = create(client_chat, model, messages, effective_temp, max_output_tokens)
        txt = (txt or "").strip() or "…"
        txt = enforce_novelty(agent, messages, txt, effective_temp)
        append_agent(agent, txt)
        if stall_triggered:
            stall_burst(trigger_key=agent.key)
        maybe_run_moderator()

    def admin_choose_next() -> str:
        if int(session.get("bots_since_user") or 0) >= max_agent_turns_before_user:
            log_thinking("admin_rule", f"Force U: bots_since_user >= {max_agent_turns_before_user}")
            return "U"
        li = aw.last_user_index(transcript_lines)
        gap = (len(transcript_lines) - 1 - li) if li is not None else len(transcript_lines)
        if gap >= max_user_gap:
            log_thinking("admin_rule", f"Force U: user gap {gap} >= max_user_gap {max_user_gap}")
            return "U"
        history = aw.clamp_history(transcript_lines, max_history_chars)
        roles_summary = aw.build_roles_summary(agent_list)
        stats = (
            f"Spoke counts: A={key_to_agent['A'].spoke}, "
            f"B={key_to_agent['B'].spoke}, C={key_to_agent['C'].spoke}. "
            f"Consecutive agent turns={session.get('bots_since_user')}. "
            f"User gap(lines)={gap}. "
            f"Moderator state={moderator_state['state']}."
        )
        admin1_messages = [
            {"role": "system", "content": aw.ADMIN1_SYSTEM},
            {"role": "user", "content": (
                f"=== SCENE ===\n{scene}\n\n"
                f"=== ROLES ===\n{roles_summary}\n\n"
                f"=== STATS ===\n{stats}\n\n"
                f"=== TRANSCRIPT (Speaker: message) ===\n{history}\n\n"
                f"Decide NEXT."
            )},
        ]
        admin1_out = create(client_admin, model, admin1_messages, 0.2, 260)
        log_thinking("admin1", admin1_out or "")
        admin2_messages = [
            {"role": "system", "content": aw.ADMIN2_SYSTEM},
            {"role": "user", "content": admin1_out or ""},
        ]
        admin2_out = (create(client_admin, model, admin2_messages, 0.0, aw.MIN_OUTPUT_TOKENS) or "").strip().upper()
        log_thinking("admin2", admin2_out)
        if admin2_out not in {"A", "B", "C", "U"}:
            log_thinking("admin_fallback", f"Invalid admin2_out={admin2_out!r}, fallback to agent")
            admin2_out = random.choice(["A", "B", "C"])
        if admin2_out == "U":
            if random.random() < prefer:
                pick = random.choice(["A", "B", "C"])
                log_thinking("admin_bias", f"Override U -> {pick} (prefer_agents={prefer})")
                return pick
            return "U"
        return admin2_out

    # --- user message already appended by caller; sync counters like Agora-2 user_turn ---
    session["bots_since_user"] = 0
    session["user_turn_count"] = int(session.get("user_turn_count") or 0) + 1
    session["turns_since_moderator"] = int(session.get("turns_since_moderator") or 0) + 1
    maybe_run_moderator()

    # Agent burst until Admin returns U (or hard caps)
    for _ in range(max_agent_turns_before_user + 2):
        nxt = admin_choose_next()
        if nxt == "U":
            break
        agent = key_to_agent[nxt]
        force_intro = not bool((session.get("has_spoken") or {}).get(nxt))
        agent_turn(agent, force_intro=force_intro)

    phase = moderator_state.get("state", "Exploration")
    concluded = phase == "Concluded"
    return {
        "responses": responses,
        "phase": phase,
        "stall": bool(moderator_state.get("stall")),
        "concluded": concluded,
        "moderator_state": dict(moderator_state),
    }
