# song-study

An app for studying Japanese song lyrics, aimed at English speakers learning
vocabulary, context, and grammar through music.

## v1 scope

**Terminology.** "Phase 1/2/3" are build stages *within* v1 — all three ship as
part of v1. "Post-v1" means after all three phases are done. Phase 2 and
post-v1 are not the same thing and are easy to confuse. Anything marked
post-v1 is out of scope for the entire current build.

Get song search and lyric display working well for tracks LRCLIB already has.
That is the whole target.

Explicitly **out of scope for v1**:

- **Any LLM calls.** Sentence- and phrase-level meaning is deferred until after
  v1 ships. Do not add an LLM dependency, an API key, or a call site for one.
  The caching schema is designed to accommodate it later (see "Analysis
  caching").
- Publishing lyrics back to LRCLIB. The `/api/publish` proof-of-work flow is a
  separate effort and is not part of this build.
- Timing or syncing user-supplied lyrics.
- Cross-song vocabulary tracking (the schema leaves room for it; the feature
  comes later).

Three of the four panels in the word lookup work without an LLM and are in
scope: the word's translation (jamdict), its other occurrences in the song
(derived from tokenization), and other words sharing its kanji (a jamdict
wildcard lookup). Only "meaning of the full line" needs a model. In v1, omit
that panel entirely rather than approximating it.

## Stack

- **Frontend:** React + TypeScript (Vite)
- **Backend:** Python (FastAPI, SQLAlchemy, Alembic)
- **Application database:** PostgreSQL — users, cached analyses, history,
  vocabulary
- **Dictionary data:** `jamdict` + `jamdict-data`. Ships JMdict, KanjiDic2,
  JMnedict, and KRAD/RADK pre-built as SQLite. **Not** loaded into Postgres.
- **LLM:** post-v1 only. No LLM calls, dependencies, or keys in v1.

## Things that do not work

These have been checked. Do not attempt them.

- **`music.youtube.com` cannot be embedded.** The IFrame Player API only
  supports `youtube.com`. Use regular YouTube embeds.
- **The YouTube IFrame player cannot search.** It takes a video ID. Finding a
  video requires the YouTube Data API.
- **Do not scrape YouTube** (yt-dlp, `youtube-search-python`, etc.) to avoid
  API quota. It violates their terms.
- **Do not use browser text selection to pick a word.** Japanese has no spaces,
  so selection yields arbitrary character ranges that don't align to word
  boundaries. Tokenize first, render each token as a clickable element.

## External API constraints

### LRCLIB (https://lrclib.net/docs)

Free, no API key, no registration. In exchange it expects good behavior:

- Set a `User-Agent` identifying this app and its version.
- Send requests **sequentially**, with a 200–500ms delay between them.
- Honor `429 Retry-After`. Ignoring it risks a ban.
- `/api/get` matches on track name, artist, album, and duration. **Duration
  must be within ±2 seconds** or it returns 404.
- On 404, fall back to `/api/search`, which ignores duration and returns up to
  20 candidates. Let the user confirm the match.
- A 404 is common and not an error state. Handle it as a normal path — see
  "No-lyrics fallback" below.
- **Never call `/api/publish`.** Writing to LRCLIB is out of scope for v1.

### YouTube Data API

- Search costs **100 units** against a 10,000/day free quota — 100 searches per
  day.
- Only search on cache miss, and cache the resolved video ID with the analysis.
- Always offer a "paste a YouTube URL" path that skips the API entirely.

## Japanese processing

- Tokenize with **fugashi + UniDic**. Use UniDic, not IPAdic — IPAdic's
  readings are unreliable.
- **Use full `unidic`, not `unidic-lite`.** fugashi offers both:

  | Package | Version | Size | Install |
  | --- | --- | --- | --- |
  | `unidic-lite` | UniDic 2.1.2, a 2013 build | small | one step |
  | `unidic` | UniDic 3.1.0, current | 770 MB on disk | `pip install`, then `python -m unidic download` |

  `unidic-lite` is the tempting default because the install is one step, and an
  agent left to choose will take it. Don't. Reading accuracy is the entire
  product here, and a 2013 dictionary is weakest on contemporary vocabulary —
  which is exactly what song lyrics are full of. fugashi's own docs recommend
  full UniDic for serious processing and position lite as a smoke-test option.
  Treat `unidic-lite` as a fallback only if deployment weight becomes a genuine
  blocker.
- Every token needs: surface form, dictionary form (lemma), reading, part of
  speech, and conjugation form.
- **Furigana goes over the kanji only, not the okurigana.** A verb like 食べる
  takes its reading over the first character alone, not spread across the whole
  word. Getting this wrong looks broken to anyone who reads Japanese.
- **Assume some readings will be wrong.** J-pop uses non-standard and invented
  readings where the sung word differs from the written one. No analyzer
  catches these. Always leave a manual override path.
- Key vocabulary on the **dictionary form**, never the surface form. Otherwise
  one verb becomes five separate entries.

### Furigana alignment

There is **no drop-in Python library** for this. Every implementation combines a
tokenizer with a hand-written alignment function, and so will ours. It is small
— roughly fifty lines — and it is the most fixture-covered code in the project
for exactly that reason.

**Convert the reading to hiragana first.** UniDic returns readings in
*katakana* (タベル, not たべる). Alignment silently fails without this step,
because nothing matches between a katakana reading and hiragana okurigana. Use
`jaconv`.

**Anchor on every kana run, not just the trailing one.** Interspersed okurigana
is common, especially in compound verbs: 申し込む, 受け取る, 待ち合わせ,
引っ越す, 落ち着く, 乗り換える. Naive suffix-stripping renders ruby text over a
kana character on all of these.

Split the surface into alternating kanji and kana runs, match the kana runs
against the reading as fixed anchors, and assign the gaps to the kanji runs:

```
surface:  申 | し | 込 | む
reading:  もう  し   こ   む
result:   申(もう) し 込(こ) む
```

Trailing-only okurigana is just the degenerate case with one anchor at the end.

Two edge cases: a kana anchor can also occur inside a neighboring kanji's
reading, so matching needs backtracking rather than a first-match scan; and the
sokuon in 引っ越す is a mid-word kana run that the same machinery handles but
that is easy to omit from test cases.

**A multi-kanji run takes the whole gap as one span.** 日本語 → にほんご is a
single span. Do not attempt per-character splits; see the jukujikun note under
"Fixture format".

## Dictionary data

Use **`jamdict`**. Do not write an XML parser, a download script, or a seed
script for dictionary data.

```bash
pip install jamdict jamdict-data
```

```python
from jamdict import Jamdict
jam = Jamdict()
jam.lookup('食べ%る')   # wildcard matching supported
```

`jamdict-data` ships JMdict, KanjiDic2, JMnedict, and the KRADFILE/RADKFILE
radical mappings already built as SQLite. There is no ingestion step.

- **EDRDG attribution is required.** Surface it in the UI.
- "Other words sharing this kanji" is a wildcard lookup, not a join table you
  build. Do not construct a kanji→words index; jamdict already indexes this.
- KRAD/RADK maps kanji to their visual components. Not needed for v1, but it is
  already there — a natural post-v1 addition, since what a character is *built
  from* is often more useful to a learner than more words containing it.

### Why the dictionary is not in Postgres

Dictionary data is static, read-only, and arrives pre-built. Putting it in
Postgres would mean writing and maintaining an ETL for data that never changes
between releases.

The tradeoff: dictionary tables cannot be joined against application tables in
a single query. No v1 feature needs that — "other words sharing this kanji" is
a pure dictionary question. If a later feature does, import jamdict's data into
Postgres then, with the schema already proven.

Postgres owns everything that is actually ours: users, cached analyses,
history, `song_vocabulary`.

## Deployment weight

Two large, static reference datasets ship with the backend:

- **UniDic** — 770 MB on disk (full `unidic`)
- **`jamdict-data`** — 51 MB compressed, meaningfully larger unpacked

Roughly a gigabyte total. That is acceptable, but it needs deliberate handling:

- **Install both in an early Docker layer, before copying application code, and
  pin their versions.** Neither changes between releases, so Docker caches that
  layer and a code edit does not re-download a gigabyte.
- Remember that full `unidic` needs `python -m unidic download` as a *separate
  step* after `pip install`. Missing it produces a confusing runtime failure
  rather than an install error.
- If image size ever becomes a real blocker, both can be mounted as volumes
  rather than baked in — jamdict accepts a custom database path, and UniDic's
  separate download step allows the same. Do not do this preemptively.

Note that SQLite here is **jamdict's internal storage format**, not a database
we operate. There is no connection pool, migration chain, backup concern, or
schema we own. It is a package that ships a data file.

## Word lookup flow

Glosses are **not** cached in the analysis blob. They are resolved from jamdict
at request time. Caching them would create a staleness class that neither
`lyrics_fingerprint` nor `schema_version` catches — a `jamdict-data` bump would
change gloss text while both triggers stayed identical.

Resolution is split by cost:

- **Eager, with the song:** one short gloss per *unique lemma*. A song has
  300–600 tokens but only 100–200 distinct lemmas, since particles and common
  verbs repeat heavily. This powers the vocabulary list view and makes a token
  tap show something immediately instead of after a round trip.
- **Lazy, on tap:** full sense list and kanji neighbours.
- **Free:** "other places this word appears in the song" requires no lookup.
  The frontend already holds the token list; it is a filter over data in hand.

```
GET /songs/{lrclib_track_id}
  → { lines: [...], tokens: [...], glosses: { "食べる": "to eat", ... } }

GET /words/{lemma}
  → { senses: [...] }

GET /kanji/{char}/words?offset=0&limit=5
  → { words: [...], has_more: true }
```

**Key the gloss map by lemma; tokens reference it.** Do not attach a gloss
object to each token, or a particle appearing forty times ships forty copies of
the same definition. This also satisfies the shared-component requirement
directly: both the lyrics view and the vocabulary view read the same token list
and the same gloss map, differing only in how they group it.

Put an **in-process LRU cache** on lemma lookups. The dictionary is static for
the life of the process, so the cache needs no invalidation logic, and common
particles and verbs hit constantly across songs.

### Kanji neighbours

- Return **5 at a time**, with a "load more" control. Never return an
  exhaustive list — a common character like 日 appears in hundreds of JMdict
  entries.
- **Rank by commonality** using JMdict's priority markers (`ichi1`, `news1`,
  `spec1`, and the `nfXX` frequency bands, where a lower band is more common).
  Unranked results bury a learner in obscure compounds, which defeats the point
  of the panel.
