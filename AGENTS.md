# Instructions for AI agents working in this repo

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
