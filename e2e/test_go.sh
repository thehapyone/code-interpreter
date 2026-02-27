#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)
RUNS_DIR=${RUNS_DIR:-"$SCRIPT_DIR/runs"}
RUN_ID=${RUN_ID:-run-$(date +%Y%m%d-%H%M%S)-go-$RANDOM}
WORKDIR=${WORKDIR:-"$RUNS_DIR/$RUN_ID"}
mkdir -p "$WORKDIR"

API_KEY=${API_KEY:-dev-demo-key}
ENTITY_ID=${ENTITY_ID:-go_agent_$RANDOM}
BASE_URL=${BASE_URL:-http://localhost:8000}

echo "[go] artifacts: $WORKDIR"

runtime_available=$(curl -s "$BASE_URL/health" | jq -r '.runtime_capabilities["go"].available // false')
if [[ "$runtime_available" != "true" ]]; then
  echo "[go] skipping: runtime unavailable"
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
  -o "$WORKDIR/go-upload.json"

SESSION_ID=$(jq -r '.session_id' "$WORKDIR/go-upload.json")
FILE_ID=$(jq -r '.files[0].id' "$WORKDIR/go-upload.json")

GO_CODE=$(cat <<'GO'
package main

import (
    "fmt"
    "os"
    "strconv"
    "strings"
)

func main() {
    data, err := os.ReadFile("demo-data.csv")
    if err != nil {
        panic(err)
    }
    lines := strings.Split(strings.TrimSpace(string(data)), "\n")
    lines = lines[1:]
    sum := 0
    for _, line := range lines {
        parts := strings.Split(line, ",")
        val, _ := strconv.Atoi(strings.TrimSpace(parts[1]))
        sum += val
    }
    fmt.Printf("go rows=%d\n", len(lines))
    fmt.Printf("go sum=%d\n", sum)
    os.WriteFile("go-output.txt", []byte(fmt.Sprintf("rows=%d,sum=%d\n", len(lines), sum)), 0o644)
}
GO
)

jq -n \
  --arg code "$GO_CODE" \
  --arg entity "$ENTITY_ID" \
  --arg file_id "$FILE_ID" \
  --arg session "$SESSION_ID" \
  '{
    code: $code,
    lang: "go",
    entity_id: $entity,
    files: [
      {id: $file_id, session_id: $session, name: "demo-data.csv"}
    ]
  }' > "$WORKDIR/go_payload.json"

curl -s -X POST "$BASE_URL/exec" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d @"$WORKDIR/go_payload.json" | tee "$WORKDIR/go_response.json" | jq

curl -s -H "x-api-key: $API_KEY" "$BASE_URL/files/$SESSION_ID?detail=full" \
  -o "$WORKDIR/go_files.json"
jq < "$WORKDIR/go_files.json"

GO_OUTPUT_ID=$(jq -r '.[] | select(.name == "go-output.txt") | .id' "$WORKDIR/go_files.json" | head -n 1)
if [[ -n "$GO_OUTPUT_ID" && "$GO_OUTPUT_ID" != "null" ]]; then
  curl -s -H "x-api-key: $API_KEY" "$BASE_URL/download/$SESSION_ID/$GO_OUTPUT_ID" \
    -o "$WORKDIR/go-output.txt"
  echo "[go] downloaded go-output.txt to $WORKDIR"
fi
