# Prompt 2 — Build v1

Run this in a **fresh context, after the fixtures exist and have been
reviewed.** Read `AGENTS.md` first; it holds constraints this prompt does not
repeat.

---

Build an app for studying Japanese song lyrics, aimed at English speakers
learning vocabulary, context, and grammar.

Golden fixtures already exist at `backend/tests/fixtures/tokenization.json`.
They are the specification for pipeline correctness. Make them pass; do not
edit them to match your output.

## Stack

- Frontend: React + TypeScript (Vite)
- Backend: Python (FastAPI, SQLAlchemy, Alembic)
- Application database: PostgreSQL — users, cached analyses, history,
  vocabulary
- Dictionary data: `jamdict` + `jamdict-data` (ships JMdict, KanjiDic2,
  JMnedict, KRAD/RADK pre-built as SQLite). Do NOT load dictionary data into
  Postgres. See `AGENTS.md` for why.
- Japanese processing: `fugashi`, full `unidic`, `jaconv`
- Provide a docker compose file for local Postgres
- **No LLM.** Sentence- and phrase-level meaning is deferred until after v1. Do
  not add a model dependency, an API key, or a call site for one.

## Phase 1 — Japanese text pipeline

Build and verify this before any UI, auth, or web layer. Expose it as a CLI
that takes an artist and title and prints the full analysis, so output can be
judged as plain text before an interface hides it.

- Fetch lyrics from LRCLIB. See `AGENTS.md` for the client rules — they are
  not optional, and violating them risks a ban on a free service.
- Try `/api/get` first using track name, artist, album, and duration. Duration
  must match within ±2 seconds. On 404, fall back to `/api/search` and let the
  caller choose from the results.
- Tokenize with fugashi and **full `unidic`** — not `unidic-lite`, and not
  IPAdic. `unidic-lite` is the convenient default and the wrong choice here;
  see "Japanese processing" in `AGENTS.md`. Full UniDic needs
  `python -m unidic download` as a separate step after `pip install`.
- For each token produce: surface form, dictionary form, reading, part of
  speech, and conjugation form. **Map UniDic's Japanese POS tags into the
  normalized English vocabulary** defined in `AGENTS.md` under "Part-of-speech
  values". Without that mapping the fixtures fail on spurious mismatches.
- Generate furigana as spans, aligned to the kanji portion only. There is no
  drop-in library for this; you are writing the alignment function. Read
  "Furigana alignment" in `AGENTS.md` before starting — it covers the
  katakana-to-hiragana conversion (use `jaconv`) and the interspersed-okurigana
  case, both of which are easy to get subtly wrong.
- Use `jamdict` for all dictionary lookups. Do not write an XML parser, a
  download script, or a seed script.
- "Other words sharing this kanji" is a jamdict wildcard lookup. Do not build a
  kanji-to-words index.
- **Build the golden test harness.** The fixture file is inert data; write the
  pytest module that loads it, runs each input through the pipeline, and
  asserts the result. See "The harness" in `AGENTS.md`. The fixtures are the
  definition of done for this phase.

**Stop here and let me review the CLI output before starting Phase 2.**

## Phase 2 — Core UI

This phase introduces persistence. There are no user accounts yet — those come
in Phase 3 — so nothing is scoped to a user here.

- Create the `tracks`, `analyses`, and `song_vocabulary` tables. The LRCLIB
  track ID is the natural key for a track. Store the analysis as JSONB with
  `schema_version` and `lyrics_fingerprint` columns beside it; see "Analysis
  caching" in `AGENTS.md` for how the fingerprint is computed and why. Build
  `song_vocabulary` as a table now, but not the cross-song feature that uses it.
- Song search hits LRCLIB only. The user picks a track from the results.
- Only after selection, resolve a YouTube video with ONE YouTube Data API
  search, and store the video ID on the track record. Do not scrape YouTube.
  Provide a "paste a YouTube URL" fallback that skips the API entirely.
- Surface EDRDG attribution for JMdict and KanjiDic2 in the UI.
- Play via the YouTube IFrame Player API using youtube.com. `music.youtube.com`
  cannot be embedded.
- Use LRCLIB's synced timestamps to highlight the current line during playback.
  Include a manual offset slider, since YouTube uploads often carry intros or
  padding that shift them out of sync.
- Render every token as an individually clickable element. Japanese has no
  spaces, so do NOT rely on text selection for word lookup.
- Tapping a token opens a panel with three sections: the word's translation
  (JMdict), every other place in this song where the same dictionary form
  appears (quoted as lines, not line numbers), and other words sharing its
  kanji. The fourth section from the original design — the meaning of the full
  line — needs an LLM and is deferred. Omit it rather than approximating it.
- Add a second view listing all vocabulary in the song, grouped by dictionary
  form with occurrence counts. It must reuse the exact same token component and
  lookup panel as the lyrics view. Define the token data model once and share
  it.
- **Last:** when LRCLIB has no lyrics for a song, let the user paste plain
  lyrics and run the full analysis on that text. No timing, no syncing, no
  publishing. Mark these analyses as user-supplied so they are never promoted
  into the shared cache; Phase 3 attaches them to accounts. Build this only
  after search and display work well for tracks LRCLIB already has.

## Phase 3 — Accounts

The schema from Phase 2 already exists. This phase adds users on top of it.

- Use a hosted auth provider or an established library. Do not implement
  password hashing or session management by hand.
- Track per-user history of analyzed songs with proper foreign keys.
- LRCLIB-derived analyses are shared: when another user opens a song that has
  already been analyzed, reuse it. Analyses of user-pasted lyrics are the
  exception — attach those to the account that supplied them and never promote
  them into the shared cache.

## Working agreement

- Configure `ruff`, `mypy`, and `tsc` in strict mode before writing substantial
  code. Run them before reporting work as done.
- Ask before adding dependencies beyond those named here.
- Never commit API keys. Use environment variables from the start.
- Stop at the end of each phase for review rather than continuing straight
  through.
