# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on song search step 1 (YouTube Music search)

- `SongResult` (`backend/app/main.py`) repeats the fields of `Song`
  (`backend/app/youtube_music.py`), converted with `dataclasses.asdict`.
  Making `Song` a Pydantic model would drop the copy, but every other module
  here (e.g. `lrclib.py`) returns dataclasses converted in `main.py`, so it
  would be a repo-wide convention change. Opus 5, low: the choice is the
  hard part.
- `formatDuration` in `frontend/src/SongSearch.tsx` duplicates the m:ss logic
  of `formatTimestamp` in `frontend/src/timing.ts`. Sharing it means splitting
  that function and covering the whole-second case in `timing.test.ts`.
  Haiku 4.5, low: one obvious answer.

## Song search

- Play the picked song in `SongSearch`/`NewDocumentForm` with the existing
  `YouTubePlayer` (`frontend/src/YouTubePlayer.tsx`, `videoId` prop), shown
  once a song is picked and following the picked video ID as it changes, laid
  out as on the document page. Sonnet 5, low: reuses a component against a
  clear precedent.
