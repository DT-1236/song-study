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

| Size | Input read |
|---|---|
| S | under 1M |
| M | 1M–5M |
| L | 5M–15M |
| XL | 15M and over |

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

| Date | Work | PR | Phase | Model, effort | Est. | Calls | Input read | Output | Size |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-07 | Katakana card keyed by JMDict entry (backlog) | #78 | initial pass | Opus 5.5, — | — | 52 | 6.8M | 51k | L |
| 2026-10-07 | Katakana card keyed by JMDict entry (backlog) | #78 | /simplify (4 subagents) | Opus 5.5, — | — | 41 | 4.0M | 11k | M |
| 2026-10-08 | Mobile step 1, responsive shell | #100 | initial pass | Sonnet 5.5, medium | — | 18 | 1.2M | 11k | M |
| 2026-10-08 | Mobile step 1, responsive shell | #100 | /simplify (4 subagents) | Sonnet 5.5, medium | — | 16 | 860k | 4k | S |
| 2026-10-08 | Browser harness | #101 | initial pass | Opus 5.5, high | — | 52 | 5.6M | 52k | L |
| 2026-10-09 | Deploy step 1, deployment files | #106 | initial pass | Sonnet 5.5, medium | M | 25 | 1.5M | 12k | M |
| 2026-10-09 | Deploy step 1, deployment files | #106 | /simplify (4 subagents) | Sonnet 5.5, medium | — | 18 | 735k | 3k | S |
| 2026-10-09 | Mobile step 2, new document form and documents list | #108 | initial pass | Sonnet 5.5, low | M | 15 | 815k | 5k | S |
| 2026-10-09 | Mobile step 2, new document form and documents list | #108 | /simplify (inline, no subagents) | Sonnet 5.5, low | — | 3 | 209k | 2k | S |
| 2026-10-10 | Backlog sweep 6: postgres gets only its own env | — | backlog item | Sonnet 5.5, medium | — | 9 | 405k | 4k | S |
| 2026-10-10 | Backlog sweep 6: prod migrate service | — | backlog item | Sonnet 5.5, medium | — | 5 | 208k | 2k | S |
| 2026-10-10 | Backlog sweep 6: BuildKit cache mounts | — | backlog item | Sonnet 5.5, low | — | 6 | 248k | 1k | S |
| 2026-10-10 | Backlog sweep 6: `.lyrics-box` as a `<div>` | — | backlog item | Sonnet 5.5, low | — | 11 | 467k | 2k | S |
| 2026-10-10 | Backlog sweep 6: `useInert` and `inputRef` | — | backlog item | Haiku 5.5, low | — | 7 | 310k | 4k | S |
| 2026-10-10 | Backlog sweep 6: `NO_HOVER` (moved into the mobile plan) | — | backlog item | Haiku 5.5, low | — | 12 | 536k | 5k | S |
| 2026-10-10 | Backlog sweep 6: `PAGE_NAMES` questions (2 sessions, no change) | — | backlog item | Haiku 5.5 / Sonnet 5.5, low | — | 6 | 243k | 2k | S |
| 2026-10-10 | Backlog sweep 6: gather and commit items | — | backlog sweep | Opus 5.5, medium | — | 29 | 1.5M | 9k | M |
| 2026-10-10 | Backlog sweep 6 | — | /simplify (4 subagents) | Opus 5.5, medium | — | 25 | 1.4M | 8k | M |

## Post-mortem log

None yet.
