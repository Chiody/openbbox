.PHONY: install dev start scan status clean docker docker-up docker-down help

PYTHON ?= python3
PORT   ?= 9966

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies in a virtual environment
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e .
	@echo "\n✓ Installed. Run: source .venv/bin/activate && openbbox start"

dev: ## Start in development mode with auto-reload
	$(PYTHON) -m uvicorn server.app:app --host 0.0.0.0 --port $(PORT) --reload

start: ## Start the OpenBBox server
	$(PYTHON) -m cli.main start --port $(PORT)

scan: ## One-time scan of all IDE logs
	$(PYTHON) -m cli.main scan

status: ## Show detected IDEs and stats
	$(PYTHON) -m cli.main status

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist build .eggs .pytest_cache htmlcov .coverage

docker: ## Build Docker image
	docker build -t openbbox .

docker-up: ## Start with Docker Compose
	docker compose up -d

docker-down: ## Stop Docker Compose
	docker compose down
