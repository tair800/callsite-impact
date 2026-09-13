.DEFAULT_GOAL := help
SHELL := /bin/sh

ARTIFACT := artifacts/evaluation.json

.PHONY: help install fmt lint types test gate corpus harness killtest api clean corpus-holdout killtest-holdout sweep

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install exactly what the lockfiles pin
	uv sync --frozen
	cd harness && npm ci

fmt: ## Format
	uv run ruff format .

lint: ## Lint
	uv run ruff format --check .
	uv run ruff check .

types: ## Strict type check
	uv run mypy

test: ## The offline suite. No corpus, no network, no node, no credential.
	uv run pytest -m "not corpus and not node"

gate: lint types test ## The full local gate, in the order CI runs it
	$(MAKE) killtest

corpus: ## Fetch and verify the vendor corpus (network; MIT specs only)
	uv run python -m callsite_impact.corpus.acquire

harness: ## Install the TypeScript harness
	cd harness && npm ci

killtest: ## THE MEASUREMENT: generate, admit, compile, classify, score
	uv run python -m callsite_impact.measure --out $(ARTIFACT)

corpus-holdout: ## Fetch the confirmatory slice frozen in corpus/holdout.py (ADR-004)
	uv run python -m callsite_impact.corpus.acquire --holdout

killtest-holdout: ## Score the held-out slice. Measured once; no rule may change afterwards.
	uv run python -m callsite_impact.measure --manifest corpus/holdout-manifest.json --workdir work-holdout --out artifacts/holdout.json --detail artifacts/holdout-findings.json

sweep: ## Sensitivity: the corpus at several generation budgets (ADR-004)
	uv run python scripts/budget_sweep.py

api: ## Serve the read-only API over the committed artifact
	uv run uvicorn "callsite_impact.api:create_app" --factory --reload --port 8000

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage harness/generated work work-holdout work-sweep
