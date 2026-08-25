# Dummy 账号与会话脚本（teaser 素材）

两套：**就职**（首选，决策图可控）、**育儿**（备用，选项要靠对话逼出来）。
所有数字常量来自代码，不是估计：`option_board.py` `LABEL_MAX=72` / `SIM_THRESHOLD=0.5` /
`MAX_DISPLAY=6` / `STABLE_TURNS=3`，`turn_summaries.py` `MAX_STANCES_PER_TURN=4` /
`QUOTE_MAX_WORDS=20`，`agentwake_new.py` `MODERATOR_USER_TURN_INTERVAL=2`。

---

# A · 就职场景

## A1 Profile（一次性，7 个字段）

| 字段 | 填 |
|---|---|
| age | `31` |
| education | `PhD candidate (D3) in Human-Computer Interaction; MA in Industrial Design` |
| industry_experience | `4 years as a product designer in consumer electronics, then 3 years back in academia` |
| career_stage | `job_change` |
| family_situation | `Partner works as a designer in Tokyo and does not want to relocate. No children.` |
| long_term_goal | `To keep doing research I choose myself, and to still be doing it in ten years` |
| risk_tolerance | `medium` |

## A2 Scenario Intake（每次会话，7 个字段）

**decision_field**
```
Where to go after finishing the PhD next March — research track or industry
```

**options**（一行一条，逐条「添加」。每行都在 72 字符以内，措辞刻意拉开避免被 `SIM_THRESHOLD=0.5` 合并）
```
Kyoto national lab postdoc — 3-year contract, JPY 4.8M, PI track
US tech firm research scientist — JPY 9.5M, relocate to Singapore
Shibuya startup UX lead — JPY 7.2M plus equity, stay in Tokyo
```

**deadline**
```
The lab needs an answer by mid-March; the startup offer expires in two weeks
```

**current_status** → `pending_grad`

**priority_ranking**（一行一条）
```
Research autonomy
My partner's career
Long-term stability
Salary
```
> 薪酬**故意排最后**：这样 JPY 9.5M 那条一被提起，就和用户自己排的优先级冲突，
> 三个 agent 立刻有架可吵。`stance.py` 的 `PRIORITY_TO_STANCE` 会读这个排序，
> 在 Convergence 阶段调整三个立场的话语权。

**comparison_anchor**
```
I lean toward the postdoc, but I am not confident it is the right call
```
> 先声明倾向，是为了后面能问出"我这个倾向要付出什么代价"，保证被选中的选项
> against 栏不为空——论文 4-system.tex:51 特别强调这一点。

**external_pressure**
```
My advisor assumes I will take the postdoc. I have not told him about the other two.
```

## A3 Agent 构成

立场是**强制绑定**的，改不了（`stance.py` `STANCE_ASSIGNMENTS`）：
A=`growth_centered` / B=`stability_centered` / C=`life_centered`。
能配的是决策风格、情绪、数量、名字。

| Agent | 立场（锁死） | 决策风格 | 情绪 | 在图里的作用 |
|---|---|---|---|---|
| A | Growth | **Spontaneous** | Joy，中低强度 | 快速押注、早早表态 → 撑起 for 栏 |
| B | Stability | **Rational** | Fear，中低强度 | 结构化拆解代价 → 撑起 against 栏 |
| C | Life | **Intuitive** | Surprise 或默认 | 一句话重构问题 → 出好引文（引文上限 20 词） |

不建议三个都 Rational：话都长得一样，teaser 里看不出"沿决策风格分化"这条卖点。
如果跑出来 A 的内容太薄，把 A 换成 Rational 再跑一遍。

## A4 依次输入的 8 句（括号里是这句要打中的卡）

1. ```
   I finish my PhD in March and I have three offers on the table. I keep going back and forth — I am afraid I will regret whichever one I pick.
   ```
   → `growth_affective_forecasting`（"regret"）

