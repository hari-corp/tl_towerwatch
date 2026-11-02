SLOT ?= review
TARGET ?= owner/name#1

.PHONY: help install test lint check run review

help:  ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

install:  ## Sync dependencies (including dev tools)
	uv sync --extra dev

test:  ## Run the test suite (no network)
	uv run pytest

lint:  ## Lint with the project's pinned ruff rules
	uv run ruff check .

check: test lint  ## Definition of done: tests + lint
	@echo "OK: tests and lint passed"

run:  ## Start the web app on 127.0.0.1:8000
	uv run tl_towerwatch serve

review:  ## Render a prompt: make review TARGET=owner/name#123 SLOT=post_review
	uv run tl_towerwatch review "$(TARGET)" --slot "$(SLOT)"
