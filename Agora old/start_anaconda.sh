#!/bin/bash
# Anaconda环境启动脚本 / Anaconda Environment Startup Script

echo "🚀 使用Anaconda环境启动服务器..."
echo "Starting server with Anaconda environment..."

# 使用Anaconda的Python
ANACONDA_PYTHON="/Users/ivrc23/anaconda3/bin/python"

# 检查Python是否存在
if [ ! -f "$ANACONDA_PYTHON" ]; then
    echo "❌ 错误: 未找到Anaconda Python"
    echo "Error: Anaconda Python not found"
    exit 1
fi

# 检查依赖
echo "📦 检查依赖..."
$ANACONDA_PYTHON -c "import flask" 2>/dev/null || {
    echo "⚠️  正在安装依赖..."
    $ANACONDA_PYTHON -m pip install flask flask-cors openai -q
}

# 启动服务器
echo "✅ 启动Web服务器..."
echo "✅ Starting Web Server..."
echo ""
echo "🌐 请在浏览器中打开: http://localhost:5000"
echo "🌐 Open in browser: http://localhost:5000"
echo ""
echo "按 Ctrl+C 停止服务器"
echo "Press Ctrl+C to stop the server"
echo ""

cd "$(dirname "$0")"
$ANACONDA_PYTHON app.py

