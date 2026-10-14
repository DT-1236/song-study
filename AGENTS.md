# Instructions for AI agents working in this repo

## Development vs. deployment

- Local development may differ from a deployment only in configuration:
  `http` instead of `https`, `localhost` hostnames, throwaway secrets, debug
  flags. Each of those is an environment variable (or a value derived from
  one), and no code branches on "dev" vs. "prod".
- Everything else is written the way it would be deployed, even if that's
  more work now: the same origin layout, cookie and session behavior, auth
  flow, routing and database engine. A bug in any of those only surfaces at
  deploy time, which is the most expensive time to find it.
- Before adding a dev-only shortcut, ask whether it changes the shape of the
  code (CORS for a split origin, a default user, a special-cased URL) or only
  a value. Only a value is fine; otherwise reconfigure the dev setup, such as
  the Vite proxy, to match deployment instead.

## Function descriptions (docstrings)

- Limit a docstring to the function's _intended effect_, phrased in terms
  of its inputs — what it does/returns, not how. Add one to two lines of
  reasoning only when the _why_ isn't obvious from the signature/effect
  alone (a non-obvious constraint, a domain rule the caller needs to know).
- Keep implementation details — which helper it delegates to, a specific
  data-shape quirk being worked around, an algorithmic choice — out of the
  docstring. Put them as inline comments next to the specific line they
  explain instead. That keeps the note easy to find and update if that
  implementation ever changes, rather than living one level removed in
  prose above the whole function.
- Example (`backend/app/tokenization.py`'s `mixed_reading`):

  ```python
  def mixed_reading(word: str) -> str:
      """The reading of `word` in JMDict's convention: kanji rendered in
      hiragana, kana kept exactly as written — including katakana, since
      JMDict's kana_forms mix hiragana and katakana per word (無理ゲー's
      real entry is keyed to むりゲー, not むりげー).
      """
      # Reuses the furigana span alignment: each span's own text is already
      # in whatever script it's written in, so non-kanji spans just pass
      # through unchanged.
      spans, _, _ = _build_furigana_spans(word, citation_reading(word))
      ...
  ```

  The docstring says what it does (kanji rendered to hiragana, kana kept
  as-is) and why (JMDict's kana convention differs from Sudachi's own
  always-katakana reading). The "reuses the furigana span alignment"
  note is an implementation detail, so it sits as a comment directly
  above the line it's about, not in the docstring.

## Formatting

- Both halves of the repo are formatted by a tool, so don't hand-align code or
  argue with the output: run the formatter before committing.
  - Frontend and Markdown: `npm run format` in `frontend/` (Prettier). It
    covers `frontend/` plus `README.md`, `AGENTS.md`, `docs/` and `deploy/`. The config
    keeps the style the code was already written in — no semicolons, single
    quotes. Prettier aligns Markdown tables, so a table you edit is rewritten
    to the widest cell on the next run; edit the row and let it re-pad the rest.
  - Backend: `.venv/bin/ruff format --config ruff.toml app tests migrations
../scripts` in `backend/` (`make format` there runs it). Ruff's formatter is Black-compatible and left on its defaults (88 columns, double
    quotes), so `backend/ruff.toml` only pins the target Python version.
- `npm run format:check` and `ruff format --check` are the read-only versions,
  for confirming a branch is clean without rewriting files.
- Ruff's _linter_ (`ruff check --config ruff.toml app tests migrations ../scripts`) is adopted and clean —
  keep it that way, and don't add a `# noqa` without a comment saying why the
  rule is wrong here rather than the code.
  - It runs as a pre-commit hook, reporting without `--fix`. A hook that
    rewrites code mid-commit is how a sweep lands unread, and the findings
    worth having are the ones you read: the last sweep turned up a closure
    over a loop variable and two deliberate blind excepts.
  - `ruff check --fix` by hand is fine. Read what it changed before committing.
- The formatters and the linter run as pre-commit hooks, which is belt and
  braces for the above rather than a replacement. They only run once you've
  installed them: `.venv/bin/pre-commit install` in `backend/`, once per
  clone. `pre-commit run --all-files` runs them over the whole repo.

## Testing

- Tests and ad-hoc verification scripts run against the test database
  (`TEST_DATABASE_URL`, set up in `backend/tests/support.py`), never the
  app database at `DATABASE_URL` — not even inside a transaction that gets
  rolled back. That still takes locks and advances sequences on real data,
  and a row already cached there can quietly skip the code path a test
  claims to exercise.
- Fixtures never contain song lyrics or other copyrighted text, even when
  copied from the app database. For realistic Japanese text, use a
  public-domain work (e.g. from Aozora Bunko) and keep its credits, as
  `backend/tests/fixtures/kumo_no_ito.py` does. For other real data, copy
  exactly the rows a case reads instead of pointing the test at the app
  database.

## Browser checks

