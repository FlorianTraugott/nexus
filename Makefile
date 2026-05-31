# ════════════════════════════════════════════════════════════
#  NEXUS AI — developer shortcuts
#  Run `make help` to see all commands.
# ════════════════════════════════════════════════════════════

.PHONY: help up down build logs dev lint format test hooks clean migrate upgrade downgrade

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:  ## Start the full dev stack (postgres + backend)
	docker compose up --build

down:  ## Stop the stack and remove containers
	docker compose down

build:  ## Build all images without starting
	docker compose build

logs:  ## Tail backend logs
	docker compose logs -f backend

dev:  ## Run the backend locally (without Docker)
	cd backend && uvicorn app.main:app --reload

lint:  ## Run all linters
	cd backend && ruff check . && black --check . && mypy app

format:  ## Auto-format code
	cd backend && ruff check --fix . && black .

test:  ## Run the test suite
	cd backend && pytest

migrate:  ## Generate a migration from model changes (usage: make migrate MSG="description")
	docker compose exec backend alembic revision --autogenerate -m "$(MSG)"

upgrade:  ## Apply all pending migrations
	docker compose exec backend alembic upgrade head

downgrade:  ## Roll back the most recent migration
	docker compose exec backend alembic downgrade -1

hooks:  ## Install pre-commit git hooks
	pre-commit install

clean:  ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
