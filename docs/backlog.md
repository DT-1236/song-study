# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## `/simplify` on 2e67314..296c658 (readiness sort and summary, shared maturity and line-end polling, readiness batching)

- Extract a `useLatest(value)` hook for the "keep the newest callback in a ref" pattern, written out
  four times: `useLineEndPolling.ts` (`onEndRef`), `YouTubePlayer.tsx` (`onReadyRef`), and
  `DocumentViewPage.tsx` (`handleClickRef`, `handleKeyDownRef`). Each is a `useRef` plus an effect
  assigning `.current`; replace them with the hook. Model: Sonnet 5, low effort — mechanical, but
  four call sites whose listeners must keep reading through the ref.
