

from __future__ import annotations

from typing import Dict, List, Optional
import math
import os
import re


# =============================
# Paths (folders are next to this .py file)
# =============================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EMOTION_DIR = os.path.join(SCRIPT_DIR, "emotion block")
DECISION_DIR = os.path.join(SCRIPT_DIR, "decision block")


# =============================
# Emotion setup
# =============================
EMOTIONS = ["anger", "disgust", "fear", "joy", "sadness", "surprise"]

EMOTION_EXAMPLES = {
    "anger": [
        "This is inefficient—fix it now.",
        "Stop circling. Make the call.",
        "We need clarity. Now.",
    ],
    "disgust": [
        "That doesn’t sit right.",
        "This feels off—red flag.",
        "I can’t support that.",
    ],
    "fear": [
        "This could be risky—what’s the downside?",
        "I’m not fully comfortable yet.",
        "Let’s double-check.",
    ],
    "joy": [
        "This has real potential.",
        "That’s exciting—great direction.",
        "Let’s build on this momentum.",
    ],
    "sadness": [
        "This feels heavy.",
        "We should think about the impact.",
        "Let’s move gently.",
    ],
    "surprise": [
        "Wait—that changes things.",
        "I didn’t expect that.",
        "Hold on—what does that imply?",
    ],
}

# -----------------------------
# Keyword design (English-only)
# -----------------------------
# Strong keywords = near-decisive evidence
_STRONG_KEYWORDS: Dict[str, List[str]] = {
    "anger": [
        "furious", "enraged", "livid", "outraged", "seething", "rage", "pissed",
        "i can't stand this", "this is unacceptable",
    ],
    "disgust": [
        "repulsed", "revolted", "nauseated", "sickened",
        "disgusting", "grossed out", "makes me sick",
    ],
    "fear": [
        "terrified", "panicking", "panic", "horrified", "dread", "scared to death",
        "i'm scared", "i am scared", "i'm terrified", "i am terrified",
    ],
    "joy": [
        "ecstatic", "euphoric", "overjoyed", "thrilled", "delighted",
        "this is amazing", "i love this",
    ],
    "sadness": [
        "devastated", "heartbroken", "hopeless", "miserable", "depressed",
        "i can't stop crying", "i feel empty",
    ],
    "surprise": [
        "shocked", "stunned", "astounded", "speechless",
        "no way", "i didn't see that coming",
    ],
}

# Weak keywords = supportive evidence
_KEYWORDS: Dict[str, List[str]] = {
    "anger": [
        "angry", "mad", "annoyed", "irritated", "frustrated", "upset",
        "fed up", "resentful",
    ],
    "disgust": [
        "disgust", "gross", "ew", "icky", "unpleasant", "off-putting",
        "creepy", "weird in a bad way",
    ],
    "fear": [
        "afraid", "scared", "worried", "anxious", "nervous", "uneasy",
        "concerned", "uncertain",
    ],
    "joy": [
        "happy", "excited", "glad", "proud", "grateful", "hopeful",
        "satisfied", "content",
    ],
    "sadness": [
        "sad", "down", "low", "lonely", "guilty", "ashamed",
        "disappointed", "regret",
    ],
    "surprise": [
        "surprised", "unexpected", "wow", "wait", "huh", "interesting",
        "didn't expect", "did not expect",
    ],
}

# Valence-Arousal-Control centroids (keep your original mapping)
EMOTION_CENTROIDS = {
    "joy": (0.85, 0.65, 0.55),
    "sadness": (0.15, 0.20, 0.20),
    "anger": (0.10, 0.90, 0.85),
    "fear": (0.10, 0.85, 0.15),
    "disgust": (0.10, 0.55, 0.65),
    "surprise": (0.50, 0.90, 0.45),
}


# -----------------------------
# Probabilistic helpers
# -----------------------------
def _softmax(logits: Dict[str, float], temperature: float = 1.0) -> Dict[str, float]:
    mx = max(logits.values())
    exps = {k: math.exp((v - mx) / max(1e-6, temperature)) for k, v in logits.items()}
    s = sum(exps.values())
    return {k: exps[k] / s for k in exps}


