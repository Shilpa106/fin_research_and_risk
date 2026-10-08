.PHONY: help install dev test eval lint format typecheck up down clean

PYTHON ?= python
UVICORN ?= uvicorn

help:
	@echo "Enterprise Financial Research & Risk Copilot Task Runner"
	@echo ""
	@echo "Available commands:"
	@echo "  make install     - Install pinned production and dev dependencies"
	@echo "  make dev         - Run local development server with hot-reload"
	@echo "  make test        - Run test suite via pytest"
	@echo "  make eval        - Run GenAI evaluation benchmark and CI regression gate"
	@echo "  make lint        - Run linting checks using Ruff"
	@echo "  make format      - Format source files using Ruff"
	@echo "  make typecheck   - Run static type checking using Mypy"
	@echo "  make up          - Start local Docker Compose environment"
	@echo "  make down        - Tear down local Docker Compose containers"
	@echo "  make clean       - Remove cached bytecode and test artifacts"

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install alembic ruff mypy

dev:
	$(UVICORN) src.api.main:app --host 0.0.0.0 --port 8000 --reload

test:
	$(PYTHON) -m pytest -v

eval:
	$(PYTHON) -m src.evaluation.cli --fail-on-regression

lint:
	$(PYTHON) -m ruff check src/ tests/

format:
	$(PYTHON) -m ruff format src/ tests/

typecheck:
	$(PYTHON) -m mypy src/

up:
	docker-compose up -d

down:
	docker-compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
