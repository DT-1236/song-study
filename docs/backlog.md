# Backlog

Improvements a review turned up that weren't worth doing in the change that
found them. Each entry says where it came from and what doing it would cost,
so it can be picked up without re-deriving the reasoning.

## From `/simplify` on PR #24 (users, ownership, Google login)

- **Handle a 401 centrally in the frontend's `apiFetch`.**
  `AuthGate` checks `/auth/me` once, at load, so a session that expires mid-use
  surfaces as per-call error text. `apiFetch` could catch a 401 and send the
  browser back to the login page (or reset the gate's state).
  *Sonnet 5, medium* — conventional React against a clear behavior.

## From adding Prettier and Ruff (formatting only)

- **Narrow the blind `except` in `heteronym_readings`.**
  `app/tokenization.py` catches bare `Exception` around a SudachiPy lookup and
  returns `[]`. That's the right fallback — it runs per token while tokenizing,
  and "no heteronym readings" is a fine answer — but as written it also
  swallows a real bug. Narrowing it needs a list of what SudachiPy's `lookup`
  actually raises, which is why the Ruff adoption left it with a `# noqa` and
  a comment rather than guessing.
  *Sonnet 5, medium* — the work is finding out what that library raises; the
  edit itself is one line.
