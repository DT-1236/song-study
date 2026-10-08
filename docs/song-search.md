# Song search on the New document page

## Context

Making a document today means pasting three things in by hand: an LRCLIB track
ID, the lyrics (or neither), and a YouTube video ID. The goal is a search-first
flow instead:

1. Search YouTube for the **song** (not the MV or covers).
2. Pick a song. LRCLIB is then searched for tracks whose title matches the
   song's title in whole or in part.
3. Those LRCLIB results are filtered to the ones whose duration matches the
   song's.
4. Pick an LRCLIB track and save.

The manual fields stay as a fallback (decided 2026-10-07).

### Feasibility: what LRCLIB actually supports (checked live, 2026-10-07)

- `GET /api/search` takes `q` (full text over title/artist/album) or
  `track_name` with optional `artist_name`/`album_name`. It returns **at most 20
  results**. `page` and `offset` are ignored, so there's no paging. **`duration`
  is ignored**, so duration filtering has to happen on our side. Each result
  includes `duration`, `syncedLyrics`, `plainLyrics` and `instrumental`, so no
  follow-up fetch is needed to filter or preview.
- Matching is **whole-token only**. `夜に駆` → 0 results, and `駆ける` doesn't find
  夜に駆ける, because a Japanese title with no spaces counts as one token.
  Partial matching has to come from sending a few query variants (title +
  artist, title alone, the title with decorations like `(feat. …)` / `(TV
  Size)` removed), merging them by id, and checking title containment
  ourselves.
- Uploaders' titles are messy (`YOASOBI「アイドル」 Official Music Video`).
  Starting from clean song metadata helps a lot, which is why YouTube Music's
  "songs" search is the source (decided 2026-10-07).
- The API sends `Access-Control-Allow-Origin: *`, but calls still go through
  the backend: that's the existing pattern, and it uses the
  `lrclib.USER_AGENT` LRCLIB asks for.

## Build order

There are four steps, each on its own branch and PR. Steps 1 and 2 don't
depend on each other. Step 3 needs both, and step 4 needs step 3. The
"Approach" section below is the spec for steps 1–3, and "Step 4" after it is
the spec for the last. Each step runs its own tests plus the relevant part of
Verification.

| Step | Status | Ships | Model | Effort | Why |
|---|---|---|---|---|---|
| 0 — Doc | Done | This plan committed as `docs/song-search.md`, so each step's session reads the same spec | Haiku 4.5 | low | Mechanical: copy the plan into the repo |
| 1 — YouTube Music song search | Done | `ytmusicapi` dep, `app/youtube_music.py`, `GET /api/songs/search`, `SongSearch.tsx`; a pick fills Title + YouTube video ID. Usable on its own | Sonnet 5 | medium | Wrapping a library against a clear spec. Its result shape is loose (missing album/duration), but that's visible, not silent |
| 2 — LRCLIB track search | Done | `search_tracks` in `app/lrclib.py`, `GET /api/lrclib/search`, tests. No UI yet; check it with curl against the test backend | **Opus 5** | **high** | The subtle part. The query variants, title normalization (NFKC, Japanese brackets, `feat.`), and partial-failure handling all fail *silently*: the right track just never shows up |
| 3 — LRCLIB matches in the form | Done | `LrclibMatches.tsx`, NewDocumentForm wiring, manual fields under `<details>`, CSS | Sonnet 5 | medium | Conventional React. The traps are a typed title being overwritten and a required lyrics box hidden in `<details>`, and the browser check catches both |
| 4 — LRCLIB lyrics and playback highlight | Done | `GET /api/lrclib/tracks/{id}`; picking an LRCLIB option fills a disabled lyrics field, and timed lyrics highlight the playing line beside the video; `usePlayingLine` and the highlight settings shared with `DocumentViewPage` | **Opus 5** | medium | The shared hook is lifted out of `DocumentViewPage`'s playback effect, whose seek and nudge handling fails silently (a highlight a line late, or stuck). The rest is conventional React |

Each step runs in its own session at its listed model and effort, and ends
with a `/simplify` pass before its PR. Steps fully specified here can run at
the listed effort; escalate a step that stalls rather than starting higher.

## Approach

### Backend

**New dependency:** `ytmusicapi` pinned in `backend/requirements.txt`. Check the
current version with `pip index versions ytmusicapi` when implementing.

**New `backend/app/youtube_music.py`**
- `search_songs(query: str) -> list[Song]` calls
  `YTMusic().search(query, filter="songs", limit=10)` without auth. Create the
  client lazily at module level.
