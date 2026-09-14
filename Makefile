.PHONY: install test lint typecheck check compose-config

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .

typecheck:
	python -m mypy

compose-config:
	docker compose config --quiet

check: test lint typecheck compose-config