- **Group by kanji.** For a multi-kanji word like 日本語, show a group per
  character, 5 each, each independently expandable. "Other words sharing its
  kanji" has no single answer otherwise.
- Exclude the word itself from its own neighbour list.
- Pagination is plain `offset`/`limit`. The underlying data is static and the
  ranking is deterministic, so no cursor is needed.

## Where lyrics live

- **Song lyrics never enter the source tree.** They are runtime data: fetched
  from LRCLIB, cached in Postgres. Git history is permanent, so a lyric
  committed once and deleted later is still in the repo forever.
- The same applies to test fixtures — see "Verification".

## Database conventions

- The **LRCLIB track ID** is the natural key for a track. Never key cached work
  on title/artist strings — they are unstable.
- Store the rendered analysis as **JSONB** with a `schema_version` column
  beside it, so analyses can be invalidated in bulk when the pipeline improves.
- Also maintain a normalized `song_vocabulary` table (`track_id`,
  `dictionary_form`, indexed on `dictionary_form`). The JSONB blob serves page
  rendering; this table is what makes cross-song vocabulary queries possible
  later without reprocessing the library. **Build the table, not the feature** —
  cross-song vocabulary is post-v1.
- **Analyses derived from LRCLIB lyrics are shared across users.** One song is
  analyzed once. This does *not* apply to analyses of user-pasted lyrics, which
  stay private to the user who supplied them — see "No-lyrics fallback".

