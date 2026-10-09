FROM python:3.11-slim

WORKDIR /app

# Requirements first, so a code-only change doesn't reinstall the dictionaries.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations migrations
COPY app app

# One worker: each extra one pays the tokenizer's ~100 MB again.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
