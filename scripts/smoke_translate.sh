#!/usr/bin/env bash
# Smoke-test envit5 SSE /translate for both directions + health.
set -euo pipefail

API_BASE="${ENVIT5_API_BASE:-http://127.0.0.1:18800}"

echo "== GET ${API_BASE}/health =="
curl -sS "${API_BASE}/health" | tee /tmp/envit5_health.json
echo
python3 - <<'PY'
import json, sys
h = json.load(open("/tmp/envit5_health.json"))
assert h.get("ready") is True, f"model not ready: {h}"
print("health OK — device:", h.get("device"), "model:", h.get("model_id"))
PY

smoke_one() {
  local label="$1"
  local payload="$2"
  local out="/tmp/envit5_smoke_${label}.txt"
  echo
  echo "== POST /translate (${label}) =="
  curl -sS -N -X POST "${API_BASE}/translate" \
    -H 'Content-Type: application/json' \
    -H 'Accept: text/event-stream' \
    -d "${payload}" | tee "${out}"
  echo
  # Require at least one token event and a done event
  grep -q 'event: token' "${out}" || { echo "FAIL ${label}: no token events"; exit 1; }
  grep -q 'event: done' "${out}" || { echo "FAIL ${label}: no done event"; exit 1; }
  grep -q 'event: meta' "${out}" || { echo "FAIL ${label}: no meta event"; exit 1; }
  echo "OK ${label}"
}

smoke_one "vi-en" '{"text":"Xin chào các bạn","direction":"vi-en","max_new_tokens":64}'
smoke_one "en-vi" '{"text":"Hello everyone","direction":"en-vi","max_new_tokens":64}'

# Multi-sentence with special cases: ellipsis, repeated commas, quoted period.
MULTI='{"text":"Wait... Really? He said \"Hi.\" a,, b,,, c. Next sentence here.","direction":"en-vi","max_new_tokens":64}'
smoke_one "multi-chunk" "${MULTI}"

echo
echo "All smoke checks passed."
