# Handoff：立场知识库检索几乎不命中（问题描述）

本文件只描述现象与查证到的事实，**不提方案**。未验证的部分都明确标了。
不要把我的推测当结论。

---

## 1 · 现象

用真实的英文用户发言去查知识卡，**24 次检索机会命中 1 次**。

测法：取 `DUMMY_SESSIONS.md` 里为 employment 场景准备的 8 句用户输入（写成正常
英文句子，不是关键词），对 growth / stability / life 三个立场卡池各查一次，
调用与运行时完全相同的 `_match_topic_card(msg, cards, "en", allow_soft=False)`。

结果（`—` 表示无命中）：

```
T1: —  |  —                            |  —
T2: —  |  —                            |  —
T3: —  |  stability_contract_pitfalls  |  —
T4: —  |  —                            |  —
T5: —  |  —                            |  —
T6: —  |  —                            |  —
T7: —  |  —                            |  —
T8: —  |  —                            |  —
```

唯一那次命中靠的是 "contract" 这个词恰好出现在句子里。

落空的恰恰是最该命中的几条：

| 用户实际说的 | 本该命中 | 卡片的英文关键词 |
|---|---|---|
| "I am afraid **I will regret** whichever one I pick" | `growth_affective_forecasting` | `will I regret` / `how will I feel` / … |
| "**can I ever come back to academia**? Or is that a one-way door?" | `stability_reversibility` | `can I go back` / `no way back` / … |
| 同上 | `growth_academia_vs_industry_comp`（**专为学术 vs 业界写的卡**） | `academia vs industry` / `stay in academia` / `leave academia` / … |
| "I have watched people **stay postdocs for six years**" | `growth_promotion_plateau` | `stuck at this level` / `hit a ceiling` / … |
| "**My partner has her own design career** in Tokyo" | `life_partner_career` | `partner's job` / `spouse's career` / `dual career` / … |

第一条差在 "will I regret" 与 "I will regret" 的词序；第二条差在 "come back"
与 "go back"；第五条差在 "has her own design career" 与 "partner's job"。
**全部是字面差异，语义上都是精确对应。**

复现（在 `backend/` 目录下）：见本文件第 5 节。

---

## 2 · 已查证的机制

### 2.1 检索是纯子串包含，不是论文写的 BM25

`backend/stance_knowledge.py:249` 起，`_match_topic_card()` 的 pass 1（运行时
唯一走的一条，`allow_soft` 默认 False）：

```python
msg_lower = user_message.lower().strip()
for card in topic_cards:
    for kw in card.get("keywords", []):
        if kw.lower() in msg_lower:
            return card
```

- 无评分：`grep -niE "bm25|idf|tfidf|score|rank" backend/stance_knowledge.py`
  **零命中**
- 无排序：命中即返回，取决于卡片在 JSON 数组里的先后
- 无阈值

论文 `sections/4-system.tex:92` 写的是：

> the latest message is **scored by BM25** … and the **top-scoring card** is
> injected … or nothing is injected when **no card clears a minimum score**

三个分句与实现都对不上（另有一处相同表述在 `:33`，两处共引用
`robertson1994some` / `robertson2009probabilistic` / `lewis2020retrieval`）。

### 2.2 关键词表是人工枚举的，英文条目平均每卡 6 条

`background_templates/stance_knowledge/{scenario}.json`，每张卡一个
`keywords` 数组。中英混排，比例：

| 场景 | 触发词总数 | 中文 | 英文 |
|---|---|---|---|
| employment | 341 | 155 (45%) | 186 (55%) |
| parent_child | 319 | 150 (47%) | 169 (53%) |

employment 30 张卡 / 186 条英文触发词 ≈ 每卡 6 条英文写法。用户要恰好用上其中
一条的字面形式才会命中。

### 2.3 论文里那个自检（`[XX%]` TODO）测不出这个问题

`4-system.tex:92` 末尾有：

> The corpus resolves [XX\%] of phrases to their own card and [XX\%] to a linked
> neighbor, leaving [XX\%] misses … % TODO: run the check and fill in the three figures

我按描述实现并跑了（用每条触发词自身作为 query，查所属立场的卡池）：

```
employment  : 341 条 → 自身卡 100.0%，邻居 0%，miss 0%
parent_child: 319 条 → 自身卡 100.0%，邻居 0%，miss 0%
```

**但这个 100% 是构造上必然的，不说明任何问题。** 在"子串包含 + 首个命中"下，
用触发词自己去查，除非更靠前的卡片有一个关键词恰好是这条触发词的子串，
否则一定命中自己。这个自检衡量的是关键词表内部有没有互相遮蔽，
**不衡量真实句子的命中率** —— 而后者才是第 1 节看到的问题。

如果要把这三个数填进论文，需要注意它们不支持"检索有效"这个结论。

### 2.4 未命中时确实不注入 generic fallback（论文这条是对的）

两条运行时路径都在调用 block 之前先做命中判定：

- `backend/agentwake_new.py:429-445`：`if not card_id: return ""`，
  以及 `if not hit or hit.get("is_fallback"): return ""`
