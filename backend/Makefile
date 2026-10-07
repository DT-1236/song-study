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

test: install
	$(BIN)/pytest

format: install
	$(BIN)/ruff format app tests migrations

format-check: install
	$(BIN)/ruff format --check app tests migrations

lint: install
	$(BIN)/ruff check app tests migrations