### Analysis caching

LRCLIB exposes **no revision identifier**. The `id` field is the *track* ID,
not a lyrics revision. There is no `updatedAt`, and responses carry no `ETag`
or `Last-Modified`. The lyrics behind a track ID can change silently when
someone publishes a new revision.

Do not mistake the `version: '1.0'` field inside the `lyricsfile` YAML for a
revision marker. It is the **format** version and does not change when lyrics
are edited. Keying staleness on it would silently never invalidate.

Content hashing is therefore the mechanism, and it is more precise than a
revision counter would be — it changes only when the analyzed text changes, not
when unrelated metadata is touched.

- Store a `lyrics_fingerprint` alongside every cached analysis: a SHA-256 of
  the **normalized** text of the specific field that was analyzed, not the raw
  JSON response.
- Normalize before hashing: Unicode **NFC**, then strip trailing whitespace per
  line, then join with `\n`. NFC matters here — Japanese text arrives in both
  composed and decomposed forms, and in half- and full-width variants,
  depending on the contributor. Skipping it causes spurious reprocessing.
- On a cache hit, re-fetch from LRCLIB and compare fingerprints. This does not
  save the fetch (which is free); it saves the expensive work of re-tokenizing
  and, post-v1, re-calling the LLM.
- `lyrics_fingerprint` and `schema_version` are two independent invalidation
  triggers: upstream text changed, or our pipeline changed.
