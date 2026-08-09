# -*- coding: utf-8 -*-
import json
import re

CJK = re.compile(r"[\u4e00-\u9fff]")

import sys
scenario = sys.argv[1] if len(sys.argv) > 1 else "parent_child"
with open(f"background_templates/stance_knowledge/{scenario}.json", encoding="utf-8") as f:
    d = json.load(f)
print(f"=== {scenario} ===")

all_ids = {}
for stance, cfg in d.items():
    for c in cfg["topic_cards"]:
        all_ids[c["id"]] = stance

print(f"Total cards: {len(all_ids)}")
print()

# --- 1. structure ---
required = {"id", "tag", "keywords", "text", "source", "source_type", "related_cards"}
errs = []
for stance, cfg in d.items():
    for c in cfg["topic_cards"]:
        missing = required - set(c.keys())
        if missing:
            errs.append(f"{c['id']}: missing {missing}")
        if not ("zh" in c["tag"] and "en" in c["tag"]):
            errs.append(f"{c['id']}: tag not bilingual")
        if not ("zh" in c["text"] and "en" in c["text"]):
            errs.append(f"{c['id']}: text not bilingual")
    fb = cfg["generic_fallback"]
    for k in ("zh", "en", "source", "tag"):
        if k not in fb:
            errs.append(f"{stance} fallback: missing {k}")
print("1. Structure:", "OK" if not errs else errs)

# --- 2. keyword EN/ZH parity ---
print("\n2. Keyword parity (zh / en):")
parity_issues = []
for stance, cfg in d.items():
    for c in cfg["topic_cards"]:
        zh = [k for k in c["keywords"] if CJK.search(k)]
        en = [k for k in c["keywords"] if not CJK.search(k)]
        flag = "" if len(en) >= len(zh) else "  <-- EN fewer than ZH"
        if flag:
            parity_issues.append(c["id"])
        print(f"   {c['id']:<38} {len(zh)} / {len(en)}{flag}")
print("   Parity issues:", parity_issues if parity_issues else "none")

# --- 3. related_cards edges ---
print("\n3. related_cards:")
under_two = []
broken = []
cross_stance_count = 0
total_edges = 0
for stance, cfg in d.items():
    for c in cfg["topic_cards"]:
        n = len(c["related_cards"])
        total_edges += n
        if n < 2:
            under_two.append((c["id"], n))
        for r in c["related_cards"]:
            if r not in all_ids:
                broken.append((c["id"], r))
            elif all_ids[r] != stance:
                cross_stance_count += 1
print(f"   Total edges: {total_edges}")
print(f"   Cross-stance edges: {cross_stance_count}")
print(f"   Cards with <2 edges: {under_two if under_two else 'none'}")
print(f"   Broken references: {broken if broken else 'none'}")

# --- 4. constraint: disclaimer present ---
print("\n4. Disclaimer sentence present in zh text:")
no_disclaimer = [c["id"] for stance, cfg in d.items() for c in cfg["topic_cards"]
                 if ("一般性框架" not in c["text"]["zh"] and "一般性" not in c["text"]["zh"])]
print("  ", no_disclaimer if no_disclaimer else "all cards OK")

# --- 5. excluded sensitive topics ---
print("\n5. Excluded-topic check:")
banned_by_scenario = {
    "parent_child": ["霸凌", "bully", "拒学", "school refusal", "多动", "ADHD", "自闭", "autism",
                      "学习障碍", "learning disability", "体罚", "corporal punishment", "打孩子"],
    "employment": ["歧视", "discrimination", "性骚扰", "harassment", "签证", "visa",
                    "移民", "immigration", "抑郁症", "depression diagnosis", "仲裁", "lawsuit",
                    "劳动仲裁", "sue "],
}
banned = banned_by_scenario.get(scenario, [])
hits = []
for stance, cfg in d.items():
    for c in cfg["topic_cards"]:
        blob = (c["text"]["zh"] + c["text"]["en"] + " ".join(c["keywords"])).lower()
        for b in banned:
            if b.lower() in blob:
                hits.append((c["id"], b))
print("  ", hits if hits else "no banned topics found")

# --- 6. keyword self-match ---
print("\n6. Keyword self-match test:")
def match(msg, cards):
    low = msg.lower()
    for c in cards:
        for kw in c["keywords"]:
            if kw.lower() in low:
                return c
    return None

total = passed = 0
fails = []
for stance, cfg in d.items():
    for c in cfg["topic_cards"]:
        for kw in c["keywords"]:
            total += 1
            msg = f"关于{kw}我想聊聊" if CJK.search(kw) else f"I want to talk about {kw}"
            hit = match(msg, cfg["topic_cards"])
            if hit and hit["id"] == c["id"]:
                passed += 1
            else:
                fails.append((c["id"], kw, hit["id"] if hit else None))
print(f"   {passed}/{total} passed")
if fails:
    print("   Failures (keyword shadowed by an earlier card):")
    for f in fails:
        print("    ", f)
