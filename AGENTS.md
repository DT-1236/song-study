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

- Limit a docstring to the function's *intended effect*, phrased in terms
  of its inputs — what it does/returns, not how. Add one to two lines of
  reasoning only when the *why* isn't obvious from the signature/effect
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

## Skipped review findings

- When a `/simplify` run finds something it decides not to fix — because the
  fix would change behavior, reach well outside the reviewed diff, or isn't
  worth its cost yet — add it to `docs/backlog.md` rather than leaving it
  only in the run's summary. Give each entry a bullet under a heading naming
  the run (`/simplify` on PR #N, and what it covered): what the finding is,
  where it is, and what fixing it would cost, so it can be picked up later
  without re-deriving the reasoning.
- End each entry with the model and effort expected to complete it, chosen
  as `docs/flashcards.md` does ("Which model to run each step with"): the
  model by how subtle the change is (Opus 5 where a mistake is silent or the
  surrounding code is delicate, Sonnet 5 for pattern application against a
  clear spec, Haiku 4.5 for a mechanical change with one obvious answer),
  and the effort by how much is already decided. Add a few words on why when
  the pairing isn't obvious.
- Skip false positives; they aren't backlog.

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
- It does *not* work for files GitHub refuses to diff at all (files past
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
