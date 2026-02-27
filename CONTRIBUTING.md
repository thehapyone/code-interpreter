# Contributing to Code Interpreter

Thank you for your interest in contributing! This document covers how to set up your environment, run tests, and submit changes.

## Table of Contents
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Code Style](#code-style)
- [Testing](#testing)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Reporting Issues](#reporting-issues)

---

## Getting Started

### Prerequisites
- Python 3.14+
- [uv](https://github.com/astral-sh/uv) (package manager)
- Docker (for container-based testing)
- Node.js (optional, for UI development)

### Setup

```bash
git clone https://github.com/thehapyone/code-interpreter.git
cd code-interpreter
make install   # installs all Python dependencies via uv
```

To run the server locally:

```bash
make dev       # starts FastAPI with hot-reload at http://localhost:8000
```

---

## Development Workflow

### Useful Make Targets

| Command | Description |
|---------|-------------|
| `make install` | Sync all dependencies |
| `make dev` | Run server with hot-reload |
| `make lint` | Ruff lint checks |
| `make format` | Auto-format with Ruff |
| `make format-check` | Verify formatting without changes |
| `make typecheck` | mypy strict type checking |
| `make test` | Run unit tests |
| `make coverage` | Run tests with coverage report |
| `make e2e` | Run end-to-end language smoke tests |
| `make openapi` | Regenerate `openapi.json` after API changes |
| `make openapi-check` | Verify `openapi.json` is up to date |

### If You Change API Endpoints

Run `make openapi` to regenerate `openapi.json` and include the updated file in your PR. Call out any client-visible changes in the PR description.

---

## Code Style

- **Formatter/Linter:** Ruff (`make format`, `make lint`)
- **Type checking:** mypy strict mode in `src/` (`make typecheck`)
- **Line length:** 100 characters
- **Imports:** sorted by Ruff/isort rules
- **Naming:** `snake_case` for modules/functions, `PascalCase` for classes, `test_*.py` for test files
- **Commits:** follow [Conventional Commits](https://www.conventionalcommits.org/) — e.g. `feat:`, `fix:`, `chore(deps):`, `docs:`

---

## Testing

### Unit Tests

```bash
make test       # run all tests
make coverage   # run with HTML + XML coverage reports
```

Tests live in `tests/` and use `pytest` with `pytest-asyncio`. Keep async tests explicit and use the `slow` / `integration` markers where appropriate.

### End-to-End Tests

```bash
make e2e        # starts a temporary server and runs language smoke tests
```

E2E tests live in `e2e/` and exercise each supported runtime (Python, Bash, Node.js, TypeScript, Go, C++). Add or update `e2e/` coverage when changing runtime behaviour.

---

## Submitting a Pull Request

1. Fork the repository and create a branch from `master`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes, following the code style above.
3. Run the full check suite before pushing:
   ```bash
   make lint && make typecheck && make test && make e2e
   ```
4. Push your branch and open a PR against `master`.
5. Fill in the PR template — include a description of what changed, how it was tested, and any API impact.

PRs are reviewed on a best-effort basis. Small, focused changes are easier to review and merge quickly.

---

## Reporting Issues

Use [GitHub Issues](https://github.com/thehapyone/code-interpreter/issues) to report bugs or request features. Please use the provided issue templates so the report includes the information needed to act on it.

For security vulnerabilities, see [SECURITY.md](SECURITY.md) — do not open a public issue.
