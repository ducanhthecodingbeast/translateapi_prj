# Translate Sandbox HTML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one static HTML page (`frontend/index.html`) that is a translate-only, face-test-styled sandbox for the local envit5 FastAPI on `:18800`, intended for public path `https://aiface.ript.vn/translate`.

**Architecture:** Single self-contained HTML file with inline CSS + JS. Browser talks to FastAPI via `fetch`: `GET /health`, `POST /translate` (SSE body stream), `POST /cancel` when superseding. No build step, no npm, no Streamlit changes.

**Tech Stack:** HTML5, CSS3, vanilla JS (`fetch` + ReadableStream SSE parse). Existing FastAPI + sse-starlette backend (unchanged).

## Global Constraints

- Translate-only — no face recognition UI/APIs
- Visual language matches face-test: cream canvas, terracotta primary, soft secondary, metric chips, Vietnamese-first labels
- Default API base: `http://127.0.0.1:18800`
- Live-as-you-type on by default; debounce 450ms; min 2 chars; max_new_tokens 256 (cap 512)
- Public path target: `/translate` (deploy/nginx out of scope for this file)
- Do not modify `backend/*` or `frontend/streamlit_app.py`
- Do not start servers, kill processes, or delete files unless the user explicitly asks

## File map

| Path | Action | Responsibility |
|------|--------|----------------|
| `frontend/index.html` | Create | Full UI + SSE client |
| `docs/superpowers/specs/2026-07-13-translate-sandbox-html-design.md` | Already written | Design authority |
| `docs/superpowers/plans/2026-07-13-translate-sandbox-html.md` | Create | This plan |
| `README.md` | Optional one-line note | Mention HTML sandbox path |

---

### Task 1: Scaffold page shell (markup + face-test CSS)

**Files:**
- Create: `frontend/index.html`

**Interfaces:**
- Produces: DOM ids used by later JS:
  - `#apiBase`, `#debounceMs`, `#maxNewTokens`, `#liveToggle`
  - `#btnHealth`, `#statusLog`
  - `#chipReady`, `#chipDevice`, `#chipMeta`
  - `#direction`, `#sourceText`
  - `#btnTranslate`, `#btnClear`
  - `#translationOut`, `#streamStatus`

- [ ] **Step 1: Create `frontend/index.html` with full layout + CSS + working JS**

Because this is one self-contained file and the user asked to continue to code, implement the complete page in one pass (shell + health + SSE), then commit.

Layout (2×2 cards):

1. Hero left: badge `TRANSLATION SANDBOX`, H1, short desc, 3 chips
2. Config right: API base, debounce, max tokens, live checkbox, **Kiểm tra health**, status log
3. Source: direction select, textarea, **Dịch ngay** / **Xóa**
4. Translation: output panel + stream status line

CSS tokens:

```css
:root {
  --canvas: #f3ebe3;
  --canvas-2: #faf6f1;
  --card: #f7f0e8;
  --card-deep: #f3e9df;
  --ink: #1c1917;
  --muted: #6b635b;
  --hairline: #e4d9cd;
  --white: #ffffff;
  --primary: #c46a4f;
  --secondary: #ebe2d7;
  --secondary-ink: #3f3a35;
  --ok: #2f6f4e;
  --radius: 22px;
}
```

Defaults:
- apiBase `http://127.0.0.1:18800`
- debounceMs `450`
- maxNewTokens `256`
- liveToggle checked
- direction: auto | vi-en | en-vi
- empty translation: `Bản dịch sẽ hiện khi bạn gõ…`
- empty status log: `Chưa kiểm tra API.`

- [ ] **Step 2: Implement health + chips + log**

`GET {base}/health` → HealthResponse `{ status, model_id, device, ready }`.
Auto-run on load. Wire **Kiểm tra health**.

- [ ] **Step 3: Implement SSE translate + cancel + live debounce**

- `POST {base}/translate` with `{ text, direction, max_new_tokens }`, Accept `text/event-stream`
- Parse SSE events: meta, chunk, token, done, error
- On supersede: AbortController.abort + POST `/cancel`
- Live: debounce on source input when live checked and len >= 2
- **Dịch ngay**: force translate
- **Xóa**: clear + cancel
- genId to ignore stale streams

- [ ] **Step 4: Commit**

```bash
cd "/home/aiface/Face_recognize/translating demo"
git add frontend/index.html docs/superpowers/plans/2026-07-13-translate-sandbox-html.md docs/superpowers/specs/2026-07-13-translate-sandbox-html-design.md
git commit -m "feat: add face-test style translate sandbox HTML"
```

- [ ] **Step 5: Optional README one-liner** if frontend section exists

```markdown
- `frontend/index.html` — face-test-style translate sandbox (target path `/translate`)
```

## Manual test checklist (API must already be up — do not start it)

- Health button / auto-health updates chips when API up
- Type ≥2 chars → debounced stream fills translation
- Type mid-stream → cancel + new stream
- Live off + Dịch ngay works
- Xóa clears panes
- Bad base URL → status log error, no throw

## Spec coverage

| Spec item | Covered |
|-----------|---------|
| Single HTML face-test look | Task 1 |
| Health + chips | Step 2 |
| Live SSE + cancel | Step 3 |
| Dịch ngay / Xóa | Step 3 |
| Path `/translate` documented | plan + spec |
| Backend/Streamlit untouched | yes |

## Execution note

User chose path `/translate` and said continue to code. Implement inline in one complete `frontend/index.html`, then commit. Do not start the translation API unless asked.
