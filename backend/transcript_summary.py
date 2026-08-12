# -*- coding: utf-8 -*-
"""
transcript_summary.py

会话结束后告诉用户一件事：**这场讨论最后倒向哪边，为什么，以及什么还没定。**

不是会议记录。过程只在能解释走向是怎么形成的时候才出现——哪一段之后倾向变了、
被什么触发的。剩下的篇幅给结论本身：支撑它的理由、仍然站得住的反面理由、
你自己在其中起了什么作用、什么条件变了会把结论翻过来。

刻意保留的两个"不好听"的部分：反面理由和"你有没有确认过这个走向"。一份只说
结论、不说结论有多脆的总结，会让用户以为三个 agent 替他把事定了。

    python transcript_summary.py logs/004707.jsonl
    python transcript_summary.py logs/004707.jsonl --lang en
    python transcript_summary.py logs/004707.jsonl --out logs/004707_summary.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional

from agentwake_new import clamp_history, create_response
from lang_utils import normalize_lang, pick

# 想换模型或调稳一点，改这两个常量即可，不做成命令行参数——用户不该为了看一份
# 总结先去选模型。温度比群聊的 0.8 低很多：这是归纳，不需要人格和发挥。
MODEL = os.getenv("AGORA_SUMMARY_MODEL") or "gpt-4o"
TEMPERATURE = 0.3
MAX_OUTPUT_TOKENS = 900

# 每个阶段送进模型的转写上限，够装下正常一场会话的一个阶段。
MAX_SEGMENT_CHARS = 6000

INITIAL_PHASE = "Exploration"

# 内部阶段名 -> 用户能看懂的说法。用户不需要知道主持人的状态机叫什么。
PHASE_NAMES = {
    "Exploration":  {"zh": "摊开问题", "en": "Laying out the problem"},
    "Structuring":  {"zh": "梳理与比较", "en": "Structuring the trade-offs"},
    "Narrowing":    {"zh": "缩小范围", "en": "Narrowing down"},
    "Convergence":  {"zh": "形成结论", "en": "Converging"},
}


# -------------------------------
# 读日志 + 按阶段切分
# -------------------------------

def load_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _parse_time(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


_STATE_CHANGE_RE = re.compile(r"^\s*(\w+)\s*->\s*(\w+)\s*(?:\|\s*(.*))?$", re.DOTALL)


def load_state_changes(chat_path: str) -> List[dict]:
    """
    阶段边界不靠模型猜，靠主持人自己写下的记录：同一个房间的
    `{room}_moderator.jsonl` 里 `admin3_state_change` 那几行带时间戳。
    只看 state_change，不看 admin3_moderator——那两种行记的是同一次切换，
    两个都算会把每个边界切成两刀。
    """
    base, ext = os.path.splitext(chat_path)
    mod_path = f"{base}_moderator{ext}"
    if not os.path.exists(mod_path):
        return []
    changes = []
    for row in load_jsonl(mod_path):
        if row.get("character") != "admin3_state_change":
            continue
        m = _STATE_CHANGE_RE.match(row.get("txt", ""))
        t = _parse_time(row.get("time", ""))
        if m and t is not None:
            changes.append({"to": m.group(2), "from": m.group(1), "time": t})
    return changes


def segment_by_phase(msgs: List[dict], changes: List[dict]) -> List[dict]:
    """
    每条消息归给它写下时正在生效的阶段。空阶段丢掉：主持人按轮次跑，两次检查
    之间可能一条消息都没有，报告里留个空章节只是噪音。
    """
    segments = [{"phase": changes[0]["from"] if changes else INITIAL_PHASE, "messages": []}]
    pending = list(changes)
    for m in msgs:
        t = _parse_time(m.get("time", ""))
        while pending and t is not None and t >= pending[0]["time"]:
            segments.append({"phase": pending.pop(0)["to"], "messages": []})
        segments[-1]["messages"].append(m)
    return [s for s in segments if s["messages"]]


# -------------------------------
# 让模型归纳
# -------------------------------

# 阶段级只问一件事：这一段之后，倾向有没有动、被什么推动的。不要逐条流水账——
# 用户要看的是走向怎么形成，不是谁在第几轮说了什么。
PHASE_PROMPT = {
    "zh": (
        "你在分析一场决策讨论中的一段。参与者：用户本人（记录里写作 user，发言中被称为 @U），"
        "以及 ChatbotA / ChatbotB / ChatbotC 三位立场不同的 AI 顾问。\n"
        "只根据原文判断，不要补充原文里没有的事实或推测。\n"
        "严格输出一个 JSON 对象，不要写解释文字或代码块标记：\n"
        '{\n'
        '  "what_happened": "这一段主要在争什么，一到两句",\n'
        '  "shift": "这一段结束时，倾向朝哪个方向动了；没有动就写\\"没有变化\\"",\n'
        '  "driver": "推动这个变化的是哪一句话或哪条理由（点名是谁说的）；没有变化就写\\"—\\""\n'
        '}'
    ),
    "en": (
        "You are analyzing one stretch of a decision discussion. Participants: the user "
        "(logged as user, addressed as @U) and three AI advisors with different stances, "
        "ChatbotA / ChatbotB / ChatbotC.\n"
        "Judge only from the text; add nothing that is not in it.\n"
        "Output strictly one JSON object, no prose and no code fences:\n"
        '{\n'
        '  "what_happened": "what was mainly contested here, 1-2 sentences",\n'
        '  "shift": "which way the leaning moved by the end of this stretch; write \\"no change\\" if it did not",\n'
        '  "driver": "the line or argument that moved it, naming who said it; \\"—\\" if nothing moved"\n'
        '}'
    ),
}

# 整场级是这个脚本的重点：结论走向 + 它有多可靠。
#
# why 条目只标注说话人，不让模型断言"是否引用了你提供的信息"。原先的措辞要求
# 每条标注来源，实测（2026-08-12，7 个房间 × 2 次重跑）52 条 why 里 18 条带
# 出处章，其中 16 条正面断言"引用了你提供的信息"，11 条盖在顾问自己的推论上
# ——纯属编造，且 luna 和 4o 两个摘要器都犯，是提示词本身的问题。
# "谁说的"是模型对着带名字的逐行记录做的抄读任务，基本不错；"是不是用户
# 提供的"要区分 intake 事实和顾问推论，属于证据链查表，生成器做不了。出处
# 想恢复的话由确定性代码从 stance/quote 证据链渲染，追不到就不写。
OVERALL_PROMPT = {
    "zh": (
        "下面是一场决策讨论按阶段整理出的记录。请判断这场讨论最终倒向哪一边，并写给用户本人看。\n"
        "用第二人称称呼用户（“你”），直说结论，不要客套、不要鼓励式套话。\n"
        "只使用记录里的内容，不要引入新的事实，也不要给出记录里没人提过的建议。\n"
        "尤其注意诚实：如果倾向只来自其中一两位顾问、或者用户本人从没确认过，必须说明；"
        "如果讨论根本没有分出方向，direction 就写“没有形成明确走向”，不要硬凑一个结论。\n"
        "理由只标注说话人。绝不要写“这是你提供的信息”“引用了你提供的信息”这类来源断言"
        "——信息最初来自谁不由你判断。\n"
        "严格输出一个 JSON 对象，不要写解释文字或代码块标记：\n"
        '{\n'
        '  "direction": "讨论最终指向哪个选择，一句话直说",\n'
        '  "strength": "这个走向有多强，只能是这三个词之一：明确 / 倾向 / 未定",\n'
        '  "strength_reason": "为什么是这个强度，一句（谁支持、谁没表态、你有没有确认过）",\n'
        '  "why": ["支撑这个走向的具体理由，每条注明是谁说的（你 / ChatbotA / ChatbotB / ChatbotC）"],\n'
        '  "against": ["反过来仍然成立、但在讨论里没有被正面回应的理由"],\n'
        '  "your_role": "你自己的发言对这个走向起了什么作用；如果你从没确认过它，明确指出",\n'
        '  "would_change": ["哪些信息补上或哪些条件变了，会把这个走向翻过来"],\n'
        '  "your_call": ["最终仍然只能由你决定的问题"]\n'
        '}'
    ),
    "en": (
        "Below is a stage-by-stage record of one decision discussion. Judge which way it "
        "finally leaned, and write it for the user themselves.\n"
        "Address them as \"you\". State the conclusion directly; no pleasantries, no encouragement.\n"
        "Use only what is in the record. Introduce no new facts and no advice nobody raised.\n"
        "Be honest above all: if the leaning comes from only one or two advisors, or the user "
        "never confirmed it, say so. If the discussion never picked a direction, write "
        "\"no clear direction formed\" — do not manufacture a conclusion.\n"
        "Attribute each reason only to its speaker. Never assert where a piece of information "
        "originally came from — no \"based on information you provided\" or similar provenance "
        "claims; that is not yours to judge.\n"
        "Output strictly one JSON object, no prose and no code fences:\n"
        '{\n'
        '  "direction": "which choice the discussion finally pointed to, one sentence",\n'
        '  "strength": "how strong that leaning is; exactly one of: clear / leaning / undecided",\n'
        '  "strength_reason": "why that strength, one sentence (who backed it, who stayed silent, whether you confirmed it)",\n'
        '  "why": ["concrete reasons backing the leaning, each naming who said it (you / ChatbotA / ChatbotB / ChatbotC)"],\n'
        '  "against": ["reasons on the other side that still hold and were never answered in the discussion"],\n'
        '  "your_role": "what your own input did to this leaning; state plainly if you never confirmed it",\n'
        '  "would_change": ["what information or changed conditions would flip this"],\n'
        '  "your_call": ["what only you can decide"]\n'
        '}'
    ),
}


def _extract_json(text: str) -> Optional[dict]:
    """模型时不时会套上 ```json。为这个丢掉整段内容不值得，所以先剥壳再解析。"""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _ask(system: str, body: str) -> Optional[dict]:
    raw = create_response(
        MODEL,
        [{"role": "system", "content": system}, {"role": "user", "content": body}],
        TEMPERATURE, MAX_OUTPUT_TOKENS,
    )
    return _extract_json(raw)


def summarize_segment(segment: dict, lang: str) -> Optional[dict]:
    lines = [f"{m['character']}: {m['txt']}" for m in segment["messages"]]
    return _ask(PHASE_PROMPT[lang], clamp_history(lines, MAX_SEGMENT_CHARS))


def summarize_overall(segments: List[dict], lang: str) -> Optional[dict]:
    parts = []
    for s in segments:
        name = pick(PHASE_NAMES.get(s["phase"], {"zh": s["phase"], "en": s["phase"]}), lang)
        parts.append(f"[{name}]\n" + json.dumps(s.get("summary") or {}, ensure_ascii=False, indent=2))
    return _ask(OVERALL_PROMPT[lang], "\n\n".join(parts))


# -------------------------------
# 排版
# -------------------------------

L = {
    "title":     {"zh": "这场讨论最后倒向哪边", "en": "Where this discussion landed"},
    "meta":      {"zh": "{date} · 共 {n} 条发言 · 你发言 {u} 次",
                  "en": "{date} · {n} messages · you spoke {u} time(s)"},
    "strength":  {"zh": "把握程度", "en": "How firm"},
    "why":       {"zh": "支撑这个走向的理由", "en": "What backs it"},
    "against":   {"zh": "反面仍然站得住的理由", "en": "What still stands against it"},
    "your_role": {"zh": "你在其中的位置", "en": "Where you stand in this"},
    "how":       {"zh": "走向是怎么形成的", "en": "How it got there"},
    "shift":     {"zh": "倾向变化", "en": "Shift"},
    "driver":    {"zh": "被什么推动", "en": "Driven by"},
    "change":    {"zh": "什么会把这个结论翻过来", "en": "What would flip it"},
    "your_call": {"zh": "只能由你决定的", "en": "Only you can decide"},
    "one_stage": {"zh": "（这场会话没有走完分阶段的流程，下面按一整段来看。）",
                  "en": "(This session did not go through the staged flow; shown as one stretch.)"},
    "no_result": {"zh": "这场讨论没有整理出明确的走向。",
                  "en": "No clear direction came out of this discussion."},
    "failed":    {"zh": "无法生成总结：{err}\n（检查网络和 agentwake_new.py 顶部的 API key 后重试。）",
                  "en": "Could not generate the summary: {err}\n(Check the network and the API key at the top of agentwake_new.py, then retry.)"},
}

# 模型只被允许在这三个档里选，所以这里可以安全地加标记，不会漏档。
STRENGTH_MARK = {
    "明确": "●●●", "倾向": "●●○", "未定": "●○○",
    "clear": "●●●", "leaning": "●●○", "undecided": "●○○",
}


def _t(key: str, lang: str, **kw) -> str:
    text = pick(L[key], lang)
    return text.format(**kw) if kw else text


def _section(title: str, items) -> List[str]:
    if not items:
        return []
    if isinstance(items, str):
        return [f"## {title}", "", items, ""]
    return [f"## {title}", ""] + [f"- {i}" for i in items] + [""]


def render(msgs: List[dict], segments: List[dict], overall: Optional[dict],
           lang: str, staged: bool) -> str:
    date = (msgs[0].get("time", "")[:10]) if msgs else ""
    out = [
        f"# {_t('title', lang)}",
        "",
        _t("meta", lang, date=date, n=len(msgs),
           u=sum(1 for m in msgs if m["character"] == "user")),
        "",
    ]

    if not overall:
        out += [_t("no_result", lang), ""]
    else:
        # 结论本身放最上面，且不折叠进小标题——这是用户打开这份东西唯一必看的一行。
        out += ["> " + str(overall.get("direction") or _t("no_result", lang)), ""]
        strength = str(overall.get("strength") or "").strip()
        if strength:
            mark = STRENGTH_MARK.get(strength, "")
            reason = overall.get("strength_reason") or ""
            out += [f"**{_t('strength', lang)}**：{strength} {mark}"
                    + (f" —— {reason}" if reason else ""), ""]
        out += _section(_t("why", lang), overall.get("why"))
        out += _section(_t("against", lang), overall.get("against"))
        out += _section(_t("your_role", lang), overall.get("your_role"))

    # 过程只保留"走向怎么动的"，每段两三行，不做逐条复盘。
    out += [f"## {_t('how', lang)}", ""]
    if not staged:
        out += [_t("one_stage", lang), ""]
    for i, s in enumerate(segments, 1):
        name = pick(PHASE_NAMES.get(s["phase"], {"zh": s["phase"], "en": s["phase"]}), lang)
        summary = s.get("summary") or {}
        out.append(f"**{i}. {name}** — {summary.get('what_happened', '')}")
        if summary.get("shift"):
            out.append(f"- {_t('shift', lang)}：{summary['shift']}")
        if summary.get("driver") and summary["driver"] not in ("—", "-"):
            out.append(f"- {_t('driver', lang)}：{summary['driver']}")
        out.append("")

    if overall:
        out += _section(_t("change", lang), overall.get("would_change"))
        out += _section(_t("your_call", lang), overall.get("your_call"))
    return "\n".join(out).rstrip() + "\n"


# -------------------------------
# 入口
# -------------------------------

def build_result(chat_path: str, lang: str = "zh") -> dict:
    """Return structured summary pieces plus rendered markdown.

    Shape:
      {
        "markdown": str,
        "overall": dict | None,
        "segments": [{phase, summary, ...}],
        "staged": bool,
      }
    """
    msgs = load_jsonl(chat_path)
    if not msgs:
        raise RuntimeError(f"聊天记录是空的：{chat_path}")
    changes = load_state_changes(chat_path)
    segments = segment_by_phase(msgs, changes)
    for s in segments:
        s["summary"] = summarize_segment(s, lang)
    overall = summarize_overall(segments, lang)
    markdown = render(msgs, segments, overall, lang, staged=bool(changes))
    # Strip heavy message bodies before returning segments
    light_segments = []
    for s in segments:
        light_segments.append({
            "phase": s.get("phase"),
            "summary": s.get("summary"),
            "message_count": len(s.get("messages") or []),
        })
    return {
        "markdown": markdown,
        "overall": overall,
        "segments": light_segments,
        "staged": bool(changes),
    }


def build(chat_path: str, lang: str = "zh") -> str:
    return build_result(chat_path, lang)["markdown"]


def main() -> int:
    ap = argparse.ArgumentParser(description="告诉用户这场讨论最后倒向哪边、为什么。")
    ap.add_argument("chat_log", help="聊天记录路径，例如 logs/004707.jsonl")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"], help="用什么语言写。默认中文")
    ap.add_argument("--out", default=None, help="同时写到这个文件，例如 logs/004707_summary.md")
    args = ap.parse_args()

    # 默认输出中文，而 Windows 控制台默认不是 UTF-8，不改会打成乱码。
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    if not os.path.exists(args.chat_log):
        print(f"找不到聊天记录：{args.chat_log}", file=sys.stderr)
        return 2

    lang = normalize_lang(args.lang)
    try:
        text = build(args.chat_log, lang)
    except Exception as e:
        # 没 key、断网、超额——说清楚为什么，不要甩一段 traceback 给用户。
        print(_t("failed", lang, err=e), file=sys.stderr)
        return 1

    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[已写入] {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
