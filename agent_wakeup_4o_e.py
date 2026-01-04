import argparse
import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple

from zoneinfo import ZoneInfo
from openai import OpenAI

TZ = ZoneInfo("Asia/Tokyo")
Speaker = Literal["A", "B", "C", "U"]


# ----------------- basic utils -----------------

def now_local_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def make_room_id_6() -> str:
    return f"{random.randint(0, 999999):06d}"


def append_jsonl(fp, obj: dict) -> None:
    fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
    fp.flush()


def extract_text(resp) -> str:
    t = (getattr(resp, "output_text", "") or "").strip()
    if t:
        return t
    parts = []
    for item in (getattr(resp, "output", None) or []):
        if getattr(item, "type", None) == "message":
            for c in (getattr(item, "content", None) or []):
                if getattr(c, "type", None) == "output_text":
                    txt = (getattr(c, "text", "") or "").strip()
                    if txt:
                        parts.append(txt)
    return "\n".join(parts).strip()


def truncate(s: str, max_chars: int) -> str:
    s = s or ""
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n... (truncated) ..."


def build_transcript(history: List[dict], max_turns: int = 0) -> str:
    items = history if max_turns <= 0 else history[-max_turns:]
    return "\n".join(f"{m['character']}: {m['txt']}" for m in items) or "(none)"


def sanitize_single_message(text: str, agent_name: str, all_names: List[str]) -> str:
    if not text:
        return "..."
    t = text.strip()
    t = re.sub(rf"^\s*{re.escape(agent_name)}\s*:\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*(USER|user|You|YOU)\s*:\s*", "", t)

    other_prefixes = [n for n in all_names if n != agent_name] + ["user", "You"]
    pattern = r"(?m)^\s*(" + "|".join(re.escape(p) for p in other_prefixes) + r")\s*:\s*"
    m = re.search(pattern, t)
    if m:
        t = t[: m.start()].rstrip()

    return t.strip() if t.strip() else "..."


def parse_next_token(s: str) -> Optional[Speaker]:
    if not s:
        return None
    u = s.strip().upper()
    m = re.search(r"\bNEXT\s*=\s*([ABCU])\b", u)
    if m:
        return m.group(1)  # type: ignore
    # allow plain single char line
    lines = [ln.strip() for ln in u.splitlines() if ln.strip()]
    if lines and lines[-1] in ("A", "B", "C", "U"):
        return lines[-1]  # type: ignore
    if u and u[0] in ("A", "B", "C", "U"):
        return u[0]  # type: ignore
    return None


# ----------------- Known user facts (only from user messages) -----------------

def normalize_quotes(s: str) -> str:
    return (s or "").replace("’", "'").replace("“", '"').replace("”", '"')


def update_user_facts(facts: Dict[str, str], user_text: str) -> Dict[str, str]:
    t = normalize_quotes(user_text).lower()

    if re.search(r"\b(battery|battery life)\b", t):
        if re.search(r"\b(no\s+high\s+requirements?|don't\s+care|do\s+not\s+care|not\s+important)\b", t) or (
            re.search(r"\bnot\b", t) and re.search(r"\b(care|need|require)\b", t)
        ):
            facts["battery"] = "User does not have high requirements for battery life."
        elif re.search(r"\bimportant|care|need\b", t):
            facts["battery"] = "Battery life matters to the user."

    if re.search(r"\b(one fixed place|fixed place|one place|stationary|desk)\b", t) or re.search(r"\busually\b.*\b(one place|at home|desk)\b", t):
        facts["portability"] = "User usually uses it in one fixed place; portability is not a major requirement."
    if re.search(r"\bportable|portability|travel|on the go\b", t):
        if re.search(r"\bnot\b.*\b(important|needed|need)\b", t):
            facts["portability"] = "Portability is not important to the user."
        elif re.search(r"\bimportant|need|prefer\b", t):
            facts["portability"] = "User wants portability (at least sometimes)."

    if re.search(r"\b(aaa|triple a)\b.*\b(game|games|gaming)\b", t) or re.search(r"\bplay\b.*\b(aaa|triple a)\b", t):
        facts["use_case"] = "User wants to play AAA games."

    if re.search(r"\bnoise\b|\bquiet\b|\bfan noise\b", t) and re.search(r"\bconcern\b|\bissue\b|\bimportant\b|\bsensitive\b", t):
        facts["noise"] = "Noise level is a concern for the user."

    if re.search(r"\bspace\b|\bsmall\b|\blimited\b|\btight\b", t) and re.search(r"\blimited\b|\btight\b|\bsmall\b", t):
        facts["space"] = "Space is limited for the setup."

    return facts


