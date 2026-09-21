# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## From `/simplify` on PR #24 (users, ownership, Google login)

- **One helper for the owner-scoped document select.**
  `get_document`, `_lock_document` and `owned_document_id` each write their own
  `WHERE id = :id AND owner_id = :owner_id`, now across two modules. A single
  `_owned_document_row(conn, id, user_id, for_update=False)` would remove the
  repetition. The gain is small, and `owned_document_id` lives in `app/users.py`
  so the helper would need a home both can reach.
  *Haiku 4.5, low* — mechanical, with one obvious shape.

- **The comment above `app.include_router(api)` is wrong.**
  It says including a router copies its routes, so inclusion must come last.
  This FastAPI version nests the router instead (`_IncludedRouter`, which is why
  `tests/support.py`'s `api_routes()` has to walk it), so the ordering may no
  longer be load-bearing. Worth checking before someone relies on either claim.
  *Haiku 4.5, low* — read the FastAPI version's `include_router`, then fix the
  comment or keep it with a real reason.

- **Handle a 401 centrally in the frontend's `apiFetch`.**
  `AuthGate` checks `/auth/me` once, at load, so a session that expires mid-use
  surfaces as per-call error text. `apiFetch` could catch a 401 and send the
  browser back to the login page (or reset the gate's state).
  *Sonnet 5, medium* — conventional React against a clear behavior.

## From adding Prettier and Ruff (formatting only)

- **Adopt `ruff check`, not just `ruff format`.**
  Installing Ruff for formatting also brings its linter, and it currently
  reports 187 findings across `app/`, `tests/` and `migrations/` — 177 of them
  auto-fixable. The bulk is mechanical: 115 `UP007`/`UP045` (`Optional[X]` and
  `Union[X, Y]` → `X | None`, `X | Y`), 21 `I001` (unsorted imports), 18
  `UP035` (deprecated `typing` imports) and 16 `F401` (unused imports). The
  remainder needs judgment and is worth reading one at a time: `B023`
  (a closure capturing a loop variable) and `BLE001` (a blind `except`) can
  each be a real bug rather than a style point. Kept out of the formatting
  change so that diff stays reviewable as pure reflow.
  *Sonnet 5, medium* — the auto-fixes are pattern application against a clear
  spec, but the dozen judgment findings should be read by a human before the
  `--fix` sweep is committed.

- **No CI runs either formatter.**
  Pre-commit hooks now run both, but they're opt-in per clone (`pre-commit
  install`) and skippable with `--no-verify`, so nothing enforces them for
  everyone. The drift is not hypothetical: `DocumentViewPage.tsx` was already
  out of Prettier format on main by the time the hooks were fixed. There's
  still no CI workflow in the repo at all, so this means adding one.
  *Haiku 4.5, low* — a standard GitHub Actions workflow once someone decides
  that's the mechanism.
