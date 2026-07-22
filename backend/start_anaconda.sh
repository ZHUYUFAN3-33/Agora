#!/bin/bash
# Start Agora API with a local Anaconda Python (machine-specific path)

echo "Starting Agora API with Anaconda Python..."

ANACONDA_PYTHON="/Users/ivrc23/anaconda3/bin/python"

if [ ! -f "$ANACONDA_PYTHON" ]; then
    echo "Error: Anaconda Python not found at $ANACONDA_PYTHON"
    exit 1
fi

$ANACONDA_PYTHON -c "import flask" 2>/dev/null || {
    echo "Installing dependencies..."
    $ANACONDA_PYTHON -m pip install flask flask-cors openai -q
}

export PORT="${PORT:-5001}"
echo "API: http://localhost:${PORT}"
echo "Health: http://localhost:${PORT}/api/health"
echo "Frontend: cd ../frontend && npm run dev → http://localhost:5173"
echo ""

cd "$(dirname "$0")"
$ANACONDA_PYTHON app.py
