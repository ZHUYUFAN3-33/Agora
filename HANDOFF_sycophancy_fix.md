# Handoff：三个 agent 是否在附和用户既有倾向（问题描述）

本文件只描述现象与已查证的事实，**不提方案**。凡是我没验证的，都在下面明确标了
「未验证」。请不要把我的推测当结论。

---

## 1 · 观察到的现象

为 CHI 论文做 teaser 图，用 dummy 账号 DEMO01（employment 场景）在
https://agora-chat-2.fly.dev 跑了一场真实会话。

intake 的 `comparison_anchor` 字段填的是：

> "I lean toward the postdoc, but I am not confident it is the right call"

三个选项是：

```
Kyoto national lab postdoc — 3-year contract, JPY 4.8M, PI track
US tech firm research scientist — JPY 9.5M, relocate to Singapore
Shibuya startup UX lead — JPY 7.2M plus equity, stay in Tokyo
```

第一轮（每个 agent 各两次发言）结束后：

- **ChatbotA（growth）**：Kyoto "decisively in front"
- **ChatbotB（stability）**：不同意"decisively"，但排序仍是"eliminate Singapore；
  除非融资条款特别好否则不要 startup；Kyoto 需要证据支撑"——落点仍在 Kyoto
- **ChatbotC（life）**：明确 drop Singapore，"my instinct is still toward the
  Kyoto postdoc"

即三个 agent 都落到了用户预先声明的倾向上。完整原文用户手里有存档。

**这是 N=1 的一次观察，没有对照组。** 见第 3 节。

---

## 2 · 已查证的事实（每条都标了怎么验的）

### 2.1 用户的倾向确实进了 prompt，且被框成「已定输入」

在 `backend/` 下实跑 `profile_store.format_known_context()` 并打印输出，
确认渲染结果包含：

```
=== KNOWN USER CONTEXT (provided by user, do not re-ask) ===
...
[This decision]
- Do you already lean toward one option? Optional. -> I lean toward the postdoc, but I am not confident it is the right call
```

两点：

- 它和 deadline、options、priority_ranking **并排在同一个 `[This decision]`
  段里**，格式上与客观事实没有任何区分；
- 块标题是 `(provided by user, do not re-ask)`，这句话统辖整个块。

### 2.2 `comparison_anchor` 在代码里没有任何特殊处理

`grep -rn "comparison_anchor" backend/` 只有一处命中：
`backend/scenario_templates/employment.json:195`（字段定义本身）。
没有任何 .py 读取它、没有任何 prompt 逻辑把它与其他字段区别对待。

parent_child 场景的对应字段（`child_stated_preference`、`parent_stated_concern`）
**未做同样检查** —— 未验证。

### 2.3 有一条 nudge 要求每轮引用 KNOWN USER CONTEXT 的内容

`backend/agentwake_new.py:2225`（另一处在 ~3592）：

> "Anchor this message to the user's actual case: name at least one specific
> detail from KNOWN USER CONTEXT (…)"

可引用清单来自 `ANCHOR_EXAMPLES`（`agentwake_new.py:1066`），employment 那条是：

> "a ranked priority, the deadline, a named option and its salary/level/location,
> the career stage"

注意：这个清单里**没有**列 comparison_anchor。但清单是 nudge 的举例，
不是白名单——**它是否实际限制了 agent 只能引用这几项，我没有验证。**

### 2.4 反「屈从」的指令存在，但针对的是其他 agent，不是用户

grep 过 `scenes/ stance_templates/ decision/ emotion/ personas/ chatbot*.txt scene.txt`
以及 `agentwake_new.py / stance.py / agent_assembly.py`，找到的相关指令只有三处：

- `stance_templates/employment.json:39` 与 `:48`（stability 立场）：
  "Push back on 'growth potential' claims…" —— 指向 growth agent 的主张
- `stance_templates/employment.json:76`（life 立场，收尾槽位）：
  "Do not downplay the life cost just to reach agreement."
- `stance_templates/parent_child.json:28`（child 立场，收尾槽位）：
  "If the majority leans elsewhere, spell out the child's cost before conceding
  anything."

这三条都是**抵抗其他 agent / 抵抗多数意见**，且都挂在特定立场的特定槽位上。

搜 `sycophan|even if the user|disagree with the user|independent of the user|
user's lean|challenge the user|push back`（跨上述全部文件）：
针对**用户倾向**的指令，**零命中**。

> 我搜的是这些关键词。措辞不同的等价指令可能被漏掉 —— 这是关键词搜索的固有局限。

### 2.5 收尾权重机制漏掉了用户排最前的两项

`backend/stance.py:204` 的 `PRIORITY_TO_STANCE` 是硬编码关键词表，
只认 `growth/成长/发展`、`stability/salary/薪酬/稳定`、
`location/culture/life/地点/文化/生活`。

用本场实际 ranking 跑 `stance._employment_weight_hint()`，结果：

| 立场 | 命中档位 | 注入的提示（节选） |
|---|---|---|
| growth | `absent` | "your stance isn't mentioned — put this overlooked dimension back on the table" |
| stability | `top` | "ranked as top priority. Your view carries more weight in the closing stage" |
| life | `absent` | 同 growth |

原因：排第 1 的 `Research autonomy` 和排第 2 的 `My partner's career`
**字面上都不含表里的关键词**，落空；排第 3、4 的 `Long-term stability` 和
`Salary` 都命中 stability。

