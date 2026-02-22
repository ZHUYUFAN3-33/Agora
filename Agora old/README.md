# 多智能体聊天机器人系统 / Multi-Agent Chatbot System

一个基于OpenAI API的多智能体对话系统，用于电脑购买咨询场景。三个AI代理从不同角度为用户提供建议。

## 📋 项目简介 / Project Description

这个系统包含三个具有不同性格的AI代理：
- **ChatbotA** 🔥 - 兴奋急躁的朋友：推动快速决策，强调行动和体验
- **ChatbotB** 🧠 - 冷静分析型顾问：提供理性分析，关注长期价值
- **ChatbotC** 🛡️ - 怀疑节俭的风险守卫：质疑必要性，防止冲动消费

## 🚀 快速开始 / Quick Start

### 1. 安装依赖 / Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥 / Configure API Key

编辑 `app.py` 文件，设置您的OpenAI API密钥：

```python
API_KEY = "your-api-key-here"
```

或者设置环境变量：

```bash
export OPENAI_API_KEY="your-api-key-here"
```

### 3. 运行Web服务器 / Run Web Server

```bash
python app.py
```

服务器将在 `http://localhost:5000` 启动。

### 4. 打开浏览器 / Open Browser

在浏览器中访问 `http://localhost:5000` 即可使用Web界面。

## 📁 项目结构 / Project Structure

```
chatbot项目-打包/
├── app.py                  # Flask Web API后端
├── requirements.txt        # Python依赖包
├── agent_wakeup_4o_e.py   # 核心多代理逻辑
├── agentgroup.py          # 多代理群聊（命令行版本）
├── agent1.py              # 单代理测试
├── env_context.json        # 环境配置（价格范围、品牌等）
├── chatbot1.txt           # Agent 1角色定义
├── chatbot2.txt           # Agent 2角色定义
├── chatbot3.txt           # Agent 3角色定义
├── scene.txt              # 场景描述
├── static/                # Web前端文件
│   ├── index.html         # 主页面
│   ├── style.css          # 样式文件
│   └── script.js          # JavaScript逻辑
└── logs/                  # 对话日志目录
```

## 🎯 使用方法 / Usage

### Web界面使用 / Web Interface

1. 点击"开始新对话"按钮
2. 输入您的问题（例如："我想买一台笔记本电脑，预算5000美元"）
3. 三个AI代理会自动回复，从不同角度提供建议
4. 继续对话，代理会根据上下文智能回复

### 命令行使用 / Command Line

如果您想使用命令行版本：

```bash
# 使用智能调度版本（推荐）
python agent_wakeup_4o_e.py

# 使用固定顺序版本
python agentgroup.py

# 单代理测试
python agent1.py
```

## 🔧 API端点 / API Endpoints

### POST `/api/start`
开始一个新的对话会话

**响应：**
```json
{
  "room_id": "123456",
  "message": "Chat session started",
  "agents": [...]
}
```

### POST `/api/message`
发送用户消息并获取代理回复

**请求：**
```json
{
  "room_id": "123456",
  "message": "我想买一台笔记本电脑"
}
```

**响应：**
```json
{
  "room_id": "123456",
  "user_message": "我想买一台笔记本电脑",
  "responses": [
    {
      "agent": "ChatbotA",
      "agent_key": "A",
      "message": "...",
      "time": "..."
    }
  ],
  "known_facts": [...]
}
```

### GET `/api/history/<room_id>`
获取对话历史记录

### GET `/api/health`
健康检查端点

## 📝 配置说明 / Configuration

### 环境上下文 (env_context.json)

- `price_range_usd`: 价格范围 [$800, $6000]
- `allowed_categories`: 允许的电脑类别
- `brand_pool`: 品牌池（办公、游戏、工作站等）
- `pricing_behavior_rules`: 定价行为规则

### 代理角色定义

- `chatbot1.txt`: Agent 1的11条行为规则
- `chatbot2.txt`: Agent 2的11条行为规则
- `chatbot3.txt`: Agent 3的10条行为规则

### 场景描述 (scene.txt)

描述对话场景和可用的电脑型号及价格范围。

## 🛠️ 技术栈 / Tech Stack

- **后端**: Python 3.8+, Flask, OpenAI API
- **前端**: HTML5, CSS3, JavaScript (Vanilla)
- **AI模型**: GPT-4o, GPT-5.2等（可配置）

## 📊 日志系统 / Logging

所有对话和思考过程都会记录在 `logs/` 目录：

- `{room_id}.jsonl` - 对话消息日志
- `{room_id}_thinkinglog.jsonl` - 管理员决策过程日志

## ⚠️ 注意事项 / Notes

1. **API密钥安全**: 请勿将API密钥提交到版本控制系统
2. **费用**: 使用OpenAI API会产生费用，请注意使用量
3. **网络**: 确保能够访问OpenAI API（可能需要代理）
4. **Python版本**: 建议使用Python 3.8或更高版本

## 🐛 故障排除 / Troubleshooting

### 无法连接到服务器
- 确保 `app.py` 正在运行
- 检查端口5000是否被占用
- 查看控制台错误信息

### API调用失败
- 检查API密钥是否正确
- 确认网络连接正常
- 查看OpenAI API状态

### 代理不回复
- 检查 `chatbot1.txt`, `chatbot2.txt`, `chatbot3.txt` 文件是否存在
- 确认 `scene.txt` 文件存在
- 查看服务器日志

## 📄 许可证 / License

本项目仅供学习和研究使用。

## 👥 贡献 / Contributing

欢迎提交Issue和Pull Request！

---

**Enjoy your multi-agent chatbot experience! 🚀**

