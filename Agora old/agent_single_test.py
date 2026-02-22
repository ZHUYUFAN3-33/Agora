import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Literal, Optional

from zoneinfo import ZoneInfo
from openai import OpenAI

SCENE_FILE = "scene.txt"
AGENT_RULE_FILE = "chatbot2.txt"

MODEL_NAME = "gpt-5-nano"
AGENT_DISPLAY_NAME = "Blake"

TZ = ZoneInfo("Asia/Tokyo")


def now_local_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def extract_text(resp) -> str:
    """Robustly extract visible text from a Responses API result."""
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


def history_as_transcript(history: List[dict]) -> str:
    # history items: {"character": "...", "txt": "..."}
    return "\n".join(f"{m['character']}: {m['txt']}" for m in history)


@dataclass
class AgentSpec:
    key: Literal["A"]
    name: str
    role_text: str


def call_chat_agent(
    client: OpenAI,
    model: str,
    scene: str,
    agent: AgentSpec,
    history: List[dict],
    is_first_utterance: bool,
    debug: bool = False,
) -> str:
    transcript = history_as_transcript(history)

    if is_first_utterance:
        output_rules = f"""Output requirements (FIRST UTTERANCE ONLY):
- Output EXACTLY two lines.
- Line 1: a brief name introduction ONLY, like: "Hi, I'm {agent.name}."
-- Line 2: a casual, human opening remark that asks ONE simple question or sets the tone.
- Do NOT list multiple criteria or options.
- Sound like a real friend, not a system or salesperson.
- Do NOT mention or quote your profile text. Do NOT list rules. Do NOT speak for other characters. No stage directions.
- Keep line 2 concise (1–3 sentences).
- The opening should express excitement about timing and collaboration ("looking together"),
  not sound like a questionnaire or task briefing.
"""
        prompt = f"""[Chat transcript so far]
{transcript if transcript else "(none)"}

It is your first time speaking. Follow the FIRST UTTERANCE format now."""
    else:
        output_rules = """Output requirements:
- Output ONLY your single message for this turn (no name prefix).
- Do NOT speak for other characters. No stage directions. No rule explanations.
- Keep it natural and consistent with your profile.
"""
        prompt = f"""[Chat transcript so far]
{transcript if transcript else "(none)"}

Now it's your turn to speak. Write your message:"""

    instructions = f"""You are participating in a roleplay chat as a single agent.

[Shared scene / pinned reference]
{scene}

[Your identity]
Codename: {agent.key}
Display name: {agent.name}

[Your character profile]
{agent.role_text}

{output_rules}
"""

    resp = client.responses.create(
        model=model,
        instructions=instructions,
        input=prompt,
        reasoning={"effort": "low"},
        max_output_tokens=512,
    )
    text = extract_text(resp).strip()

    if debug:
        try:
            print("DEBUG(bot)", agent.name, "status:", resp.status, "incomplete:", resp.incomplete_details, "usage:", resp.usage)
        except Exception:
            pass

    # Retry once if empty
    if not text:
        resp2 = client.responses.create(
            model=model,
            instructions=instructions,
            input=prompt,
            reasoning={"effort": "low"},
            max_output_tokens=1024,
        )
        text = extract_text(resp2).strip()

        if debug:
            try:
                print("DEBUG(bot-retry)", agent.name, "status:", resp2.status, "incomplete:", resp2.incomplete_details, "usage:", resp2.usage)
            except Exception:
                pass

    if not text:
        return f"Hi, I'm {agent.name}.\nTell me what you’ll use the computer for and what budget pressure you have—then I’ll help."

    return text


def main():
    client = OpenAI(api_key="sk-tnIxDvUFzbMtFbnGpiLC5FXqep9dRMRdsdvUWs2g9hT3BlbkFJmfl6UE3khKvUqT_xeZpq66twaUika-kvxbrc-srSQA")

    scene = read_text(SCENE_FILE)
    bot_profile = read_text(AGENT_RULE_FILE)

    agent = AgentSpec(
        key="A",
        name=AGENT_DISPLAY_NAME,
        role_text=bot_profile
    )

    history: List[dict] = []
    has_spoken = False

    print("Single-agent test (hard-coded config). Type /quit to exit.")
    print("-" * 60)

    while True:
        user_in = input("You: ").rstrip("\n")
        if user_in.strip() == "/quit":
            print("Bye.")
            break

        history.append({"time": now_local_iso(), "character": "user", "txt": user_in})

        txt = call_chat_agent(
            client=client,
            model=MODEL_NAME,
            scene=scene,
            agent=agent,
            history=history,
            is_first_utterance=(not has_spoken),
            debug=False,
        )

        print(f"{agent.name}: {txt}")
        history.append({"time": now_local_iso(), "character": agent.name, "txt": txt})
        has_spoken = True


if __name__ == "__main__":
    main()
