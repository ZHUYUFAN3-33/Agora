#!/bin/bash
# 启动脚本 / Startup Script

echo "🚀 启动多智能体聊天机器人系统..."
echo "Starting Multi-Agent Chatbot System..."

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到Python3，请先安装Python"
    echo "Error: Python3 not found, please install Python first"
    exit 1
fi

# 检查依赖是否安装
echo "📦 检查依赖..."
if ! python3 -c "import flask" 2>/dev/null; then
    echo "⚠️  正在安装依赖..."
    pip3 install -r requirements.txt
fi

# 启动服务器
echo "✅ 启动Web服务器..."
echo "✅ Starting Web Server..."
echo ""
echo "🌐 请在浏览器中打开: http://localhost:5000"
echo "🌐 Open in browser: http://localhost:5000"
echo ""
python3 app.py

