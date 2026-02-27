# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2025-02-06

### Added
- Stateful Python execution via Jupyter kernels with SSE streaming support (`/exec/stream`).
- Multi-language runtime support: Bash, Node.js, TypeScript (`ts-node`), Go (`go run`), and C++ (`g++`).
- Session-scoped file upload/download with LibreChat-compatible response fields.
- `/health` and `/libraries` endpoints for runtime and library capability discovery.
- `CODE_INTERPRETER_API_KEY` authentication via `x-api-key` header.
- Configurable resource limits: `SUBPROCESS_MAX_MEMORY_MB`, `SUBPROCESS_MAX_CPU_SECONDS`, `EXECUTION_TIMEOUT`.
- Non-root Docker image with configurable `APP_UID`/`APP_GID` build args.
- Docker Compose stack with security hardening (capability dropping, `no-new-privileges`, resource limits).
- Session kernel eviction when `MAX_SESSIONS` is reached.
- `/mnt/data` path alias for LibreChat notebook compatibility.
- Optional `BASH_STRICT_MODE` (`set -euo pipefail` prelude for bash/sh).
- Optional `LOG_REQUESTS` for request debugging.
- GitHub Actions CI pipeline (lint, typecheck, unit tests, e2e smoke tests).
- Automated Docker Hub publishing on push to `master` and version tags.
- OpenAPI specification (`openapi.json`) for MCP client import.
