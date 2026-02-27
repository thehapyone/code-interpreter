#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)
RUNS_DIR=${RUNS_DIR:-"$SCRIPT_DIR/runs"}
RUN_ID=${RUN_ID:-run-$(date +%Y%m%d-%H%M%S)-bash-$RANDOM}
WORKDIR=${WORKDIR:-"$RUNS_DIR/$RUN_ID"}
mkdir -p "$WORKDIR"

API_KEY=${API_KEY:-dev-demo-key}
ENTITY_ID=${ENTITY_ID:-bash_agent_$RANDOM}
BASE_URL=${BASE_URL:-http://localhost:8000}

echo "[bash] artifacts: $WORKDIR"

BASH_CODE='set -euo pipefail
echo "hello from bash" > bash-output.txt
cat bash-output.txt'

jq -n --arg code "$BASH_CODE" --arg entity "$ENTITY_ID" '{code: $code, lang: "bash", entity_id: $entity}' > "$WORKDIR/bash_payload.json"

curl -s -X POST "$BASE_URL/exec" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d @"$WORKDIR/bash_payload.json" | tee "$WORKDIR/bash_response.json" | jq

SESSION_ID=$(jq -r '.session_id' "$WORKDIR/bash_response.json")
curl -s -H "x-api-key: $API_KEY" "$BASE_URL/files/$SESSION_ID?detail=full" | tee "$WORKDIR/bash_files.json" | jq

OUTPUT_ID=$(jq -r '.[] | select(.name == "bash-output.txt") | .id' "$WORKDIR/bash_files.json" | head -n 1)
if [[ -n "$OUTPUT_ID" && "$OUTPUT_ID" != "null" ]]; then
  curl -s -H "x-api-key: $API_KEY" "$BASE_URL/download/$SESSION_ID/$OUTPUT_ID" -o "$WORKDIR/bash-output.txt"
  echo "Downloaded bash-output to $WORKDIR/bash-output.txt"
fi
