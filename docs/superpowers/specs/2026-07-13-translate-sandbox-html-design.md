# Translate Sandbox HTML — Design Spec

**Date:** 2026-07-13  
**Status:** Approved (design dialogue)  
**Project:** `/home/aiface/Face_recognize/translating demo`  
**Related:** existing FastAPI SSE API on port 18800; Streamlit UI remains; face-test visual language at `https://aiface.ript.vn/face-test`

## Goal

Ship a single static HTML page that is a **translate-only** sandbox for the local envit5 FastAPI (`:18800`). Look and feel must follow the live Face Recognition Sandbox (cream cards, terracotta CTAs, soft secondary buttons, metric chips, Vietnamese-first labels) — not the Streamlit/NVIDIA green UI.

## Non-goals

- Face recognition, webcam, student store, or any face-test APIs
- Replacing or rewriting Streamlit
- Multi-worker / production hosting redesign
- Auth, rate-limit UI beyond surfacing 429/503
- Changing `/face-test` or face APIs (public path for this page is **`/translate`**)

## Approach

**Face-test style sandbox page (Approach A)** + live-as-you-type SSE client against **local** `http://127.0.0.1:18800`.

One file: `frontend/index.html` (inline CSS + JS). No new build step, no new dependencies.

## Visual system (match face-test)

| Token | Value / role |
|-------|----------------|
| Page canvas | Warm cream / soft gradient (`#faf9f5` family) |
| Cards | Large rounded cream surfaces, soft shadow, hairline border |
| Ink | Near-black charcoal (`#141413`) |
| Muted text | Warm gray |
| Primary CTA | Solid terracotta / coral (`#cc785c` family) — pill buttons |
| Secondary | Soft beige / gray pill |
| Optional accent | Teal for one non-primary action if needed |
| Inputs | White, rounded / pill, charcoal labels |
| Chips | Small metric pills (API ready · device · direction/chunks) |
| Empty states | Muted short Vietnamese copy |
| Type | Bold display title + short body; Vietnamese-first labels |

No NVIDIA green. No Streamlit chrome.

## Page layout

### Row 1 — Hero (2 cards)

**Left — hero**
- Pill badge: `TRANSLATION SANDBOX`
- Large title: e.g. *Dịch VI↔EN streaming, test trực tiếp trên web.*
- Short description: live token stream via envit5 FastAPI
- **3 metric chips:** API ready · device · last direction / chunks

**Right — Cấu hình API**
- API base URL (default `http://127.0.0.1:18800`)
- Debounce (ms), max new tokens
- Live-while-typing checkbox
- **Kiểm tra health** (terracotta primary)
- No extra secondary in this card (health is the only action)
- Status / health log box (empty: “Chưa kiểm tra API.”)

### Row 2 — Work (2 cards)

**Left — Văn bản nguồn**
- Direction: Auto / VI→EN / EN→VI
- Large textarea
- **Dịch ngay** (coral) · **Xóa** (soft)
- Hint: live debounce while typing

**Right — Bản dịch**
- Stream panel (tokens append live)
- Empty: “Bản dịch sẽ hiện khi bạn gõ…”
- Status line under output (streaming / done / error)
- Show a simple streaming indicator (e.g. blinking caret or “Đang dịch…”) while SSE is open

No face register / webcam / list-store blocks.

## API contract (existing — do not change backend)

Base: configurable, default `http://127.0.0.1:18800`

| Method | Path | Role |
|--------|------|------|
| `GET` | `/health` | Ready, device, model info |
| `POST` | `/translate` | SSE stream |
| `POST` | `/cancel` | Supersede in-flight translate |

**Translate body:** `{ "text": string, "direction": "auto"|"vi-en"|"en-vi", "max_new_tokens": int }`  
- text max 20000  
- max_new_tokens default 256, cap 512  

**SSE events (in order):**
1. `meta` — `{ direction, model, chunks }`
2. optional `chunk` events
3. many `token` — `{ t }`
4. terminal `done` — `{ text, direction, chunks }` **or** `error` (incl. cancel)

Pre-stream HTTP: 400 / 429 / 503 possible; surface in status log.

CORS is already `*` on the API.

## Client behavior

1. **On load:** optional auto health check; fill metric chips + log.
2. **Live mode (default on):** after last keystroke, wait debounce (~450ms default, user-editable). If text length ≥ 2, start translate. Shorter text clears output or leaves empty state.
3. **Supersede:** if a stream is active when a new translate starts → `POST /cancel`, then new `POST /translate`.
4. **Dịch ngay:** force translate immediately (same SSE path), ignore debounce wait.
5. **Xóa:** clear source + translation + streaming state; cancel if busy.
6. **Kiểm tra health:** `GET /health` → update chips + log.
7. **Parse SSE:** line-oriented `event:` / `data:` (same semantics as Streamlit client). Append tokens to the translation panel; on `done` finalize text; on `error` show message.
8. **Errors:** network failure, non-OK HTTP, SSE `error`, 400/429/503 → status log box, face-test empty/status style. Do not crash the page.

## File / structure

```
translating demo/
  frontend/
    streamlit_app.py          # unchanged
    live_textarea_component/  # unchanged
    index.html                # NEW — sandbox page
  docs/superpowers/specs/
    2026-07-13-translate-sandbox-html-design.md  # this file
```

Serve `index.html` at public path **`/translate`** (`https://aiface.ript.vn/translate`). Local file work does not require starting servers or nginx.

## Testing (manual — no auto-run unless asked)

- Health button updates chips when API up / clear error when down
- Type ≥2 chars → debounced stream fills translation
- Change text mid-stream → cancel + new stream
- Direction Auto / VI→EN / EN→VI produce sensible output
- Dịch ngay works with live off
- Xóa clears both panes
- Long text / empty text edge cases handled without throw

## Success criteria

1. One HTML file, face-test visual language, translate-only.
2. Talks to local `:18800` health + SSE translate + cancel.
3. Live-as-you-type + Dịch ngay + Xóa work as specified.
4. Streamlit and backend untouched.
5. Vietnamese-first UI labels; empty states readable.

## Defaults (locked)

- Auto-health on load: **on** (lightweight `GET /health`)
- Live mode: **on**
- Debounce: **450** ms
- `max_new_tokens`: **256**
- Min chars before live translate: **2**
- API base: `http://127.0.0.1:18800`

## Public path (locked)

- **`/translate`** → `https://aiface.ript.vn/translate`
- Must not collide with `/face-test`
- Nginx (or host) maps this path to `frontend/index.html` at deploy time — out of scope for HTML file itself except documenting the target path