- Check UI changes in headless Brave with the committed harness, following
  `docs/browser-checks.md`: `make browser-up`, then `make browser-check` (the
  smoke check) before a check of your own built on
  `frontend/browser/harness.mjs`.
- Don't hand-roll servers, Vite configs or Playwright setup in a scratchpad.
  If the harness lacks something a check needs, add it to the harness.
- When a check errors, hangs or is blocked by the harness rather than by
  the change under test, a model at Sonnet's tier or above should consider
  updating the harness itself (`harness.mjs`, `servers.sh`,
  `browser_server.py`) rather than working around it in the check. Either
  way, record the fix or the new gotcha in `docs/browser-checks.md` in the
  same PR, so the next session doesn't rediscover it. A Haiku-class model
  doesn't change the harness: it reports the problem in its summary instead.

## Token usage

- A plan that gives each step a model and effort also gives it a size: the
  expected token use of its initial pass, as a bucket (S, M, L, XL) from
  `docs/token-usage.md`.
- Record what the work actually used in that doc's ledger, measured with
  `python3 scripts/token_usage.py`: after the initial pass, and again after
  each `/simplify` or backlog sweep. Commit the rows with the PR.
- When a phase lands two or more buckets above its estimate, write the
  post-mortem `docs/token-usage.md` describes before closing the session.

## Skipped review findings

- When a `/simplify` run finds something it decides not to fix — because the
  fix would change behavior, reach well outside the reviewed diff, or isn't
  worth its cost yet — add it to `docs/backlog.md` rather than leaving it
  only in the run's summary. Give each entry a bullet under a heading naming
  the run (`/simplify` on PR #N, and what it covered): what the finding is,
  where it is, and what fixing it would cost, so it can be picked up later
  without re-deriving the reasoning.
- End each entry with the model and effort expected to complete it, chosen
  as `docs/completed/flashcards.md` does ("Which model to run each step with"): the
  model by how subtle the change is (Opus 5 where a mistake is silent or the
  surrounding code is delicate, Sonnet 5 for pattern application against a
  clear spec, Haiku 4.5 for a mechanical change with one obvious answer),
  and the effort by how much is already decided. Add a few words on why when
  the pairing isn't obvious.
- Skip false positives; they aren't backlog.

## Backlog items

- Work in the current sweep branch's worktree (`backlog-sweep-N`, which the
  sweep session creates before any item starts), not the main checkout, and
  read `docs/backlog.md` there. An item based on `main` edits a backlog that
  earlier items have already changed, so every handoff conflicts. If you
  weren't given the worktree's path, `git worktree list` shows it; ask if
  there's no sweep branch.
- Leave the change uncommitted in that worktree (no commit, branch or PR). The
  overarching sweep session commits each item and runs `/simplify` over them
  together, which is easier when each item's diff is still loose and unmixed
  with commit history. Say in the summary which files the item touched.

## Pull requests

- When opening, updating, or reviewing a PR with a large diff, don't rely
  on GitHub's default web view alone — it collapses or hides some
  files/diffs automatically ("Large diffs are not rendered by default",
  files tucked behind a "Load diff" click, very long files, etc.).
- Leave inline, file/line-level review comments via the GitHub API
  (`gh api repos/{owner}/{repo}/pulls/{pr}/comments`, or the
  `pulls/{pr}/reviews` endpoint with a `comments` array) so reviewers get
  file-specific context even for files the UI doesn't auto-display. This
  works for any file/line GitHub actually computed a diff for.
- It does _not_ work for files GitHub refuses to diff at all (files past
  its hard size limits, or marked `linguist-generated`) — for those, only
  a general PR-level comment is possible, since there's no diff to anchor
  a line comment to.

### Detecting which files GitHub actually collapses

Don't use the presence/absence of the `patch` field from
`gh api repos/{owner}/{repo}/pulls/{pr}/files` as the signal — that field is
omitted only past a much higher truncation limit than the web UI's collapse
threshold, so relying on "patch present" as "the UI renders this" is wrong
(verified wrong on this repo's PR #5: every file had `patch` present, yet
the web UI still collapsed `tokenization.py`).

Use the **byte length of that `patch` field** as the proxy instead:

```
gh api repos/{owner}/{repo}/pulls/{pr}/files --paginate \
  -q '.[] | "\(.patch | length)\t\(.filename)"' | sort -rn
```

On PR #5, the user confirmed `tokenization.py` (26,056 bytes) was collapsed
in the web UI; `DocumentViewPage.tsx` (25,269 bytes) and `glosses.py`
(19,246 bytes) were treated as very likely/likely collapsed by the same
proxy, with the next-largest file at 13,910 bytes as a separate, clearly
smaller tier. No exact byte threshold is confirmed — GitHub doesn't publish
one — so treat this as a strong ranking signal (comment on the outliers)
rather than a precise cutoff, and it's worth asking the user to confirm
which files they actually see collapsed when in doubt.
