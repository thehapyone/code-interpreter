#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)
RUNS_DIR=${RUNS_DIR:-"$SCRIPT_DIR/runs"}
RUN_ID=${RUN_ID:-run-$(date +%Y%m%d-%H%M%S)-$RANDOM}
WORKDIR=${WORKDIR:-"$RUNS_DIR/$RUN_ID"}
mkdir -p "$WORKDIR"

API_KEY=${API_KEY:-dev-demo-key}
BASE_URL=${BASE_URL:-http://localhost:8000}
ENTITY_ID=${ENTITY_ID:-demo_agent}

PAYLOAD=$(jq -n --arg entity "$ENTITY_ID" '{code: "print(42)", lang: "brainfuck", entity_id: $entity}')

STATUS=$(curl -s -o "$WORKDIR/unsupported-response.json" -w "%{http_code}" \
  -X POST "$BASE_URL/exec" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d "$PAYLOAD")

jq < "$WORKDIR/unsupported-response.json"

if [[ "$STATUS" != "400" ]]; then
  echo "Expected 400 from unsupported language test, got $STATUS" >&2
  exit 1
fi

detail=$(jq -r '.detail' "$WORKDIR/unsupported-response.json")
if [[ $detail != Unsupported* ]]; then
  echo "Unexpected error detail: $detail" >&2
  exit 1
fi

echo "Unsupported language test passed (artifacts: $WORKDIR)"
