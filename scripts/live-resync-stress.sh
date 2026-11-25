#!/usr/bin/env bash
# Drive keyed reads while repeated operator resyncs run through the MCP mirror.
# Every credential is supplied through the environment. This script never reads
# an env file, and it never prints a credential.
set -Eeuo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:3199}"
API_KEY="${API_KEY:?set API_KEY to a read-enabled API key}"
ADMIN_KEY="${ADMIN_KEY:?set ADMIN_KEY to an admin API key with manage:keys}"
PROCESS_PATTERN="${PROCESS_PATTERN:-utmelab-api}"
REPLICA_PATH="${REPLICA_PATH:-}"
SERVER_LOG="${SERVER_LOG:-}"

CYCLES="${CYCLES:-3}"
START_DELAY="${START_DELAY:-10}"
COOLDOWN="${COOLDOWN:-60}"
DURATION="${DURATION:-$((START_DELAY + CYCLES * COOLDOWN + 20))}"
SAMPLE_INTERVAL="${SAMPLE_INTERVAL:-0.2}"
WRK_THREADS="${WRK_THREADS:-4}"
WRK_CONNS="${WRK_CONNS:-32}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-240}"
MAX_FAIL_SECS="${MAX_FAIL_SECS:-2}"
MIN_OK_PCT="${MIN_OK_PCT:-99.9}"
OUTDIR="${OUTDIR:-/tmp/opencode/resync-stress/run-$(date -u +%Y%m%dT%H%M%SZ)}"

mkdir -p "$OUTDIR"
WRK_PID=""
SAMPLER_PID=""

now() { date +%s.%N; }

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

cleanup() {
  [[ -n "$WRK_PID" ]] && kill "$WRK_PID" 2>/dev/null || true
  [[ -n "$SAMPLER_PID" ]] && kill "$SAMPLER_PID" 2>/dev/null || true
  touch "$OUTDIR/stop"
  [[ -n "$WRK_PID" ]] && wait "$WRK_PID" 2>/dev/null || true
  [[ -n "$SAMPLER_PID" ]] && wait "$SAMPLER_PID" 2>/dev/null || true
}
trap cleanup EXIT

for cmd in curl jq wrk awk find date; do
  require_cmd "$cmd"
done

read_code() {
  local file="$1"
  curl -sS --max-time 5 -o "$file" -w '%{http_code}' \
    -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/exams" 2>/dev/null || echo "000"
}

health_code() {
  curl -sS --max-time 5 -o "$OUTDIR/health.json" -w '%{http_code}' \
    "$BASE_URL/health" 2>/dev/null || echo "000"
}

mcp_status() {
  local code
  code=$(curl -sS --max-time 10 -o "$OUTDIR/status-rpc.json" -w '%{http_code}' \
    -H "X-API-Key: $ADMIN_KEY" \
    -H 'content-type: application/json' \
    -H 'accept: application/json, text/event-stream' \
    --data '{"jsonrpc":"2.0","id":900,"method":"tools/call","params":{"name":"status","arguments":{}}}' \
    "$BASE_URL/mcp/admin" 2>/dev/null || echo "000")
  [[ "$code" == "200" ]] || return 1
  jq -er '.result.content[0].text // empty' "$OUTDIR/status-rpc.json" > "$OUTDIR/status.json" || return 1
  jq -e . "$OUTDIR/status.json" >/dev/null 2>&1
}

wait_ready() {
  local deadline=$(( $(date +%s) + WAIT_TIMEOUT )) code
  while :; do
    code=$(read_code "$OUTDIR/readiness.json")
    if [[ "$code" == "200" ]] && jq -e 'type == "array"' "$OUTDIR/readiness.json" >/dev/null 2>&1; then
      return 0
    fi
    [[ $(date +%s) -ge "$deadline" ]] && return 1
    sleep 1
  done
}

