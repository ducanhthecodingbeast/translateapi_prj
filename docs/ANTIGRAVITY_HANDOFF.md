# Antigravity handoff — mrdungdemo sentence-chunk translation

**Why this exists:** Claude Code auto-mode cannot run Bash (`claude-opus-4-8[1m]` classifier unavailable). Code + criteria are on disk; shell/git/deploy need another runner.

**Repo:** https://github.com/ducanhthecodingbeast/mrdungdemo  
**Local workdir:** `/home/dangnguyenducanh/claude + codex/mrdungdemo`  
**Remote demo:** `cnsh:/home/aiface/dangnguyenducanh/facerecognition/mrdungdemo` (API `:18800`)  
**Criteria:** `docs/ACCEPTANCE_CRITERIA.md`  
**Gate:** do **not** push `main` until A* unit green + feature-branch commit. Demo live needs D* remote smoke.

**Out of scope:** face backend, aiface.ript.vn, Streamlit rewrite, auth, docker GPU.

---

## Already done (do not re-implement unless tests fail)

| File | Change |
|------|--------|
| `backend/model_service.py` | `split_sentences`, `pack_chunks`, multi-chunk `stream_translate` |
| `backend/schemas.py` | `MAX_TEXT_LENGTH=20000`, default 256 / cap 512 |
| `backend/app.py` | SSE `meta.chunks`, `chunk` events |
| `tests/test_chunking.py` | special cases `...` `,,` quotes |
| `scripts/selfcheck_chunking.py` | no-GPU self-check (stubs torch) |
| `scripts/smoke_translate.sh` | multi-chunk sample |
| `docs/ACCEPTANCE_CRITERIA.md` | pass/fail matrix |

---

## Task 1 — Local unit gate (Required, do first)

**Agent type:** full / self  
**CWD:** `/home/dangnguyenducanh/claude + codex/mrdungdemo`

```bash
python3 scripts/selfcheck_chunking.py
# and if pytest available:
python3 -m pip install pytest pydantic -q
PYTHONPATH=backend python3 -m pytest tests/test_chunking.py tests/test_direction.py -v
```

**Pass:** print `ALL CHECKS PASSED` / all pytest green.  
**Fail:** fix only `split_sentences` / `pack_chunks` / tests for:

- `...` / `…` one unit  
- `,,` / `,,,` never split  
- quotes + period: uppercase next → split; lowercase → continue  
- body 20000; max_new_tokens cap 512  

**Deliverable:** paste full test output + list of files fixed (if any).

---

## Task 2 — Worktree branch (after Task 1 green)

**Agent type:** full / self  
**CWD:** same repo

```bash
cd "/home/dangnguyenducanh/claude + codex/mrdungdemo"
git status -sb
git worktree list
# create feature worktree (adjust if branch exists)
git worktree add -b feat/sentence-chunking \
  "/home/dangnguyenducanh/claude + codex/mrdungdemo-chunking-wt" HEAD
# ensure uncommitted changes are on the feature branch worktree
# (if edits are only on main working tree, commit there onto feat branch OR copy)
```

**Rules:**

- Do **not** push main yet  
- Do **not** force-push  
- Scope: only chunking files listed above  

**If dirty main has the edits:** create branch from current dirty tree:

```bash
git checkout -b feat/sentence-chunking
# worktree optional once branch exists
```

**Deliverable:** `git status`, branch name, worktree path.

---

## Task 3 — Commit on feature branch (after Task 1+2)

```bash
git add backend/model_service.py backend/schemas.py backend/app.py \
  tests/test_chunking.py tests/test_direction.py \
  scripts/smoke_translate.sh scripts/selfcheck_chunking.py \
  README.md docs/ACCEPTANCE_CRITERIA.md docs/ANTIGRAVITY_HANDOFF.md
git status
git commit -m "$(cat <<'EOF'
feat: sentence-chunk progressive SSE translation

Split on sentence ends with special cases (... ellipsis, ,, commas,
quotes). Pack under 480 source tokens; stream multi-chunk under one lock.
Raise body limit to 20k; per-chunk max_new_tokens default 256 cap 512.

EOF
)"
```

**Deliverable:** commit hash + `git show --stat`.

---

## Task 4 — Criteria checklist (A* + C*)

Open `docs/ACCEPTANCE_CRITERIA.md`, mark A1–A13 and C1–C4 with PASS/FAIL from Task 1–3.  
**Push main only if A* + C* all PASS.**

---

## Task 5 — Merge + push main (only if Task 4 green)

```bash
git checkout main
git merge --ff-only feat/sentence-chunking
git push origin main
```

No force-push. If non-ff, stop and report.

---

## Task 6 — Remote cnsh pull + smoke (customer demo)

**On cnsh** (path: `/home/aiface/dangnguyenducanh/facerecognition/mrdungdemo`):

```bash
git pull origin main
# restart API on 18800 (however you currently run uvicorn)
# example:
# pkill -f 'uvicorn app:app' || true
# cd backend && python3 -m uvicorn app:app --host 127.0.0.1 --port 18800
curl -sS http://127.0.0.1:18800/health
bash scripts/smoke_translate.sh
```

**Pass:** health ready; smoke OK including multi-chunk special-case text.  
**Deliverable:** health JSON + smoke log tail.

---

## Paste-ready Antigravity prompts

### Agent A — tests

> Work only in `/home/dangnguyenducanh/claude + codex/mrdungdemo`. Run `python3 scripts/selfcheck_chunking.py` and pytest for `tests/test_chunking.py` + `tests/test_direction.py`. Fix failures only in split/pack/tests. Report full output. Do not push. Do not touch face projects.

### Agent B — git worktree + commit

> After unit tests green: create branch `feat/sentence-chunking` (worktree OK), commit only chunking-related files with message about sentence-chunk SSE. Do not merge/push main. Report commit hash.

### Agent C — push + remote smoke

> Only if Agent A+B green: ff-merge `feat/sentence-chunking` → main, push origin main. Then on cnsh pull, restart API 18800, run `scripts/smoke_translate.sh`. Report health + smoke.

---

## Claude Code limitation (for humans)

This session **cannot** call Antigravity (`agy`) as a tool. Open Antigravity separately and paste Agent A/B/C prompts, or run the commands yourself. Claude Code can still edit files / update criteria when shell recovers.