def _entropy(p: Dict[str, float]) -> float:
    return -sum(v * math.log(max(v, 1e-12)) for v in p.values())


def _normalized_entropy(p: Dict[str, float]) -> float:
    # 0 = confident (peaky), 1 = uncertain (flat)
    h = _entropy(p)
    hmax = math.log(len(p))
    return min(1.0, max(0.0, h / max(1e-12, hmax)))


# -----------------------------
# Tokenizer (English only)
# -----------------------------
def _tokenize(text: str) -> List[str]:
    """
    English-only tokenizer with clean word boundaries.
    Supports contractions like "don't".
    """
    text = text.lower()
    return re.findall(r"[a-z]+(?:'[a-z]+)?", text)


def emotion_probs_from_text(text: str) -> Optional[Dict[str, float]]:
    """
    Keyword-dominant emotion inference from English text.
    - Returns None if text is missing/empty (non-mandatory input).
    - Strong keywords dominate weak keywords.
    - Softmax with lower temperature when strong evidence exists.
    """
    if text is None or str(text).strip() == "":
        return None

    lowered = text.lower()
    tokens = _tokenize(text)

    # Baseline logits: negative so no-signal stays relatively flat
    logits = {e: -1.0 for e in EMOTIONS}

    # light linguistic modifiers
    intensifiers = {"very": 0.5, "really": 0.4, "extremely": 0.7, "so": 0.3, "super": 0.4}
    negators = {"not", "never", "no", "hardly", "barely"}

    intensity_bonus = sum(intensifiers[w] for w in tokens if w in intensifiers)
    has_neg = any(w in negators for w in tokens)

    max_hit_score = 0.0

    for e in EMOTIONS:
        weak_hit = 0.0
        strong_hit = 0.0

        # weak keywords
        for kw in _KEYWORDS.get(e, []):
            kw_l = kw.lower()
            if " " in kw_l:
                if kw_l in lowered:
                    weak_hit += 1.0
            else:
                if kw_l in tokens:
                    weak_hit += 1.0

        # strong keywords
        for kw in _STRONG_KEYWORDS.get(e, []):
            kw_l = kw.lower()
            if " " in kw_l:
                if kw_l in lowered:
                    strong_hit += 1.0
            else:
                if kw_l in tokens:
                    strong_hit += 1.0

        # Keyword-dominant scoring (high weights)
        score = 3.0 * weak_hit + 7.0 * strong_hit + intensity_bonus

        # Negation dampens but does not completely erase strong hits
        if has_neg:
            score -= 0.8

        logits[e] += score
        max_hit_score = max(max_hit_score, score)

    # Make distribution sharp if strong evidence exists
    if max_hit_score >= 7.0:       # e.g., at least one strong keyword
        temperature = 0.40
    elif max_hit_score >= 3.0:     # e.g., at least one weak keyword
        temperature = 0.55
    else:
        temperature = 1.00

    return _softmax(logits, temperature=temperature)


def _gauss(x, mu, s=0.18) -> float:
    return math.exp(-0.5 * ((x - mu) / s) ** 2)


def emotion_probs_from_sliders(v: Optional[float], a: Optional[float], c: Optional[float]) -> Optional[Dict[str, float]]:
    """
    Slider-based emotion mapping using Gaussian similarity to centroids.
    - Returns None if any slider is missing (non-mandatory input).
    """
    if v is None or a is None or c is None:
        return None

    raw: Dict[str, float] = {}
    for e, (mv, ma, mc) in EMOTION_CENTROIDS.items():
        raw[e] = _gauss(v, mv) * _gauss(a, ma) * _gauss(c, mc)

    total = sum(raw.values())
    if total < 1e-12:
        # degenerate numeric fallback (should be rare)
        return {e: 1.0 / len(EMOTIONS) for e in EMOTIONS}

    return {e: raw[e] / total for e in EMOTIONS}


