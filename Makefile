# Thicket developer tasks. Ports: API 8000 (thicket.config.API_PORT),
# Vite dev server 5173 (thicket.config.FRONTEND_DEV_PORT).

PYTHON ?= python3.11
VENV := backend/.venv
BIN := $(VENV)/bin
API_PORT = $(shell $(BIN)/python -c "from thicket.config import API_PORT; print(API_PORT)" 2>/dev/null || echo 8000)
IMAGE ?= thicket:local

.PHONY: help setup dev-backend dev-frontend test lint fmt schema docker-build docker-run

help:
	@echo "setup         create backend/.venv, install backend[birdnet,ml,dev] and frontend deps"
	@echo "dev-backend   API with auto-reload on http://127.0.0.1:8000"
	@echo "dev-frontend  Vite dev server on http://localhost:5173 (proxies /api to :8000)"
	@echo "test          backend pytest (and frontend unit tests when present)"
	@echo "lint          ruff check + format check (and frontend lint/typecheck)"
	@echo "fmt           ruff format + autofix"
	@echo "schema        regenerate shared/api.schema.json (and frontend types)"
	@echo "docker-build  build $(IMAGE)"
	@echo "docker-run    run $(IMAGE) on :8000 with a persistent volume"

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip

setup: $(BIN)/python
	$(BIN)/python -m pip install -e "backend[birdnet,ml,dev]"
	@if [ -f frontend/package.json ]; then cd frontend && npm ci; fi

dev-backend:
	cd backend && .venv/bin/uvicorn thicket.main:app --reload --host 127.0.0.1 --port $(API_PORT)

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/pytest -q
	@if [ -f frontend/package.json ]; then cd frontend && npm test; fi

lint:
	$(BIN)/ruff check backend ml
	$(BIN)/ruff format --check backend
	@if [ -f frontend/package.json ]; then cd frontend && npm run lint && npm run typecheck; fi

fmt:
	$(BIN)/ruff format backend
	$(BIN)/ruff check --fix backend ml

schema:
	$(BIN)/python backend/scripts/export_schema.py
	@if [ -f frontend/package.json ]; then cd frontend && npm run gen:types; fi

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm -p 8000:8000 -v thicket-data:/data --name thicket $(IMAGE)
