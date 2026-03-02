# Agora - 多智能体聊天机器人系统  
# Multi-Agent Chatbot System  
# マルチエージェントチャットボットシステム

---

## 如何运行 / How to Run / 実行方法

### 方式一：新版 React 前端（推荐）

**终端 1 - 启动后端：**
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

在浏览器打开：**http://localhost:5173**

---

### 方式二：旧版静态前端

**单终端运行：**
```bash
cd backend
pip install -r requirements.txt
python app.py
```

后端会自动选择可用端口（5000–5009），在浏览器打开终端显示的地址（如 **http://localhost:5000**）。

---

## 项目简介 / Project Description

基于 OpenAI API 的多智能体对话系统，支持电脑购买咨询等场景。三个 AI 代理从不同角度为用户提供建议：

- **ChatbotA** 🔥 — 兴奋急躁：推动快速决策
- **ChatbotB** 🧠 — 冷静分析：理性分析、长期价值
- **ChatbotC** 🛡️ — 怀疑节俭：质疑必要性、防止冲动消费

### 实验模式

- **Full**：完整 persona / emotion / decision
- **Limited**：仅颜色与名称
- **Single**：单 Agent，中立风格

---

## 项目结构 / Project Structure

```
Agora/
├── backend/             # 后端 + 旧版静态前端
│   ├── app.py           # Flask API
│   ├── agentwake_new.py
│   ├── requirements.txt
│   ├── chatbot1-3.txt
│   ├── info.jsonl
│   ├── new_module/new/  # 多场景、emotion、decision 配置
│   ├── static/          # 旧版 HTML/CSS/JS
│   └── logs/
├── frontend/            # React 前端
│   ├── src/
│   ├── public/
│   └── package.json
├── config/              # 配置模块
├── agent-module/        # Agent 逻辑模块
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

## 注意事项 / Notes

1. **API 密钥**：请勿提交到版本控制
2. **费用**：使用 OpenAI API 会产生费用
3. **端口**：前端 (`frontend`) 默认连接 `localhost:5001`，需用 `PORT=5001` 启动后端

---

## 技术栈 / Tech Stack

- **后端**：Python 3.8+, Flask, OpenAI API
- **前端（旧）**：HTML5, CSS3, JavaScript
- **前端（新）**：React, Vite, Tailwind, MUI, shadcn/ui