def facts_to_bullets(facts: Dict[str, str]) -> str:
    if not facts:
        return "- (none yet)"
    return "\n".join([f"- {v}" for v in facts.values()])


# ----------------- Agents -----------------

@dataclass
class AgentSpec:
    key: Literal["A", "B", "C"]
    name: str
    role_text: str


def call_chat_agent(
    client: OpenAI,
    model: str,
    scene: str,
    agent: AgentSpec,
    history: List[dict],
    known_user_facts: Dict[str, str],
    is_first_utterance: bool,
    all_agent_names: List[str],
    debug: bool = False,
) -> str:
    transcript = build_transcript(history, max_turns=0)
    others = [n for n in all_agent_names if n != agent.name]
    others_str = ", ".join(others) if others else "(none)"
    facts_block = facts_to_bullets(known_user_facts)

    base_style = """You are one of several friendly advisors in a group chat helping the user.
Tone: friendly, human, concise, not salesy.
Read the shared transcript and reply ONCE in your persona.
You may reference or critique other agents’ points, but keep it natural.


"""

    grounding_contract = """Grounding contract (CRITICAL):
- You must NOT invent or assume any new user preferences, constraints, or personal details.
- You may ONLY reference user details from the "Known user facts" list below.
- If something is unknown, speak conditionally ("If you want X...") or ask ONE short question.
- Do NOT speak as the user. Do NOT write first-person statements that describe the user's situation (no "I prefer...", "my space is...", etc.).
"""

    participants = f"""Participants:
- You are: {agent.name}
- Other agents: {others_str}
- User label: user
"""

    known_facts = f"""Known user facts (the ONLY user facts you can reference):
{facts_block}
"""

    if is_first_utterance:
        output_rules = f"""Output rules (FIRST MESSAGE ONLY):
- Output exactly 2 lines.
- Line 1: "Hi, I'm {agent.name}."
- Line 2: a short friendly opener that fits your character profile and the scene.
- Do not mention rules or profiles.
"""
    else:
        output_rules = """Output rules:
- Keep it concise.
- If user details are missing, keep advice conditional rather than guessing.
"""

    instructions = f"""{base_style}

[Scene]
{scene}

[{agent.name}'s character profile]
{agent.role_text}

{participants}

{known_facts}

{grounding_contract}

{output_rules}
"""
    last_bot_lines = [m for m in history if m["character"] != "user"]
    last_bot = last_bot_lines[-1]["character"] if last_bot_lines else "(none)"
    last_bot_txt = last_bot_lines[-1]["txt"] if last_bot_lines else ""
    prompt = f"""Chat transcript so far:
{transcript}

Must-do:
- Briefly respond to the most recent other-agent message from {last_bot}: "{truncate(last_bot_txt, 180)}"
- Then add your own advice.

Now write your next message as {agent.name}:"""

    text = ""
    try:
        resp = client.responses.create(
            model=model,
            instructions=instructions,
            input=prompt,
            max_output_tokens=700,
            temperature=0.7,
        )
        text = extract_text(resp)
    except Exception as e:
        if debug:
            print("DEBUG(chat_agent) failed:", agent.name, repr(e))
        text = ""

    return sanitize_single_message(text or "...", agent.name, all_agent_names)


# ----------------- Moderator: single-call MEMO + NEXT -----------------

ADMIN_ONEPASS_INSTRUCTIONS = """You are the moderator of a group chat.

Goal:
- A/B/C are friends giving advice; generally prefer bots to speak and build on each other.
- You may choose U when it is genuinely useful (ask/confirm key info, let user react, avoid spinning).
- HARD RULE: If bots_since_user >= 5 then you MUST choose U.

Soft rhythm:
- Prefer 2–4 bot turns per user turn when possible.
- Rotate A/B/C to avoid one bot dominating.
- Inter-agent comments are optional, not mandatory.

Output format (STRICT):
- First: 3–8 lines of memo (plain text).
- Last line MUST be exactly: NEXT=<A|B|C|U>
- No extra text after the NEXT line.
"""