2. ```
   If I take the Singapore research scientist job, can I ever come back to academia? Or is that a one-way door?
   ```
   → `stability_reversibility` + `growth_academia_vs_industry_comp` ← **这句最关键**，
   一句话同时点燃 growth 和 stability 两个卡池，是三个 agent 第一次真正对立的地方

3. ```
   @B I want to hear you specifically on the contract side — the 3-year lab contract and the 2-year visa. Which one actually leaves me more exposed?
   ```
   → `stability_contract_pitfalls`；**第一次 @ 点名**，timeline 视图靠这个才有 mention 边

4. ```
   My partner has her own design career in Tokyo. Moving to Singapore means we live apart for at least two years.
   ```
   → `life_relocation_family_impact` + `life_partner_career`

5. ```
   Compare the Kyoto one against the Shibuya one for me. What does each actually cost me?
   ```
   → 用选项的**特征词**（Kyoto / Shibuya）提问，`turn_summaries` 才能把 stance 绑到
   正确的 `option_id`，for/against 两栏才填得进去

6. ```
   @A you keep pushing the PI track, but I have watched people stay postdocs for six years. What makes you think that will not be me?
   ```
   → `growth_promotion_plateau`；**第二次 @ 点名**，而且是**质疑**，容易触发
   `[MOVE] challenge` → `map_facts` 把它记成 `opposes` 边（红/虚线，图上最好看的那种）

7. ```
   Honestly the salary gap is 4.7 million yen a year. Am I being naive putting research autonomy above that?
   ```
   → `life_income_adaptation` + `stability_financial_buffer`

8. ```
   Say I go with the postdoc, the way I am leaning right now. What am I giving up that I will not be able to get back?
   ```
   → **收尾必问**。逼出对"倾向选项"的 concern 条目，保证 against 栏非空

跑完这 8 句，用户回合数 = 8，`MODERATOR_USER_TURN_INTERVAL=2` → moderator 跑过 4 次，
足够推进到 Narrowing/Convergence，倾向条才会显示"讨论倾向于 X"。

---

# B · 育儿场景

## B1 Profile

| 字段 | 填 |
|---|---|
| age | `42` |
| child_age | `14` |
| child_count | `1` |
| parenting_style_baseline | `mixed` |
| child_autonomy_baseline | `medium` |
| communication_habit | `occasional` |
| past_conflict_pattern | `We argued last year about whether he should sit the grade exam. I gave in, but he barely talked to me about school for two months afterwards.` |

## B2 Scenario Intake

**decision_topic**
```
Whether to stop the piano lessons he has taken for six years
```

**decision_owner** → `joint`

**child_stated_preference**
```
He says he wants the practice time for basketball tryouts, and that he does not hate piano but will not sit another grade exam.
```

**parent_stated_concern**
```
I worry he will regret it later, and that this becomes the precedent for quitting whenever something gets hard. Six years of fees and my own hours are also in it.
```

**disagreement_exists** → `yes`

**urgency**
```
Next term's fees are due at the end of this month and are non-refundable once paid.
```

**external_input**
```
His teacher says he has real ability but has not progressed in two years. His father thinks stopping is fine.
```

## B3 关键差异：**必须在第一条发言里把选项列出来**

育儿场景的 `scenario_templates/parent_child.json` **没有 `options` 字段**，
`seed_intake()` 拿不到东西，选项卡只能从 agent 的 `[OPTIONS]` 提案里长出来。
所以第一句必须把三个做法说死，让 agent 的提案有东西可对齐：

```
He has played piano for six years and now wants to stop. I am weighing three things:
keep the two lessons a week as they are; stop completely; or cut to one lesson a week
with a different teacher who does not push grade exams. Fees are due at the end of the month.
```

## B4 Agent 构成

立场锁死：A=`child_centered` / B=`parent_centered` / C=`relationship_centered`。

