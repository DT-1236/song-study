# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

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