def fuse(p_text: Optional[Dict[str, float]], p_slider: Optional[Dict[str, float]], text: str) -> Dict[str, float]:
    """
    Fusion rule:
    - text and sliders are BOTH optional
    - If BOTH missing -> hard error (as requested)
    - If only one exists -> return it
    - If both exist -> adaptive fusion:
        * If text is confident (peaky due to keyword hits), suppress slider strongly
        * If text is short/uncertain, allow slider more influence
    """
    if p_text is None and p_slider is None:
        raise ValueError("Emotion selection error: both text input and slider input are missing.")

    if p_text is None:
        return p_slider  # type: ignore[return-value]
    if p_slider is None:
        return p_text

    tokens = _tokenize(text or "")
    text_len = len(tokens)

    text_uncertainty = _normalized_entropy(p_text)     # 0 confident, 1 uncertain
    slider_uncertainty = _normalized_entropy(p_slider)

    # Baseline slightly text-favoring (keyword should dominate)
    alpha = 0.45  # slider weight

    # Short text: allow slider ONLY if text is uncertain
    if text_len <= 3:
        alpha += 0.10 * text_uncertainty

    # KEY: confident text (low entropy) => suppress slider aggressively
    alpha -= 0.55 * (1.0 - text_uncertainty)

    # Slider uncertain => suppress it
    alpha -= 0.15 * slider_uncertainty

    # clamp slider weight
    alpha = min(0.65, max(0.05, alpha))

    fused: Dict[str, float] = {}
    for e in EMOTIONS:
        fused[e] = math.exp(
            (1 - alpha) * math.log(max(p_text[e], 1e-12)) +
            alpha * math.log(max(p_slider[e], 1e-12))
        )

    s = sum(fused.values())
    return {e: fused[e] / s for e in EMOTIONS}