| Agent | 立场 | 决策风格 | 情绪 |
|---|---|---|---|
| A | Child | **Intuitive** | 默认 |
| B | Parent | **Rational** | Fear，中低 |
| C | Relationship | **Dependent** | 默认 |

C 用 Dependent（consensus-oriented）是刻意的：它会不断把问题推回给用户和另外两个 agent，
产生大量 @ 提及 → timeline 视图的边会明显更密。

## B5 依次输入的 7 句

1. 上面 B3 那段（含三个选项）
2. ```
   He says the practice time should go to basketball tryouts instead. Is wanting to stop at fourteen his call to make?
   ```
   → `child_personal_jurisdiction` + `child_participation_voice`
3. ```
   @B six years of lessons and my own evenings are in this. Am I just protecting what I already spent?
   ```
   → `parent_academic_pressure` + `parent_financial_stress`；第一次 @ 点名
4. ```
   Every practice session ends in a row now. That is the part I actually cannot keep doing.
   ```
   → `relationship_conflict_normativity` + `relationship_warmth_structure`
5. ```
   His teacher says he has ability but has not progressed in two years. Everyone else in his year is still going.
   ```
   → `parent_intensive_norms` + `child_learning_motivation`
6. ```
   @A compare stopping completely against cutting to one lesson a week. What does he lose in each?
   ```
   → 第二次 @ 点名 + 用选项特征词逼出 per-option stance
7. ```
   If I let him stop, which is where I am leaning, what do I lose that I cannot get back?
   ```
   → 收尾，保证 against 栏非空

---

# C · 让决策图好看的 8 条（都对应代码里的具体常量）

1. **选项 ≤72 字符**。`LABEL_MAX=72`，超了从中间截断，卡片上会出现半句话。
2. **三个选项措辞互相拉开**。`SIM_THRESHOLD=0.5`，两条选项相似度过半会被合并成一张卡。
   别写 "Option A: Sony" / "Option B: Sony subsidiary"。
3. **全程咬住同一个决策问题**。一个"形状不同"的问题会开一条新轴（axis），而
   `option_board.py:375` 里 intake 轴排序值是 -1，会被对话新开的轴盖过去，图就散了。
4. **至少 8 个用户回合**。`MODERATOR_USER_TURN_INTERVAL=2`，phase 每 2 个**用户**回合
   才推进一次（agent 之间聊多少句都不算）。少于 8 句推不到 Convergence，顶部倾向条不会出现。
5. **用选项里的特征词提问**（"Kyoto 那个"、"停完全 vs 减到一节"）。
   `turn_summaries` 要靠这个把 `stances[].option_id` 绑对，绑不上 for/against 两栏就是空的。
6. **至少两次 @ 点名，其中一次是质疑**。@ 产生 mention 边；质疑容易让 agent 自报
   `[MOVE] challenge`，`map_facts.py:57` 把 challenge 记成 `opposes`——timeline 上唯一
   有颜色的边就是它，全是 neutral 的图很平。
7. **最后一句必须问"我这个倾向要放弃什么"**。论文写的是"选中的选项，代价要留在旁边"，
   不问就大概率是空的 against 栏。
8. **图开出来不满意就点 "Look closer"**。for/against 是 LLM 事后抽的
   （`turn_summaries.py`，`AGORA_SUMMARY_MODEL`），失败会退化成截断原文；重跑一次通常就好了。

---

# D · 可行性判断

**高，但有三处会翻车，且都能提前避免：**

| 风险 | 触发条件 | 规避 |
|---|---|---|
| 三张卡并成一张 | 选项措辞太像 | C-2 |
| 图散成多条轴 | 中途换了决策问题 | C-3 |
| for/against 全空 | 没用特征词提问 / summary 调用失败 | C-5、C-8 |

育儿场景额外多一层风险：**没有 intake options**，选项完全依赖 agent 提案，
所以 B3 那句必须一字不差地把三个做法说出来。如果 teaser 只做一个，**建议用就职**。
