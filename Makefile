# DocIntel — convenience targets
#
# Backend: Python 3.12 + uv
# Frontend: Node + npm

.PHONY: help backend-install backend-init backend-api backend-worker backend-test \
        backend-lint frontend-install frontend-dev frontend-build frontend-typecheck \
        eval-fixtures eval-run clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

backend-install:  ## Install backend dependencies
	cd backend && uv sync --extra dev

backend-init:  ## Init dev DB (SQLite) and seed demo user
	cd backend && uv run python -m app.cli init-db

backend-api:  ## Start FastAPI API on :8000
	cd backend && uv run uvicorn app.main:app --reload --port 8000

backend-worker:  ## Start the background worker
	cd backend && uv run python -m app.worker

backend-test:  ## Run backend test suite
	cd backend && uv run pytest tests/ -q

backend-lint:  ## Lint backend
	cd backend && uv run ruff check app tests

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

frontend-install:  ## Install frontend dependencies
	cd frontend && npm install

frontend-dev:  ## Start frontend dev server (:3000)
	cd frontend && npm run dev

frontend-build:  ## Build frontend for production
	cd frontend && npm run build

frontend-typecheck:  ## Typecheck frontend
	cd frontend && npm run typecheck

# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

eval-fixtures:  ## Generate synthetic labeled evaluation dataset
	python eval/generate_fixtures.py

eval-run:  ## Run deterministic evaluation baseline
	python eval/run_eval.py

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean:  ## Remove local runtime data (dev DB, uploads, eval outputs)
	rm -rf backend/data/docintel.db* backend/data/uploads
	rm -rf eval/data eval/dataset eval/ground_truth.jsonl eval/results.json eval/results.csv eval/report.md