def call_admin_onepass(
    client: OpenAI,
    model: str,
    scene: str,
    agents: List[AgentSpec],
    history: List[dict],
    known_user_facts: Dict[str, str],
    bots_since_user: int,
    last_speaker_label: str,
    consecutive_count: int,
    debug: bool = False,
) -> Tuple[Optional[Speaker], str, str]:
    # code-level hard rule (your product invariant)
    if bots_since_user >= 5:
        return "U", "Forced: bots_since_user>=5\nNEXT=U", "forced_local"

    transcript = build_transcript(history, max_turns=16)
    facts_block = facts_to_bullets(known_user_facts)
    profiles_short = "\n\n".join([f"[{a.key}/{a.name}]\n{truncate(a.role_text, 800)}" for a in agents])

    prompt = f"""bots_since_user={bots_since_user}
last_speaker={last_speaker_label}
consecutive_count={consecutive_count}

Known user facts:
{facts_block}

Scene:
{truncate(scene, 1200)}

Agent profiles:
{profiles_short}

Recent transcript:
{transcript}

Decide who should speak next."""
    raw = ""
    err = ""
    try:
        r = client.responses.create(
            model=model,
            instructions=ADMIN_ONEPASS_INSTRUCTIONS,
            input=prompt,
            max_output_tokens=450,
            temperature=0.3,
        )
        raw = extract_text(r).strip()
    except Exception as e:
        err = repr(e)
        if debug:
            print("DEBUG(admin-onepass) failed:", err)
        return None, "", err

    nxt = parse_next_token(raw)
    if nxt not in ("A", "B", "C", "U"):
        # one retry: force minimal output to rescue parsing
        try:
            r2 = client.responses.create(
                model=model,
                instructions="Output EXACTLY one line: NEXT=<A|B|C|U>",
                input=f"Choose NEXT for the next speaker. bots_since_user={bots_since_user}.",
                max_output_tokens=12,
                temperature=0.0,
            )
            raw2 = extract_text(r2).strip()
            nxt2 = parse_next_token(raw2)
            if nxt2 in ("A", "B", "C", "U"):
                return nxt2, (raw + "\n\n[RESCUED]\n" + raw2), ""
        except Exception as e:
            err = repr(e)
            if debug:
                print("DEBUG(admin-rescue) failed:", err)

        return None, raw, "parse_failed"

    return nxt, raw, ""


# ----------------- fallback -----------------

def make_fallback_queue_4bots_then_user() -> List[Speaker]:
    perm = random.sample(["A", "B", "C"], 3)
    extra = random.choice(perm[:2])  # not the last one
    return [perm[0], perm[1], perm[2], extra, "U"]


