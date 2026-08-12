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
| GET | `/api/export-logs/<room_id>` | Export logs zip — **requires auth** (owner or admin) unless the room has no owner |
| POST | `/api/telemetry/<room_id>` | Client behavior events → `{room}_ux.jsonl` |
| POST | `/api/log-param-change` | Customizer changes → `{room}_params.jsonl` |
| GET | `/api/admin/export?user_id=` | Per-user bundle zip (admin) |
| GET | `/api/admin/rooms/<room_id>/export` | Per-room bundle zip (admin) |
| GET | `/api/health` | Health check |
| POST | `/api/emotion/analyze` | Emotion analysis |
| GET | `/api/agent-prompt/<agent_key>` | Default agent prompt |

## Per-room logs

One append-only file per concern, all written to `AGORA_DATA_DIR/logs/`:

| File | Records |
|------|---------|
| `{room}.jsonl` | the visible transcript |
| `{room}_thinkinglog.jsonl` | the scheduler — who speaks next and why |
| `{room}_moderator.jsonl` | phase/state classification |
| `{room}_rationale.jsonl` | per-turn moves, mentions, dropped turns |
| `{room}_memory.jsonl` | memory snippet chains |
| `{room}_config.jsonl` | effective agent config — which condition produced this room |
| `{room}_params.jsonl` | what the user changed in the customizer (a diff log) |
| `{room}_generation.jsonl` | one row per LLM call: tokens, latency, status, refusals |
| `{room}_novelty.jsonl` | repetition-guard scores and keep/drop decisions |
| `{room}_ux.jsonl` | client behavior: map dwell, chip clicks, composer timing |

Plus derived artifacts (`_decision_map`, `_option_board`, `_turn_summaries`,
`_choices`, `_summary_meta`). Every export ships a `README.txt` documenting all of
them field by field — see `export_bundle.py`.

Adding a log means adding one row to `SESSION_LOG_FILES` (app.py) and one to
`ROOM_ARTIFACTS` (export_bundle.py); opening, closing, exporting and deleting all
follow from those two lists.

## Notes

- This package no longer serves an HTML/CSS/JS UI. Old `static/` and `Assets/` were removed.
- Prefer `PORT=5001` when using the React frontend (see root README).
