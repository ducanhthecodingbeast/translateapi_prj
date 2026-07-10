# Acceptance criteria — sentence-chunk translation (demo gate)

**Gate rule:** do **not** merge/push `main` until every **Required** item is PASS.
**Branch rule:** all remaining work lands on a worktree branch; main only after green.

Repo: https://github.com/ducanhthecodingbeast/mrdungdemo  
Local: `.../claude + codex/mrdungdemo`  
Remote demo: `cnsh:.../facerecognition/mrdungdemo` (API `:18800`)

---

## A. Unit (no GPU) — Required

| ID | Criterion | How to verify | Pass |
|----|-----------|---------------|------|
| A1 | Basic sentence split on `.!?` | `split_sentences("Hello world. How are you? Fine!")` → 3 sents | |
| A2 | `...` is one terminator | `"Wait... Really?"` → `["Wait...", "Really?"]` | |
| A3 | Unicode `…` is one terminator | `"Done… Yes."` → `["Done…", "Yes."]` | |
| A4 | `,,` / `,,,` never split | `"a,, b,,, c. Next."` → `["a,, b,,, c.", "Next."]` | |
| A5 | Quotes protect interior, then split for new sentence | `'He said "Hi." Bye.'` → 2 sents | |
| A6 | Quoted ellipsis + lowercase continues | `'She whispered "Wait..." then left.'` → 1 sent | |
| A7 | Lone commas never split | `"apples, oranges, bananas"` → 1 sent | |
| A8 | VI multi-sentence | 3 sents for `Xin chào. Tôi là sinh viên. Bạn khỏe không?` | |
| A9 | Pack under budget | `pack_chunks` never exceeds `max_tokens` except single-word overflow | |
| A10 | Hard-split oversized sentence by words | 5 words / max 2 → pieces ≤ 2 words | |
| A11 | Body limit 20000 | accept 5000 chars; reject 20001 | |
| A12 | `max_new_tokens` default 256, cap 512 | schema clamp | |
| A13 | Direction tests still green | `pytest tests/test_direction.py` | |

```bash
cd mrdungdemo
PYTHONPATH=backend python3 -m pytest tests/test_chunking.py tests/test_direction.py -v
```

---

## B. SSE contract (local or remote API) — Required for demo

| ID | Criterion | How to verify | Pass |
|----|-----------|---------------|------|
| B1 | `/health` → `ready: true` | `curl -s localhost:18800/health` | |
| B2 | Short VI→EN streams | meta + ≥1 token + done | |
| B3 | Short EN→VI streams | same | |
| B4 | `meta.chunks` present (int ≥ 1) | parse first meta event | |
| B5 | Multi-sentence special-case text streams full tail | text with `...`, `,,`, quoted `.` → `done.text` non-empty, no cancel | |
| B6 | Optional `chunk` events `{i,n}` | if present, `0 ≤ i < n` | |
| B7 | Cancel still works | `/cancel` during long job → error cancelled or supersede | Optional |

```bash
bash scripts/smoke_translate.sh
```

---

## C. Git / worktree process — Required before main push

| ID | Criterion | Pass |
|----|-----------|------|
| C1 | Feature branch on worktree (not direct main edits for final) | |
| C2 | All A* green on that branch | |
| C3 | Diff limited to chunking scope (no face / unrelated) | |
| C4 | Commit message clear | |
| C5 | Merge/push **main** only after A* + C* (and B* if API available locally) | |
| C6 | No force-push to main | |

---

## D. Remote cnsh deploy — Required for customer demo

| ID | Criterion | How | Pass |
|----|-----------|-----|------|
| D1 | `git pull` on cnsh project path has latest main | ssh/cnsh | |
| D2 | API restarted, `/health` ready | port 18800 | |
| D3 | `smoke_translate.sh` green on remote | | |
| D4 | Demo sample with `...` `,,` quotes translates end-to-end | curl or Streamlit | |

---

## Out of scope (do not block)

- Face backend / aiface.ript.vn
- Streamlit rewrite
- Auth, docker GPU compose, multi-worker

---

## Sign-off

| Gate | Owner | Result | Date |
|------|-------|--------|------|
| Local unit A* | | | |
| SSE B* | | | |
| Git C* | | | |
| Remote D* | | | |
| **Push main allowed?** | | YES only if A+C pass; demo live only if D pass | |
