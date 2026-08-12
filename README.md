# Agora

Multi-agent chat for co-creation and decision experiments (OpenAI API).  
多智能体协作对话系统。  
マルチエージェント協働チャットシステム。

Current focus: **English UI** + **Agora-2 scenarios** (Employment, Parent-Child) with profile/intake before chat. Locally: Flask API + Vite React. Production (Fly.io): one container serves the built SPA and `/api`.

---

## How to run / 如何运行 / 実行方法

### 1. OpenAI key（各自本地配置 / set up locally yourself）

`.env` **不会进仓库**，每人自己建：

```bash
cp backend/.env.example backend/.env
```

然后编辑 `backend/.env`，把占位符换成你自己的密钥：

```env
OPENAI_API_KEY=sk-你的密钥
```

- Do this yourself on every machine / clone — nobody else’s key is shared via git.
- Never commit `.env`.
- Without a valid key, chat / Summary will fail (401 / API errors). Restart Flask after editing.

Optional admin bootstrap (same `.env`):

```env
AGORA_ADMIN_USER_ID=admin
AGORA_ADMIN_PASSWORD=change-me
```

On Flask start, that User ID is created/promoted as admin. Open `/admin` after login. Forgot password → users contact admin (no self-reset). Accounts + profiles live in `backend/data/agora.db` (gitignored).

### Study accounts (P01…P32)

32 participant accounts ship with the app, so nobody has to register: on every
boot, [`backend/seed_users.json`](backend/seed_users.json) is seeded into SQLite
(`user_store.seed_users_from_file`). Accounts that already exist are skipped, so
a redeploy never disturbs a participant mid-study. Profiles are created **empty**
on purpose — intake is the participant's to fill on first use.

The seed file holds password *hashes* only. The plaintext sheet you hand out is
`test_accounts_<stamp>.csv` at the repo root, written by the generator and
gitignored. **Keep that file** — a lost password cannot be recovered from a hash;
the fallback is `/admin` → set password, or regenerating the sheet.

```bash
python backend/scripts/make_test_users.py              # regenerate all 32 (new passwords)
python backend/scripts/make_test_users.py --append --start 33 --count 8   # add P33…P40
```

Then commit `backend/seed_users.json` and `fly deploy`. IDs are zero-padded
(`P01`, not `P1`) because a User ID must be at least 3 characters.

To force everyone back onto a freshly generated sheet, deploy with
`fly secrets set AGORA_SEED_USERS_RESET=1` — that resets seeded passwords and
signs those accounts out, but leaves their rooms, logs, and profiles intact.
Unset it afterwards (`fly secrets unset AGORA_SEED_USERS_RESET`), or every
restart will kick participants out of a live session.

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

### Deploy on Fly.io（生产收数 / production）

Keeps SQLite, chat logs, profiles, and cross-session memory on a **persistent volume**. Same-origin `/api` (no `VITE_API_BASE` needed).

