.PHONY: test lint-ci

PYTHON ?= python3

test: ## Run unit tests (scripts/tests)
	PYTHONPATH=scripts $(PYTHON) -m pytest

lint-ci: test ## CI parity: pytest + ruff (gitops + tests)
	ruff check scripts/gitops scripts/tests
