# Agora AI — 场景信息层 (Profile + Intake + Domain Background)

本目录实现之前讨论的三层信息架构，双语（中/英）全覆盖，并已接入 `agentwake_new.py`。
场景数据按场景类型拆成独立文件，新增场景时不用碰已有场景的文件。

## 文件清单

```
scenario_templates/
  employment.json       就职场景的 Profile + Scenario Intake 字段定义
  parent_child.json     亲子场景的 Profile + Scenario Intake 字段定义
background_templates/
  employment.json       就职场景的静态框架 + 针对性背景条目
  parent_child.json     亲子场景的静态框架 + 针对性背景条目
  stance_knowledge/     立场知识库卡片（关键词 + 双语正文 + 来源）
    employment.json / parent_child.json
scenes/                 场景描述文本，按场景 × 语言命名，终端切场景靠这个目录
  employment_zh.txt / employment_en.txt
  parent_child_zh.txt / parent_child_en.txt
decision/                Decision Style 预设槽位（已填好原始五个文件，新增风格时按名字加 txt 即可）
  Rational.txt / Intuitive.txt / Dependent.txt / Spontaneous.txt / Avoidant.txt
emotion/                 Emotion 预设槽位（已填好原始六个文件，新增情绪时按名字加 txt 即可）
  Joy.txt / Anger.txt / Fear.txt / Sadness.txt / Disgust.txt / Surprise.txt
lang_utils.py            语言判定（detect_lang）、双语取值（pick）、公共区块标题文案
profile_store.py         User Profile 持久化存取、Scenario Intake 交互式收集、KNOWN USER CONTEXT 拼装
scenario_background.py   Domain Background 匹配逻辑与 DOMAIN BACKGROUND 拼装
stance.py                Stance 维度：强制绑定表、双语立场文本、Convergence 阶段权重提示
stance_knowledge.py      关键词触发的立场知识库（纯本地字典，零网络/零LLM）
session_memory.py        跨会话记忆：读取/拼接/生成/追写 memory/{user_id}__{scenario_type}.jsonl
agent_assembly.py        组装接口：拼接 decision + emotion（+ stance + hint 预加载知识）成一个固定 agent
agora_context.py         对外唯一入口 prepare_session_context()，串联上面两个模块
agora2_http.py           Flask 适配层：hint / memory / per-scenario profile / session_update
agentwake_new.py         已 patch 的主脚本（含 session_memory_text / preloaded_knowledge 注入）
README.md                本文件
```

## Hint + Stance Knowledge（HTTP / 产品路径）

- 前端一个选填输入框 → `POST /api/start` 的 `hint`
- 同一句话写入 A/B/C 的 agent config；`agent_assembly` 用 hint 查该 agent 立场知识库
- 命中则预加载 `BACKGROUND (from setup)`（整场固定）；不命中则不注入
- 每轮用户最新发言另走动态通道（`stance_knowledge_on_hit`），与 hint 独立共存

## 跨 Session Memory（HTTP / 产品路径）

- 身份：`user_id` + `scenario_type`
- 存储：`memory/{user_id}__{scenario_type}.jsonl`（gitignored）
- 读：`/api/start` 时加载最近 3 条注入 system prompt；`GET /api/agora2/memory` 供 UI 显示 Session N / 历史
- 写：用户触发 Decision summary 成功后，额外一次 LLM 归档 `summary` + `open_threads`（用户无感）
- 二次及以后会话：前端短表单 `session_update`（距上次新情况）并入 known context


每个场景的 `scenario_templates/{scenario_type}.json` 和 `background_templates/{scenario_type}.json`
都是独立的 json 文件（不再是一个大文件里嵌套多个场景 key），字段结构与内容和之前版本完全一致，只是拆开存放。

## Agent 组装接口（agent_assembly.py）

之前 `chatbot1/2/3.txt` 是手工把 emotion.txt + decision 风格.txt 的内容拼进去的，代码不做校验、
容易和 `info.jsonl` 里写的标签对不上。`agent_assembly.py` 把这个拼接过程变成代码：

```python
from agent_assembly import build_all_agent_specs

specs = build_all_agent_specs(agent_configs, scenario_type="employment", lang="zh")
# specs["A"] = {
#   "agent_key": "A", "decision": "Rational", "emotion": "Joy",
#   "role_text": "<decision+emotion 拼好的完整文本>",
#   "stance": "growth_centered",
#   "stance_text": "<该立场的指令文本>",
# }
```

