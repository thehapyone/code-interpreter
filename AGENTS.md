# Repository Guidelines

## Project Structure & Module Organization
- `src/mcp_code_interpreter/` contains the FastAPI server, session registry, execution runners, and runtime discovery.
- `tests/` holds the pytest suite; `e2e/` contains language smoke tests and artifacts.
- `ui/` is the optional Vite/React development UI.
- `docs/ARCHITECTURE.md` documents request flows and system design.
- Runtime data lives in `uploads/`, `notebooks/`, and `logs/` during local runs.

## Build, Test, and Development Commands
- `make install` syncs dependencies via `uv`.
- `make dev` runs the API with reload at `http://localhost:8000`.
- `make run` starts the API without reload (closer to prod).
- `make lint`, `make format`, `make format-check` run Ruff checks and formatting.
- `make typecheck` runs strict mypy against `src/` and `tests/`.
- `make test` runs pytest; `make coverage` adds coverage reports.
- `make e2e` runs end-to-end language smoke tests (starts a temporary server).
- `make openapi` regenerates `openapi.json` after API changes; `make openapi-check` verifies it’s up to date.
- UI helpers: `make ui-install`, `make ui-dev`, `make ui-build`.

## Coding Style & Naming Conventions
- Python target is 3.14 with 4-space indentation and max line length 100.
- Formatting and linting use Ruff; keep imports sorted and follow Ruff rules.
- Prefer explicit typing; mypy is strict in `src/` (tests are looser).
- Naming: `snake_case` for modules/functions, `PascalCase` for classes, `test_*.py` for tests.

## Testing Guidelines
- Frameworks: `pytest` with `pytest-asyncio`; markers include `slow` and `integration`.
- Place new tests under `tests/` matching `test_*.py`; keep async tests explicit.
- For runtime changes, add or update `e2e/` coverage and verify via `make e2e`.

## LibreChat / Code Interpreter Notes
- Uploads are stored under `uploads/<session_id>/mnt/data/` and are available in Python as `/mnt/data/<filename>`.
- `/upload` returns LibreChat-compatible fields (`message: "success"`, plus `fileId`/`filename`) while keeping richer metadata (`id`/`name`, `path`, etc.).
- `/exec` accepts `args` as a string or list (LibreChat may send `[]`) and accepts `session_id` (or derives it from attached file refs).
- When `LOG_REQUESTS=true`, multipart bodies are not parsed for previews to avoid interfering with uploads.

## Commit & Pull Request Guidelines
- Commit style follows Conventional Commits (examples: `feat: ...`, `fix: ...`, `chore(deps): ...`).
- PRs should include a concise description, testing evidence (`make test`, `make e2e`, etc.), and note any API changes.
- If endpoints change, regenerate `openapi.json` and call out client impact in the PR.
- Do not add AI attribution lines (e.g. `Co-Authored-By: Claude ...`) to commit messages or PR descriptions.

## Security & Configuration Tips
- Use `CODE_INTERPRETER_API_KEY` for API auth in shared environments.
- Avoid committing secrets; store local settings in `.env` and keep uploads/logs out of version control.
- Python has `pip` available; prefer `python -m pip` from within the session (`sys.executable`) for per-environment installs. Consider the security implications of allowing arbitrary installs in shared deployments.
