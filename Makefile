# IndITR — common developer tasks
# Requires: docker compose v2, Python 3.11+

.DEFAULT_GOAL := help

# ── Docker ────────────────────────────────────────────────────────────────────

build:          ## Build the API image
	docker compose build api

up:             ## Start api + frontend + ollama (detached)
	docker compose up -d

down:           ## Stop and remove containers (keeps volumes)
	docker compose down

logs:           ## Stream api logs
	docker compose logs -f api

restart-api:    ## Rebuild and restart the api service only
	docker compose up -d --build api

# ── Model setup (run once after `make up`) ────────────────────────────────────

pull-models:    ## Pull qwen2.5 + llava into the ollama container
	docker compose run --rm model-init

# ── Testing ───────────────────────────────────────────────────────────────────

smoke:          ## Run smoke test against http://localhost:8000
	python scripts/smoke_test.py --base-url http://localhost:8000

smoke-docker:   ## Run smoke test inside the api container
	docker compose run --rm api python scripts/smoke_test.py --base-url http://localhost:8000

test:           ## Run full pytest suite (local)
	pytest

test-cov:       ## Run pytest with coverage
	pytest --cov=inditr --cov-report=term-missing -v

# ── Local dev (no Docker) ─────────────────────────────────────────────────────

dev:            ## Start API in hot-reload mode (needs local Python venv)
	uvicorn inditr.api.main:app --reload --host 0.0.0.0 --port 8000

install:        ## Install package + dev deps into active venv
	pip install -e ".[dev]"

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:          ## Remove containers, volumes, and built image
	docker compose down -v --rmi local

help:           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: build up down logs restart-api pull-models smoke smoke-docker \
        test test-cov dev install clean help
