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