**预设槽位**：`decision/` 和 `emotion/` 两个根目录文件夹，`agent_assembly.py` 按 `info.jsonl` 里的
`decision`/`emotion` 名字去这两个文件夹找同名 `.txt` 文件拼接。两个文件夹已经放好你最初上传的全部
文件，不用重新配置；以后新增决策风格或情绪，只需要把对应命名的 txt 丢进对应文件夹，`info.jsonl`
里引用得上就能用，不用改代码。如果引用了一个还没放文件的名字，拼出来的文本里会有一行醒目的
`[MISSING PRESET: decision/xxx.txt — ...]`，不会静默出错。

**stance 为什么单独放，不直接拼进 role_text**：decision/emotion 是纯静态的，跟场景无关；stance 虽然
在某个场景内也是静态的，但它依赖 `scenario_type`，且 Convergence 阶段的权重提示还依赖 Scenario Intake
（那时候 role_text 早就拼好了）。所以 `build_agent_spec()` 把 `role_text`（decision+emotion）和
`stance_text` 分开返回，`agentwake_new.py` 里 `role_text` 走 `ChatAgent.role_text`（一次性写死），
`stance_text` 继续走原来的动态注入通道（`system_prompt()` 的 `YOUR STANCE` 区块），避免同一段
stance 文字在 prompt 里出现两次。

在 `agentwake_new.py` 里通过 `--assemble_roles` 开启（默认关闭，行为等价于原来的 `--bot1/2/3`）：

```bash
# 用预设槽位现场拼装 role_text，而不是读 chatbot1/2/3.txt
python agentwake_new.py --scenario_type employment --user_id luoyu --lang zh --assemble_roles

# 预设文件夹路径也可以自定义
python agentwake_new.py --assemble_roles --decision_dir my_decision --emotion_dir my_emotion
```

单独预览某个 agent 拼出来的样子（不启动群聊、不调用 API）：

```bash
python agent_assembly.py --decision Rational --emotion Joy --scenario_type employment --agent_key A
```

## Stance 维度（就职 + 亲子）

`stance.py` 实现的是"强制绑定"，不是自由配置：

```python
STANCE_ASSIGNMENTS = {
    "parent_child": {"A": "child_centered", "B": "parent_centered", "C": "relationship_centered"},
    "employment":   {"A": "growth_centered", "B": "stability_centered", "C": "life_centered"},
}
```

`main()` 加载完 `info.jsonl` 之后，如果 `--scenario_type` 命中这张表，会**无条件覆盖** `agent_configs[*]["stance"]`，
不读、也不校验 `info.jsonl` 里原本写了什么。没在表里的场景类型（比如以后新增的单人决策场景）不会有 stance，
`assign_stance()` 返回 `None`，`ChatAgent.system_prompt()` 里的 `YOUR STANCE` 区块直接跳过。

Convergence 阶段还会额外注入一句权重提示，数据来源不需要新增字段，直接复用已收集的 intake：
- 亲子场景：读 `decision_owner`（家长主导 / 孩子主导 / 共同决定），决定三个 stance 在收尾阶段谁的话语权更高
- 就职场景：读 `priority_ranking`，按 `PRIORITY_TO_STANCE` 关键词表（中英文关键词都收录）判断用户排的优先级
  里有没有命中某个 agent 的立场、排第几，命中靠前则该 agent 收尾阶段权重更高，完全没命中则提示它"这正是你
  存在的意义，主动把被忽略的维度摆回桌面"

## 场景切换（终端）

不需要专门的"切换命令"，`--scenario_type` 和 `--lang` 这两个参数本来就要传，场景描述文件跟着它们自动选：

```bash
# 就职场景 · 中文 -> 自动读 scenes/employment_zh.txt
python agentwake_new.py --scenario_type employment --lang zh --assemble_roles

# 亲子场景 · 英文 -> 自动读 scenes/parent_child_en.txt
python agentwake_new.py --scenario_type parent_child --lang en --assemble_roles
```

解析优先级：显式传 `--scene 路径` 永远优先（用来跑自定义场景描述）；不传且给了 `--scenario_type` 时，
按 `scenes/{scenario_type}_{lang}.txt` 自动找；两者都没给，退回旧脚本的默认值 `./scene.txt`（完全兼容原来的用法）。

