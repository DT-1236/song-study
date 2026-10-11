FROM python:3.11-slim

WORKDIR /app

# Requirements first, so a code-only change doesn't reinstall the dictionaries.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY alembic.ini .
COPY migrations migrations
COPY app app

# One worker: each extra one pays the tokenizer's ~100 MB again.
# Migrations run in the compose file's one-shot `migrate` service, not here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
