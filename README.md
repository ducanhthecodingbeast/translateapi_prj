# envit5 VI↔EN Token-Streaming Translation Demo

Basic demo of **Vietnamese ↔ English** translation with **true token streaming** using [VietAI/envit5-translation](https://huggingface.co/VietAI/envit5-translation).

- **API:** FastAPI + Server-Sent Events (SSE)
- **UI:** Streamlit
- **Model:** loaded once in the API process (not on every Streamlit rerun)

## Layout

```
translationmodel_testing/
  backend/           # FastAPI: /health, /translate (SSE)
  frontend/          # Streamlit SSE client
  scripts/           # download_model.py, smoke_translate.sh
  models/            # optional local cache (gitignored weights)
  tests/             # unit tests for direction/prefix helpers
```

## Requirements

- Python 3.10+ recommended
- CUDA GPU optional (falls back to CPU)
- Hugging Face access to download `VietAI/envit5-translation` on first run

## Install

```bash
cd translationmodel_testing

# Backend
python3 -m pip install -r backend/requirements.txt

# Frontend
python3 -m pip install -r frontend/requirements.txt

# Test helpers (optional)
python3 -m pip install pytest
```

### Optional: prefetch model weights

```bash
python3 scripts/download_model.py
# or pin cache under ./models
HF_HOME=./models python3 scripts/download_model.py
```

## Run API

```bash
cd backend
# Default demo ports avoid common host conflicts (8000/8501 often busy):
python3 -m uvicorn app:app --host 127.0.0.1 --port 18800
```

First start downloads the model if needed (can take a few minutes), then loads it onto CUDA if available.

### Health check

```bash
curl -s http://127.0.0.1:18800/health
```

Expected:

```json
{
  "status": "ok",
  "model_id": "VietAI/envit5-translation",
  "device": "cuda",
  "ready": true
}
```

### SSE translate (curl)

```bash
curl -N -X POST http://127.0.0.1:18800/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Xin chào các bạn","direction":"vi-en"}'
```

You should see a `meta` event, several `token` events, then a `done` event with the full English text.

### Smoke script (both directions)

```bash
# with API already running
bash scripts/smoke_translate.sh
```

## Run Streamlit UI

In a second terminal:

```bash
cd frontend
# optional override if you change the API port:
# ENVIT5_API_BASE=http://127.0.0.1:18800
streamlit run streamlit_app.py --server.port 18501 --server.address 127.0.0.1
```

Open http://127.0.0.1:18501 — paste text, choose Auto / VI→EN / EN→VI, click **Translate**, and watch tokens appear as the model produces them.

## API contract (summary)

| Method | Path | Behavior |
|--------|------|----------|
| `GET` | `/health` | `{ status, model_id, device, ready }` |
| `POST` | `/translate` | JSON body → SSE stream |

**Request**

```json
{
  "text": "Xin chào",
  "direction": "auto",
  "max_new_tokens": 256
}
```

- `text`: required, non-empty after strip, max **2000** chars  
- `direction`: `vi-en` | `en-vi` | `auto`  
- `max_new_tokens`: optional, default 1000, max 1000  

**SSE events:** `meta` → `token`* → `done` (or `error`)

**HTTP errors (before stream):** 400 validation / auto-detect fail · 429 busy · 503 model not ready

## Unit tests (no GPU)

```bash
pytest tests/test_direction.py -v
```

## Notes

- Concurrency is a single in-process generate lock (v1). A second request while one is running gets HTTP 429.
- envit5 requires source prefixes: `vi: ` for VI→EN and `en: ` for EN→VI (applied automatically).
- Do not commit `secret.env` or model weight files.
