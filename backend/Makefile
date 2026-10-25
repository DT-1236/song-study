VENV := .venv
BIN := $(VENV)/bin
PORT ?= 8000
# Dev-server auto-reload; run `make start RELOAD=` to turn it off.
RELOAD ?= --reload

.PHONY: venv install migrate start test format format-check lint

# Creates the virtualenv only if it doesn't exist yet.
venv: $(BIN)/python

$(BIN)/python:
	python3 -m venv $(VENV)

# Reinstalls only when requirements.txt is newer than the last install.
install: $(VENV)/.installed

$(VENV)/.installed: requirements.txt | venv
	$(BIN)/python -m pip install -r requirements.txt
	touch $@

# Applies pending migrations to DATABASE_URL (Postgres must be running:
# `docker compose up -d postgres` from the repo root).
migrate: install
	$(BIN)/alembic upgrade head

start: migrate
	$(BIN)/uvicorn app.main:app $(RELOAD) --port $(PORT)

# Four workers, each with a test database of its own: past four, starting
# each one costs more than it saves. Plain `pytest` stays single-process.
test: install
	$(BIN)/pytest -n 4

format: install
	$(BIN)/ruff format --config ruff.toml app tests migrations ../scripts

format-check: install
	$(BIN)/ruff format --config ruff.toml --check app tests migrations ../scripts

lint: install
	$(BIN)/ruff check --config ruff.toml app tests migrations ../scripts
