# Song Study

A tool for studying Japanese song lyrics. Paste in a song's lyrics and its
YouTube video, and it's automatically annotated with furigana and dictionary
definitions, with playback synced alongside the text.

## Features

### Documents
- Create a document from a title, lyrics, and an optional YouTube video ID.
- Browse existing documents in a paginated, sortable list.
- Edit a document's lyrics in place; saving re-runs furigana and gloss
  processing from scratch (any reading corrections or resolved conflicts for
  that document are cleared, since they no longer correspond to anything).
- A sidebar tracks up to 5 recently-viewed documents as quick-access tabs,
  evicting the least-recently-used one once the limit is reached.

### Furigana & reading analysis
- Lyrics are tokenized with [SudachiPy](https://github.com/WorksApplications/SudachiPy),
  and each token is annotated with furigana, its dictionary form/reading,
  and part of speech (with a POS legend in the sidebar).
- Tokens with more than one plausible reading (heteronyms) or an ambiguous
  furigana split are flagged for review, with a picker to choose the
  correct one.
- Tokens with no automatic candidate, or where none of the candidates match
  a real dictionary entry, can have their reading corrected manually.

### Dictionary glosses
- Hovering or clicking a token shows its [JMDict](https://www.edrdg.org/jmdict/j_jmdict.html)
  definitions, tagged with part of speech and usage notes.
- Compounds with no single JMDict entry are broken down and glossed piece by
  piece instead.
- A standalone JMDict search in the sidebar looks up any word directly,
  independent of the loaded document.

### YouTube playback
- An embedded player syncs alongside the lyrics for a linked video.
- Keyboard shortcuts mirror YouTube's own: Space to play/pause, `,`/`.` to
  seek backward/forward by an adjustable step.
- Text and furigana size are independently adjustable.

## Tech stack

- **Backend**: FastAPI, SQLAlchemy, PostgreSQL, Alembic migrations, SudachiPy
  for tokenization, jamdict/JMDict for dictionary lookups.
- **Frontend**: React, TypeScript, Vite, React Router.

## Getting started

Prerequisites: Docker (for PostgreSQL), Python 3.11+, Node 18+.

```bash
cp .env.example .env
docker compose up -d postgres

cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# in a second terminal
cd frontend
cp .env.example .env
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` and talks to the backend at
`http://localhost:8000` by default (see each `.env.example` to change either).

## Running tests

Backend tests run against their own database, `TEST_DATABASE_URL` in `.env`
(`song_study_test` on the same Postgres server by default), which is dropped
and re-created from the migrations on every run. They never connect to
`DATABASE_URL`.

```bash
cd backend
pytest
```
