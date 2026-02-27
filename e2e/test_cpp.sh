#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)
RUNS_DIR=${RUNS_DIR:-"$SCRIPT_DIR/runs"}
RUN_ID=${RUN_ID:-run-$(date +%Y%m%d-%H%M%S)-cpp-$RANDOM}
WORKDIR=${WORKDIR:-"$RUNS_DIR/$RUN_ID"}
mkdir -p "$WORKDIR"

API_KEY=${API_KEY:-dev-demo-key}
ENTITY_ID=${ENTITY_ID:-cpp_agent_$RANDOM}
BASE_URL=${BASE_URL:-http://localhost:8000}

echo "[cpp] artifacts: $WORKDIR"

runtime_available=$(curl -s "$BASE_URL/health" | jq -r '.runtime_capabilities["c++"].available // false')
if [[ "$runtime_available" != "true" ]]; then
  echo "[cpp] skipping: runtime unavailable"
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
  -o "$WORKDIR/cpp-upload.json"

SESSION_ID=$(jq -r '.session_id' "$WORKDIR/cpp-upload.json")
FILE_ID=$(jq -r '.files[0].id' "$WORKDIR/cpp-upload.json")

CPP_CODE=$(cat <<'CPP'
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

int main() {
    std::ifstream file("demo-data.csv");
    if (!file.is_open()) {
        std::cerr << "unable to open demo-data.csv" << std::endl;
        return 1;
    }
    std::string header;
    std::getline(file, header);
    int rows = 0;
    int sum = 0;
    std::string line;
    while (std::getline(file, line)) {
        std::stringstream ss(line);
        std::string name;
        std::string value_str;
        if (!std::getline(ss, name, ',')) {
            continue;
        }
        if (!std::getline(ss, value_str, ',')) {
            continue;
        }
        rows += 1;
        sum += std::stoi(value_str);
    }
    std::cout << "cpp rows=" << rows << std::endl;
    std::cout << "cpp sum=" << sum << std::endl;
    std::ofstream out("cpp-output.txt");
    out << "rows=" << rows << ",sum=" << sum << std::endl;
    return 0;
}
CPP
)

jq -n \
  --arg code "$CPP_CODE" \
  --arg entity "$ENTITY_ID" \
  --arg file_id "$FILE_ID" \
  --arg session "$SESSION_ID" \
  '{
    code: $code,
    lang: "cpp",
    entity_id: $entity,
    files: [
      {id: $file_id, session_id: $session, name: "demo-data.csv"}
    ]
  }' > "$WORKDIR/cpp_payload.json"

curl -s -X POST "$BASE_URL/exec" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d @"$WORKDIR/cpp_payload.json" | tee "$WORKDIR/cpp_response.json" | jq

curl -s -H "x-api-key: $API_KEY" "$BASE_URL/files/$SESSION_ID?detail=full" \
  -o "$WORKDIR/cpp_files.json"
jq < "$WORKDIR/cpp_files.json"

CPP_OUTPUT_ID=$(jq -r '.[] | select(.name == "cpp-output.txt") | .id' "$WORKDIR/cpp_files.json" | head -n 1)
if [[ -n "$CPP_OUTPUT_ID" && "$CPP_OUTPUT_ID" != "null" ]]; then
  curl -s -H "x-api-key: $API_KEY" "$BASE_URL/download/$SESSION_ID/$CPP_OUTPUT_ID" \
    -o "$WORKDIR/cpp-output.txt"
  echo "[cpp] downloaded cpp-output.txt to $WORKDIR"
fi
