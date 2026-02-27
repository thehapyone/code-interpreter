SHELL := /bin/bash
PYTHON ?= python3
UV ?= uv
PACKAGE := mcp_code_interpreter
APP_IMPORT := $(PACKAGE).server:app
DOCKER ?= docker
DOCKER_IMAGE ?= ghcr.io/thehapyone/code-interpreter
DOCKER_TAG ?= latest
COMPOSE_FILE ?= docker-compose.yml

REPORT_DIR ?= reports

.PHONY: help install lock lint format format-check typecheck test coverage e2e dev run docker-build docker-push docker-run compose-up compose-down clean ui-install ui-dev ui-build

help:
	@echo "Available targets:"
	@echo "  install     - Sync project dependencies with uv"
	@echo "  lock        - Refresh uv.lock"
	@echo "  lint        - Run Ruff lint checks"
	@echo "  format      - Apply Ruff formatter"
	@echo "  format-check- Verify formatting without writing changes"
	@echo "  typecheck   - Run mypy static analysis"
	@echo "  test        - Run the pytest suite"
	@echo "  coverage    - Run pytest with coverage"
	@echo "  dev         - Start FastAPI with reload (local dev)"
	@echo "  run         - Start FastAPI without reload"
	@echo "  docker-build- Build the Docker image"
	@echo "  docker-push - Push the Docker image"
	@echo "  docker-run  - Run Docker image locally"
	@echo "  compose-up  - Launch docker-compose stack"
	@echo "  compose-down- Stop docker-compose stack"
	@echo "  clean       - Remove build artifacts"
	@echo "  ui-install  - Install npm deps for the dev UI"
	@echo "  ui-dev      - Start the dev UI via npm run dev"
	@echo "  ui-build    - Build the dev UI for production"
	@echo "  openapi     - Regenerate openapi.json from the FastAPI schema"
	@echo "  openapi-check - Verify openapi.json is up to date"

install:
	$(UV) sync

lock:
	$(UV) lock

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .

format-check:
	$(UV) run ruff format --check .

typecheck:
	$(UV) run mypy src/$(PACKAGE) tests

test:
	$(UV) run pytest

coverage:
	@mkdir -p $(REPORT_DIR)
	$(UV) run pytest --cov=$(PACKAGE) --cov=tests --cov-report=term-missing --cov-report=xml:$(REPORT_DIR)/coverage.xml --junitxml=$(REPORT_DIR)/junit.xml

e2e:
	@set -euo pipefail; \
		PORT=$${PORT:-8000}; \
		BASE_URL=$${BASE_URL:-http://127.0.0.1:$${PORT}}; \
		API_KEY=$${API_KEY:-dev-demo-key}; \
		RUNS_DIR=$${RUNS_DIR:-e2e/runs}; \
		echo "Starting app for e2e on $$BASE_URL (PORT=$$PORT)"; \
		LOG_FILE=$${LOG_FILE:-reports/e2e-server.log}; \
		mkdir -p reports "$$RUNS_DIR"; \
		CODE_INTERPRETER_API_KEY="$$API_KEY" PORT="$$PORT" $(UV) run uvicorn $(APP_IMPORT) --host 0.0.0.0 --port $$PORT > "$$LOG_FILE" 2>&1 & \
		SERVER_PID=$$!; \
		trap 'kill $$SERVER_PID 2>/dev/null || true' EXIT; \
		for i in $$(seq 1 30); do \
			if curl -sf "$$BASE_URL/health" >/dev/null; then \
				echo "Server healthy (attempt $$i)"; \
				break; \
			fi; \
			echo "Waiting for server... ($$i/20)"; \
			sleep 1; \
		done; \
		if ! curl -sf "$$BASE_URL/health" >/dev/null; then \
			echo "Server did not become ready; logs:"; \
			tail -n 40 "$$LOG_FILE" || true; \
			exit 1; \
		fi; \
		BASE_URL="$$BASE_URL" API_KEY="$$API_KEY" RUNS_DIR="$$RUNS_DIR" bash e2e/run_all.sh

dev:
	$(UV) run uvicorn $(APP_IMPORT) --host 0.0.0.0 --port 8000 --reload

run:
	$(UV) run uvicorn $(APP_IMPORT) --host 0.0.0.0 --port 8000

docker-build:
	$(DOCKER) build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

docker-push:
	$(DOCKER) push $(DOCKER_IMAGE):$(DOCKER_TAG)

docker-run:
	$(DOCKER) run --rm -it -p 8000:8000 \
	  -v $$(pwd)/uploads:/app/uploads \
	  -v $$(pwd)/notebooks:/app/notebooks \
	  $(DOCKER_IMAGE):$(DOCKER_TAG)

compose-up:
	$(DOCKER) compose -f $(COMPOSE_FILE) up -d

compose-down:
	$(DOCKER) compose -f $(COMPOSE_FILE) down

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov dist build

ui-install:
	cd ui && npm install

ui-dev:
	cd ui && npm run dev -- --host

ui-build:
	cd ui && npm run build

openapi:
	uv run python scripts/generate_openapi.py openapi.json

openapi-check:
	uv run python scripts/generate_openapi.py openapi.generated.json
	@if ! diff -u openapi.json openapi.generated.json; then \
		echo "OpenAPI specification does not match!"; \
		exit 1; \
	fi
	rm openapi.generated.json
	echo "OpenAPI specification is up to date."