- `Song` dataclass: `video_id`, `title`, `artists` (names joined with `、`/`, `),
  `album` (or None), `duration_seconds` (or None), `thumbnail_url` (the
  smallest thumbnail).
- Skip results without a `videoId`. Any exception from the library becomes
  `YouTubeMusicUnavailable` with a user-facing message. Comment that the
  library is unofficial and can break when YouTube changes.

**Extend `backend/app/lrclib.py`** (reuses `_get_json`, `USER_AGENT`,
`_API_GET`, `sanitize_text`)
- `search_tracks(title, artist, duration) -> list[LrclibCandidate]`:
  - Build query variants with no duplicates:
    `track_name=title&artist_name=artist`, `q=f"{title} {artist}"`,
    `q=title`, and `q=` the cleaned title when it differs (strip trailing
    `(…)`, `[…]`, `（…）`, `【…】`, ` - …` subtitles such as ` - From "…"`
    and ` - Into The Night`, and `feat.` segments).
  - Run them concurrently (`ThreadPoolExecutor`, ≤4 requests per pick).
    Ignore a variant that fails as long as at least one succeeds; otherwise
    re-raise `LrclibUnavailable`.
  - Merge by `id`. Drop instrumental tracks and tracks with no lyrics.
  - Title match: normalize both titles (NFKC, casefold, drop
    whitespace/punctuation). Equal is `"whole"`; either containing the other
    is `"partial"`; anything else is dropped. This is the "partial or whole
    match" the API can't do itself.
  - Per candidate: `id`, `uri` (`f"{_API_GET}/{id}"`, the same canonical form
    `normalize_lrclib_uri` produces), `track_name`, `artist_name`,
    `album_name`, `duration`, `synced` (bool), `title_match`
    (`"whole"`/`"partial"`), `duration_delta` (None when the song's
    duration is unknown, since `duration` is optional), and
    `within_tolerance` (|delta| ≤ `_DURATION_TOLERANCE_SECONDS = 3`; LRCLIB's
    own `/api/get` allows about ±2s, and YouTube Music rounds to whole
    seconds). Also a short `preview` (the first two non-empty lyric lines,
    via `parse_synced_lyrics` or plain text).
  - Sort order: within tolerance first, then synced, then whole before
    partial, then smallest |delta|.
- Update the module docstring to cover search.

**New endpoints in `backend/app/main.py`**. Both take `user_id: CurrentUser`
so they aren't an open proxy:
- `GET /api/songs/search?q=` → `list[SongResult]`. Raises 502 on
  `YouTubeMusicUnavailable`.
- `GET /api/lrclib/search?title=&artist=&duration=` → `list[LrclibCandidate]`.
  Maps `LrclibUnavailable` to 502 the same way `_fetch_lrclib_for_link` does.
- `POST /documents` stays unchanged: the picks just fill in `lrclib_uri`,
  `youtube_video_id` and `title`, so the existing create path,
  duplicate-video check and LRCLIB fetch all apply as they are.

### Frontend

**`frontend/src/api.ts`:** add `SongResult` and `LrclibCandidate` types, plus
`searchSongs(q)` and `searchLrclib({ title, artist, durationSeconds })`,
following `searchJmdict`'s shape (`URL`, `assertOk`).

**New `frontend/src/SongSearch.tsx`:** a search input and a button. It
searches on Enter or a click, not on every keystroke, since each search hits
an unofficial YouTube endpoint. It's a `div` rather than a nested `<form>`.
The results list shows each song's thumbnail, title, artists · album and m:ss.
Clicking a song calls `onPick(song)`.

**New `frontend/src/LrclibMatches.tsx`:** given the picked song, it fetches
`searchLrclib` in an effect (with the same cancellation pattern as
`JmdictSearch`). It shows the in-tolerance candidates as a radio list: track
· artist · album, duration with ±Δs, a "synced" badge and a preview line. The
remaining matches sit behind a "Show N with other lengths" toggle. A last
option, "None — I'll paste the lyrics", is always there. The component calls
`onChoose(candidate | null)`. The parent pre-selects the first candidate
when it's within tolerance and synced.

**`frontend/src/NewDocumentForm.tsx`:**
- Top: `<SongSearch>`. Picking a song sets `youtubeVideoId` and sets `title`
  when the title is empty or was itself auto-filled (tracked with a flag, so
  a typed title is never overwritten). It then renders `<LrclibMatches>`.
