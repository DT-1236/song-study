"""JMDict-backed lookups. Currently just the standalone search box (paste a
word, see every JMDict entry for it) — the per-token gloss pipeline that
will live here too is still being built out.
"""

from __future__ import annotations

import threading

from jamdict import Jamdict

_jam_local = threading.local()


def _get_jamdict() -> Jamdict:
    """One Jamdict instance per thread, not a shared module-level singleton.

    FastAPI runs sync endpoint functions in a worker thread pool, so
    different requests can land on different threads. Jamdict wraps a
    sqlite3 connection, and sqlite3 connections aren't safe to use from a
    thread other than the one that created them — a shared singleton means
    whichever thread happens to create it "owns" it, and any request handled
    by a different thread crashes with 'SQLite objects created in a thread
    can only be used in that same thread'. threading.local() sidesteps this
    entirely: each thread gets its own instance (and its own connection),
    so nothing is ever shared across threads in the first place.
    """
    jam = getattr(_jam_local, "instance", None)
    if jam is None:
        jam = Jamdict()
        _jam_local.instance = jam
    return jam


_SEARCH_RESULT_LIMIT = 50


def search_jmdict(query: str) -> list[dict]:
    """Ad-hoc JMDict lookup for the standalone search box in the sidebar —
    unlike a per-token gloss lookup, this isn't scoped to a single reading
    (there's no token context to key a match off of here), so every entry
    JMDict has for the exact headword is returned, with kana_forms included
    so each entry's own reading(s) stay visible to the user.
    """
    query = query.strip()
    if not query:
        return []

    jam = _get_jamdict()
    result = jam.lookup(query)
    scored_entries = []
    for e in result.entries:
        has_priority = any(k.pri for k in e.kanji_forms) or any(k.pri for k in e.kana_forms)
        scored_entries.append(
            (
                not has_priority,
                {
                    "idseq": e.idseq,
                    "kanji_forms": [k.text for k in e.kanji_forms],
                    "kana_forms": [k.text for k in e.kana_forms],
                    "senses": [
                        {
                            "pos": s.pos,
                            "misc": s.misc,
                            "field": s.field,
                            "gloss": [g.text for g in s.gloss if g.lang == "eng"],
                        }
                        for s in e.senses
                    ],
                },
            )
        )
    scored_entries.sort(key=lambda pair: pair[0])
    return [entry for _, entry in scored_entries][:_SEARCH_RESULT_LIMIT]
