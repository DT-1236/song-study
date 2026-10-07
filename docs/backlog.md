# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PR #91 (LRCLIB track search)

- **Keep `_get_json` to transport errors.** `backend/app/lrclib.py`'s
  `_get_json` turns a 404 into `LrclibError("LRCLIB has no track at that
  address.")`, a message only `/api/get` should give. Instead, have it raise
  `LrclibUnavailable` for every HTTP, network or JSON failure, and give a 404
  its own subclass of that (or a `None` return). `fetch_lyrics` then raises the
  "no track" `LrclibError` itself. `search_tracks`' all-variants-failed branch
  shrinks to `raise errors[0]`, and the `LrclibError` case of
  `test_search_fails_when_every_variant_does` goes away. Update the 404 case of
  `test_request_failures` and `FakeLrclib.__call__`'s unknown-record branch to
  match. Linking a missing track must still be a 422. *Sonnet 5, medium*:
  the target shape is decided, and the existing 404/422 tests catch a slip.
- **Map upstream outages to 502 once.** `backend/app/main.py` repeats
  `except …Unavailable: raise HTTPException(502, str(exc))` in `songs_search`,
  `lrclib_search` and `_fetch_lrclib_for_link`. Register
  `app.exception_handler(LrclibUnavailable)` and
  `app.exception_handler(YouTubeMusicUnavailable)`, each returning a 502
  `JSONResponse({"detail": str(exc)})`, and drop those try blocks.
  `_fetch_lrclib_for_link` keeps its 422 for `LrclibError`, which must stay
  below the handler (`LrclibUnavailable` subclasses it). The existing 502 tests
  in `test_lrclib.py` and `test_youtube_music.py` cover it. *Haiku 4.5,
  low*: mechanical, one obvious answer.
