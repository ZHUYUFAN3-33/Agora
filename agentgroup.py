# run_group_chat.py
# Multi-agent group chat: 3 agents with separate system prompts + shared transcript.
# One command to run:
#   python run_group_chat.py
#
# Commands inside chat:
#   /history   -> print full transcript
#   /save      -> save transcript to chat_log.txt
#   /exit      -> quit

import sys
import subprocess
import json
import os
from pathlib import Path
from datetime import datetime

# =========================
# 0) AUTO-INSTALL DEPENDENCY
# =========================
def ensure_package(pkg_name: str):
    try:
        __import__(pkg_name)
    except ImportError:
        print(f"[INFO] Installing missing package: {pkg_name}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])

ensure_package("openai")
from openai import OpenAI

# =========================
# 1) API KEY (EDIT THIS)
# =========================
OPENAI_API_KEY = "sk-tnIxDvUFzbMtFbnGpiLC5FXqep9dRMRdsdvUWs2g9hT3BlbkFJmfl6UE3khKvUqT_xeZpq66twaUika-kvxbrc-srSQA"  # <<< replace with your real key
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# =========================
# 2) PATHS
# =========================
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "env_context.json"
A1_RULES = BASE_DIR / "chatbot1.txt"
A2_RULES = BASE_DIR / "chatbot2.txt"
A3_RULES = BASE_DIR / "chatbot3.txt"

# =========================
# 3) LOADERS
# =========================
def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

# =========================
# 4) ENV BLOCK (shared)
# =========================
def build_env_block(env: dict) -> str:
    pr0, pr1 = env["price_range_usd"]
    cats = ", ".join(env["allowed_categories"])

    bp = env.get("brand_pool", {})
    def join_list(k): return ", ".join(bp.get(k, []))

    rules = "\n  - ".join(env.get("pricing_behavior_rules", [])) or "(none)"

    return f"""
[ENVIRONMENT CONTEXT — READ ONLY]
- Valid budget range (USD): {pr0}–{pr1}
- GPU upper limit: {env["gpu_upper_limit"]}
- Allowed categories: {cats}
- Brand pool examples (use sparingly; max 1 brand/model per reply):
  • Office: {join_list("office_laptops")}
  • Gaming: {join_list("gaming_laptops")}
  • Workstations: {join_list("workstations")}
  • Desktops: {join_list("desktops")}
  • Budget/Compact: {join_list("budget_compact")}
- Pricing behavior rules:
  - {rules}
[END ENVIRONMENT CONTEXT]
""".strip()

# =========================
# 5) AGENT WRAPPER
# =========================
AGENTS = {
    "A1": {"name": "Agent 1 (Excitable)", "rules_file": A1_RULES},
    "A2": {"name": "Agent 2 (Calm)",      "rules_file": A2_RULES},
    "A3": {"name": "Agent 3 (Negative)",  "rules_file": A3_RULES},
}

def build_system_prompt(env_block: str, agent_rules: str) -> str:
    # env_block first = hard boundaries; agent_rules second = personality and behavior
    return f"{env_block}\n\n{agent_rules}".strip()

def format_transcript_for_agents(transcript: list[str], max_lines: int = 40) -> str:
    # Provide only recent lines to control context; you can increase max_lines if needed.
    recent = transcript[-max_lines:] if len(transcript) > max_lines else transcript
    return "\n".join(recent)

def call_agent(
    client: OpenAI,
    model: str,
    system_prompt: str,
    transcript_text: str,
    agent_id: str,
    mode: str,
) -> str:
    """
    mode:
      - "main": must respond with 1 short message.
      - "followup": respond ONLY if you have something new; otherwise output <NO_FOLLOWUP>.
    """
    if mode == "main":
        user_instruction = f"""
You are {agent_id}. This is a live group chat with other agents and the user.
Read the shared transcript and reply ONCE in your persona.
You may reference or critique other agents’ points, but keep it natural.

SHARED TRANSCRIPT (most recent):
{transcript_text}

Now reply with ONE message.
""".strip()
    else:
        user_instruction = f"""
You are {agent_id}. This is a live group chat.
Only add a FOLLOW-UP message if you have something meaningfully new to add
(e.g., reacting to another agent, asking a key missing question, or correcting something).
If you have nothing new, output exactly: <NO_FOLLOWUP>

SHARED TRANSCRIPT (most recent):
{transcript_text}

Now decide whether to follow up.
""".strip()

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_instruction},
        ],
    )
    return resp.output_text.strip()

# =========================
# 6) MAIN LOOP
# =========================
def main():
    if OPENAI_API_KEY == "YOUR_API_KEY_HERE":
        raise RuntimeError("Please set your OpenAI API key inside run_group_chat.py")

    env = load_json(ENV_FILE)
    env_block = build_env_block(env)

    agent_system_prompts = {}
    for aid, meta in AGENTS.items():
        rules = load_text(meta["rules_file"])
        agent_system_prompts[aid] = build_system_prompt(env_block, rules)

    client = OpenAI()
    model = "gpt-5.2"  # change if needed

    transcript: list[str] = []
    transcript.append(f"[System] Group chat started at {datetime.now().isoformat(timespec='seconds')}")

    print("\nMulti-Agent Group Chat ready.")
    print("Commands: /history  /save  /exit\n")

    while True:
        user_text = input("User: ").strip()
        if not user_text:
            continue

        if user_text.lower() in {"/exit", "exit", "quit", "/quit"}:
            print("Exiting.")
            break

        if user_text.lower() == "/history":
            print("\n===== FULL TRANSCRIPT =====")
            print("\n".join(transcript))
            print("===========================\n")
            continue

        if user_text.lower() == "/save":
            out = BASE_DIR / "chat_log.txt"
            out.write_text("\n".join(transcript), encoding="utf-8")
            print(f"[Saved] {out}")
            continue

        transcript.append(f"[User] {user_text}")

        # -------- Round 1: each agent speaks once --------
        for aid in ["A1", "A2", "A3"]:
            ttxt = format_transcript_for_agents(transcript, max_lines=50)
            reply = call_agent(
                client=client,
                model=model,
                system_prompt=agent_system_prompts[aid],
                transcript_text=ttxt,
                agent_id=AGENTS[aid]["name"],
                mode="main",
            )
            transcript.append(f"[{AGENTS[aid]['name']}] {reply}")
            print(f"\n{AGENTS[aid]['name']}: {reply}")

        # -------- Round 2: optional follow-ups (each agent may speak or skip) --------
        for aid in ["A1", "A2", "A3"]:
            ttxt = format_transcript_for_agents(transcript, max_lines=60)
            follow = call_agent(
                client=client,
                model=model,
                system_prompt=agent_system_prompts[aid],
                transcript_text=ttxt,
                agent_id=AGENTS[aid]["name"],
                mode="followup",
            )
            if follow.strip() and follow.strip() != "<NO_FOLLOWUP>":
                transcript.append(f"[{AGENTS[aid]['name']}] {follow}")
                print(f"\n{AGENTS[aid]['name']} (follow-up): {follow}")

        print("")  # spacing between user turns

if __name__ == "__main__":
    main()
