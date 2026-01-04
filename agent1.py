# run_agent1.py
# One-file runnable Agent 1 (auto install + embedded API key)

import sys
import subprocess
import json
from pathlib import Path
import os

# ============================================================
# 0. AUTO-INSTALL DEPENDENCY
# ============================================================
def ensure_package(pkg_name):
    try:
        __import__(pkg_name)
    except ImportError:
        print(f"[INFO] Installing missing package: {pkg_name}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])

ensure_package("openai")

from openai import OpenAI

# ============================================================
# 1. API KEY (EDIT THIS LINE ONLY)
# ============================================================
OPENAI_API_KEY = "sk-tnIxDvUFzbMtFbnGpiLC5FXqep9dRMRdsdvUWs2g9hT3BlbkFJmfl6UE3khKvUqT_xeZpq66twaUika-kvxbrc-srSQA"  # <<< replace with your real key
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# ============================================================
# 2. LOAD FILES
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
RULES_FILE = BASE_DIR / "chatbot4.txt"
ENV_FILE = BASE_DIR / "env_context.json"

def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

# ============================================================
# 3. BUILD ENVIRONMENT CONTEXT BLOCK
# ============================================================
def build_env_block(env: dict) -> str:
    pr0, pr1 = env["price_range_usd"]
    cats = ", ".join(env["allowed_categories"])

    bp = env["brand_pool"]
    office = ", ".join(bp["office_laptops"])
    gaming = ", ".join(bp["gaming_laptops"])
    desktops = ", ".join(bp["desktops"])

    rules = "\n  - ".join(env.get("pricing_behavior_rules", []))

    return f"""
[ENVIRONMENT CONTEXT — READ ONLY]
- Valid budget range (USD): {pr0}–{pr1}
- GPU upper limit: {env["gpu_upper_limit"]}
- Allowed categories: {cats}
- Brand examples (use sparingly; max 1 per reply):
  • Office: {office}
  • Gaming: {gaming}
  • Desktops: {desktops}
- Pricing behavior rules:
  - {rules}
[END ENVIRONMENT CONTEXT]
""".strip()

# ============================================================
# 4. MAIN CHAT LOOP
# ============================================================
def main():
    if OPENAI_API_KEY == "YOUR_API_KEY_HERE":
        raise RuntimeError("Please set your OpenAI API key inside run_agent1.py")

    agent_rules = load_text(RULES_FILE)
    env = load_json(ENV_FILE)
    env_block = build_env_block(env)

    # System prompt = environment + 11-rule agent personality
    system_prompt = f"{env_block}\n\n{agent_rules}"

    client = OpenAI()
    model = "gpt-5.2"  # change if needed

    messages = [{"role": "system", "content": system_prompt}]

    print("\nAgent 1 (Excitable & Impatient Friend) is ready.")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Exiting.")
            break

        messages.append({"role": "user", "content": user_input})

        response = client.responses.create(
            model=model,
            input=messages
        )

        reply = response.output_text.strip()
        print(f"\nAgent 1: {reply}\n")

        messages.append({"role": "assistant", "content": reply})

# ============================================================
# 5. ENTRY POINT
# ============================================================
if __name__ == "__main__":
    main()
