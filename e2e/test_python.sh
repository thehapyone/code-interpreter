#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)
RUNS_DIR=${RUNS_DIR:-"$SCRIPT_DIR/runs"}
RUN_ID=${RUN_ID:-run-$(date +%Y%m%d-%H%M%S)-$RANDOM}
WORKDIR=${WORKDIR:-"$RUNS_DIR/$RUN_ID"}
mkdir -p "$WORKDIR"

API_KEY=${API_KEY:-dev-demo-key}
ENTITY_ID=${ENTITY_ID:-demo_agent_$RANDOM}
BASE_URL=${BASE_URL:-http://localhost:8000}

echo "[python] artifacts: $WORKDIR"

cat <<'CSV' > "$WORKDIR/demo-data.csv"
name,value
Alice,10
Bob,20
CSV

curl -s -X POST "$BASE_URL/upload" \
  -H "x-api-key: $API_KEY" \
  -F "entity_id=$ENTITY_ID" \
  -F "files=@$WORKDIR/demo-data.csv" \
  -o "$WORKDIR/upload-response.json"

jq < "$WORKDIR/upload-response.json"

SESSION_ID=$(jq -r '.session_id' "$WORKDIR/upload-response.json")
FILE_ID=$(jq -r '.files[0].id' "$WORKDIR/upload-response.json")

curl -s -H "x-api-key: $API_KEY" "$BASE_URL/files/$SESSION_ID?detail=simple" | jq
curl -s -H "x-api-key: $API_KEY" "$BASE_URL/files/$SESSION_ID?detail=full"   | jq

READ_CODE=$(cat <<'PY'
import pandas as pd
df = pd.read_csv("demo-data.csv")
print("Rows:", len(df))
print("Sum:", df["value"].sum())
PY
)

jq -n \
  --arg code "$READ_CODE" \
  --arg entity "$ENTITY_ID" \
  --arg file_id "$FILE_ID" \
  --arg session "$SESSION_ID" \
  '{
    code: $code,
    lang: "py",
    entity_id: $entity,
    files: [
      {id: $file_id, session_id: $session, name: "demo-data.csv"}
    ]
  }' > "$WORKDIR/read_payload.json"

curl -s -X POST "$BASE_URL/exec" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d @"$WORKDIR/read_payload.json" | jq

STREAM_CODE=$(cat <<'PY'
import time
for i in range(3):
    print(f"tick {i}")
    time.sleep(1)
PY
)

jq -n \
  --arg code "$STREAM_CODE" \
  --arg entity "$ENTITY_ID" \
  '{code: $code, lang: "py", entity_id: $entity}' > "$WORKDIR/stream_payload.json"

curl -N -X POST "$BASE_URL/exec/stream" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d @"$WORKDIR/stream_payload.json"

MATPLOTLIB_CODE=$(cat <<'PY'
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("demo-data.csv")
pct = df["value"] / df["value"].sum()
print("Distribution (%)")
print((pct * 100).round(2))

x = np.linspace(0, 2 * np.pi, 200)
y = np.sin(x)
plt.figure(figsize=(4, 3))
plt.plot(x, y, label="sin(x)")
plt.title("Sine Wave")
plt.legend()
plt.tight_layout()
plt.savefig("sine-plot.png")
print("plot saved to sine-plot.png")
PY
)

jq -n \
  --arg code "$MATPLOTLIB_CODE" \
  --arg entity "$ENTITY_ID" \
  --arg file_id "$FILE_ID" \
  --arg session "$SESSION_ID" \
  '{
    code: $code,
    lang: "py",
    entity_id: $entity,
    files: [
      {id: $file_id, session_id: $session, name: "demo-data.csv"}
    ]
  }' > "$WORKDIR/matplotlib_payload.json"

curl -s -X POST "$BASE_URL/exec" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d @"$WORKDIR/matplotlib_payload.json" | jq

curl -s -H "x-api-key: $API_KEY" "$BASE_URL/files/$SESSION_ID?detail=full" \
  -o "$WORKDIR/files-after.json"
jq < "$WORKDIR/files-after.json"

PLOT_FILE_ID=$(jq -r '.[] | select(.name == "sine-plot.png") | .id' "$WORKDIR/files-after.json" | head -n 1)

if [[ -n "$PLOT_FILE_ID" && "$PLOT_FILE_ID" != "null" ]]; then
  curl -s -H "x-api-key: $API_KEY" \
    "$BASE_URL/download/$SESSION_ID/$PLOT_FILE_ID" \
    -o "$WORKDIR/sine-plot.png"
  echo "Downloaded sine-plot.png to $WORKDIR/sine-plot.png"
fi

curl -s -H "x-api-key: $API_KEY" "$BASE_URL/download/$SESSION_ID/$FILE_ID" > "$WORKDIR/demo-data-downloaded.csv"

jq -r '.[].id' "$WORKDIR/files-after.json" | while read -r fid; do
  [[ -z "$fid" || "$fid" == "null" ]] && continue
  curl -s -X DELETE -H "x-api-key: $API_KEY" "$BASE_URL/files/$SESSION_ID/$fid" > /dev/null || true
done

curl -s -H "x-api-key: $API_KEY" "$BASE_URL/download/$SESSION_ID/$FILE_ID"
