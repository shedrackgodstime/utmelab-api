# utmelab-bank
#
# `make help` lists everything. Nothing here reaches the network, so `make check`
# is safe to run at any time.

PY      := uv run python
PKG     := utmelab_bank
SRC     := src
TESTS   := tests
VAR     := ../var

.DEFAULT_GOAL := help
.PHONY: help check test lint fmt types contract tasks sources clean install

help:  ## List the targets
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Editable install with the dev extras
	$(PY) -m pip install -e ".[dev]"

check: fmt lint types test  ## Everything the gate runs

test:  ## The test suite
	PYTHONPATH=$(SRC) $(PY) -m pytest $(TESTS) -q

lint:  ## ruff, format check then lint
	ruff format --check $(SRC) $(TESTS)
	ruff check $(SRC) $(TESTS)

fmt:  ## Apply ruff's formatting
	ruff format $(SRC) $(TESTS)

types:  ## mypy, strict
	mypy

contract:  ## Compare the bank database against what the api says it reads
	PYTHONPATH=$(SRC) $(PY) -m $(PKG) contract --local-database "sqlite:$(VAR)/bank.db"

contract-deep:  ## The same, plus columns that exist and are never written
	PYTHONPATH=$(SRC) $(PY) -m $(PKG) contract --deep --local-database "sqlite:$(VAR)/bank.db"

tasks:  ## What every task does and what it fills
	PYTHONPATH=$(SRC) $(PY) -m $(PKG) tasks

sources:  ## What every source can fetch
	PYTHONPATH=$(SRC) $(PY) -m $(PKG) sources

selectors:  ## Every --where phrase the selector vocabulary understands
	PYTHONPATH=$(SRC) $(PY) -m $(PKG) selectors

clean:  ## Remove caches. Never touches var/, which holds run output.
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
