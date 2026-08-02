# DIFF: Agora `backend/` vs Kourakulsy/Agora-2 `agora_backend/`

Generated: 2026-07-22  
This repo: `ZHUYUFAN3-33/Agora` @ `00548b9` (API-only after Phase A)  
Agora-2: `Kourakulsy/Agora-2` @ `8b9c498` (orphan Initial commit)  
No shared git history — content comparison only.

## 1. High-level

| | This repo | Agora-2 |
|--|--|--|
| Shape | Flask API (`app.py` ~974 lines) + thin `agentwake_new.py` (~343) | CLI `agentwake_new.py` (~1347) + context modules; **no HTTP/Flask** |
| UI contract | React calls `/api/*` | Terminal / argparse only |
| Scenarios | 9× Scene Layer txt (`scene1`–`scene9`) | 2 types: `employment`, `parent_child` |
| Agent identity | emotion + decision (+ chatbot txt / pool) | emotion + decision **+ forced stance** + assembled roles |
| User context | Light `update_user_facts` in chat | Profile + Scenario Intake + Domain Background |
| i18n | Mostly EN scene prompts | Full zh/en (`lang_utils.pick`) |

## 2. File map

### Only in this repo (keep or migrate carefully)
- `app.py` — entire product API
- `emotion block/emotion.py` — slider/text emotion fusion used by `/api/emotion/analyze`
- `new_module/new/scene1.txt` … `scene9.txt`
- `chatbot1.txt`–`chatbot3.txt`, agent pool loading in Flask
- `env_context.json`, older `agent_wakeup_4o_e.py`

### Only in Agora-2 (new capabilities)
- `agora_context.py`, `profile_store.py`, `scenario_background.py`
- `agent_assembly.py`, `stance.py`, `lang_utils.py`, `transcript_report.py`
- `scenario_templates/`, `background_templates/`, `scenes/*_{zh,en}.txt`
- `profiles/`, `intake_examples/`, `info_example.jsonl`

### Same idea, different layout
| Concept | This repo | Agora-2 |
|--|--|--|
| Decision presets | `new_module/new/decision block/*.txt` | `decision/*.txt` (same 5 names) |
| Emotion presets | `new_module/new/emotion block/*.txt` (lowercase) | `emotion/*.txt` (Capitalized) |
| Core scheduler | library for Flask | CLI `main()` + richer loop (novelty, consensus guard, stance) |

### Noise in Agora-2 repo (do not copy as-is)
`.idea/`, `.claude/`, `__pycache__/`, sample `logs/`

## 3. Hard integration facts

1. **Cannot drop-in replace `agentwake_new.py`.**  
   This repo’s `app.py` imports helpers that Agora-2’s file does not export as a library API, e.g. `ensure_dir`, `make_room_id_6`, `update_user_facts`, `facts_to_bullets`, `history_to_transcript_lines`, `build_transcript`, `sanitize_single_message`, `create_response_with_client`, `ADMIN*_SYSTEM`, `extract_text`. Agora-2 uses `create_response(...)` and embeds the turn loop inside `main()`.

2. **Agora-2 has no `app.py`.** Phase C must keep (and extend) this Flask layer, or rewrite the HTTP surface.

3. **Scenario systems are incompatible.** This repo = static scene id → prompt blob. Agora-2 = `scenario_type` + profile/intake JSON + background matching + stance table. React `scenes_config.json` (9 scenes) does not map 1:1.

4. **Emotion/decision text is reusable** with path/casing normalization; content is close enough to treat as presets.

5. **Deps:** keep Flask stack; add Agora-2’s `requests` only if you adopt their HTTP fallback for OpenAI.

## 4. Architecture sketch (recommended mental model)

```
React (frontend)
    → Flask app.py  (session, /api/start, /api/message)
        → prepare_session_context()     [from Agora-2]
        → agent_assembly + stance       [from Agora-2]
        → turn loop / ChatAgent         [merge: Agora-2 richness + this repo’s library API]
        → emotion.py analyze            [this repo, optional]
```

## 5. Phase C options (recommendations)

See chat summary — three strategies ranked for production safety.
