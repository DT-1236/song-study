# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on PR #92 (LRCLIB error handling)

- **Report a 404 from `_get_json` as `None`.** `backend/app/lrclib.py`'s
  `_get_json` raises the private `_NotFound(LrclibUnavailable)` with the "no
  track at that address" message, which `fetch_lyrics` turns back into an
  `LrclibError`. Have `_get_json` return `None` on a 404 instead (annotate it
  `Any | None`), and delete `_NotFound`. `fetch_lyrics` raises
  `LrclibError("LRCLIB has no track at that address.")` on `None`.
  `search_tracks` counts a `None` result as a failed variant by appending
  `LrclibUnavailable("Couldn't search LRCLIB.")` to `errors`, so an all-404
  search is still a 502. In `backend/tests/test_lrclib.py`, `FakeLrclib.__call__`
  returns `None` for an unknown record. The 404 case leaves
  `test_request_failures` for its own test asserting `_get_json` returns
  `None`, which also lets that test drop its exact-type assertion. Linking a
  missing track must still be a 422. *Sonnet 5, low*: the shape is decided,
  and the existing 404/422 tests catch a slip.

## `/simplify` on the LRCLIB matches form (song search step 3)

- **Use `useApiResource` in `LrclibMatches`.** `frontend/src/LrclibMatches.tsx`
  hand-rolls the cancelled flag, `.then`/`.catch` and `errorMessage` that
  `useApiResource(() => searchLrclib(…), [song], 'LRCLIB search failed.')`
  already gives. The pre-selection of a synced in-tolerance first match then
  needs its own small effect on `data`, since the hook exposes no completion
  callback. Worth it only if that effect stays small. *Sonnet 5, low*: the
  browser check on the New document page catches a missed pre-selection.

## `/simplify` on the document page's LRCLIB search (lrclib-change-search)

- **One editing mode on the document page.** `frontend/src/DocumentViewPage.tsx`'s
  `DocumentViewPage` tracks `editingLyrics`, `timingDraft` and `lrclibSong`
  separately, though only one can be set at a time. A derived `editing` flag
  now hides the other modes' buttons. Replace the three with one state, e.g.
  `{ kind: 'view' } | { kind: 'lyrics', draft } | { kind: 'timings', draft }
  | { kind: 'lrclib', song }`, so a new mode can't forget a guard. That
  touches every reader of `timingDraft` (the timing editor's save, cancel,
  discard dialog, leave blocker and `shownTimings`). Decide too whether the
  font-size and furigana controls should hide during the LRCLIB preview,
  which has no furigana. *Opus 5, medium*: the timing draft's unsaved-changes
  guards fail silently if a transition drops the draft. The target shape is
  decided, which is why medium effort is enough.
