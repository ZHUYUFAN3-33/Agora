# DIFF: Agora `backend/` vs Kourakulsy/Agora-2 `agora_backend/`

Updated: 2026-08-03  
Upstream pin: local `agora2/backend-dev` tip (scheduling sourced from CLI `agentwake_new.py`).

## Current integration shape

```
React → Flask app.py
         → agentwake_new.run_user_turn()   ← shared scheduling core (CLI-faithful)
         → agentwake_new.main()            ← CLI uses the same primitives / full loop
```

- **Deleted** slim `agora2_loop.py` (was a divergent second scheduler).
- Flask and offline CLI tests share mention hard-route, no-repeat, Concluded latch, Admin-3 user-turn cadence, `[MESSAGE]`/`[RATIONALE]`, rationale.jsonl events.
- `prefer_agents` default **0.85** (CLI-faithful); override with `AGORA_PREFER_AGENTS`.
- HTTP `run_user_turn` includes in-session `maybe_distill_snippet` / `YOUR MEMORY` (session-persisted snippets + `{room}_memory.jsonl`).

## Still product-only in this repo

- `app.py` — HTTP, auth, rooms, admin
- `agora2_http.py` — intake/profile bridge for React
- `user_store.py` — SQLite accounts/sessions
- Legacy `scene1`–`scene9` pipeline when `pipeline != agora2`

## Scenario systems

| | Agora-2 path | Legacy |
|--|--|--|
| IDs | `employment`, `parent_child` | `scene1`…`scene9` |
| Context | profile + intake + stance | scene txt + light facts |
