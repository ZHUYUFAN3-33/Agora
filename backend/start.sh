#!/bin/bash
# Start Agora API server

echo "Starting Agora API..."

if ! command -v python3 &> /dev/null; then
    echo "Error: Python3 not found"
    exit 1
fi

if ! python3 -c "import flask" 2>/dev/null; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
fi

export PORT="${PORT:-5001}"
echo "API: http://localhost:${PORT}"
echo "Health: http://localhost:${PORT}/api/health"
echo "Frontend: cd ../frontend && npm run dev → http://localhost:5173"
echo ""
python3 app.py
