# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## From `/simplify` on PR #24 (users, ownership, Google login)

- **Fold the ownership check into `_fetch_tokens`'s queries.**
  `get_document_tokens` runs a separate `SELECT EXISTS` before reading tokens,
  which adds a round trip to the reading view, the app's hottest read
  (`test_first_processing_takes_a_fixed_number_of_round_trips` counts moved
  12→13, 10→11, 2→3). Filtering by owner inside the token and conflict queries
  (a foreign document then returns no tokens and falls through to the existing
  owner-scoped text read, which 404s) would restore the old counts. It changes
  every caller of `_fetch_tokens`, and the extra query is cheap at this scale.
  *Sonnet 5, high* — the change is specified, but a wrong owner filter fails
  silently by leaking another user's tokens.

- **One helper for the owner-scoped document select.**
  `get_document`, `_lock_document` and `_require_owned_document` each write
  their own `WHERE id = :id AND owner_id = :owner_id`. A single
  `_owned_document_row(conn, id, user_id, for_update=False)` would remove the
  repetition. The gain is small.
  *Haiku 4.5, low* — mechanical, with one obvious shape.

- **Make ownership a FastAPI dependency instead of a check in each route.**
  Every token route starts with `_require_owned_document(...)`, so a new one
  that forgets it is silently unscoped. A dependency on the path, something
  like `OwnedDocument = Annotated[int, Depends(owned_document_id)]`, would make
  that impossible and could be shared with `_lock_document`. The catch: the
  tests call route functions directly and bypass dependencies, so this goes
  together with the next item.
  *Opus 5, high* — a cross-cutting change to how every route is scoped, where
  a missed route is a silent leak.

- **Test the routes through a `TestClient` with `dependency_overrides`.**
  `dependency_overrides[current_user_id]` is the general way to act as a given
  user, and would replace the `_as_test_user` wrappers in `tests/support.py`.
  `httpx2` is already installed. It also lets the tests cover the routing and
  the dependencies that direct calls skip.
  *Sonnet 5, medium* — conventional test-harness work once the dependency
  above exists.

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
  `npm run format:check` and `ruff format --check` exist but nothing enforces
  them, so the repo can drift back out of format. There's no CI workflow in
  the repo at all yet, so this means adding one (or a pre-commit hook).
  *Haiku 4.5, low* — a standard GitHub Actions workflow once someone decides
  that's the mechanism.
