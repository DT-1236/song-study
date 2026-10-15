# Token usage

What planned work actually costs in tokens, per phase, so that plan
estimates can be checked against it and an expensive surprise gets looked
into while the session that caused it is still fresh.

## Sizes

Plans estimate a step's initial pass as one of these buckets, next to its
model and effort. The measure is **input read**: the context sent on every
API call of the phase, summed, subagents included. Every call re-reads
everything before it, so this grows with turns × context size, and it is
what a session costs.

| Size | Input read   |
| ---- | ------------ |
| S    | under 1M     |
| M    | 1M–5M        |
| L    | 5M–15M       |
| XL   | 15M and over |

The size is for the initial pass only. `/simplify` and backlog sweeps are
measured as phases of their own, so their cost can be compared across PRs.

## Recording

Run `python3 scripts/token_usage.py` in the session doing the work: it
measures the session it runs in (`$CLAUDE_CODE_SESSION_ID`), split at each
typed prompt and each skill such as `/simplify`. Add a row to the ledger for
each phase:

- after the initial pass, once its PR is open;
- after each `/simplify` or backlog sweep on that PR.

Commit the rows with the PR they measure. Where the work comes from a plan,
also set that step's Actual column, as `<size>; simplify <size>`.

## Post-mortems

When a phase lands **two or more buckets above its estimate** (an M that
measured XL), add an entry to the post-mortem log below before closing the
session. Run `python3 scripts/token_usage.py --top 10` for the tool calls
that grew the context most, and say in a few lines:

- what drove the cost: one huge read, many iterations, a hang, a re-derived
  setup;
- whether it was avoidable, and the change that avoids it next time (a
  harness fix, a doc note, a narrower read), made in the same PR where it's
  small.

One bucket over is normal variance and needs no post-mortem.

## Ledger