```bash
# 想用自己写的场景描述，绕过自动匹配
python agentwake_new.py --scenario_type employment --scene my_custom_scene.txt --assemble_roles
```

新增第三个场景时，在 `scenes/` 下补两个文件（`{新场景名}_zh.txt` / `{新场景名}_en.txt`）就行，
不用改 `agentwake_new.py`。

## 安装依赖

```bash
pip install -r requirements.txt
```

`openai` / `requests` 是调用 API 用的；`tzdata` 只在 Windows 上需要——`zoneinfo` 在 Windows 上
不自带 IANA 时区库，缺它的话 `ZoneInfo("Asia/Tokyo")` 会抛 `ZoneInfoNotFoundError`。这行代码在
模块顶层执行，所以缺包时整个脚本连 import 都过不去。现在加了兜底：找不到时区数据会打一条
warning 并退回系统本地时间，只影响日志时间戳，不会阻止脚本运行——但日志时间会不是东京时间，
所以还是建议按上面装全。

信息层那几个模块（`agora_context.py` / `profile_store.py` / `scenario_background.py` /
`agent_assembly.py` / `stance.py`）不依赖任何第三方包，单独测试时不装也能跑。

## 运行方式

```bash
# 中文，就职场景
python agentwake_new.py --scenario_type employment --user_id luoyu --lang zh

# 英文，亲子场景
python agentwake_new.py --scenario_type parent_child --user_id someone --lang en

# 不启用信息层（旧行为，等价于之前的脚本）
python agentwake_new.py
```

启动后会先在终端走一遍 Profile 确认（老用户展示已存数值，回车即保留）与 Scenario Intake 收集，
结束后正式进入群聊循环，`KNOWN USER CONTEXT` 与 `DOMAIN BACKGROUND` 两个区块会被自动注入所有 agent
的 system prompt，且在 `get_phase_context()` 追加了不重复提问 / 不滥用背景知识的约束。

用户数据存储在 `profiles/{user_id}.json`，包含持久 `profile` 字段和逐次 `session_history`，下次用
同一个 `--user_id` 运行时会自动读取并进入确认流程，而不是重新问一遍。

## 跳过填写：预设好的测试数据

`profiles/` 和 `intake_examples/` 下已经放好了两个场景 × 两种语言的完整示例数据，测试时不用手动打字：

```
profiles/
  demo_employment.json       就职场景示例 Profile（中文内容）
  demo_employment_en.json    就职场景示例 Profile（英文内容）
  demo_parent_child.json     亲子场景示例 Profile（中文内容）
  demo_parent_child_en.json  亲子场景示例 Profile（英文内容）
intake_examples/
  employment_zh.json / employment_en.json
  parent_child_zh.json / parent_child_en.json
info_example.jsonl           三个 agent 的示例 decision+emotion 标签
```

两个新增开关组合起来就能做到零输入跑通全流程：

- `--auto_confirm_profile`：Profile 里已经有值的字段不再询问，直接静默使用；只有例子里没填的必填项
  才会退回正常提问（示例数据都是全的，所以正常不会触发）
- `--intake_file 路径`：Scenario Intake 直接从这个 json 读，不走交互式提问

```bash
# 就职场景，中文，零输入
python agentwake_new.py \
  --scenario_type employment --user_id demo_employment --lang zh \
  --assemble_roles \
  --info info_example.jsonl \
  --auto_confirm_profile --intake_file intake_examples/employment_zh.json

# 亲子场景，英文，零输入
python agentwake_new.py \
  --scenario_type parent_child --user_id demo_parent_child_en --lang en \
  --assemble_roles \
  --info info_example.jsonl \
  --auto_confirm_profile --intake_file intake_examples/parent_child_en.json
```

跑完这两行会直接打印 `Chat room id` 和 `Agents: A=... B=... C=...`，紧接着进入群聊——如果只是想看
`KNOWN USER CONTEXT` / `DOMAIN BACKGROUND` 拼出来什么样、不想启动群聊，用下面这条不会触发 API 调用：

```bash
python agora_context.py --user_id demo_employment --scenario_type employment --lang zh \
  --auto_confirm_profile --intake_file intake_examples/employment_zh.json
```

