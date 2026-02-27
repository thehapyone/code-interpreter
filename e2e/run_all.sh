#!/bin/bash
set -euo pipefail

DIR=$(cd -- "$(dirname -- "$0")" && pwd)

TESTS=(
  "python:$DIR/test_python.sh"
  "bash:$DIR/test_bash.sh"
  "node:$DIR/test_node.sh"
  "typescript:$DIR/test_typescript.sh"
  "go:$DIR/test_go.sh"
  "cpp:$DIR/test_cpp.sh"
  "unsupported:$DIR/test_unsupported_lang.sh"
)

failures=0

echo "Running e2e suite..."
for entry in "${TESTS[@]}"; do
  name=${entry%%:*}
  script=${entry#*:}
  echo "------------------------------------------------------------------"
  echo "[e2e] $name start"
  if bash "$script"; then
    echo "[e2e] $name PASSED"
  else
    echo "[e2e] $name FAILED"
    failures=$((failures + 1))
  fi
done

echo "------------------------------------------------------------------"
if [[ $failures -gt 0 ]]; then
  echo "[e2e] completed with $failures failure(s)"
  exit 1
fi
echo "[e2e] all tests passed"
