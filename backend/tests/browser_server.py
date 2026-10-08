"""Serve the app for headless browser checks (docs/browser-checks.md): a
freshly migrated database of its own, seeded with one tokenized document,
with every request acting as the test user.

Run from backend/ as `python -m tests.browser_server`; `make browser-up` at
the repo root starts it alongside a Vite that proxies to it. Writes the seeded
ids as JSON to BROWSER_SEED_FILE when that's set.
"""

import json
import os

import uvicorn
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.env import load_env
from tests.fixtures import kumo_no_ito

load_env()

# A database of its own rather than TEST_DATABASE_URL's: pytest drops and
# re-creates that one on every run, which would wipe the seeded rows from
# under a check that's running. The name keeps the `_test` suffix that
# tests.support insists on.
_test_url = make_url(os.environ["TEST_DATABASE_URL"])
os.environ["TEST_DATABASE_URL"] = _test_url.set(
    database=_test_url.database.removesuffix("_test") + "_browser_test"
).render_as_string(hide_password=False)

from tests import support  # must come after setting TEST_DATABASE_URL above

# Far above any id the app database hands out, so a request that somehow
# reaches that database finds nothing rather than a real document.
FIRST_DOCUMENT_ID = 900001


def seed() -> dict:
    """Re-create the database and seed it, returning the seeded ids."""
    support.recreate_test_database()
    with support.engine.begin() as conn:
        conn.execute(
            text("SELECT setval('documents_id_seq', :id, false)"),
            {"id": FIRST_DOCUMENT_ID},
        )
    document_id = support.create_tokenized_document(kumo_no_ito.TEXT, kumo_no_ito.TITLE)
    return {"user_id": support.TEST_USER_ID, "document_id": document_id}


if __name__ == "__main__":
    seeded = seed()
    print("seeded", json.dumps(seeded), flush=True)
    if seed_file := os.environ.get("BROWSER_SEED_FILE"):
        with open(seed_file, "w") as f:
            json.dump(seeded, f)
    uvicorn.run(
        support.main.app,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8001")),
    )