**踩过的坑，顺手记一下**：`auto_confirm_profile` 一开始对"值是空字符串"的可选字段处理有误——
把空字符串当成"没填"，于是照样跳出交互提问，在非交互环境下会卡住等待输入。已修复：可选字段哪怕是
空值，`auto_confirm_profile` 下也会跳过，不再触发提问。另外亲子场景的 Domain Background 原本按
`child_age` 匹配年龄区间，但 `child_age` 实际存在 Profile 层而不是 Scenario Intake 层，`agora_context.py`
只把 intake 传给匹配函数，导致一直匹配不中、只能落到 fallback 文案。现在改成把 Profile 和 Intake
合并后再做匹配，两层任何一层的字段都能命中。这两处都已经在这版代码里改掉，示例数据也是照着
修好之后的版本验证过的。

## 单独测试某一层

```bash
# 只测 Profile+Intake 收集，不启动群聊
python profile_store.py --user_id luoyu --scenario_type employment --lang zh

# 只测 Domain Background 匹配（不需要交互输入）
python scenario_background.py

# 测完整流程（Profile+Intake+Background）
python agora_context.py --user_id luoyu --scenario_type parent_child --lang en
```

## 扩展新场景

1. 在 `scenario_templates/` 下新建 `{新场景名}.json`，写 `profile_fields` / `scenario_fields`（每个字段的
   `question` 必须是 `{"zh": ..., "en": ...}`），结构参考 `employment.json` / `parent_child.json`。
2. 在 `background_templates/` 下新建同名 `{新场景名}.json`，写 `static_framework` / `targeted_entries` /
   `fallback_text`，决定 `match_type` 是 `"keyword"` 还是 `"age_range"`（如需第三种匹配方式，在
   `scenario_background.py` 里加一个 `_match_xxx` 函数并在 `get_scenario_background()` 里分发）。
3. 在 `agentwake_new.py` 的 `--scenario_type` 参数 `choices` 里加上新场景名。
4. 如果新场景也涉及多方视角/多重优先级（不是单一决策者），在 `stance.py` 的 `STANCE_ASSIGNMENTS` 和
   `STANCE_PROMPTS` 里加一组三档 stance；如果是单一决策者场景（像原来的就职场景那样），跳过这一步，
   `assign_stance()` 会自动返回 `None`，不启用 stance。

不需要改 `profile_store.py` / `agora_context.py` / `ChatAgent.system_prompt()` 本身，也不需要碰其他
场景已有的文件。

## 对话质量：无效信息治理

早期实跑（`logs/442575.jsonl`）的问题是信息密度极低：8 条 agent 发言里 5 条是复述，
平均每条 1.88 个问题、100% 以问句结尾且从没人回答，全程零分歧。用 `transcript_report.py`
量化后定位到六个原因，逐个改掉：

**1. 主持人从来没跑起来（根因）**
`run_moderator()` 原本只在 `user_turn()` 里按用户发言数触发（每 3 次）。但 `--prefer_agents`
默认 0.85，用户大约 8~9 行才发一次言，凑够 3 次要到 25 行之后——两个 moderator 日志都是空的。
后果是 `moderator_state` 全程停在初始的 `Exploration`，40 条 `PHASE_PROMPTS` 里只有
`Exploration/S/*` 五条被用到，Structuring / Narrowing / Convergence、stall 检测、Convergence
阶段的 stance 权重提示**全是不可达代码**。每个 agent 每轮拿到的都是同一句"需求不清楚就提问"，
所以它们就一直提问。

现在改成按**总轮次**计（`MODERATOR_TURN_INTERVAL = 4`，agent 和用户发言都算），
`maybe_run_moderator()` 在 `agent_turn()` 和 `user_turn()` 末尾都调用。超过 stall 阈值后
按 `MODERATOR_STALL_RECHECK = 2` 加密复查，但不会每行都跑（那等于每条发言多一次 API 调用）。

**2. 提问按阶段限额** —— 新增 `QUESTION_BUDGET` 表。提问在选项空间还开着的时候有用、到了该收敛
的时候纯属有害，所以额度绑定阶段：Exploration/Structuring 最多一问且有条件，Narrowing/Convergence
**禁止向其他 agent 提问**，只能表态。同时删掉了 system prompt 里"Often ask another bot a direct
question"和那六个提问句式示例——那是问句泛滥的直接来源。

