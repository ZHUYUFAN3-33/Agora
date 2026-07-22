# Agora - 多智能体聊天机器人系统  
# Multi-Agent Chatbot System  
# マルチエージェントチャットボットシステム

---

## 如何运行 / How to Run / 実行方法

**终端 1 - 启动后端（API only）：**
```bash
cd backend
pip install -r requirements.txt
PORT=5001 python app.py
```

**终端 2 - 启动前端：**
```bash
cd frontend
npm install
npm run dev
```

在浏览器打开：**http://localhost:5173**（后端 API：`http://localhost:5001`）

在 **Chat 页面**（`/chat`）且**不在输入框内**时，按 **`x`** 进入/退出 **对话内手动标注**：在消息里选中文本后选择 **Decision Layer**、**Emotion Layer** 或 **Scene Layer**（Scene 高亮色 `#7BC3FF`）；**Esc** 可关闭未确认的选区弹层。标注模式打开时，顶栏有 **Clear all** 可清空当前会话内所有标注。切换会话也会清空标注状态。

---

### 论文配图（独立页面）

用于论文插图的标注示意（dummy 对话 + Decision / EXPRESSION 分层），按 **`x`** 切换标注显示：

```bash
cd paper
npm install
npm run dev
```

默认端口若与主前端冲突，可执行：`npm run dev -- --port 5174`。

---

## 项目简介 / Project Description

基于 OpenAI API 的多智能体协作对话系统，用于多场景共创与决策实验（电脑购买只是其中一个测试场景，不是唯一目标）。系统通过可配置的 Agent 角色、情绪层与决策层来观察不同协作策略下的讨论路径与结论质量。

默认示例中，三个 AI 代理从不同角度提供建议：

- **ChatbotA** 🔥 — 兴奋急躁：推动快速决策
- **ChatbotB** 🧠 — 冷静分析：理性分析、长期价值
- **ChatbotC** 🛡️ — 怀疑节俭：质疑必要性、防止冲动消费

### 实验模式

- **Full**：完整 persona / emotion / decision，可在自定义面板中调整名称、颜色、情绪、决策风格和附加提示。
- **Limited**：先从 6 个 preset profile 中选 3 个进入对话；界面只开放基础显示项，但后端仍使用与 Full 相同的多 Agent 调度器。
- **Single**：单 Agent，中立风格，直接返回一条回复，不进入多 Agent 调度。

### 当前调度说明 / Scheduler Notes

- **Full** 和 **Limited** 共用同一个后端 speaker scheduler；差异主要在可选 agent 池和前端可编辑项，不在调度器本身。
- 每次用户发言后，后端会在 `max_agent_turns_before_user` 与 `max_user_gap` 约束内连续生成多条 agent 回复。
- 当前版本加入了两条代码级约束：尽量避免同一个 agent 连续发言；同一轮 user turn 内优先轮到还没发言的 agent，再考虑重复发言。
- 当 moderator 判定 `stall=true` 时，会触发一次 burst 推进讨论；当前实现会跳过刚刚已经发言的 agent，避免它在 burst 里再重复说一遍。

---

## 理论基础 / Theoretical Grounding

### 情绪层（Emotion）

- 使用三维情绪空间：`Valence`（愉悦度）+ `Arousal`（唤醒度）+ `Control`（控制感）。
- 其中 `Control` 在理论上对应 PAD 模型中的 `Dominance` 维度。
- 系统采用“文本关键词 + 三维滑条中心点 + 概率融合”的混合判定方式，将状态映射到六类离散情绪：`joy / anger / fear / sadness / surprise / disgust`。

### 决策层（Decision）

- 使用五种决策风格：`Rational / Intuitive / Dependent / Avoidant / Spontaneous`。
- 该风格集合与 Scott & Bruce 的 General Decision-Making Style（GDMS）五维框架一致，用于控制 Agent 的“推理方式”而非“结论内容”。

> 说明：当前仓库实现为工程化落地版本，代码与提示词中采用了上述理论结构，但未在代码内显式附论文引用条目。

---

## 版本流程（参照 Fig.3）/ Version Flow Mapping

你的当前版本可按下面流程理解：

1. **Team Selection（选 Agent 组合）**  
   在会话开始时为每个 Agent 指定（或覆盖）`decision + emotion` 配置，形成团队分工。
2. **Discuss the Problem（进入问题讨论）**  
   用户输入问题后，多 Agent 在同一线程内基于各自风格协同回应。
3. **Thinking Mode（Explore / Focus）**  
   - **Explore**：发散探索，提出候选方向、补充维度与新假设。  
   - **Focus**：收敛整理，强调取舍、排序与可执行建议。
4. **Summary Recap（摘要回顾）**  
   通过结构化总结提炼关键观点与推荐路径（可用于对话回看和日志导出）。
5. **Facilitation（过程引导）**  
   当讨论停滞或分歧较大时，系统通过规则化提示推进下一步（例如要求明确取舍、降低风险或促成承诺）。

你和图中的差异重点是：图里强调“角色专家团队共创”，你这个版本进一步把每个 Agent 的行为拆成了可独立控制的 `Emotion Layer + Decision Layer`，所以更适合做可重复实验和消融对比。

---

## 项目结构 / Project Structure

```
Agora/
├── backend/             # Flask API only
│   ├── app.py           # HTTP API
│   ├── agentwake_new.py
│   ├── requirements.txt
│   ├── chatbot1-3.txt
│   ├── info.jsonl
│   ├── new_module/new/  # 多场景、emotion、decision 配置
│   └── logs/
├── frontend/            # React (Vite) UI
│   ├── src/
│   ├── public/
│   └── package.json
├── paper/               # 论文配图独立页
└── README.md
```

---

## 环境变量 / Environment Variables

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI API 密钥（可选，不设则使用内置默认） |
| `PORT` | 后端端口，默认自动选择 5000–5009；新版前端需 `5001` |

---

## API 端点 / API Endpoints

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/start` | 创建新对话 |
| POST | `/api/message` | 发送消息并获取回复 |
| GET | `/api/history/<room_id>` | 获取对话历史 |
| GET | `/api/export-logs/<room_id>` | 导出日志 zip |
| GET | `/api/health` | 健康检查 |

---

## 引导流程 / Onboarding Guide

新版 React 前端内置 7 步 welcome tutorial：

1. `Agents`
2. `Basic`
3. `Emotion`
4. `Behavior`
5. `Scene`
6. `Suggested Prompts`
7. `Input`

其中 `Basic / Emotion / Behavior` 会映射到 `Customize Agent` modal 内的三张 card；`Scene / Suggested Prompts / Input` 对应主界面区域。

---

## 注意事项 / Notes

1. **API 密钥**：请勿提交到版本控制
2. **费用**：使用 OpenAI API 会产生费用
3. **端口**：前端 (`frontend`) 默认连接 `localhost:5001`，需用 `PORT=5001` 启动后端
4. **后端重启**：`backend/app.py` 以 `use_reloader=False` 启动，修改后端调度逻辑后需要手动重启 Flask 服务，前端不会自动拿到新逻辑

---

## 技术栈 / Tech Stack

- **后端**：Python 3.8+, Flask, OpenAI API
- **前端（旧）**：HTML5, CSS3, JavaScript
- **前端（新）**：React, Vite, Tailwind, MUI, shadcn/ui