wait_pending_false() {
  for _ in $(seq 1 "$WAIT_TIMEOUT"); do
    mcp_status || true
    if [[ -s "$OUTDIR/status.json" ]] \
      && [[ "$(jq -r '.sync_resync_enabled // false' "$OUTDIR/status.json")" == "true" ]] \
      && [[ "$(jq -r 'if has("sync_resync_pending") then .sync_resync_pending else true end' "$OUTDIR/status.json")" == "false" ]] \
      && [[ "$(jq -r 'if has("sync_resync_draining") then .sync_resync_draining else true end' "$OUTDIR/status.json")" == "false" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

mcp_resync() {
  local id="$1"
  local file="$OUTDIR/resync-$id.json"
  curl -sS --max-time 30 -o "$file" -w '%{http_code}' \
    -H "X-API-Key: $ADMIN_KEY" \
    -H 'content-type: application/json' \
    -H 'accept: application/json, text/event-stream' \
    --data "{\"jsonrpc\":\"2.0\",\"id\":$id,\"method\":\"tools/call\",\"params\":{\"name\":\"resync_now\",\"arguments\":{}}}" \
    "$BASE_URL/mcp/admin" 2>/dev/null || echo "000"
}

sampler() {
  local n=0 code latency result
  while [[ ! -f "$OUTDIR/stop" ]]; do
    n=$((n + 1))
    result=$(curl -sS --max-time 5 -o "$OUTDIR/last-read.json" -w '%{http_code}|%{time_total}' \
      -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/exams" 2>/dev/null || true)
    IFS='|' read -r code latency <<< "$result"
    [[ -n "$code" ]] || code="000"
    [[ -n "$latency" ]] || latency="5"
    printf '%s\t%s\t%s\n' "$(now)" "$code" "$latency" >> "$OUTDIR/samples.tsv"
    if (( n % 25 == 0 )); then
      printf '%s\t%s\n' "$(now)" "$(health_code)" >> "$OUTDIR/health.tsv"
    fi
    sleep "$SAMPLE_INTERVAL"
  done
}

echo "start $(now)" > "$OUTDIR/events.tsv"
: > "$OUTDIR/samples.tsv"
: > "$OUTDIR/health.tsv"

[[ "$(health_code)" == "200" ]] || fail "health failed before the run"
wait_ready || fail "keyed reads were not ready before the run"
mcp_status || fail "MCP status failed before the run"
cp "$OUTDIR/status.json" "$OUTDIR/status-before.json"
jq -e '
  .sync_state == "ready" and
  .sync_readiness == "ready" and
  .sync_resync_enabled == true and
  .sync_resync_pending == false and
  .sync_resync_draining == false
' "$OUTDIR/status-before.json" >/dev/null || fail "service was not ready with the resync gate open"

wrk -t"$WRK_THREADS" -c"$WRK_CONNS" -d"${DURATION}s" --latency \
  -H "X-API-Key: $API_KEY" "$BASE_URL/api/v1/exams" \
  > "$OUTDIR/wrk.txt" 2>&1 &
WRK_PID=$!

sampler &
SAMPLER_PID=$!

sleep "$START_DELAY"
for (( i = 1; i <= CYCLES; i++ )); do
  wait_pending_false || fail "resync did not finish before cycle $i"
  trigger_at=$(now)
  printf '%s\ttrigger\t%d\n' "$trigger_at" "$i" >> "$OUTDIR/events.tsv"
  code=$(mcp_resync "$i")
  printf '%s\ttrigger_http\t%d\t%d\n' "$(now)" "$i" "$code" >> "$OUTDIR/events.tsv"
  [[ "$code" == "200" ]] || fail "MCP resync $i returned HTTP $code"
  if ! jq -e '.error == null and (.result | type == "object")' "$OUTDIR/resync-$i.json" >/dev/null 2>&1; then
    fail "MCP resync $i returned a JSON-RPC error"
  fi
  sleep "$COOLDOWN"
done

printf '%s\ttriggers_done\n' "$(now)" >> "$OUTDIR/events.tsv"
wait "$WRK_PID"
WRK_PID=""
touch "$OUTDIR/stop"
wait "$SAMPLER_PID" || true
SAMPLER_PID=""

[[ "$(health_code)" == "200" ]] || fail "health failed after the run"
wait_ready || fail "keyed reads did not recover after the run"
mcp_status || fail "MCP status failed after the run"
cp "$OUTDIR/status.json" "$OUTDIR/status-after.json"
jq -e '
  .sync_state == "ready" and
  .sync_readiness == "ready" and
  .sync_resync_pending == false and
  .sync_resync_draining == false
' "$OUTDIR/status-after.json" >/dev/null || fail "service did not return to a ready, undrained state"
printf '%s\tend\n' "$(now)" >> "$OUTDIR/events.tsv"

pgrep -af "$PROCESS_PATTERN" > "$OUTDIR/processes.txt" || true
[[ -s "$OUTDIR/processes.txt" ]] || fail "server process disappeared during the run"

if [[ -n "$REPLICA_PATH" ]]; then
  dir=$(dirname "$REPLICA_PATH")
  base=$(basename "$REPLICA_PATH")
  find "$dir" -maxdepth 1 -type f \
    \( -name "$base.resync-*" -o -name "$base.resync-superseded-*" -o -name "$base.resync-failed-*" \) \
    -printf '%f\n' | sort > "$OUTDIR/artifacts.txt" || true
fi

if [[ -n "$SERVER_LOG" && -r "$SERVER_LOG" ]]; then
  grep -E 'sync_resync_|sync state changed|sync attempt failed|schema contract' "$SERVER_LOG" \
    | tail -200 > "$OUTDIR/log-events.txt" || true
fi

awk -F'\t' '
  { total++ }
  $2 == 200 { ok++; sum += $3; if ($3 > max) max = $3 }
  $2 == 503 { unavailable++ }
  END {
    if (total == 0) total = 1
    printf "samples=%d ok=%d fail=%d ok_pct=%.4f unavailable=%d avg_latency=%.4f max_latency=%.4f\n", \
      total, ok, total - ok, 100 * ok / total, unavailable + 0, sum / (ok ? ok : 1), max + 0
  }
' "$OUTDIR/samples.tsv" > "$OUTDIR/read-summary.txt"

awk -F'\t' '
  $2 != 200 {
    if (start == "") start = $1
    last = $1
    next
  }
  start != "" {
    d = last - start
    if (d > worst) worst = d
    start = ""
  }
  END {
    if (start != "") {
      d = last - start
      if (d > worst) worst = d
    }
    printf "max_consecutive_failure_secs=%.3f\n", worst + 0
  }
' "$OUTDIR/samples.tsv" > "$OUTDIR/failure-window.txt"

awk -F'\t' '
  { total++ }
  $2 == 200 { ok++ }
  END {
    if (total == 0) total = 1
    printf "health_samples=%d ok=%d ok_pct=%.4f\n", total, ok, 100 * ok / total
  }
' "$OUTDIR/health.tsv" > "$OUTDIR/health-summary.txt"

ok_pct=$(awk -F'[= ]' '/ok_pct/{print $2}' "$OUTDIR/read-summary.txt")
fail_secs=$(awk -F= '/max_consecutive_failure_secs/{print $2}' "$OUTDIR/failure-window.txt")

{
  echo "outcome directory: $OUTDIR"
  cat "$OUTDIR/read-summary.txt"
  cat "$OUTDIR/failure-window.txt"
  cat "$OUTDIR/health-summary.txt"
  echo "cycles: $CYCLES"
  echo "duration requested: ${DURATION}s"
} | tee "$OUTDIR/report.txt"

awk -v ok="$ok_pct" -v min="$MIN_OK_PCT" -v fail="$fail_secs" -v max="$MAX_FAIL_SECS" \
  'BEGIN { exit !(ok >= min && fail <= max) }' \
  || fail "read availability crossed the threshold (min ok ${MIN_OK_PCT}%, max failure ${MAX_FAIL_SECS}s)"

echo "PASS: staged resync stayed inside the availability budget"