**3. 新增信息契约 + 程序侧兜底** —— system prompt 里明确列出五类合格贡献（新维度／引用具体用户信息／
两选项在某维度上的具体比较／排除某选项并给理由／直接反驳某个具体主张），并允许"确实没有新东西"时
一句话表态然后闭嘴。光靠 prompt 不够（模型服从几轮就会滑回去），所以 `novelty_ratio()` 给每条回复
打分，低于 `--novelty_threshold` 就带纠正指令重试一次，**只有重试分数更高才采纳**。

**4. 强制消费已收集的信息** —— 原来 prompt 只说"别重复问 KNOWN USER CONTEXT 里有的东西"，
结果 deadline、priority_ranking、options 里的薪酬职级全程一个字没用上，讨论只围着"离家远近"打转。
现在要求每条消息必须点名引用至少一条具体的用户信息，并明确"换成任何用户都成立的说法不算贡献"。

**5. 防止过早合流** —— 三个 agent 带着三种被强制绑定的立场，第 5 轮就集体倒向同一个选项，
连本该为另一选项辩护的 growth_centered 都在说"两个选项各有各的好"。stance 文本里写了"要指出冲突"
但没有任何东西强制它。现在 stance 区块补了一句"这不是可以为了和气让渡的偏好"，并且
`has_disagreement()` 检测最近若干条发言是否毫无分歧，是则往下一轮任务里插入 CONSENSUS WARNING。

**6. 语言指令** —— `system_prompt()` 从头到尾没有一句告诉 agent 用什么语言回答，`--lang` 只影响
intake 问题和区块标题，所以 `--lang zh` 跑出来是英文夹中文公司名。现在按 `--lang` 注入 LANGUAGE 行。

**保留的**：情绪表达是人格载体，没有禁掉，只是要求"情绪长在论证里而不是独立成句"，并且同一个情绪
措辞不能在一场会话里重复第二次（原日志里 ChatbotB 两次"This feels heavy"）。另外提问和称呼统一
改成 `@ChatbotB` / `@U` 形式。

### transcript_report.py

```bash
python transcript_report.py logs/442575.jsonl                  # 单个日志打分
python transcript_report.py logs/442575.jsonl logs/新日志.jsonl  # 改动前后对比
```

输出每条发言的 novelty / 问句数 / @ 数 / 是否分歧，以及整体的平均新增信息量、复述占比、
每条问句数、以问句结尾比例、分歧比例。它复用 `agentwake_new.py` 里同一套打分函数，
所以报告和运行时的判据不会漂移。

### 关于 --novelty_threshold 的诚实说明

阈值是在 `logs/442575.jsonl` 上**实测标定**的，不是拍脑袋定的：明显复述的消息落在 0.19~0.44，
真正有新内容的落在 0.55~0.69，默认值 0.35 取在这个间隔里偏保守的一侧。

两个已知局限，用之前需要知道：

- **它测的是词汇复用，不是语义复述。** 第一版把评价性词汇（better / crucial / invaluable / richer）
  算作新内容，导致复述消息也能拿 0.31~0.48 分——这类褒贬词是无限可再生的，说了等于没说，
  已经加进停用词表。但换一批同义词仍然骗得过它，所以这只是**兜底**，不是精确分类器；
  真正防重复的主力是主持人推进阶段 + 提问限额。
- **标定样本是英文的。** 现在补了语言指令、实跑会走 `--lang zh`，中文走的是 CJK 二字组路径，
  这条路径还没有用真实输出验证过。跑完第一场中文会话请用 `transcript_report.py` 重新看一遍
  分数分布再调阈值。

`has_disagreement()` 的关键词表同样是标定过的：第一版收了 however / overlook / downside /
trade-off，结果在原日志上误判了两条本质是附和的消息（"let's not overlook 乙公司's potential"
是软性补充不是反对），导致 CONSENSUS WARNING 在一场全是共识的会话里一次都没触发。现在只收
明确表达对立的说法。这里是**故意从严**的：漏判只多一次冗余提醒，误判则等于这个机制失效。

## 给用户看的决策走向总结：transcript_summary.py

和 `transcript_report.py` 分工不同：那个是**开发者工具**，打的是消息质量分（复述率 / 问句 /
分歧），用来调阈值和做前后对比；这个是**给用户看的**，回答一个问题——**这场讨论最后倒向哪边、
为什么、什么还没定**。所以里面刻意不出现 novelty 这类内部指标，也不做逐条会议记录。