1. Install CLI and log in: [fly.io/docs/hands-on/install-flyctl](https://fly.io/docs/hands-on/install-flyctl/) — `fly auth login`
2. Edit [`fly.toml`](fly.toml): set `app = "your-unique-name"` (and `primary_region` if you prefer, e.g. `nrt` / `sjc`).
3. From the **repo root**:

```bash
fly apps create your-unique-name          # once; must match fly.toml `app`
fly volumes create agora_data --size 3 --region nrt
fly secrets set \
  OPENAI_API_KEY='sk-...' \
  AGORA_ADMIN_USER_ID='admin' \
  AGORA_ADMIN_PASSWORD='a-strong-password'
fly deploy
```

4. Open `https://your-unique-name.fly.dev` — health: `/api/health`. Admin UI: `/admin` after login.
5. The 32 study accounts (`P01`…`P32`) are seeded automatically on first boot —
   see [Study accounts](#study-accounts-p01p32). Confirm in `/admin` → Users, then
   hand out the rows of `test_accounts_<stamp>.csv`.

**Collect / export data**

- In-app: `/admin` export (per user, or per session from the session list), or the
  per-room log zip from Chat. All require login; admins can export any user's data.
- Every zip contains a `README.txt` describing each log field by field, and a
  `manifest.json` with per-file line counts. Read the manifest first: it flags
  sessions that were started but never used, and sessions where the on-disk log and
  the database disagree.
- Layout is one directory per session:
  `{user}/rooms/{room_id}/chat.jsonl`, `…/thinking.jsonl`, `…/derived/…`
- From the volume:

```bash
fly ssh console -C 'ls -la /data'
# download DB + logs (example)
fly ssh sftp get /data/agora.db ./agora-backup.db
```

**Notes**

- `min_machines_running = 1` and `auto_stop_machines = off` so in-memory rooms are not wiped by scale-to-zero.
- Gunicorn uses **1 worker** (sessions are process-local) and `--timeout 180` for long multi-agent turns.
- Custom domain later: `fly certs add your.domain` (DNS to Fly). Avoid putting a Cloudflare orange-cloud proxy in front of `/api/message` on the free plan (~100s origin timeout → 524).
- Cost is roughly a few USD/month for the machine + volume; OpenAI usage is separate.

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
├── Dockerfile               # Multi-stage: frontend build + gunicorn
├── fly.toml                 # Fly.io app + /data volume
├── backend/                 # Flask API (+ serves SPA in production)
│   ├── app.py               # HTTP routes + static SPA
│   ├── data_paths.py        # AGORA_DATA_DIR / DB / logs / profiles / memory
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
| `OPENAI_API_KEY` | Yes (for chat) | In `backend/.env` or `fly secrets` |
| `PORT` | No | Local: `5001` for Vite proxy. Fly: `8080` |
| `VITE_API_BASE` | No | Defaults to `/api` (same-origin). Override only if you point the UI at another API host. |
| `AGORA_ADMIN_USER_ID` / `AGORA_ADMIN_PASSWORD` | Prod recommended | Bootstrap admin on first boot |
| `AGORA_SEED_USERS_FILE` | No | Study-account seed. Default: `backend/seed_users.json` |
| `AGORA_SEED_USERS_RESET` | No | `1` = reset seeded passwords to the seed file on boot. Leave unset during a study |
| `AGORA_DATA_DIR` | Prod | Fly: `/data` (volume). Local: unset → `backend/` |
| `AGORA_DB_PATH` | No | Fly: `/data/agora.db`. Local default: `backend/data/agora.db` |
| `AGORA_STATIC_DIR` | Prod | Path to built `frontend/dist` inside the container |
| `FLASK_DEBUG` / `FLASK_HOST` | No | Local `python app.py` only; production uses gunicorn |

---

## Main API

| Method | Path | Notes |
|--------|------|--------|
| GET | `/api/health` | Liveness |
| GET | `/api/agora2/scenarios?lang=en\|zh` | Scenario cards for the UI |
| GET | `/api/agora2/template/<type>` | Profile + intake fields (`employment` / `parent_child`) |
| GET | `/api/agora2/profile-template?scenario_type=` | Per-scenario profile fields |
| GET | `/api/agora2/memory?scenario_type=` | Cross-session memory (Session N / history) |
| POST | `/api/start` | Create room; Agora-2 body may include `lang`, `profile`, `intake`, `hint`, `session_update` |
| POST | `/api/message` | User message → agent replies (+ dynamic stance knowledge) |
| GET | `/api/history/<room_id>` | History |
| GET | `/api/export-logs/<room_id>` | Export zip — requires auth (owner or admin) |
| POST | `/api/telemetry/<room_id>` | Client behavior events → `{room}_ux.jsonl` |
| POST/GET | `/api/summary/<room_id>` | Decision summary; also appends cross-session memory |
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

- **Backend:** Python 3.9+, Flask, gunicorn, flask-cors, OpenAI SDK, python-dotenv  
- **Frontend:** React, Vite, Tailwind, MUI, Motion  
- **Production:** Fly.io (Docker + volume); optional local share via Cloudflare Quick Tunnel (`cloudflared`)
