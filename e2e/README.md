# End-to-End Test Kit

These scripts exercise the REST API against a live server (e.g., one started via `make dev`).

## Prerequisites
- Server running on `http://localhost:8000` (override with `BASE_URL`).
- `CODE_INTERPRETER_API_KEY` set on the server; set `API_KEY` to the same value when running tests.
- `jq` installed locally.

## Scripts
- `test_python.sh` – full happy-path flow: upload -> exec -> stream -> matplotlib plot saved to `sine-plot.png` -> cleanup.
- `test_bash.sh` – exercises the bash runtime (creates a file, verifies it can be downloaded).
- `test_node.sh` – runs a Node.js snippet that processes CSV data and emits `node-output.json` (skipped if `node` is unavailable on the server).
- `test_typescript.sh` – uses `npx ts-node` to generate a TypeScript report; automatically skipped when `ts-node` binaries are missing.
- `test_go.sh` – compiles and runs a Go program that writes `go-output.txt`.
- `test_cpp.sh` – compiles a small C++17 program to validate the `g++` toolchain.
- `test_unsupported_lang.sh` – verifies unsupported languages return a 400.
- `run_all.sh` – executes every scenario in sequence; scripts exit early (with success) when their runtime capability is disabled or not installed.

## Usage
```
export API_KEY=dev-demo-key
export BASE_URL=http://localhost:8000
bash e2e/run_all.sh
```

Artifacts (payloads, responses, `sine-plot.png`, etc.) are stored under `${WORKDIR:-e2e/runs/<timestamp>}` so you can inspect each run afterward. The `RUNS_DIR` env var lets you point somewhere else if desired.
