# Design: envit5 VI↔EN Token-Streaming Translation Demo

**Date:** 2026-07-09  
**Status:** Approved (brainstorming) — awaiting user review of this written spec  
**Repo path:** `translationmodel_testing/`

## 1. Summary

Build a **basic demo** of Vietnamese↔English **token-streaming** translation using [VietAI/envit5-translation](https://huggingface.co/VietAI/envit5-translation).

- **UI:** Streamlit  
- **API:** FastAPI with **Server-Sent Events (SSE)** for true incremental decode  
- **Model:** envit5 loaded once in the API process  
- **Workflow:** Qwen MCP coding agent scaffolds → Fable reviews against this spec → human hardens streaming/edge cases and decides merge  

“Token streaming” here means **real incremental decode**: tokens are pushed to the client as the model produces them, not a full generate followed by a fake word-by-word reveal.

## 2. Goals

1. User pastes Vietnamese or English text, chooses or auto-detects direction, clicks Translate, and sees **tokens appear as the model produces them**.
2. Model is loaded **once** in FastAPI (not on every Streamlit rerun).
3. Demo is **curl-testable** without the UI (`POST /translate` streams SSE).
4. Clear separation of roles: criteria/spec (Fable) → scaffold (Qwen MCP) → review/harden (Fable + human).

## 3. Non-goals (v1)

- Languages other than VI/EN  
- Speech / ASR / TTS  
- Batch file upload or multi-document pipelines  
- Fine-tuning or training  
- Auth, multi-tenant, production rate limiting beyond a simple in-process lock  
- Multi-user request queue  
- Docker production hardening (local run scripts only)  
- Model comparison UI  
- Using MCP servers as the **inference** path (MCP is for the coding agent only)  
- Fake/chunked reveal of a fully generated string  

## 4. Success criteria

| ID | Criterion |
|----|-----------|
| SC1 | `GET /health` returns model loaded status and device |
| SC2 | `vi→en` and `en→vi` both apply correct envit5 prefixes (`vi: ` / `en: `) |
| SC3 | SSE stream emits partial tokens; final event includes full text |
| SC4 | Streamlit shows live growing output (no “wait then dump”) |
| SC5 | Empty or over-limit input rejected with a clear error |
| SC6 | A second request after the first completes works (no stuck generator / lock leak) |
| SC7 | README documents install, model download, run API, run Streamlit, and a curl SSE example |

## 5. Architecture

### 5.1 Approach (locked)

**A — SSE FastAPI + Streamlit client**

```
┌─────────────────┐     HTTP POST + SSE      ┌──────────────────┐
│  Streamlit UI   │ ───────────────────────► │  FastAPI backend │
│  (frontend/)    │ ◄── event: token/done ── │  (backend/)      │
└─────────────────┘                          │        │         │
                                             │        ▼         │
                                             │  envit5 service  │
                                             │  TextIterator    │
                                             │  Streamer        │
                                             └──────────────────┘
```

### 5.2 Why this approach

- Clear process boundary: model lifecycle lives in API, not Streamlit reruns  
- Curl-friendly for smoke tests without UI  
- SSE is simpler than WebSocket for one-way token push  
- Fits “Streamlit + API + token streaming” brief  

### 5.3 Alternatives considered

| Approach | Trade-off | Decision |
|----------|-----------|----------|
| B — WebSocket | Better cancel/control later; heavier for basic demo; awkward in Streamlit | Rejected for v1 |
| C — Polling buffer | No SSE dependency; worse UX; more server state | Rejected for v1 |
| Streamlit-only (no API) | Fastest scaffold; model reload/session issues; no reusable API | Rejected |
| MCP LLM as translator | Already wired (GLM/Qwen/etc.); not true envit5 MT demo | Rejected for inference |

## 6. Components

### 6.1 Repository layout

```
translationmodel_testing/
  backend/
    app.py                 # FastAPI entry: /health, /translate
    model_service.py       # load envit5, direction, stream generate
    schemas.py             # Pydantic request/response models
    requirements.txt
  frontend/
    streamlit_app.py
    requirements.txt
  models/                  # optional local HF cache / symlink (weights gitignored)
  scripts/
    smoke_translate.sh     # curl SSE smoke for both directions
    download_model.py      # optional prefetch of VietAI/envit5-translation
  docs/superpowers/specs/  # this design + later implementation plan
  README.md
  secret.env               # existing secrets; not required for envit5 local HF download
  .mcp.json                # existing MCP coding-agent servers (Qwen, etc.)
```

Empty `backend/`, `frontend/`, and `models/` directories already exist; implementation fills them.

### 6.2 Model contract (envit5)

- **Model ID:** `VietAI/envit5-translation`  
- **Prefixes (required by model card):**  
  - VI→EN: input prefixed with `vi: `  
  - EN→VI: input prefixed with `en: `  
- **Direction modes:** `vi-en` | `en-vi` | `auto`  
- **Auto heuristic (v1):** prefer Vietnamese if text has Vietnamese diacritics / characteristic letters; otherwise English. If confidence is low or text is empty of letters, require explicit direction (return 400 with message).  
- **Decode:** Hugging Face `TextIteratorStreamer` (or equivalent) on a background thread; API generator yields tokens as they arrive.  
- **Device:** CUDA if available, else CPU; report in `/health`.  
- **Concurrency (v1):** single in-process generate lock. If busy → HTTP 429 with clear message. No queue.

### 6.3 API surface

| Method | Path | Behavior |
|--------|------|----------|
| `GET` | `/health` | `{ "status", "model_id", "device", "ready" }` |
| `POST` | `/translate` | JSON body → SSE stream |

**Request body (`POST /translate`)**

```json
{
  "text": "Xin chào",
  "direction": "auto",
  "max_new_tokens": 256
}
```

- `text` (string, required): non-empty after strip; max length **2000 characters**  
- `direction` (string, required): `"vi-en"` | `"en-vi"` | `"auto"`  
- `max_new_tokens` (int, optional): default 256; clamp to a safe upper bound (e.g. 512)

**SSE events**

| Event | Data (JSON) | When |
|-------|-------------|------|
| `meta` | `{ "direction": "vi-en", "model": "VietAI/envit5-translation" }` | First event after accept |
| `token` | `{ "t": "<piece>" }` | Each decoded piece |
| `done` | `{ "text": "<full>", "direction": "vi-en" }` | Successful completion |
| `error` | `{ "message": "..." }` | Failure mid-stream; then close |

**HTTP errors (before stream starts)**

| Code | Case |
|------|------|
| 400 | Empty text, over-length, invalid direction, auto-detect failed |
| 429 | Generate lock held |
| 503 | Model not loaded / not ready |

### 6.4 Streamlit UI

- Text area for source text  
- Direction select: **Auto** / **VI→EN** / **EN→VI**  
- Translate button  
- Live output via SSE consumer (`httpx` stream or equivalent) feeding `st.write_stream` or a growing placeholder  
- Display resolved direction (from `meta` / `done`)  
- Surface pre-stream HTTP errors and mid-stream `error` events with `st.error`  
- Configurable API base URL (default `http://127.0.0.1:8000`), e.g. env var or sidebar input  

### 6.5 Default ports / process model

- FastAPI: `http://127.0.0.1:8000`  
- Streamlit: `http://127.0.0.1:8501`  
- Two processes for local demo; no reverse proxy required in v1  

## 7. Error handling

| Situation | Behavior |
|-----------|----------|
| Empty / whitespace-only text | 400, no SSE |
| Text length > 2000 | 400, no SSE |
| Invalid `direction` | 400, no SSE |
| Auto cannot decide | 400, message asks user to pick direction |
| Model not ready | 503 on `/translate` |
| Exception during generate | SSE `error` event, stream closes cleanly; lock released |
| Concurrent second request | 429 until first finishes |
| Client disconnect mid-stream | Stop generation if practical; always release lock in `finally` |

## 8. Testing and smoke

Minimum verification for “demo ready”:

1. Start API; `GET /health` → `ready: true`  
2. `scripts/smoke_translate.sh` (or documented curl) for `vi→en` and `en→vi`; observe multiple `token` events then `done`  
3. Streamlit: tokens grow live for both directions  
4. Empty and over-long inputs show clear errors  
5. Run a second translation after the first completes successfully  
6. Optional: unit-level tests for prefix selection and auto-detect helper (no GPU required)

## 9. Workflow: Qwen scaffolds, Fable reviews, human hardens

| Role | Responsibility |
|------|----------------|
| Human | Approve design/plan; run demo; harden if desired; merge decisions |
| Qwen MCP (coding agent) | Scaffold `backend/`, `frontend/`, `scripts/`, `README.md` to match this design |
| Fable (reviewer) | Write this spec + implementation plan; review diffs against SC1–SC7; fix critical streaming/lock issues if agent misses them |

### 9.1 Agent constraints (Qwen)

- Implement only what this design specifies  
- Do **not** add auth, batch UI, multi-model switch, Docker Compose production stack, or MCP inference  
- Prefer small focused files as in §6.1  
- Must leave a working `scripts/smoke_translate.sh` and README run steps  
- Secrets: do not commit weights or copy `secret.env` into the app path  

### 9.2 Acceptance package for agent handoff

Agent delivery is accepted only if:

- SC1–SC7 are demonstrably met, or gaps are listed explicitly  
- `backend/app.py`, `backend/model_service.py`, `backend/schemas.py` exist and match API contract  
- `frontend/streamlit_app.py` streams tokens (not one-shot dump)  
- Smoke script and README present  

## 10. Dependencies (indicative)

**Backend:** `fastapi`, `uvicorn[standard]`, `pydantic`, `torch`, `transformers`, `sentencepiece` (or model-required tokenizers), `accelerate` if needed  

**Frontend:** `streamlit`, `httpx`  

Pin versions in each `requirements.txt` during implementation. Model weights downloaded from Hugging Face at first run or via `scripts/download_model.py`.

## 11. Out-of-scope follow-ups (post-v1)

- Cancel mid-stream (WebSocket or SSE with cancel endpoint)  
- Request queue / multi-GPU  
- Docker Compose for one-command demo  
- Side-by-side comparison with MCP LLMs  
- UI design system polish (`getdesign` / brand themes)  
- Longer document sentence-chunk progressive translation  

## 12. Open decisions closed during brainstorming

| Question | Decision |
|----------|----------|
| Demo purpose | Translation model demo (envit5), not generic chat |
| Inference path | Local envit5, not MCP chat models |
| App split | Streamlit + FastAPI |
| Streaming style | True incremental decode |
| Directions | Auto VI↔EN only |
| Transport | SSE (Approach A) |
| Build workflow | Hybrid: Qwen scaffolds via MCP; Fable reviews; human hardens |

---

## Appendix A — Example curl (normative for SC7)

```bash
curl -N -X POST http://127.0.0.1:8000/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Xin chào các bạn","direction":"vi-en"}'
```

Expected: `meta`, several `token` lines, then `done` with full English text.

## Appendix B — Example health response

```json
{
  "status": "ok",
  "model_id": "VietAI/envit5-translation",
  "device": "cuda",
  "ready": true
}
```
