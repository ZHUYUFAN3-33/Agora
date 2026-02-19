"""
emotion.py
Interactive emotion router (keyword + sliders)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import math
import os
import re


EMOTIONS = ["anger", "disgust", "fear", "joy", "sadness", "surprise"]
DEFAULT_PROMPT_DIR = "prompts"


# =============================
# Example utterances
# =============================
EMOTION_EXAMPLES = {
    "anger": [
        "No. That’s not the right move.",
        "Stop hesitating and act.",
        "This is inefficient—fix it now.",
        "You already know what needs to happen.",
        "Act. Don’t overthink it."
    ],
    "disgust": [
        "That doesn’t feel right.",
        "I wouldn’t go near that.",
        "This feels off.",
        "Let’s not entertain that.",
        "No. Drop it."
    ],
    "fear": [
        "I’m not fully comfortable with that yet.",
        "What if this goes wrong?",
        "Maybe we should double-check first.",
        "There’s uncertainty here.",
        "Can we reduce the risk?"
    ],
    "joy": [
        "Nice! I love that direction.",
        "This could turn out really well.",
        "Awesome—let’s build on that.",
        "That sounds exciting.",
        "Yes! That’s the energy."
    ],
    "sadness": [
        "That feels heavy…",
        "Let’s slow down.",
        "We don’t need to rush.",
        "One small step at a time.",
        "It’s okay to move gently."
    ],
    "surprise": [
        "Wait—really?",
        "That wasn’t expected.",
        "Wow, that changes things.",
        "Interesting twist.",
        "Okay, that’s new."
    ],
}


# =============================
# Keyword scoring
# =============================
_KEYWORDS = {
    "anger": ["angry", "mad", "生气", "火大", "恼火"],
    "disgust": ["恶心", "反感", "gross", "disgust"],
    "fear": ["担心", "害怕", "焦虑", "worried", "afraid"],
    "joy": ["开心", "兴奋", "happy", "excited"],
    "sadness": ["难过", "低落", "sad", "depressed"],
    "surprise": ["惊讶", "震惊", "wow", "unexpected"],
}


def _tokenize(text: str) -> List[str]:
    text = text.lower()
    return re.findall(r"[a-z']+|[\u4e00-\u9fff]+", text)


def emotion_probs_from_text(text: str) -> Dict[str, float]:
    scores = {e: 0.1 for e in EMOTIONS}
    tokens = _tokenize(text)
    joined = " ".join(tokens)

    for e, kws in _KEYWORDS.items():
        for kw in kws:
            if kw in joined:
                scores[e] += 1.0

    total = sum(scores.values())
    return {e: scores[e] / total for e in EMOTIONS}


# =============================
# Slider prior
# =============================
EMOTION_CENTROIDS = {
    "joy": (0.85, 0.65, 0.55),
    "sadness": (0.15, 0.20, 0.20),
    "anger": (0.10, 0.90, 0.85),
    "fear": (0.10, 0.85, 0.15),
    "disgust": (0.10, 0.55, 0.65),
    "surprise": (0.50, 0.90, 0.45),
}


def _gauss(x, mu, s=0.18):
    return math.exp(-0.5 * ((x - mu) / s) ** 2)


def emotion_probs_from_sliders(v, a, c):
    raw = {}
    for e, (mv, ma, mc) in EMOTION_CENTROIDS.items():
        raw[e] = _gauss(v, mv) * _gauss(a, ma) * _gauss(c, mc)
    total = sum(raw.values())
    return {e: raw[e] / total for e in EMOTIONS}


def fuse(p_text, p_slider, alpha=0.45):
    fused = {}
    for e in EMOTIONS:
        fused[e] = (p_text[e] ** (1 - alpha)) * (p_slider[e] ** alpha)
    total = sum(fused.values())
    return {e: fused[e] / total for e in EMOTIONS}


# =============================
# Prompt loader
# =============================
def load_prompt(emotion_tag):
    path = os.path.join(DEFAULT_PROMPT_DIR, f"{emotion_tag}.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# =============================
# Interactive CLI
# =============================
if __name__ == "__main__":

    print("=== Emotion Router Interactive Mode ===\n")

    text = input("Enter your text: ")

    valence = float(input("Valence (0-1): "))
    arousal = float(input("Arousal (0-1): "))
    control = float(input("Control (0-1): "))

    p_text = emotion_probs_from_text(text)
    p_slider = emotion_probs_from_sliders(valence, arousal, control)
    p_final = fuse(p_text, p_slider)

    emotion_tag = max(p_final.items(), key=lambda x: x[1])[0]
    confidence = p_final[emotion_tag]

    print("\n========== RESULT ==========")
    print("Emotion Tag:", emotion_tag)
    print("Confidence:", round(confidence, 4))

    print("\n--- p_text ---")
    print(p_text)

    print("\n--- p_slider ---")
    print(p_slider)

    print("\n--- p_final ---")
    print(p_final)

    print("\n--- Loaded Prompt ---")
    print(load_prompt(emotion_tag))

    print("\n--- Example Utterances ---")
    for line in EMOTION_EXAMPLES[emotion_tag]:
        print("-", line)

    print("\n============================")