| Date       | Work                                                                   | PR   | Phase                                  | Model, effort               | Est. | Calls | Input read | Output | Size |
| ---------- | ---------------------------------------------------------------------- | ---- | -------------------------------------- | --------------------------- | ---- | ----- | ---------- | ------ | ---- |
| 2026-10-07 | Katakana card keyed by JMDict entry (backlog)                          | #78  | initial pass                           | Opus 5.5, —                 | —    | 52    | 6.8M       | 51k    | L    |
| 2026-10-07 | Katakana card keyed by JMDict entry (backlog)                          | #78  | /simplify (4 subagents)                | Opus 5.5, —                 | —    | 41    | 4.0M       | 11k    | M    |
| 2026-10-08 | Mobile step 1, responsive shell                                        | #100 | initial pass                           | Sonnet 5.5, medium          | —    | 18    | 1.2M       | 11k    | M    |
| 2026-10-08 | Mobile step 1, responsive shell                                        | #100 | /simplify (4 subagents)                | Sonnet 5.5, medium          | —    | 16    | 860k       | 4k     | S    |
| 2026-10-08 | Browser harness                                                        | #101 | initial pass                           | Opus 5.5, high              | —    | 52    | 5.6M       | 52k    | L    |
| 2026-10-09 | Deploy step 1, deployment files                                        | #106 | initial pass                           | Sonnet 5.5, medium          | M    | 25    | 1.5M       | 12k    | M    |
| 2026-10-09 | Deploy step 1, deployment files                                        | #106 | /simplify (4 subagents)                | Sonnet 5.5, medium          | —    | 18    | 735k       | 3k     | S    |
| 2026-10-09 | Mobile step 2, new document form and documents list                    | #108 | initial pass                           | Sonnet 5.5, low             | M    | 15    | 815k       | 5k     | S    |
| 2026-10-09 | Mobile step 2, new document form and documents list                    | #108 | /simplify (inline, no subagents)       | Sonnet 5.5, low             | —    | 3     | 209k       | 2k     | S    |
| 2026-10-10 | Backlog sweep 6: postgres gets only its own env                        | #109 | backlog item                           | Sonnet 5.5, medium          | —    | 9     | 405k       | 4k     | S    |
| 2026-10-10 | Backlog sweep 6: prod migrate service                                  | #109 | backlog item                           | Sonnet 5.5, medium          | —    | 5     | 208k       | 2k     | S    |
| 2026-10-10 | Backlog sweep 6: BuildKit cache mounts                                 | #109 | backlog item                           | Sonnet 5.5, low             | —    | 6     | 248k       | 1k     | S    |
| 2026-10-10 | Backlog sweep 6: `.lyrics-box` as a `<div>`                            | #109 | backlog item                           | Sonnet 5.5, low             | —    | 11    | 467k       | 2k     | S    |
| 2026-10-10 | Backlog sweep 6: `useInert` and `inputRef`                             | #109 | backlog item                           | Haiku 5.5, low              | —    | 7     | 310k       | 4k     | S    |
| 2026-10-10 | Backlog sweep 6: `NO_HOVER` (moved into the mobile plan)               | #109 | backlog item                           | Haiku 5.5, low              | —    | 12    | 536k       | 5k     | S    |
| 2026-10-10 | Backlog sweep 6: `PAGE_NAMES` questions (2 sessions, no change)        | #109 | backlog item                           | Haiku 5.5 / Sonnet 5.5, low | —    | 6     | 243k       | 2k     | S    |
| 2026-10-10 | Backlog sweep 6: gather and commit items                               | #109 | backlog sweep                          | Opus 5.5, medium            | —    | 29    | 1.5M       | 9k     | M    |
| 2026-10-10 | Backlog sweep 6                                                        | #109 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 25    | 1.4M       | 8k     | M    |
| 2026-10-10 | Mobile step 4, settings page                                           | #110 | initial pass                           | Sonnet 5.5, medium          | M    | 19    | 1.2M       | 12k    | M    |
| 2026-10-10 | Mobile step 4, settings page                                           | #110 | /simplify (4 subagents)                | Sonnet 5.5, medium          | —    | 22    | 1.3M       | 6k     | M    |
| 2026-10-10 | Mobile step 5a, mouse-only hover and Pinned marker                     | #111 | initial pass                           | Sonnet 5.5, medium          | M    | 14    | 787k       | 7k     | S    |
| 2026-10-10 | Backlog sweep 7: gather and commit items, AGENTS.md                    | #112 | backlog sweep                          | Opus 5.5, medium            | —    | 38    | 2.1M       | 15k    | M    |
| 2026-10-10 | Backlog sweep 7 and #111                                               | #112 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 69    | 6.1M       | 24k    | L    |
| 2026-10-12 | Player bar, video hidden by default                                    | #114 | initial pass                           | Opus 5.5, medium            | —    | 71    | 7.9M       | 55k    | L    |
| 2026-10-12 | Player bar, video hidden by default                                    | #114 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 35    | 3.6M       | 13k    | M    |
| 2026-10-12 | Lyrics shown while a document processes; open it on saving             | #116 | initial pass                           | Opus 5.5, medium            | —    | 22    | 1.5M       | 12k    | M    |
| 2026-10-12 | Lyrics shown while a document processes; open it on saving             | #116 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 35    | 2.1M       | 9k     | M    |
| 2026-10-12 | Documents processed by a background job, polled by the page            | #117 | initial pass (plan + both steps)       | Opus 5.5, high              | L    | 78    | 12.3M      | 75k    | L    |
| 2026-10-12 | Documents processed by a background job, polled by the page            | #117 | /simplify (4 subagents)                | Opus 5.5, high              | —    | 48    | 6.1M       | 20k    | L    |
| 2026-10-13 | Player readiness reported by YouTubePlayer (backlog)                   | #118 | initial pass (onReadyChange, PR)       | Sonnet 5.5, high            | —    | 20    | 1.0M       | 8k     | M    |
| 2026-10-13 | Player readiness reported by YouTubePlayer (backlog)                   | #118 | rework: queue `playFrom` in the handle | Sonnet 5.5, high            | —    | 13    | 963k       | 10k    | S    |
| 2026-10-13 | Document processing step 2, open documents from the list at once       | #120 | initial pass                           | Sonnet 5.5, low             | M    | 14    | 673k       | 4k     | S    |
| 2026-10-13 | Document processing step 2, open documents from the list at once       | #120 | /simplify (inline, no subagents)       | Sonnet 5.5, low             | —    | 2     | 111k       | 1k     | S    |
| 2026-10-13 | Document text changes reset processing (trigger)                       | #121 | initial pass                           | Opus 5.5, medium            | M    | 27    | 1.7M       | 14k    | M    |
| 2026-10-13 | Document text changes reset processing (trigger)                       | #121 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 34    | 2.1M       | 7k     | M    |
| 2026-10-13 | Document processing step 4, record when processing finished            | #122 | initial pass                           | Sonnet 5.5, medium          | M    | 11    | 598k       | 6k     | S    |
| 2026-10-13 | Document processing step 4, record when processing finished            | #122 | /simplify (inline, no subagents)       | Sonnet 5.5, medium          | —    | 2     | 134k       | 1k     | S    |
| 2026-10-13 | Document processing step 5, polls read before locking                  | #123 | initial pass                           | Opus 5.5, low               | S    | 13    | 0.7M       | 5k     | S    |
| 2026-10-13 | Document processing step 5, polls read before locking                  | #123 | /simplify (4 subagents)                | Opus 5.5, low               | —    | 18    | 0.7M       | 4k     | S    |
| 2026-10-13 | LRCLIB line timings stale-checked by text (backlog)                    | #124 | initial pass                           | Sonnet 5.5, medium          | —    | 11    | 546k       | 6k     | S    |
| 2026-10-13 | LRCLIB line timings stale-checked by text (backlog)                    | #124 | /simplify (inline, no subagents)       | Sonnet 5.5, medium          | —    | 2     | 123k       | 1k     | S    |
| 2026-10-13 | Claim a document in one conditional UPDATE (backlog)                   | #125 | initial pass                           | Opus 5.5, medium            | —    | 15    | 783k       | 7k     | S    |
| 2026-10-13 | Claim a document in one conditional UPDATE (backlog)                   | #125 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 21    | 952k       | 6k     | S    |
| 2026-10-13 | Format Markdown and scripts/ with the repo's formatters                | #126 | initial pass                           | Sonnet 5.5, medium          | —    | 29    | 1.8M       | 15k    | M    |
| 2026-10-13 | Mobile step 5b, tap to preview, long-press to pin, gloss sheet         | #127 | initial pass                           | Opus 5.5, high              | L    | 89    | 15.2M      | 103k   | XL   |
| 2026-10-13 | Mobile step 5b, tap to preview, long-press to pin, gloss sheet         | #127 | /simplify (4 subagents)                | Opus 5.5, high              | —    | 52    | 6.9M       | 16k    | L    |
| 2026-10-13 | Backlog sweep 8: held token marked on its element                      | #128 | backlog item                           | Sonnet 5.5, medium          | —    | 7     | 315k       | 2k     | S    |
| 2026-10-13 | Backlog sweep 8: `useHeightProperty`                                   | #128 | backlog item                           | Sonnet 5.5, medium          | —    | 12    | 554k       | 4k     | S    |
| 2026-10-13 | Backlog sweep 8: `openGlossSurface` in the harness                     | #128 | backlog item                           | Haiku 5.5, low              | —    | 11    | 528k       | 7k     | S    |
| 2026-10-13 | Backlog sweep 8: gather and commit items                               | #128 | backlog sweep                          | Opus 5.5, medium            | —    | 26    | 1.4M       | 7k     | M    |
| 2026-10-13 | Backlog sweep 8 and #113, #115, #118                                   | #128 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 39    | 2.2M       | 8k     | M    |
| 2026-10-13 | Mobile step 6: select on touch                                         | #129 | initial pass                           | Opus 5.5, low               | M    | 26    | 1.9M       | 13k    | M    |
| 2026-10-13 | Mobile step 6: select on touch                                         | #129 | /simplify (4 subagents)                | Opus 5.5, low               | —    | 17    | 1.1M       | 4k     | M    |
| 2026-10-13 | Mobile step 7: timing buttons in the player bar                        | #131 | initial pass                           | Sonnet 5.5, medium          | M    | 21    | 1.3M       | 11k    | M    |
| 2026-10-13 | Mobile step 7: timing buttons in the player bar                        | #131 | /simplify (4 subagents)                | Sonnet 5.5, medium          | —    | 22    | 1.3M       | 6k     | M    |
| 2026-10-13 | Backlog sweep 9: header height through `useHeightProperty`             | #130 | backlog item                           | Sonnet 5.5, medium          | —    | 13    | 652k       | 7k     | S    |
| 2026-10-13 | Backlog sweep 9: `revealBelowPanel` via scroll padding                 | #130 | backlog item                           | Sonnet 5.5, medium          | —    | 7     | 310k       | 3k     | S    |
| 2026-10-13 | Backlog sweep 9: gather and commit items                               | #130 | backlog sweep                          | Opus 5.5, medium            | —    | 18    | 895k       | 7k     | S    |
| 2026-10-13 | Backlog sweep 9                                                        | #130 | /simplify (inline, no subagents)       | Opus 5.5, medium            | —    | 17    | 1.2M       | 9k     | M    |
| 2026-10-13 | Backlog sweep 10: gather and commit items                              | #132 | backlog sweep                          | Opus 5.5, medium            | —    | 13    | 625k       | 4k     | S    |
| 2026-10-13 | Backlog sweep 10                                                       | #132 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 48    | 3.1M       | 15k    | M    |
| 2026-10-13 | Backlog sweep 10: move mobile step 3 in                                | #132 | backlog sweep                          | Opus 5.5, medium            | —    | 11    | 508k       | 4k     | S    |
| 2026-10-13 | Backlog sweep 10: mobile step 3                                        | #132 | /simplify (inline, no subagents)       | Opus 5.5, medium            | —    | 10    | 582k       | 4k     | S    |
| 2026-10-13 | Timing editor render cost (backlog)                                    | #134 | initial pass                           | Opus 5.5, medium            | —    | 28    | 2.1M       | 23k    | M    |
| 2026-10-13 | Timing editor render cost (backlog)                                    | #134 | /simplify (inline, no subagents)       | Opus 5.5, low               | —    | 6     | 630k       | 4k     | S    |
| 2026-10-13 | Mobile step 3 browser check, landscape query fix                       | #136 | initial pass                           | Opus 5.5, medium            | —    | 29    | 3.2M       | 17k    | M    |
| 2026-10-13 | Auto-scroll toggle in the player bar                                   | #138 | initial pass                           | Sonnet 5.5, medium          | —    | 9     | 404k       | 4k     | S    |
| 2026-10-13 | Auto-scroll toggle in the player bar                                   | #138 | /simplify (inline, no subagents)       | Sonnet 5.5, medium          | —    | 6     | 341k       | 1k     | S    |
| 2026-10-13 | Timing bar: seek and nudge buttons told apart                          | #139 | initial pass                           | Sonnet 5.5, medium          | —    | 21    | 1.2M       | 14k    | M    |
| 2026-10-13 | Timing bar: seek and nudge buttons told apart                          | #139 | /simplify (inline, no subagents)       | Sonnet 5.5, medium          | —    | 2     | 175k       | 1k     | S    |
| 2026-10-13 | Player bar: no-wrap buttons, centered seek row                         | #140 | initial pass                           | Sonnet 5.5, medium          | —    | 11    | 520k       | 3k     | S    |
| 2026-10-13 | Nudge flash: red background fade instead of bold                       | #141 | initial pass                           | Sonnet 5.5, medium          | —    | 12    | 678k       | 4k     | S    |
| 2026-10-14 | Deploy step 2, auto-deploy                                             | #144 | initial pass                           | Opus 5.5, medium            | L    | 24    | 1.9M       | 27k    | M    |
| 2026-10-14 | Deploy step 2, auto-deploy                                             | #144 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 22    | 1.4M       | 7k     | M    |
| 2026-10-14 | Long press: countdown sweeps the token group                           | #145 | initial pass                           | Sonnet 5.5, medium          | —    | 40    | 2.5M       | 21k    | M    |
| 2026-10-14 | Mobile gloss sheet: Select, pin toggle, X close                        | #146 | initial pass                           | Sonnet 5.5, medium          | —    | 36    | 2.4M       | 19k    | M    |
| 2026-10-14 | Mobile top bar spacing, Dict label, Settings footer                    | #147 | initial pass                           | Sonnet 5.5, medium          | —    | 30    | 1.5M       | 9k     | M    |
| 2026-10-14 | New document: LRCLIB search without a song, remove lyrics              | #148 | initial pass                           | Sonnet 5.5, medium          | —    | 40    | 2.6M       | 19k    | M    |
| 2026-10-14 | YouTube search: search videos instead of songs                         | #149 | initial pass                           | Sonnet 5.5, medium          | —    | 23    | 1.2M       | 12k    | M    |
| 2026-10-14 | Post-hoc sweep: #133, #136, #137, #140, #141, #145–#151                | #152 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 70    | 5.0M       | 19k    | L    |
| 2026-10-14 | Backlog sweep 11: focus ring for keyboard focus only                   | #154 | backlog item                           | Sonnet 5.5, low             | —    | 5     | 207k       | 1k     | S    |
| 2026-10-14 | Backlog sweep 11: harness `h.document()` and `h.timeLines()`           | #154 | backlog item                           | Sonnet 5.5, medium          | —    | 8     | 363k       | 5k     | S    |
| 2026-10-14 | Backlog sweep 11: video search toggle re-runs on a `kind` prop         | #154 | backlog item                           | Opus 5.5, medium            | —    | 22    | 1.2M       | 11k    | M    |
| 2026-10-14 | Backlog sweep 11: failing browser checks, auto-scroll follows playback | #154 | backlog item                           | Opus 5.5, medium            | —    | 70    | 6.0M       | 43k    | L    |
| 2026-10-14 | Backlog sweep 11: gather and commit items                              | #154 | backlog sweep                          | Opus 5.5, medium            | —    | 19    | 950k       | 6k     | S    |
| 2026-10-14 | Backlog sweep 11: finish, verify, commit                               | #154 | backlog sweep                          | Opus 5.5, medium            | —    | 21    | 1.2M       | 7k     | M    |
| 2026-10-14 | Backlog sweep 11                                                       | #154 | /simplify (4 subagents)                | Opus 5.5, medium            | —    | 70    | 5.2M       | 19k    | L    |

## Post-mortem log

None yet.
