# Agora

Multi-agent chat for co-creation and decision experiments (OpenAI API).  
多智能体协作对话系统。  
マルチエージェント協働チャットシステム。

Current focus: **English UI** + **Agora-2 scenarios** (Employment, Parent-Child) with profile/intake before chat. Flask is **API-only**; the React app is the UI.

---

## How to run / 如何运行 / 実行方法

### 1. OpenAI key

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and set a real key:
# OPENAI_API_KEY=sk-...
```

Do not commit `.env`. Chat will fail with 401 if the key is missing or invalid.

### 2. Backend (terminal 1)

```bash
cd backend
python3 -m venv ../.venv          # once
source ../.venv/bin/activate      # Windows: ..\.venv\Scripts\activate
pip install -r requirements.txt
PORT=5001 python app.py
```

Health check: http://localhost:5001/api/health

### 3. Frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**

Vite proxies `/api` → `http://127.0.0.1:5001`, so the browser can use same-origin `/api` (needed for Cloudflare Tunnel sharing).

### Optional: share while your Mac is on (Cloudflare Quick Tunnel)

Requires [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/). Keep backend + frontend running, then:

```bash
cloudflared tunnel --url http://localhost:5173
```

Share the printed `https://….trycloudflare.com` URL.  
**Limitations:** your machine must stay awake; restarting the tunnel changes the URL; this is not cloud hosting (no domain / Named Tunnel needed).

### Optional: paper figure page

```bash
cd paper
npm install
npm run dev -- --port 5174
```

In Chat (`/chat`), outside an input: press **`x`** for in-conversation annotation (Decision / Emotion / Scene layers); **Esc** closes an unconfirmed selection; **Clear all** clears annotations for the current session.

---

## What you get in the UI

1. Open Chat → pick a scenario card (**Employment** or **Parent-Child**).
2. Fill the **English intake** (profile + session fields).
3. Continue → `/api/start` with `lang: "en"`, profile, and intake (Agora-2 pipeline).
4. Chat with assembled agents; suggested prompts come from the scenario.

Also available experimentally: Full / Limited / Single modes, emotion & decision customization, welcome tutorial (**`T`**), log export.

---

## Project structure

```
Agora/
├── backend/                 # Flask API
│   ├── app.py               # HTTP routes
│   ├── agora2_http.py       # Agora-2 adapter (non-CLI)
│   ├── agentwake_new.py     # Agent runtime
│   ├── stance.py / profile_store.py / …
│   ├── scenes/              # Scenario prompts (e.g. *_en.json)
│   ├── scenario_templates/  # Intake templates
│   ├── .env.example
│   └── requirements.txt
├── frontend/                # React + Vite UI
│   ├── src/app/pages/Chat.tsx
│   ├── src/app/components/IntakeModal.tsx
│   └── vite.config.ts       # /api proxy + trycloudflare allowedHosts
├── paper/                   # Standalone paper figure page
└── README.md
```

---

## Environment

| Variable | Required | Notes |
|----------|----------|--------|
| `OPENAI_API_KEY` | Yes (for chat) | In `backend/.env` |
| `PORT` | No | Use `5001` to match the Vite proxy |
| `VITE_API_BASE` | No | Defaults to `/api` (same-origin). Override only if you point the UI at another API host. |

---

## Main API

| Method | Path | Notes |
|--------|------|--------|
| GET | `/api/health` | Liveness |
| GET | `/api/agora2/scenarios?lang=en` | Scenario cards for the UI |
| GET | `/api/agora2/template/<type>` | Intake template (`employment` / `parent_child`) |
| POST | `/api/start` | Create room (Agora-2 when `scene_id` / `scenario_type` is employment or parent_child) |
| POST | `/api/message` | User message → agent replies |
| GET | `/api/history/<room_id>` | History |
| GET | `/api/export-logs/<room_id>` | Export zip |
| POST | `/api/emotion/analyze` | Emotion helper |

---

## Modes (brief)

- **Full** — editable personas / emotion / decision.
- **Limited** — pick from presets; same multi-agent scheduler, fewer UI edits.
- **Single** — one neutral agent, no multi-agent turn taking.

Scheduler (Full/Limited): after each user turn, agents reply within `max_agent_turns_before_user` / `max_user_gap`; avoid immediate self-repeat; prefer agents who have not spoken yet in the turn; stall burst skips the last speaker.

### Layers

- **Emotion:** Valence / Arousal / Control → discrete labels (joy, anger, fear, sadness, surprise, disgust).
- **Decision:** Rational / Intuitive / Dependent / Avoidant / Spontaneous (GDMS-style).

---

## Notes

1. Never commit API keys or `backend/.env`.
2. OpenAI usage is billed to your key.
3. After changing Flask/scheduler code, **restart** `python app.py` (`use_reloader=False`).
4. Legacy static HTML under the backend was removed; use the React frontend only.
5. Runtime profiles `backend/profiles/web_*.json` are gitignored.

---

## Tech stack

- **Backend:** Python 3.9+, Flask, flask-cors, OpenAI SDK, python-dotenv  
- **Frontend:** React, Vite, Tailwind, MUI, Motion  
- **Optional share:** Cloudflare Quick Tunnel (`cloudflared`)
