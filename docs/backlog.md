# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## /simplify on PR #159 (refresh cooldown sent with the document, LRCLIB outage backoff)

- **Tell the client how long an LRCLIB outage hold lasts.** While
  `_outage` in `backend/app/lrclib.py` holds requests back, the 502 it
  causes carries only a message, so `pauseIfAsked` on the frontend can't
  pause searches or the Refresh button the way it does for a rate limit's 429. Give the held-back error a `retry_after_seconds` (a subclass of
  `LrclibUnavailable` with its own handler in `backend/app/main.py`, or a
  field on it the 502 handler includes) and have the frontend pause on a 502
  that has one. Touches the exception handlers, `useServerPause.ts` /
  `api.ts`, and their tests. Sonnet 5.5, medium: the rate limit's 429 path
  is the pattern to follow.
