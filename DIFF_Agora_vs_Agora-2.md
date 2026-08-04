# DIFF: Agora `backend/` vs Kourakulsy/Agora-2 `agora_backend/`

Updated: 2026-08-05  
Upstream pin: `agora2/backend-dev` @ `44c518c` (prompt update).

## Current integration shape

```
React → Flask app.py
         → agentwake_new.run_user_turn()   ← shared scheduling core (CLI-faithful)
         → agentwake_new.main()            ← CLI uses the same primitives / full loop
```

- Flask and offline CLI tests share mention hard-route, no-repeat, Concluded latch, Admin-3 user-turn cadence, `[MESSAGE]`/`[RATIONALE]` (+ zh tag aliases), rationale/memory jsonl events, refusal reframe, phrase-bank stripping.
- `prefer_agents` default **0.85** (CLI-faithful); override with `AGORA_PREFER_AGENTS`.
- HTTP `run_user_turn` includes in-session `maybe_distill_snippet` / `YOUR MEMORY` (session-persisted snippets + `{room}_memory.jsonl`).

## Synced from backend-dev (behavioral)

- `stance_templates/` + template-driven `stance.py`
- `agent_assembly.strip_phrase_banks` (emotion lexical cues + decision STRUCTURAL EXAMPLES)
- Decision/emotion preset text updates (Dependent/Rational/Spontaneous/Anger)
- ChatAgent prompt: WHAT COUNTS priority order, tag-language restatement
- Bilingual tag parsing, `looks_like_refusal` / `enforce_no_refusal`
- Offline tests: refusal/language, tag parsing, stance pool scaling, …

## Still product-only in this repo

- `app.py` — HTTP, auth, rooms, admin
- `agora2_http.py` — intake/profile bridge for React
- `user_store.py` — SQLite accounts/sessions
- Dual-write session memory / profile history to SQLite (CLI uses jsonl only)
- UI `stance_override` + soft-match `preview_matched_card` for customizer tags
- Legacy `scene1`–`scene9` pipeline when `pipeline != agora2`
- Log filename: Flask uses `{room}_thinkinglog.jsonl`; CLI uses `{room}_thinking.jsonl` (same content)

## Five session logs → agent behavior?

| File | Written by | Read back into prompts? | Affects behavior? |
|--|--|--|--|
| `{room}.jsonl` | chat transcript | **No** (in-memory `history` / `transcript_lines` used) | Yes via memory, not via file |
| `{room}_thinkinglog.jsonl` | Admin-1/2 traces | **No** | No |
| `{room}_moderator.jsonl` | Admin-3 events | **No** | Phase via in-memory `moderator_state` |
| `{room}_rationale.jsonl` | rationale / mention events | **No** | Distill uses in-memory `latest_rationale` |
| `{room}_memory.jsonl` | distilled snippets | **No** | `YOUR MEMORY` from in-memory `memory_snippets` |

**Verdict:** the five jsonl files are audit/export trails. Deleting or emptying them mid-session does not change the next agent turn. The *systems that also write them* (transcript, moderator state, distill snippets) do affect prompts.

## Scenario systems

| | Agora-2 path | Legacy |
|--|--|--|
| IDs | `employment`, `parent_child` | `scene1`…`scene9` |
| Context | profile + intake + stance | scene txt + light facts |
