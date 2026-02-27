# Code Interpreter

An open-source Model Context Protocol (MCP) server that provides a notebook-like code execution surface with session affinity, multi-language support, and session-scoped file storage. Built to integrate cleanly with LibreChat’s Code Interpreter flows.

For internals and request flows, see `docs/ARCHITECTURE.md`.

## Highlights
- Stateful Python execution via Jupyter kernels with SSE streaming support.
- Additional runtimes (bash, Node.js, TypeScript, Go, C++) executed in sandboxed subprocesses.
- Session-scoped file upload/download with LibreChat-compatible responses.
- Health + runtime inventory endpoints for client capability discovery.
- Docker-first deploy with uv-based local dev workflow and Makefile helpers.

## Supported Languages
| Language | Accepted `lang` values | Runtime command | Behavior |
|----------|------------------------|-----------------|----------|
| Python | `py`, `python` | Jupyter kernel | Stateful sessions with streaming + persisted variables |
| Bash | `bash`, `sh` | `/bin/bash` with `set -euo pipefail` prelude (configurable) | Stateless per run |
| Node.js | `js`, `javascript`, `node` | `node` | Stateless script execution |
| TypeScript | `ts`, `typescript` | `npx ts-node` | Transpiles + runs in-process; skipped if `ts-node` unavailable |
| Go | `go` | `go run` | Compiles to a temp binary in the session workspace |
| C++ | `cpp`, `c++` | `g++` (C++17) -> compiled binary | Temporary binary removed after execution |

`GET /health` reports which runtimes are available and a snapshot of installed libraries. `GET /libraries` exposes the full inventory.

## Quick Start (Docker)

### Docker Run (recommended)
```bash
docker run --rm -p 8000:8000 \
  -e CODE_INTERPRETER_API_KEY=dev-demo-key \
  -v $(pwd)/uploads:/app/uploads \
  -v $(pwd)/notebooks:/app/notebooks \
  ghcr.io/thehapyone/code-interpreter:latest
```

### Docker Compose (production-like)
```bash
docker compose build \
  --build-arg APP_UID=$(id -u) \
  --build-arg APP_GID=$(id -g)
docker compose up -d
docker compose logs -f
```
Before starting, ensure writable bind mounts:
```bash
mkdir -p notebooks uploads logs
chown -R $(id -u):$(id -g) notebooks uploads logs
```
If the interpreter must join an existing Docker network used by your MCP client, set `MCP_NETWORK_EXTERNAL=true` and `MCP_NETWORK_NAME=<network>` in `.env`.

## LibreChat Integration

This server is designed to be drop-in compatible with LibreChat’s Code Interpreter workflow.

- `/upload` returns `message: "success"` and includes `fileId`/`filename` fields expected by LibreChat.
- Uploaded files are available inside Python under `/mnt/data/<filename>`.
- `/exec` accepts `args` as either a string or a list (LibreChat may send `[]`) and can use `session_id` from attached file refs for file hydration.

### LibreChat Environment Example

Use these variables in your LibreChat deployment to point at the Code Interpreter service:

```bash
#==================================#
# Code Interpreter Configuration   #
#==================================#
LIBRECHAT_CODE_API_KEY=librechat
LIBRECHAT_CODE_BASEURL=http://code_interpreter:7000
```

**Using Code Interpreter in LibreChat**

<img width="638" height="837" alt="Code Interpreter running inside LibreChat" src="https://github.com/user-attachments/assets/5b5884ae-1a26-4671-a03e-4ec766221d98" />

### `/mnt/data` Compatibility
Python kernels treat POSIX paths under `/mnt/data` as an alias to the current session workspace at `<UPLOADS_DIR>/<session_id>/mnt/data`. This helps run notebooks and examples that assume Code Interpreter’s `/mnt/data` convention.

## Configuration

Environment variables (commonly used):

| Variable | Default | Description |
|----------|---------|-------------|
| `CODE_INTERPRETER_API_KEY` | _(unset)_ | Require `x-api-key` on all endpoints when set. |
| `MAX_SESSIONS` | `50` | Max concurrent Jupyter kernels before oldest eviction. |
| `EXECUTION_TIMEOUT` | `300` | Per-execution timeout in seconds. |
| `NOTEBOOKS_DIR` | `<repo>/notebooks` | Notebook storage root. |
| `UPLOADS_DIR` | `<repo>/uploads` | Session workspace root (files + artifacts). |
| `SUBPROCESS_MAX_MEMORY_MB` | _(unset)_ | RLIMIT_AS for non-Python runs (MiB). |
| `SUBPROCESS_MAX_CPU_SECONDS` | _(unset)_ | RLIMIT_CPU for non-Python runs (seconds). |
| `BASH_STRICT_MODE` | `true` | Prepend `set -euo pipefail` to bash/sh scripts. |
| `CORS_ALLOW_ORIGINS` | `*` | Comma-separated origins allowed to call the API. |
| `LOG_REQUESTS` | `false` | Log method/path/headers + JSON preview (helps MCP client debugging). |

## API and MCP Integration
- OpenAPI is generated at `openapi.json` (run `make openapi` after changing endpoints). Import into MCP clients like LibreChat or Claude Desktop.
- Primary endpoints: `/exec`, `/exec/stream`, `/upload`, `/files/{session_id}`, `/files/{session_id}/{file_id}`, `/download/{session_id}/{file_id}`, `/health`, `/libraries`.
- Session affinity is driven by `entity_id`; reusing it binds calls to the same Python kernel and workspace.

## Usage Examples

Execute Python:
```bash
curl -X POST http://localhost:8000/exec \
  -H "Content-Type: application/json" \
  -d '{"code":"print(\"hello\")","lang":"py","entity_id":"demo"}'
```

Upload files into a session and execute with them:
```bash
curl -X POST http://localhost:8000/upload \
  -F "entity_id=demo" \
  -F "files=@data.csv"

curl -X POST http://localhost:8000/exec \
  -H "Content-Type: application/json" \
  -d '{
    "code":"import pandas as pd; print(pd.read_csv(\"data.csv\").head())",
    "lang":"py",
    "entity_id":"demo"
  }'
```

Stream outputs (Python):
```bash
curl -N -X POST http://localhost:8000/exec/stream \
  -H "Content-Type: application/json" \
  -d '{"code":"import time\nfor i in range(3):\n print(i); time.sleep(1)","lang":"py","entity_id":"demo"}'
```

## Local Development (uv + FastAPI)
```bash
make install   # uv sync
make dev       # starts FastAPI on http://localhost:8000
```

## Testing and Quality
- `make test` – async pytest suite.
- `make lint` – Ruff lint checks.
- `make format-check` – Ruff formatting verification.
- `make typecheck` – mypy (strict).
- `bash e2e/run_all.sh` – language smoke tests (server must be running, e.g., `make dev`).

## Security and Isolation
- Runs as non-root inside Docker; supports configurable UID/GID for volume permissions.
- Session workspaces isolate user files and execution artifacts; subprocess HOME points at the workspace.
- Environment allowlist prevents host env leakage; `PYTHONPATH` cleared for subprocesses.
- Optional RLIMIT caps and execution timeouts; optional strict bash prelude.
- API key authentication available via `CODE_INTERPRETER_API_KEY`.

## Project Structure (high level)
- `src/mcp_code_interpreter/` – FastAPI server, execution service, kernel manager, session registry, process runner, capability discovery.
- `tests/` – pytest suite.
- `e2e/` – language smoke tests and artifacts.
- `ui/` – optional Vite/React dev UI.
- `docs/ARCHITECTURE.md` – system architecture and diagrams.

## License
MIT
