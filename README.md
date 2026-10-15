# Song Study

A tool for studying Japanese song lyrics. Paste in a song's lyrics and its
YouTube video, and it's automatically annotated with furigana and dictionary
definitions, with playback synced alongside the text.

## Features

### Documents

- Create a document from a title, lyrics, and an optional YouTube video ID.
- Lyrics are cleaned up before they're saved, whether pasted or loaded from
  LRCLIB: look-alikes of Latin letters (a Roman numeral ⅿ, a ligature ﬁ)
  become plain letters, invisible characters are removed, and spacing within
  each line is normalized. Line breaks are kept as they are.
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
- A token with no dictionary entry that doesn't need one (a name, say) can
  be marked as ignored, which clears its flag.
- A picked or corrected reading, or an ignore, can apply at once to every
  instance of the word in the document that's read and parsed the same way
  (same reading, part of speech, and offered reading options).
  Hovering or selecting a token outlines its other such instances.
  Shift-clicking starts a selection, shown with the gloss of the token last
  added in a panel pinned to the top of the screen and no taller than the
  page content above the lyrics, so at the top of the page it covers that
  content rather than the lyrics. Meanwhile, clicking outlined instances
  adds them, and clicking anywhere else ends it. Shift-clicking neighboring tokens only marks them as a run, ahead
  of joining them into one gloss (not supported yet).

### Dictionary glosses

- Hovering or clicking a token shows its [JMDict](https://www.edrdg.org/jmdict/j_jmdict.html)
  definitions, tagged with part of speech and usage notes.
- Compounds with no single JMDict entry are broken down and glossed piece by
  piece instead.
- A standalone JMDict search in the sidebar looks up any word directly,
  independent of the loaded document. A second box takes romaji and
  converts it to kana as you type ([WanaKana](https://wanakana.com)):
  lowercase for hiragana, capitals for katakana.

### LRCLIB lyrics

- A document can be linked to an [LRCLIB](https://lrclib.net) track (its ID,
  or its `https://lrclib.net/api/get/{id}` address), at creation or later.
- Linking an existing document either keeps its own lyrics and readings,
  saving just the track ID, or replaces its lyrics with LRCLIB's. Kept lyrics
  stay editable, and use LRCLIB's line timings only while LRCLIB's lyrics
  match them line for line. Replaced lyrics can't be edited in place;
  unlinking keeps them and makes them editable again.
- Linked documents are refreshed from LRCLIB when they're opened, at most once
  a day; a Refresh button next to Unlink reloads them now (at most once every
  5 minutes). For
  replaced lyrics, a change to the text there re-processes the document from
  scratch, resetting any manually selected readings; a timing-only change
  keeps them. If LRCLIB can't be reached, the last lyrics loaded from it are
  shown.
- LRCLIB's synced lyrics are timed per line, so as the video plays, the line
  being sung is highlighted.

### YouTube playback

- An embedded player syncs alongside the lyrics for a linked video.
- Keyboard shortcuts mirror YouTube's own: Space to play/pause, `,`/`.` to
  seek backward/forward by an adjustable step.
- Text and furigana size are independently adjustable, as are the color and
  opacity of the line highlight. These and the seek step are remembered in
  the browser, the same for every document.

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
make start

# in a second terminal
cd frontend
npm install
npm run dev
```

`make start` creates `backend/.venv` if needed, installs `requirements.txt`
when it has changed, applies pending migrations, then runs the dev server
(`PORT` and `RELOAD` can be overridden, e.g. `make start RELOAD=`). `make
test`, `make format` and `make lint` are the other targets.

Open `http://localhost:5173`. The backend runs at `http://localhost:8000`, but
the browser only talks to the frontend's origin: the Vite dev server proxies
`/api` to the backend, and a deployment's reverse proxy should do the same
(`/api/*` to the backend, everything else to the built frontend). The app's
public URL is `APP_URL` in `.env`. To point the dev server's `/api` at another
backend (such as a deployed one, for debugging), set `API_PROXY_TARGET`, e.g.
`API_PROXY_TARGET=https://songs.example.com npm run dev`. Deploying and running
the app on a VM is in [`deploy/README.md`](deploy/README.md).

## Running tests

Backend tests run against their own database, `TEST_DATABASE_URL` in `.env`
(`song_study_test` on the same Postgres server by default), which is dropped
and re-created from the migrations on every run. They never connect to
`DATABASE_URL`.

```bash
cd backend
pytest
```