复现（在 `backend/` 目录下）：

```bash
/Users/Zhu/Desktop/Agora/.venv/bin/python -c "
import stance
intake={'priority_ranking':['Research autonomy',\"My partner's career\",'Long-term stability','Salary']}
for st in ('growth_centered','stability_centered','life_centered'):
    print(st, '->', stance._employment_weight_hint(intake, st, 'en')[:80])"
```

**这条与第 1 节的现象是否有因果关系，我倾向认为没有** ——
`get_convergence_weight_hint()` 的 docstring 与调用点都表明它只在
Convergence 阶段注入，而第一轮不在该阶段。但**我没有验证第一轮实际处于哪个
阶段**，所以不能完全排除。它是一个独立的问题，不一定是这次现象的原因。

---

## 3 · 未验证的部分 / 竞争性解释

**这些我之前口头上说得太肯定了，实际都没有证据支撑：**

### 3.1 最重要的一条：趋同可能就是正确推理，不是附和

用户排的优先级第 1 是 research autonomy、第 2 是 partner's career。
在这两条之下：

- Singapore 选项要求异地，直接冲突第 2 项
- startup 选项明确写了 "no research"，直接冲突第 1 项
- Kyoto 是唯一同时满足两项的

也就是说，**即使系统完全不知道用户的倾向，一个诚实的推理者也可能得出同样的
排序**。用户的倾向本身可能就是基于同样的逻辑形成的。

我没有跑「清空 `comparison_anchor`、其他一切不变」的对照，所以**无法区分
"附和用户" 和 "独立推理碰巧同结论"**。这是本文件里最大的未知。

### 3.2 没有做任何消融

- 没有对照组（不填倾向 / 填相反倾向 / 换一组选项）
- 没有重复运行（同样输入跑 N 次看方差）
- N=1

### 3.3 anchor nudge 是否真的在第一轮注入了，未验证

`agentwake_new.py:2225` 那段代码是否在本次会话的第一轮实际执行、
注入的具体文本是什么，我**没有从运行日志确认**。只是读了代码。
线上 agora-chat-2 的 room 日志里应该有（`{room}_rationale.jsonl` /
prompt 落盘与否需要查）。

### 3.4 模型本身的倾向未排除

`AGORA_MODEL=gpt-5.6-terra`。LLM 基线上就偏向同意用户，
这部分贡献有多大，无法从代码判断。

### 3.5 搜索覆盖面

第 2.4 节的结论建立在关键词搜索上。我没有逐字通读
`agentwake_new.py`（3800+ 行）的全部 prompt 拼装路径，也没有读
`new_module/`、`backend/personas/` 下的内容。措辞不同的等价约束可能存在但被漏掉。

---

## 4 · 为什么这件事对论文重要

论文摘要（`_CHI__AlterEidos_Shengyin.zip` → `sections/0-abstract.tex` 与
`main.tex` 内嵌的第二份 abstract）写的是：

> agents … producing **stable and visibly conflicting viewpoints** that a user
> can observe and engage with, **rather than one single converged answer**

正文 `sections/4-system.tex:45` 进一步写每个 agent "cannot be moved off"
其立场，且favored option 必须先说出对自身所代表利益的代价。

若第 1 节的现象在对照实验下站得住，它与上述主张直接冲突；
若站不住（即 3.1 的解释成立），那么现有证据不足以支持"存在附和问题"这个判断，
本文件的价值就只剩第 2.5 节那个独立的关键词表缺陷。

**目前我无法判断是哪一种。**

---

## 5 · 环境与分支现状（供接手者定位）

- 工作分支：`paper/figures`（从 `main` @ `5a33f57` 开出）
- 本地起服务：`.claude/launch.json` 的 `backend`(5001) / `frontend`(5173)
- 账号：本地 DB 与线上 agora-chat-2 都有 `DEMO01` / `DEMO02`，
  密码均 `agora-demo-2026`。DEMO01=employment，DEMO02=parent_child
  （分两个号是因为 profile 存储不按场景分区，扁平 dict，`age` 会互相覆盖）
- `DUMMY_SESSIONS.md`：本次用的人设、intake 逐字内容、预定的 8 句输入脚本

### 该分支上已有的未提交改动（与本问题无关，别弄丢）

1. `frontend/src/app/pages/Chat.tsx`
   - `intakePrefill` useMemo：修 intake 表单在 send-time guard 弹出时为空、
     用户按 Continue 会清空已填答案的问题
   - stance 绑定场景下 BASIC STANCE 由下拉框改为只读标签
2. `backend/agent_assembly.py`
   - `build_agent_spec()` 中，凡 `stance_enabled(scenario_type)` 为真的场景
     忽略 `stance_override`，改由 `assign_stance()` 强制分配。
     已验证：三个 agent 全传 `growth_centered` 会被纠正为 growth/stability/life
3. `.claude/launch.json`：backend 入口改用 `.venv` 的 python

前端 `tsc --noEmit` 有 6 个错误，**改动前后数量一致**（已用 git stash 对比），
与上述改动无关。

### 其他已知但与本问题无关的事项

- 线上 agora-chat-2 跑的是旧代码，上述改动均未部署
- 论文正文与代码有三处口径未对齐（阶段命名 5 vs 4、知识卡单跳扩展是否跨立场、
  未命中时是否注入 generic fallback），用户已知，单独处理
