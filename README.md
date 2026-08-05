# Agora

Multi-agent chat for co-creation and decision experiments (OpenAI API).  
多智能体协作对话系统。  
マルチエージェント協働チャットシステム。

Current focus: **English UI** + **Agora-2 scenarios** (Employment, Parent-Child) with profile/intake before chat. Locally: Flask API + Vite React. Production (Fly.io): one container serves the built SPA and `/api`.

---

## 🌿 分支说明：`feature/dialogue-naturalness`

> **这个分支是干什么的**：把 Agora-2 仓库（`Kourakulsy/Agora-2`）上开发的**对话自然度层**，
> 完整移植进本仓库的产品代码，让 **web 端的 agent 行为与 CLI 研究版完全一致**。
>
> 分支基点：`feature/flyio-production-hosting`。
> 行为基准：`Agora-2` 的 `feature/cli-dialogue-naturalness` @ **`776f5bf`**。

### 为什么需要这个分支

Agent 的审议逻辑目前有**四份副本**：跨两个仓库（本仓库 `backend/` 与 Agora-2 的
`agora_backend/`，两者**无共同 git 祖先**），且本仓库内部 `agentwake_new.py` 里的审议循环
本身又有两份 —— `run_user_turn()`（web，Flask 每轮 HTTP 调用）和 `main()`（CLI）。

自然度层在 Agora-2 的 CLI 上开发完成，但产品跑的是 web 路径。不做这次移植，**用户在网页上
看到的 agent 行为，和论文里描述的那个 agent 不是同一个**。

### 忠实性契约（本分支的核心约束）

**Agent 的可观察行为必须与 `776f5bf` 一致。** 具体地：

- 所有 prompt 文本（`CONVERSATIONAL STYLE`、`PHASE_PROMPTS`、`STALL_PROMPTS`、
  stance 优先级条款、`OUTPUT FORMAT` 中的 `[MOVE]` 说明）**逐字**取自 `776f5bf`，不做本地润色。
- 所有判定阈值（共识预警的 `>6` 行挑战冷却、`>=3` 行提醒间隔、`recent >= 4`）保持原值。
- `decision/*.txt` 五个预设与 `stance_templates/*.json` 为**逐字节复制**。
- 任何为适配本仓库而做的偏离，必须记录在下方「已知偏离」中。

若要修改 agent 行为，**先改 Agora-2 再同步过来**，不要只在本仓库改 —— 否则两边会再次分叉。

### 移植了什么（五个机制）

1. **`[MOVE]` 自报标签**。每个 agent 输出在 `[MESSAGE]`/`[OPTIONS]`/`[RATIONALE]` 之外多带一个
   私有 `[MOVE]` 块，自报本条消息做了什么：`challenge` / `extend` / `new_point` / `concede` /
   `clarify`。共识预警和收敛门改读这个信号（保留旧词表做兜底，两者取并集），礼貌措辞的反驳
   不再被漏判。块缺失或写错时静默降级回词表。

2. **定向共识预警**。`CONSENSUS WARNING` 从「广播给之后每一个发言者」改为「一次只提醒一个
   发言者，之后隔至少 3 行再考虑重发；6 行内出现过 challenge 则完全不发」。消灭了连续 2-3 条
   近乎相同的「我必须表明我的不同意见」式排队反对。

3. **收敛硬门**。进入 Convergence 要求场上出现过真实分歧，判定为
   `[MOVE] challenge 计数 OR 词表扫描`。⚠️ 本仓库**此前完全没有这道门**（测试却在检查它），
   本分支一并补上。

4. **文风约束 + 目标式任务**。system prompt 新增 `CONVERSATIONAL STYLE` 区块；`PHASE_PROMPTS`
   全部从命令句改写为结果句；每回合任务提示从 `Your task this turn` 改为 `Your goal this turn`。

5. **决策预设重写 + 管辖权条款**。`decision/*.txt` 从电报式规格表改写为自然语言思维风格画像，
   删掉了曾被逐字复读进中文会话的英文工作范例；stance 区块新增：**立场决定你捍卫什么，决策
   风格只决定你怎么论证，情绪只决定语气**。另补齐两份 stance 模板缺失的 Narrowing 阶段
   `phase_focus`。

### 为适配本仓库所做的调整（不改变行为）

| 调整 | 原因 |
|---|---|
| `challenge_tracker` 在 web 路径存进 `session`，CLI 路径保持局部变量 | `run_user_turn()` 每轮 HTTP 调用后返回，用局部变量会导致计数和两个冷却每轮清零 —— 预警会每轮重发、收敛门永远看不到 challenge。存进 session 才等价于 CLI 长驻循环的语义 |
| 五个机制在 `run_user_turn()` 和 `main()` 中**各实现一遍** | 两条审议循环是复制粘贴关系，且已各自漂移；只改一条会让 web 与 CLI 行为再次分叉 |
| `[MOVE]` 与本仓库特有的 `[OPTIONS]` 块**并存**而非替换 | `[OPTIONS]` 是本仓库的选项 chips 功能，Agora-2 没有。`parse_agent_turn()` 现返回 5 个 key |

### 已知偏离

- **`_MOVE_NAMES` 标签别名**只含 `MOVE|动作|行动|アクション`，与 `776f5bf` 一致。本仓库其他标签
  （`_MSG_NAMES` 等）额外收录了繁体/日文变体以防标签被模型翻译后泄漏进聊天。是否给 `[MOVE]`
  同样加宽 **尚未决定** —— 加宽会偏离基准，不加宽则 `[動作]` 这类写法在繁体会话中可能漏判
  （但不会泄漏，`_STRAY_TAG_RE` 仍会清理）。

### 如何验证忠实性

```bash
cd backend && python3 tests_offline/run_all.py
```

自然度层的专项测试：`test_move_tag.py`、`test_consensus_targeting.py`、`test_convergence_gate.py`、
`test_narrowing_focus.py`、`test_refusal_and_language.py`。
`test_cli_http_parity.py` 用于保证 web 与 CLI 两条路径不再分叉 —— **它挂了就说明忠实性被破坏**。

> ⚠️ 本分支**未修复**的既有失败：`test_self_novelty`、`test_stance_hint`、`test_stance_knowledge`、
> `test_stance_pool_scaling`、`test_stance_related`。这 5 个在 Agora-2 上全部通过，属于更早一次
> backend-dev 同步（`40faa5f`）遗留的缺口（测试同步了、代码没同步完），与自然度层无关，
> 需另开分支处理。

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

**Collect / export data**

- In-app: `/admin` export, or per-room log zip from Chat.
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
| GET | `/api/export-logs/<room_id>` | Export zip |
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