def load_emotion_prompt(emotion_tag: str) -> str:
    path = os.path.join(EMOTION_DIR, f"{emotion_tag}.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# =============================
# Decision setup
# =============================
DECISIONS = ["Rational", "Intuitive", "Dependent", "Avoidant", "Spontaneous"]

DECISION_DESCRIPTIONS = {
    "Rational": "Structured comparison: define objective → compare options across criteria → show trade-offs → conclude.",
    "Intuitive": "Fit-driven judgment: anchor to context → pick what feels aligned → light justification.",
    "Dependent": "Guided support: validate uncertainty → narrow to 1–2 paths → reference norms → recommend.",
    "Avoidant": "Complexity reduction: simplify → at most two paths → emphasize reversibility → low-risk step.",
    "Spontaneous": "Fast action: choose a direction quickly → minimal deliberation → immediate next step.",
}

DECISION_REPLY_EXAMPLES = {
    "Rational": [
        "Objective: choose the best option for X.",
        "Criteria: cost, risk, long-term value.",
        "Trade-off: A is cheaper, B is safer.",
        "Conclusion: pick B.",
    ],
    "Intuitive": [
        "Given your situation, B feels more aligned.",
        "It fits what you actually need right now.",
        "Go with B.",
    ],
    "Dependent": [
        "This is a tough call—it’s normal to be unsure.",
        "Between A and B, B is the safer default.",
        "I’d lean B.",
    ],
    "Avoidant": [
        "Let’s keep it simple: either do a small step now or pause.",
        "Both are reversible.",
        "Start with the low-risk step.",
    ],
    "Spontaneous": [
        "Pick B.",
        "It moves you forward immediately.",
        "Do it now, adjust later.",
    ],
}


def load_decision_prompt(decision_name: str) -> str:
    # Your files are: Rational.txt, Intuitive.txt, Dependent.txt, Avoidant.txt, Spontaneous.txt
    path = os.path.join(DECISION_DIR, f"{decision_name}.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# =============================
# Agent assembly
# =============================
def assemble_agent_txt(decision_name: str, emotion_tag: str, decision_prompt: str, emotion_prompt: str) -> str:
    return (
        "============================\n"
        "AGENT CONFIGURATION\n"
        "============================\n\n"
        f"[Selected Decision Block]\n{decision_name}\n\n"
        f"[Selected Emotion Block]\n{emotion_tag}\n\n"
        "----------------------------\n"
        "DECISION BLOCK\n"
        "----------------------------\n"
        f"{decision_prompt}\n\n"
        "----------------------------\n"
        "EMOTION BLOCK\n"
        "----------------------------\n"
        f"{emotion_prompt}\n"
    )


def _input_float(prompt: str) -> float:
    while True:
        s = input(prompt).strip()
        try:
            x = float(s)
        except ValueError:
            print("Please enter a number.")
            continue
        if 0.0 <= x <= 1.0:
            return x
        print("Value must be between 0 and 1.")


def _input_float_optional(prompt: str) -> Optional[float]:
    """
    Optional float input:
    - blank -> None
    - otherwise must be a float in [0, 1]
    """
    while True:
        s = input(prompt).strip()
        if s == "":
            return None
        try:
            x = float(s)
        except ValueError:
            print("Please enter a number, or press Enter to skip.")
            continue
        if 0.0 <= x <= 1.0:
            return x
        print("Value must be between 0 and 1, or press Enter to skip.")


def _input_choice(prompt: str, min_v: int, max_v: int) -> int:
    while True:
        s = input(prompt).strip()
        try:
            x = int(s)
        except ValueError:
            print("Please enter an integer.")
            continue
        if min_v <= x <= max_v:
            return x
        print(f"Please select a number between {min_v} and {max_v}.")


# =============================
# Interactive CLI
# =============================
if __name__ == "__main__":

    print("=== Agent Builder Interactive Mode ===\n")

    # --- Emotion selection (text and sliders are optional; both missing -> error) ---
    text = input("Enter your text (press Enter to skip): ").strip()

    print("\nOptional sliders (press Enter to skip each):")
    valence = _input_float_optional("Valence (0-1): ")
    arousal = _input_float_optional("Arousal (0-1): ")
    control = _input_float_optional("Control (0-1): ")

    p_text = emotion_probs_from_text(text)
    p_slider = emotion_probs_from_sliders(valence, arousal, control)

    try:
        p_final = fuse(p_text, p_slider, text)
    except ValueError as e:
        raise SystemExit(f"\nERROR: {e}")

    emotion_tag = max(p_final.items(), key=lambda x: x[1])[0]
    confidence = p_final[emotion_tag]

    print("\n========== EMOTION RESULT ==========")
    print("Emotion Tag:", emotion_tag)
    print("Confidence:", round(confidence, 4))

    print("\n--- Emotion Example Utterances ---")
    for line in EMOTION_EXAMPLES.get(emotion_tag, []):
        print("-", line)

    # Load emotion prompt
    try:
        emotion_prompt = load_emotion_prompt(emotion_tag)
    except FileNotFoundError:
        raise SystemExit(f"\nERROR: emotion file not found: {os.path.join(EMOTION_DIR, emotion_tag + '.txt')}")

    # --- Decision selection (5 choices) ---
    print("\n========== DECISION BLOCK SELECTION ==========")
    for i, name in enumerate(DECISIONS, start=1):
        print(f"{i}. {name}")
        print(f"   Description: {DECISION_DESCRIPTIONS[name]}")
        print("   Example replies:")
        for ex in DECISION_REPLY_EXAMPLES[name]:
            print(f"     > {ex}")
        print()

    choice = _input_choice("Select Decision Block (1-5): ", 1, 5)
    decision_name = DECISIONS[choice - 1]
    print("\nSelected Decision Block:", decision_name)

    # Load decision prompt
    try:
        decision_prompt = load_decision_prompt(decision_name)
    except FileNotFoundError:
        raise SystemExit(f"\nERROR: decision file not found: {os.path.join(DECISION_DIR, decision_name + '.txt')}")

    # --- Assemble agent.txt ---
    agent_content = assemble_agent_txt(decision_name, emotion_tag, decision_prompt, emotion_prompt)
    out_path = os.path.join(SCRIPT_DIR, "agent.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(agent_content)

    print("\n✅ Agent assembled successfully!")
    print("Saved as:", out_path)