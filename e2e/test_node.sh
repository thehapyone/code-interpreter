#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)
RUNS_DIR=${RUNS_DIR:-"$SCRIPT_DIR/runs"}
RUN_ID=${RUN_ID:-run-$(date +%Y%m%d-%H%M%S)-node-$RANDOM}
WORKDIR=${WORKDIR:-"$RUNS_DIR/$RUN_ID"}
mkdir -p "$WORKDIR"

API_KEY=${API_KEY:-dev-demo-key}
ENTITY_ID=${ENTITY_ID:-node_agent_$RANDOM}
BASE_URL=${BASE_URL:-http://localhost:8000}

echo "[node] artifacts: $WORKDIR"

runtime_available=$(curl -s "$BASE_URL/health" | jq -r '.runtime_capabilities["node"].available // false')
if [[ "$runtime_available" != "true" ]]; then
  echo "[node] skipping: runtime unavailable on server"
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
  -o "$WORKDIR/node-upload.json"

SESSION_ID=$(jq -r '.session_id' "$WORKDIR/node-upload.json")
FILE_ID=$(jq -r '.files[0].id' "$WORKDIR/node-upload.json")

NODE_CODE=$(cat <<'JS'
import { readFileSync, writeFileSync } from 'node:fs';

const lines = readFileSync('demo-data.csv', 'utf-8').trim().split('\n').slice(1);
const values = lines.map(line => Number(line.split(',')[1]));
const sum = values.reduce((acc, cur) => acc + cur, 0);
console.log(`node rows=${values.length}`);
console.log(`node sum=${sum}`);
writeFileSync('node-output.json', JSON.stringify({ rows: values.length, sum }));
JS
)

jq -n \
  --arg code "$NODE_CODE" \
  --arg entity "$ENTITY_ID" \
  --arg file_id "$FILE_ID" \
  --arg session "$SESSION_ID" \
  '{
    code: $code,
    lang: "js",
    entity_id: $entity,
    files: [
      {id: $file_id, session_id: $session, name: "demo-data.csv"}
    ]
  }' > "$WORKDIR/node_payload.json"

curl -s -X POST "$BASE_URL/exec" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d @"$WORKDIR/node_payload.json" | tee "$WORKDIR/node_response.json" | jq

curl -s -H "x-api-key: $API_KEY" "$BASE_URL/files/$SESSION_ID?detail=full" \
  -o "$WORKDIR/node_files.json"
jq < "$WORKDIR/node_files.json"

NODE_OUTPUT_ID=$(jq -r '.[] | select(.name == "node-output.json") | .id' "$WORKDIR/node_files.json" | head -n 1)
if [[ -n "$NODE_OUTPUT_ID" && "$NODE_OUTPUT_ID" != "null" ]]; then
  curl -s -H "x-api-key: $API_KEY" "$BASE_URL/download/$SESSION_ID/$NODE_OUTPUT_ID" \
    -o "$WORKDIR/node-output.json"
  echo "[node] downloaded node-output.json to $WORKDIR"
fi