- **Post-v1:** stored LLM evaluations key on the same `lyrics_fingerprint`, so
  a cached sentence-meaning result is never served against text it wasn't
  generated from. Design the v1 schema so this drops in without a migration.

## Trusting LRCLIB data

LRCLIB has **no pre-publication verification**. The publish route validates the
proof-of-work token, then inserts. There is no content validation, no
moderation queue, and no review step. The proof-of-work is an anti-spam cost,
not a quality signal.

The actual model is anonymous last-write-wins with revision history retained.
Anyone with a fresh token can overwrite anyone else's lyrics. The `/api/flag`
endpoint is advisory only — it records a report and returns; nothing is
automatically hidden or removed.

The `±2s` duration match filters *which track you match*, not whether the text
is correct.

Treat LRCLIB text as **untrusted input to the pipeline**. Expect lyrics for the
wrong song, romaji where Japanese was expected, machine translations, and
duplicated verses. Morphological analysis over bad input produces confidently
wrong furigana, which is worse than no output. Give the user a visible "these
lyrics look wrong" affordance.

## No-lyrics fallback

LRCLIB will miss plenty of tracks. When it does:

- Let the user paste plain lyrics and run the full analysis on that text.
- The analysis pipeline works on **plain text**. Tokenization, furigana, and
  glosses need no timestamps. Timestamps drive follow-along highlighting during
  playback, which is a real Phase 2 feature for LRCLIB-sourced tracks — but it
  is not a prerequisite for studying a song, so pasted lyrics simply go without
  it.
- Store pasted lyrics **privately**, keyed to the track, scoped to the user who
  supplied them. They are not shared across users the way LRCLIB-sourced
  analyses are. LRCLIB content isn't formally verified either (see "Trusting
  LRCLIB data"), but it has at least been publicly visible and subject to
  correction over time. A fresh paste has had zero scrutiny.
- Do **not** push pasted lyrics upstream. Text pasted from elsewhere is
  typically scraped from a lyrics site, and republishing it is how bad or
  unlicensed data spreads through a community database.

This is the last item in the core UI work. Get search and display right for
tracks LRCLIB already has first.

## Playback sync

- LRCLIB's classic synced format gives **line-level** timestamps. Word-level
  timing exists in some newer `lyricsfile` records — check for it before
  falling back to interpolation.
- YouTube uploads frequently carry intros or padding that push them out of sync
  with official-release timings. **Ship a manual offset slider.**

## Verification

Verify your own work rather than asserting success. Any claim that something is
correct should correspond to a command that was actually run.

### Golden fixtures for the Japanese pipeline

Furigana alignment and tokenization errors look fine at a glance and are obvious
to anyone who reads Japanese. Eyeballing does not scale, and it is exactly the
kind of judgment an agent will make optimistically about its own output. Freeze
the expected results instead.

- Maintain a fixture file of 15–20 Japanese lines with known-correct
  tokenization, dictionary forms, readings, and furigana alignment.
- **Write the fixture sentences yourself. Never use song lyrics as test
  fixtures.** Lyrics are licensed content and must not be committed to this
  repo. Ordinary constructed sentences exercise the same morphology and carry
  no licensing baggage.
- Coverage must include: verbs with trailing okurigana; a compound verb with
  **interspersed** okurigana (申し込む, 受け取る) — the case that separates a
  correct implementation from naive suffix-stripping; multi-kanji compounds;
  **jukujikun** (compounds whose reading cannot be split per character, e.g.
  今日 → きょう); words with both on'yomi and kun'yomi readings; conjugated forms
  whose lemma differs from the surface form; and at least one line mixing
  kanji, hiragana, and katakana.
- **Do not put JMdict glosses in fixtures.** They couple tests to a specific
  EDRDG release, and definitions get reworded and senses reordered
  continuously. Fixtures cover tokenization, lemmas, readings, and furigana
  alignment — stable linguistic facts. Gloss lookup is a database query; if the
  lemma is right, the lookup is right, and lemmas are already covered.
- A change that alters golden output is a **regression until proven otherwise**.
  Do not silently update fixtures to match new output — surface the diff.

### Fixture format

Location: `backend/tests/fixtures/tokenization.json`

JSON, not YAML — Japanese text is full of characters that trip YAML's quoting
rules, and golden files are regenerated programmatically, where ambiguity works
against you. Serialize with `ensure_ascii=False` and `indent=2` so Japanese
renders readably in diffs instead of as escape sequences, and keep key order
stable so diffs stay minimal.

Furigana is represented as **spans**: each run of text paired with its reading,
or `null` where no reading applies.