- Choosing a candidate sets `lrclibUri` to its id. Choosing None clears it.
- The Title stays visible at the top level. The Lyrics textarea shows at the
  top level only when no LRCLIB track is set, so the required field is never
  hidden inside a closed `<details>`.
- A `<details>` labelled "Enter IDs manually" holds the existing LRCLIB track
  and YouTube video ID inputs, which reflect whatever the picks filled in.
- Submit and reset work as they do now. Reset also clears the picked song.

**`frontend/src/App.css`:** add styles for `.song-search`, `.song-results`
and `.lrclib-matches`, reusing the existing tokens (`--border`,
`--bg-elevated`, `--accent`). `.new-document-form button` (`App.css`) gives
every button in the form `margin-top: 1rem` and `padding: 0.6rem 1.2rem`.
Qualify the new button rules so they outrank it, as the other rules
commented "Qualified to outrank .new-document-form button" do (e.g.
`.new-document-form .song-result`). Don't narrow the shared rule as part of
this work.

### Tests (`backend/tests/`, no network, no lyrics in fixtures)
- `test_lrclib.py`: extend `FakeLrclib` to route `/api/search` URLs by their
  query params. Cover: merging and deduping across variants; dropping
  non-matching titles; whole vs partial ranking; the tolerance flag and sort
  order; dropping instrumental and lyric-less tracks; the cleaned-title
  variant only when it differs; one failed variant tolerated; all failed →
  `LrclibUnavailable`; the endpoint's 502 mapping. Use invented track titles
  and kumo_no_ito / short test sentences as lyric bodies.
- New `test_youtube_music.py`: monkeypatch the client's `search` to cover
  field mapping, a missing album or duration, skipping results without a
  videoId, and an exception → 502.
- Endpoint tests go through `tests/support.py` helpers against
  `TEST_DATABASE_URL`, including the auth requirement.

## Step 4 — LRCLIB lyrics and playback highlight

Picking a LRCLIB option should work like picking a YouTube one: it fills in
the form and you see the result at once. Step 3 only stores the track's id and
hides the lyrics box, so nothing shows what was picked. This step loads the
chosen track's lyrics into the form, locks the field, and, since the track
has timings, highlights the line being sung as the video plays, as the
document page does, without furigana or glosses.

This replaces step 3's rule that the Lyrics textarea is hidden while an
LRCLIB track is set. It also replaces step 3's radio list: the matches are
shown the way the YouTube results are.

### Backend

- `GET /api/lrclib/tracks/{track_id}` (`user_id: CurrentUser`) returns
  `{text, lines}`, the shape of `LrclibLyrics`: the lyrics, and one
  `{start, end}` per line, or `lines: null` for unsynced lyrics. It calls
  `fetch_lyrics(_track_uri(track_id))`, the path linking a track already uses,
  and maps `LrclibUnavailable` to 502 through the existing handler and
  `LrclibError` to 422 as `_fetch_lrclib_for_link` does.
- It's a separate endpoint rather than a `lyrics` field on each search
  candidate: a search returns up to 20 tracks and only one is ever picked, so
  sending every track's full lyrics would be mostly wasted bytes. The cost is
  one more request per pick, made while the person is already reading the
  list.

### Frontend

- **`api.ts`:** `LrclibLyrics` type and `fetchLrclibLyrics(id)`, following
  `searchLrclib`'s shape.
- **`NewDocumentForm.tsx`:**
  - Choosing a candidate fetches its lyrics. While loading, the Lyrics field
    shows "Loading lyrics…". A failure shows the error and leaves the choice
    unset, so the form can't be saved with a track whose lyrics didn't load.
    A stale response from an earlier choice is ignored (same cancellation
    pattern as `LrclibMatches`).
  - The Lyrics field is always shown, and is disabled and filled with the
    track's text while a track is picked. Choosing None, or picking another
    song, restores the textarea with whatever the person had pasted: the
    pasted draft is its own state, never overwritten by LRCLIB's text.
  - The disabled field isn't `required`. A track typed into the manual field
    keeps today's behavior (disabled, "Loaded from LRCLIB" placeholder),
    since only picked candidates have their lyrics fetched here.
  - Submit is unchanged: the server ignores pasted text when a track is
    given.