```bash
python transcript_summary.py logs/004707.jsonl                        # 中文（默认）
python transcript_summary.py logs/004707.jsonl --lang en              # 英文
python transcript_summary.py logs/004707.jsonl --out logs/004707_summary.md
```

只有这三个参数。模型和温度是文件顶部的两个常量（`MODEL` / `TEMPERATURE = 0.3`，比群聊的 0.8
低——这是整理归纳，不需要人格发挥），要换在那里改，不做成命令行选项：用户不该为了看一份总结
先去选模型。

报告结构（第二人称写给用户，结论放最上面）：

```
> 倾向选择甲公司                     ← 走向本身，一句话，打开就能看到
把握程度：倾向 ●●○ —— 谁支持、谁没表态、你有没有确认过
支撑这个走向的理由 / 反面仍然站得住的理由 / 你在其中的位置
走向是怎么形成的                     ← 过程只保留：每个阶段倾向往哪动了、被哪句话推动
什么会把这个结论翻过来 / 只能由你决定的
```

**把握程度只有三档**（明确 ●●● / 倾向 ●●○ / 未定 ●○○），模型只能在这三个词里选，并且必须
说明理由。这一档是整份报告最关键的部分：三个 agent 的"结论"很可能只是其中一位单方面推的，
用户没确认过——不标出来，用户会以为事已经定了。

**刻意保留的两个"不好听"的部分**：`反面仍然站得住的理由`（讨论里没被正面回应的反方论据）和
`你在其中的位置`（你到底有没有确认过这个走向）。prompt 里还明确要求：如果讨论根本没有分出
方向，就写"没有形成明确走向"，不许硬凑结论；建议只能来自记录里已经浮现的内容，不许自己发明。
这个脚本的作用是让你看清走向和它有多脆，不是替你做决定。

**阶段切分是确定性的，不是让模型猜的**：脚本读同一个房间的 `{room}_moderator.jsonl`，按
`admin3_state_change` 的时间戳去切 `{room}.jsonl`，所以分段就是这些消息产生时主持人真实所处的
阶段。内部状态名会翻成用户能看懂的说法（Exploration → 摊开问题，Structuring → 梳理与比较，
Narrowing → 缩小范围，Convergence → 形成结论）。

像 `logs/442575.jsonl` 这种主持人没跑起来、moderator 日志为空的旧记录，不会硬编一套阶段边界，
而是整场作为一段处理并在"讨论经过"下注明。没有 API key 或断网时不会甩 traceback，只打印一行
说明为什么没生成。

“接下来可以做的”被限制为只能来自记录里已经浮现、但没被回答的问题，不允许模型自己发明建议——
这份总结的作用是梳理讨论，不是替用户做决定。

## 目前还没做的部分（如实说明）

- **Emotion 的四滑杆重新设计**：`agent_assembly.py` 解决的是"把六个情绪 txt 文件正确拼进 role_text"
  这个工程问题，emotion 本身内容仍是最初的 Ekman 六类静态文本。讨论过的四维度滑杆设计
  （Formality / Warmth / Energy / Expressiveness）和 `EMOTION_PRESETS` 映射表还没有写成正式模块，
  也没有接入代码——如果以后要做，`emotion/` 这个预设文件夹和 `agent_assembly.py` 的读取逻辑不用动，
  只需要把六个 txt 文件的内容换成按滑杆生成的新文本即可，是内容层面的替换，不是结构层面的重做。
- **Decision（决策风格）维度**：按讨论结论保持不变，继续用原始的五个 txt 文件（GDMS 五分类），
  不是"待完成"，是设计上确定不改。

## 双语行为说明

- `--lang zh|en` 决定：问题文案、选项标签、区块标题、缺省提示（"未填写" / "not provided"）显示成哪种语言。
- 关键词匹配（就职场景 `decision_field`）的关键词列表里中英文关键词都收录了，用户无论用中文还是
  英文填写行业名称都能命中同一条 targeted entry。
- `lang_utils.pick()` 对任何双语字段做了 fallback：如果某条目缺失当前语言，会退回另一种语言而不是
  留空，避免因为个别条目漏填导致区块内容缺失。
- `detect_lang()` 提供了一个轻量启发式（基于中文字符占比），如果以后想根据用户第一次输入自动判断
  语言而不是依赖显式 `--lang` 参数，可以用它做默认值探测；当前主脚本走的是显式参数，未默认启用。