**"Span" here means a contiguous run of text — not an HTML `<span>` element.**
A furigana span is the pair `[text, reading]`. Runs with a reading render as
`<ruby>`; runs with `null` render as bare text.

("Ruby" is the typography term for annotation text set alongside base text,
from an old British printing type size. It is unrelated to the language.
Japanese furigana is ruby text, and HTML has native elements for it.)

```json
{
  "id": "verb-okurigana",
  "note": "Reading covers 食 only; べる must not be included",
  "confidence": "high",
  "input": "毎日ご飯を食べる",
  "expected": [
    { "surface": "毎日", "lemma": "毎日", "pos": "noun",
      "furigana": [["毎日", "まいにち"]] },
    { "surface": "ご飯", "lemma": "ご飯", "pos": "noun",
      "furigana": [["ご", null], ["飯", "はん"]] },
    { "surface": "を", "lemma": "を", "pos": "particle",
      "furigana": [["を", null]] },
    { "surface": "食べる", "lemma": "食べる", "pos": "verb",
      "furigana": [["食", "た"], ["べる", null]] }
  ]
}
```

`confidence` is `"high"` or `"needs-review"`, set by whoever authored the
fixture. The test harness ignores it; it exists so a human can find the entries
worth double-checking.

### Part-of-speech values

**UniDic returns Japanese POS tags (名詞, 動詞, 助詞). Fixtures use a normalized
English vocabulary.** The pipeline must map UniDic's tags to this set — without
that mapping layer every fixture fails on a spurious mismatch.

Permitted `pos` values:

```
noun  pronoun  verb  adjective-i  adjective-na  adverb  particle
auxiliary  conjunction  prefix  suffix  counter  interjection  symbol  other
```

Keep the mapping in one place. Map anything unrecognized to `other` rather than
passing UniDic's raw tag through, so the fixture vocabulary stays closed.

Spans map one-to-one onto HTML `<ruby>` elements, so the renderer is a loop
with no parsing:

```tsx
type FuriganaSpan = [string, string | null];

function Token({ furigana }: { furigana: FuriganaSpan[] }) {
  return (
    <>
      {furigana.map(([text, reading], i) =>
        reading
          ? <ruby key={i}>{text}<rt>{reading}</rt></ruby>
          : <span key={i}>{text}</span>
      )}
    </>
  );
}
```

The backend does the alignment; the frontend never works out which kana belong
over which kanji.

Two styling notes:

- Browsers default `<rt>` to roughly half the base font size. That is often too
  small here, where reading the furigana is the entire point.
- Ruby annotations add line height. Give lyric lines enough vertical room or
  adjacent lines will collide.

**Do not use per-character readings.** Jukujikun compounds have no valid
per-character split — 今日 read as きょう belongs to the pair, not to either
character. A span model represents that correctly and handles ordinary
compounds identically. A per-character model forces you to invent splits that
do not exist.

Every fixture carries a `note` explaining what it is testing, so a failure is
self-describing.

Provide a `--update-golden` flag to regenerate expectations. Regenerating is
fine; rubber-stamping the diff is not.

### The harness

The fixture file is inert data. Something has to load it and compare, and that
harness is built in **Phase 1**, alongside the pipeline it tests:

- A pytest module that reads `tokenization.json`, runs each `input` through the
  pipeline, and asserts the result matches `expected`.
- Compare `surface`, `lemma`, `pos`, and `furigana`. Ignore `confidence` and
  `note`.
- On failure, report the fixture `id` and its `note`, so the output says what
  broke rather than dumping two token lists.
- The `--update-golden` flag lives here.

### Checks

Configure these before writing substantial code, so there is feedback from the
first commit rather than the hundredth:

- Python: `ruff` (lint) and `mypy` (types)
- TypeScript: `tsc` in strict mode
- One command that runs the whole suite — lint, types, and tests together

Run them before reporting work as done. "It should work" is not verification.

### The Phase 1 CLI is a verification artifact

The CLI that prints a full analysis for a given artist and title exists so the
Japanese pipeline can be checked as plain text, before any UI hides it. Do not
skip it or fold it into the web layer.

## Conventions

- Never commit API keys. Use environment variables from the start.
- Ask before adding dependencies beyond those already named.
- Build and verify the Japanese text pipeline before the UI, auth, or web
  layer. If furigana and tokenization aren't good, nothing built on top
  matters.

## Licensing note

Lyrics are licensed content, and LRCLIB's corpus is community-uploaded without
publisher agreements. This is a non-issue for personal use. If this is ever
published or monetized, that is the point to look at a Musixmatch or LyricFind
agreement.