- **Match list, like the song list:** `LrclibMatches` renders its candidates
  as `SongSearch` renders songs: a `<ul>` of full-width button rows (the
  `.song-results` / `.song-result` look, reusing those rules or a shared
  class) instead of radios.
  - Each row shows the track name, then artist · album, the duration with ±Δs,
    a "synced" badge, and the two-line preview. There's no thumbnail, since
    LRCLIB has none.
  - Clicking a row picks it and collapses the list to that one row, as a
    YouTube pick closes its list. The row carries a "Change" button that
    reopens the list. A pre-selected match starts collapsed the same way.
  - The other-length matches stay behind "Show N with other lengths", and
    "None — I'll paste the lyrics" stays as the last row.
  - Both lists can be recalled after a pick: clicking into the song
    search box shows its last results again (Escape closes them), and
    clicking the collapsed LRCLIB row reopens its matches. The picked row is
    marked in each.
- **Highlighted lyrics:** a textarea can't highlight a line, so when the
  track is synced the disabled field is shown as a read-only list of lines
  (`.lyrics-box` with `.timing-row` rows, classes the timing editor already
  styles) in the textarea's place, with the playing line carrying
  `.playing`. Unsynced lyrics stay in the plain disabled textarea. No
  furigana, tokens, glosses, or click-to-seek (the document page has those;
  none are needed to check a pick).
- **Shared with `DocumentViewPage`:** extract rather than copy.
  - `usePlayingLine(playerRef, timings, seeks)`, lifted from the playing-line
    effect in `DocumentViewPage` (the `lastStartedBy` search, the poll, the
    reset on cleanup). `DocumentViewPage` switches to it with no behavior
    change.
  - The highlight color and opacity settings: the form reads the same
    persisted `highlightColor` / `highlightOpacity` and sets the same
    `--highlight-color` / `--highlight-opacity` properties, via a small
    shared hook, so the highlight looks as the person configured it. Both
    pages' defaults stay in one place.
  - `YouTubePlayer` gets a ref and `onSeek` in the form, as on the document
    page, so the highlight follows a seek at once.
- **`App.css`:** the `.timing-row.playing` highlight rule is currently scoped
  to the timing editor. Widen it to the new list (a shared class, or a
  selector added to the existing rule). Qualify any new button rules as
  step 3 does, and don't touch the shared `.new-document-form button` rule.

### Tests and verification

- Backend: the endpoint returns timed lines for a synced record and
  `lines: null` for plain lyrics; a missing track is 422; an outage is 502;
  it needs auth. Extend `FakeLrclib`, with invented text.
- Frontend: nothing here is covered by the existing `timing.test.ts`, so the
  browser check carries it. If `usePlayingLine` has pure parts worth testing,
  they live in `timing.ts` beside `lastStartedBy`.
- Browser check, extending the Verification flow above:
  0. Confirm the LRCLIB matches look like the song results (rows, not
     radios), that a click collapses the list to the picked row, and that
     "Change" reopens it.
  1. Pick `夜に駆ける`, then its pre-selected LRCLIB match. Confirm the lyrics
     fill the field as a read-only list and it can't be edited.
  2. Play the video. Confirm the highlighted line follows the singing, and a
     seek (via the player's own scrubber) moves it at once.
  3. Pick an unsynced candidate, if the list has one: a disabled textarea,
     no highlight. Pick None: an editable textarea holding what was pasted
     before.
  4. Type lyrics, pick a candidate, then None: the typed lyrics are back.
  5. Change the highlight color on a document page. Confirm the form uses it.
  6. Re-check the document page's own highlight, nudge and seek behavior,
     since its effect was refactored.

## Verification
- `cd backend && .venv/bin/pytest`, `.venv/bin/ruff check app tests migrations`,
  `.venv/bin/ruff format --check …`
- `cd frontend && npm run lint && npm run build && npm test && npm run format:check`
- Browser check with headless Brave via playwright-core, using a test-DB
  backend on :8001 and a second Vite proxying `/api` to it (never the app DB):
  1. Search `夜に駆ける`. Confirm the results are songs (Topic/official
     audio).
  2. Pick one. Confirm the LRCLIB list shows in-tolerance, synced candidates
     first and that the title auto-fills.
  3. Save. Confirm the document opens with LRCLIB lyrics and the right video.
  4. Pick "None". Confirm the lyrics textarea appears and is required.

  (YouTube Music and LRCLIB are called live here, which is fine because
  neither touches the DB.)
- Steps 1, 3 and 4 get the browser check (step 1 covers only points 1 and 3;
  step 4 adds the checks in its own section).
  Step 2 is checked with pytest, plus a curl to the test backend's
  `/api/lrclib/search?title=夜に駆ける&artist=YOASOBI&duration=261`.
- Each step goes on its own branch off `main`. Confirm the branch in the
  commit command, then open that step's PR.