# ----------------- main -----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="scene.txt")
    ap.add_argument("--bot1", default="chatbot1.txt")
    ap.add_argument("--bot2", default="chatbot2.txt")
    ap.add_argument("--bot3", default="chatbot3.txt")

    ap.add_argument("--nameA", default="ChatbotA")
    ap.add_argument("--nameB", default="ChatbotB")
    ap.add_argument("--nameC", default="ChatbotC")

    ap.add_argument("--model_chat", default="gpt-4o")
    ap.add_argument("--model_admin", default="gpt-4o")

    ap.add_argument("--preset", default="ABCU", help='First turns order, e.g. "ABCU" (can be shorter)')
    ap.add_argument("--logdir", default="logs")
    ap.add_argument("--debug", action="store_true")

    args = ap.parse_args()

    scene = read_text(args.scene)
    bot1 = read_text(args.bot1) if os.path.exists(args.bot1) else ""
    bot2 = read_text(args.bot2) if os.path.exists(args.bot2) else ""
    bot3 = read_text(args.bot3) if os.path.exists(args.bot3) else ""

    agents: Dict[str, AgentSpec] = {
        "A": AgentSpec("A", args.nameA, bot1),
        "B": AgentSpec("B", args.nameB, bot2),
        "C": AgentSpec("C", args.nameC, bot3),
    }
    agent_list = [agents["A"], agents["B"], agents["C"]]
    all_agent_names = [a.name for a in agent_list]
    has_spoken: Dict[str, bool] = {"A": False, "B": False, "C": False}

    ensure_dir(args.logdir)
    room_id = make_room_id_6()
    chat_log_path = os.path.join(args.logdir, f"{room_id}.jsonl")
    thinking_log_path = os.path.join(args.logdir, f"{room_id}_thinkinglog.jsonl")

    client_chat = OpenAI(api_key="sk-tnIxDvUFzbMtFbnGpiLC5FXqep9dRMRdsdvUWs2g9hT3BlbkFJmfl6UE3khKvUqT_xeZpq66twaUika-kvxbrc-srSQA")
    client_admin = OpenAI(api_key="sk-tnIxDvUFzbMtFbnGpiLC5FXqep9dRMRdsdvUWs2g9hT3BlbkFJmfl6UE3khKvUqT_xeZpq66twaUika-kvxbrc-srSQA")

    history: List[dict] = []
    known_user_facts: Dict[str, str] = {}

    bots_since_user = 0
    turn_idx = 0
    fallback_queue: List[Speaker] = []

    last_speaker_label: str = ""
    consecutive_count: int = 0

    # persist last admin failure info so fallback rows also show it
    last_admin_raw = ""
    last_admin_err = ""

    print(f"[chat_room_id={room_id}] Log file: {chat_log_path}")
    print(f"[chat_room_id={room_id}] Thinking log: {thinking_log_path}")
    print('Type /quit to exit. When forced to speak, user can type ">>>" to skip and reset the counter (not logged).')
    print("-" * 60)

    with open(chat_log_path, "a", encoding="utf-8") as chat_fp, open(thinking_log_path, "a", encoding="utf-8") as think_fp:
        while True:
            mode = ""
            thinking = ""
            admin_raw = ""
            admin_err = ""

            # Decide next speaker
            if fallback_queue:
                speaker = fallback_queue.pop(0)
                mode = "fallback"
                thinking = f"Fallback sequence running. Next={speaker}."
                admin_raw = last_admin_raw
                admin_err = last_admin_err
                if bots_since_user >= 5:
                    speaker = "U"
                    fallback_queue.clear()
                    mode = "forced"
                    thinking = "Forced user turn (bots_since_user >= 5); cleared fallback queue."

            elif bots_since_user >= 5:
                speaker = "U"
                mode = "forced"
                thinking = "Forced user turn (bots_since_user >= 5)."

            elif turn_idx < len(args.preset):
                speaker = args.preset[turn_idx].upper()
                if speaker not in ("A", "B", "C", "U"):
                    speaker = "U"
                mode = "preset"
                thinking = f"Preset turn order applied. Next={speaker}."

            else:
                nxt, raw, err = call_admin_onepass(
                    client=client_admin,
                    model=args.model_admin,
                    scene=scene,
                    agents=agent_list,
                    history=history,
                    known_user_facts=known_user_facts,
                    bots_since_user=bots_since_user,
                    last_speaker_label=last_speaker_label or "(none)",
                    consecutive_count=consecutive_count,
                    debug=args.debug,
                )
                admin_raw = raw
                admin_err = err

                if nxt is None:
                    last_admin_raw = raw
                    last_admin_err = err or "admin_failed"
                    fallback_queue = make_fallback_queue_4bots_then_user()
                    speaker = fallback_queue.pop(0)
                    mode = "fallback_start"
                    thinking = f"Admin failed; starting fallback: {[speaker] + fallback_queue}."
                else:
                    last_admin_raw = raw
                    last_admin_err = ""
                    speaker = nxt
                    mode = "admin"
                    # first line as short thinking
                    first = raw.splitlines()[0].strip() if raw.strip() else ""
                    thinking = first or f"Admin chose Next={speaker}."

            append_jsonl(
                think_fp,
                {
                    "chat_room_id": room_id,
                    "time": now_local_iso(),
                    "mode": mode,
                    "bots_since_user": bots_since_user,
                    "next": speaker,
                    "thinking": thinking,
                    "admin_raw": admin_raw,
                    "admin_err": admin_err,
                    "known_user_facts": list(known_user_facts.values()),
                },
            )

            # User turn
            if speaker == "U":
                user_in = input("You: ").rstrip("\n")
                if user_in.strip() == "/quit":
                    print("Bye.")
                    break

                if user_in.strip() == ">>>":
                    bots_since_user = 0
                    print("[Skipped user turn; bots_since_user reset]")
                    continue

                known_user_facts = update_user_facts(known_user_facts, user_in)

                msg = {
                    "chat_room_id": room_id,
                    "time": now_local_iso(),
                    "character": "user",
                    "txt": user_in,
                }
                append_jsonl(chat_fp, msg)
                history.append(msg)

                if last_speaker_label == "user":
                    consecutive_count += 1
                else:
                    last_speaker_label = "user"
                    consecutive_count = 1

                bots_since_user = 0
                turn_idx += 1
                continue

            # Bot turn
            agent = agents[speaker]
            txt = call_chat_agent(
                client=client_chat,
                model=args.model_chat,
                scene=scene,
                agent=agent,
                history=history,
                known_user_facts=known_user_facts,
                is_first_utterance=not any(
                    m["character"] == agent.name for m in history
                ),
                all_agent_names=all_agent_names,
                debug=args.debug,
            )

            print(f"{agent.name}: {txt}")

            msg = {
                "chat_room_id": room_id,
                "time": now_local_iso(),
                "character": agent.name,
                "txt": txt,
            }
            append_jsonl(chat_fp, msg)
            history.append(msg)

            if last_speaker_label == agent.name:
                consecutive_count += 1
            else:
                last_speaker_label = agent.name
                consecutive_count = 1

            has_spoken[speaker] = True
            bots_since_user += 1
            turn_idx += 1


if __name__ == "__main__":
    main()