- `backend/agora2_http.py:146`：`if not sk_match_topic_card(...): return ""`，
  docstring 明写 "Keyword-hit only; empty string when no match (no generic fallback)"

`get_stance_knowledge_block()` 本身（`stance_knowledge.py:352`）会在无命中时
构造 `generic_fallback`（带 `is_fallback: True`），数据文件里每个立场也都存了
`generic_fallback` —— 但两条运行时路径都把它挡掉了。

所以 `4-system.tex:33` 的 "a turn that matches nothing leaves the prompt
untouched, with no generic fallback injected" **与实现一致**。
（我在更早的对话里曾把这条列为疑似矛盾，此处更正。）

### 2.5 单跳扩展跨立场（与论文相反）

`stance_knowledge.py:268` 的 `_find_card_by_id()` docstring：

> "Searches all stances within a scenario for a topic card with this id
> (related_cards can point across stances, not just within the same one)."

实现遍历 `scenario_cfg.values()`，即全部立场。`get_stance_knowledge_block()`
的 related 循环（`:365` 起）用的正是它。数据也确认跨立场，例如
`child_defiance → parent_power_struggle`。

论文 `4-system.tex:42` 与 `:92` 两处都写 "confined to the card pool of the same
stance so that expansion never crosses stance boundaries"。**矛盾。**

---

## 3 · 未验证 / 我不确定的部分

### 3.1 线上真实会话的命中率未知

第 1 节用的是我们为做图准备的 8 句脚本，不是真实被试语料。真实参与者的措辞
可能更接近关键词（也可能更远）。**线上 agora-chat-2 与 agora-chat 的 room
日志里应该能统计**，我没有去取。

`agentwake_new.py` 里有 `on_match` 回调会把命中的卡写进记录（`:452` 附近），
所以日志里可能有命中事件；但**未命中是否留痕、留在哪，我没有查**。

### 3.2 中文会话的命中率未测

我只测了英文。中文触发词有 155 条，中文表达的变体空间与英文不同，
命中率可能明显不一样。未测。

### 3.3 未命中的实际后果没有量化

无命中 → 不注入任何卡 → agent 只靠 stance 文本 + KNOWN USER CONTEXT 发言。
论文 DG1 的主张是"每个立场从专属材料出发论证，而不是只从一个立场标签出发"
（`4-system.tex` DG1）。若命中率确实很低，agent 大部分时间就是在只靠标签发言。

**但我没有做对照**：没有比较"有卡注入"与"无卡注入"两种情况下 agent 发言的
差异。所以"不命中导致发言空泛"是推论，不是观测。

### 3.4 与另一份 handoff 的关系

`HANDOFF_sycophancy_fix.md` 记录的是"三个 agent 全部附和用户既有倾向"。
那一轮里几乎没有卡命中（第 1 节 T1 全空）—— **两者可能相关**（没有各自专属
的材料，agent 更容易趋同），但我**没有证据支持这个联系**，只是时间上同时发生。
不要当作已确认的因果。

### 3.5 `allow_soft` 分支未纳入评估

`_match_topic_card` 有一个 pass 2（反向包含、仅在唯一命中时返回），
但 `allow_soft=True` 只在 agent 定制界面的 hint 预览里用，运行时每回合的路径
一律 False。我按运行时行为测的。hint 那条路径的命中率未测。

---

## 4 · 与论文的关系（供判断优先级）

`sections/4-system.tex` 中受影响的具体句子：

| 位置 | 论文写的 | 实现 |
|---|---|---|
| `:33`、`:92` | scored by BM25 / top-scoring card / minimum score | 子串包含，无评分无阈值 |
| `:42`、`:92` | expansion never crosses stance boundaries | 跨立场 |
| `:33` | no generic fallback injected | **一致** |
| `:92` | 三个 `[XX%]` 待填 | 已可跑出 100/0/0，但该数字不支持"检索有效" |

DG1 的表述在 `4-system.tex` 设计目标一节：
"Each position should argue from material specific to it, updated as the
discussion turns, rather than from a stance label alone."

---

## 5 · 复现方法

环境：`backend/` 目录下，用 `/Users/Zhu/Desktop/Agora/.venv/bin/python`
（`load_stance_knowledge()` 的默认路径是相对的，必须在 `backend/` 下跑）。

真实句子命中率：

```python
from stance_knowledge import _match_topic_card, load_stance_knowledge
kb = load_stance_knowledge()["employment"]
msg = "I am afraid I will regret whichever one I pick"
for st in ("growth_centered", "stability_centered", "life_centered"):
    c = _match_topic_card(msg, kb[st]["topic_cards"], "en", allow_soft=False)
    print(st, "->", c["id"] if c else "MISS")
```

论文那个自检：见第 2.3 节描述，遍历每张卡的每条 keyword 作为 query。

## 6 · 环境

- 分支 `paper/figures`（领先 `main` 两个提交：`6e9ab64` 代码修复、`349c931` 文档）
- 本 handoff 涉及的代码**未做任何改动**，全部是只读排查
- 论文源码在 `_CHI__AlterEidos_Shengyin.zip`（未入库），解包后看
  `sections/4-system.tex`
- 相关：`HANDOFF_sycophancy_fix.md`（同目录），另一个独立问题
