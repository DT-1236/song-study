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

# Ranks how well an entry's headword matches the raw query, best first. A
# single "%query%" jamdict lookup already returns every substring match (a
# superset of exact/prefix/suffix), so ranking happens here rather than as
# four separate lookups.
_EXACT, _PREFIX, _SUFFIX, _SUBSTRING = range(4)


def _match_tier(query: str, entry) -> int:
    texts = [k.text for k in entry.kanji_forms] + [k.text for k in entry.kana_forms]
    if any(t == query for t in texts):
        return _EXACT
    if any(t.startswith(query) for t in texts):
        return _PREFIX
    if any(t.endswith(query) for t in texts):
        return _SUFFIX
    return _SUBSTRING


def search_jmdict(query: str, max_results_per_tier: int = 3) -> list[dict]:
    """Ad-hoc JMDict lookup for the standalone search box in the sidebar —
    unlike a per-token gloss lookup, this isn't scoped to a single reading
    (there's no token context to key a match off of here), so every entry
    whose headword contains `query` is returned (kana_forms included so each
    entry's own reading(s) stay visible to the user), ranked exact match
    first, then prefix, then suffix, then substring.

    Exact matches are never capped — there's usually only a handful, and
    they're what the user is most likely looking for. The looser tiers
    (prefix/suffix/substring) are each capped independently at
    `max_results_per_tier`, so a broad query doesn't bury the closer matches
    under a wall of loosely-related compounds.
    """
    query = query.strip()
    if not query:
        return []

    jam = _get_jamdict()
    result = jam.lookup(f"%{query}%")
    scored_entries = []
    for e in result.entries:
        has_priority = any(k.pri for k in e.kanji_forms) or any(k.pri for k in e.kana_forms)
        scored_entries.append(
            (
                (_match_tier(query, e), not has_priority),
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

    results = []
    tier_counts = {_PREFIX: 0, _SUFFIX: 0, _SUBSTRING: 0}
    for (tier, _priority_key), entry in scored_entries:
        if tier in tier_counts:
            if tier_counts[tier] >= max_results_per_tier:
                continue
            tier_counts[tier] += 1
        results.append(entry)

    return results[:_SEARCH_RESULT_LIMIT]
