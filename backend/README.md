# Agora Backend (API only)

Flask HTTP API for the Agora multi-agent chatbot. The product UI is the React app in `../frontend` (Vite on port 5173).

## Quick start

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="your-api-key-here"
PORT=5001 python app.py
```

- API: `http://localhost:5001`
- Health: `http://localhost:5001/api/health`
- Frontend: from repo root, `cd frontend && npm run dev` → `http://localhost:5173`

## Project layout

```
backend/
├── app.py                 # Flask API
├── agentwake_new.py       # Multi-agent scheduler / prompts
├── requirements.txt
├── chatbot1.txt …         # Default agent role texts
├── scene.txt
├── emotion block/         # Emotion analysis helpers
├── new_module/new/        # Scenes, emotion, decision presets
└── logs/                  # Session logs (gitignored)
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service descriptor |
| POST | `/api/start` | Start a chat session |
| POST | `/api/message` | Send a message / get agent replies |
| GET | `/api/history/<room_id>` | Session history |
| GET | `/api/export-logs/<room_id>` | Export logs zip |
| GET | `/api/health` | Health check |
| POST | `/api/emotion/analyze` | Emotion analysis |
| GET | `/api/agent-prompt/<agent_key>` | Default agent prompt |

## Notes

- **对话自然度层**（`[MOVE]` 自报 / 定向共识预警 / 收敛门 / 文风约束 / 决策预设重写）见根目录
  `README.md` 的「分支说明：`feature/dialogue-naturalness`」一节。改 agent 行为前先读那里的
  忠实性契约：基准是 `Agora-2` 的 `776f5bf`，且 `agentwake_new.py` 里 `run_user_turn()`（web）
  与 `main()`（CLI）两条审议循环**必须同步修改**。
- This package no longer serves an HTML/CSS/JS UI. Old `static/` and `Assets/` were removed.
- Prefer `PORT=5001` when using the React frontend (see root README).
