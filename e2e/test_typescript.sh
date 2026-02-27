#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)
RUNS_DIR=${RUNS_DIR:-"$SCRIPT_DIR/runs"}
RUN_ID=${RUN_ID:-run-$(date +%Y%m%d-%H%M%S)-ts-$RANDOM}
WORKDIR=${WORKDIR:-"$RUNS_DIR/$RUN_ID"}
mkdir -p "$WORKDIR"

API_KEY=${API_KEY:-dev-demo-key}
ENTITY_ID=${ENTITY_ID:-ts_agent_$RANDOM}
BASE_URL=${BASE_URL:-http://localhost:8000}

echo "[typescript] artifacts: $WORKDIR"

runtime_available=$(curl -s "$BASE_URL/health" | jq -r '.runtime_capabilities["ts-node"].available // false')
if [[ "$runtime_available" != "true" ]]; then
  echo "[typescript] skipping: ts-node runtime unavailable"
  exit 0
fi

cat <<'CSV' > "$WORKDIR/demo-data.csv"
name,value
Alice,10
Bob,20
CSV

curl -s -X POST "$BASE_URL/upload" \
  -H "x-api-key: $API_KEY" \
  -F "entity_id=$ENTITY_ID" \
  -F "files=@$WORKDIR/demo-data.csv" \
  -o "$WORKDIR/ts-upload.json"

SESSION_ID=$(jq -r '.session_id' "$WORKDIR/ts-upload.json")
FILE_ID=$(jq -r '.files[0].id' "$WORKDIR/ts-upload.json")

TS_CODE=$(cat <<'TS'
import * as fs from 'fs';

const text = fs.readFileSync('demo-data.csv', 'utf-8').trim().split('\n').slice(1);
const values = text.map(line => Number(line.split(',')[1]));
const avg = values.reduce((acc, cur) => acc + cur, 0) / values.length;
console.log(`ts rows=${values.length}`);
console.log(`ts avg=${avg.toFixed(2)}`);
fs.writeFileSync('ts-report.txt', `rows=${values.length},avg=${avg.toFixed(2)}`);
TS
)

jq -n \
  --arg code "$TS_CODE" \
  --arg entity "$ENTITY_ID" \
  --arg file_id "$FILE_ID" \
  --arg session "$SESSION_ID" \
  '{
    code: $code,
    lang: "ts",
    entity_id: $entity,
    files: [
      {id: $file_id, session_id: $session, name: "demo-data.csv"}
    ]
  }' > "$WORKDIR/ts_payload.json"

curl -s -X POST "$BASE_URL/exec" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d @"$WORKDIR/ts_payload.json" | tee "$WORKDIR/ts_response.json" | jq

curl -s -H "x-api-key: $API_KEY" "$BASE_URL/files/$SESSION_ID?detail=full" \
  -o "$WORKDIR/ts_files.json"
jq < "$WORKDIR/ts_files.json"

TS_REPORT_ID=$(jq -r '.[] | select(.name == "ts-report.txt") | .id' "$WORKDIR/ts_files.json" | head -n 1)
if [[ -n "$TS_REPORT_ID" && "$TS_REPORT_ID" != "null" ]]; then
  curl -s -H "x-api-key: $API_KEY" "$BASE_URL/download/$SESSION_ID/$TS_REPORT_ID" \
    -o "$WORKDIR/ts-report.txt"
  echo "[typescript] downloaded ts-report.txt to $WORKDIR"
fi
