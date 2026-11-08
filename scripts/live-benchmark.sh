#!/usr/bin/env bash
set -euo pipefail

# Run against a live Rust server. The server must use the real .env Turso
# configuration. This script measures HTTP behavior only; it never writes to
# the database.

BASE_URL="${BASE_URL:-http://127.0.0.1:3100}"
RUNS="${RUNS:-3}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${UTMELAB_DEV_API_KEY:?set UTMELAB_DEV_API_KEY or provide a .env file}"

measure() {
  local label="$1"
  local method="$2"
  local path="$3"
  local key="$4"
  local n

  for ((n = 1; n <= RUNS; n++)); do
    if [[ "$method" == "POST" ]]; then
      curl --fail --silent --show-error --output /dev/null \
        --request POST \
        --header "X-API-Key: $UTMELAB_DEV_API_KEY" \
        --header 'Content-Type: application/json' \
        --data '{"country":"NG","seed":42}' \
        --write-out "$label run=$n status=%{http_code} time=%{time_total}s size=%{size_download}\n" \
        "$BASE_URL$path"
    elif [[ "$key" == "yes" ]]; then
      curl --fail --silent --show-error --output /dev/null \
        --header "X-API-Key: $UTMELAB_DEV_API_KEY" \
        --write-out "$label run=$n status=%{http_code} time=%{time_total}s size=%{size_download}\n" \
        "$BASE_URL$path"
    else
      curl --fail --silent --show-error --output /dev/null \
        --write-out "$label run=$n status=%{http_code} time=%{time_total}s size=%{size_download}\n" \
        "$BASE_URL$path"
    fi
  done
}

curl --fail --silent --show-error "$BASE_URL/ready" >/dev/null
measure public-summary GET /api/v1/public/summary no
measure public-exams GET /api/v1/public/exams no
measure public-syllabus GET /api/v1/public/syllabus/JAMB/use-of-english no
measure question-sample GET '/api/v1/questions/sample?exam=JAMB&subject=use-of-english&count=15&seed=42' yes
measure question-page GET '/api/v1/questions?exam=JAMB&subject=use-of-english&page=1&per_page=50' yes
measure paper-readiness GET '/api/v1/exams/JAMB/papers?country=NG' yes
measure paper-assembly POST /api/v1/papers/JAMB/use-of-english yes
