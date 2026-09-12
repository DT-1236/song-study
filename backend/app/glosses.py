"""JMDict-backed gloss lookup, run as a second pass after furigana tokenization.

Cached per (lookup_form, reading) pair in `gloss_lookups` — the same word
recurring across a document (or across documents) is only looked up once.
JMDict lookups run ~20ms each and don't benefit from being repeated in the
same process, so this pass is deliberately synchronous and run once per
unique word rather than once per token occurrence.

Lookups are keyed off normalized_form, not Sudachi's dictionary_form.
Sudachi's own dictionary carries entries for derivations like the
lexicalized potential (挟める, its own dictionary_form, normalized_form
挟む) that JMDict doesn't register as separate headwords; normalized_form
collapses exactly that kind of derived/variant spelling back to the form
JMDict actually has an entry for. Verified against a batch of genuine
potential forms (書ける->書く, 読める->読む, ...) and independent -める verbs
that only superficially resemble potentials (決める, 集める, 込める, ...):
normalization only ever fires for true derivational variants — independent
verbs keep normalized_form == dictionary_form.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional

from jamdict import Jamdict
from sqlalchemy import text

from app.tokenization import TokenRecord, a_split_decomposition, heteronym_readings, mixed_reading, to_hiragana

_SKIP_POS_MAJOR = {"補助記号", "空白"}

# No Japanese script at all (hiragana/katakana/kanji) and at least one Latin
# letter — good enough to catch the English/romaji tokens Sudachi leaves
# untransliterated (gifted, the wanted, yeah, ...) without needing anything
# fancier. Doesn't try to catch stray romanized Japanese or numbers-only
# tokens; those fall through to the normal JMDict path same as before.
_JAPANESE_SCRIPT_RE = re.compile(r"[ぁ-んァ-ヶー一-龥]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


def is_probably_english(word: str) -> bool:
    return bool(_LATIN_LETTER_RE.search(word)) and not _JAPANESE_SCRIPT_RE.search(word)


def _lookup_english_entries(word: str) -> list[dict]:
    """Stub: English words currently get no gloss at all rather than a
    doomed JMDict query (JMDict has no English headwords to match against).
    This is the seam for a real English dictionary lookup later — same
    signature/return shape as _lookup_entries, and gloss_lookups.source
    already marks which rows went through this path so a real
    implementation can find and re-process exactly them."""
    return []

_jam_local = threading.local()


def _get_jamdict() -> Jamdict:
    """One Jamdict instance per thread, not a shared module-level singleton.

    FastAPI runs sync endpoints in a worker thread pool, and Jamdict wraps
    a sqlite3 connection that's only safe to use from the thread that
    created it — a shared singleton would crash any request handled by a
    different thread.
    """
    jam = getattr(_jam_local, "instance", None)
    if jam is None:
        jam = Jamdict()
        _jam_local.instance = jam
    return jam


def _serialize_senses(entry) -> list[dict]:
    """The {pos, misc, field, gloss} shape both jamdict entry serializers
    (this file's per-token lookup and the ad-hoc search box) build from an
    entry's senses — English glosses only, since that's the only language
    this app shows."""
    return [
        {
            "pos": s.pos,
            "misc": s.misc,
            "field": s.field,
            "gloss": [g.text for g in s.gloss if g.lang == "eng"],
        }
        for s in entry.senses
    ]


def _lookup_entries(lookup_form: str, reading_hiragana: str) -> list[dict]:
    jam = _get_jamdict()
    # Only result.entries is used, so the per-character (KanjiDic) and
    # name (JMnedict) lookups are skipped, as in search_jmdict.
    result = jam.lookup(lookup_form, lookup_chars=False, lookup_ne=False)
    scored_entries = []
    for e in result.entries:
        matching_kana = [
            k
            for k in e.kana_forms
            if k.text == reading_hiragana and (not k.restr or lookup_form in k.restr)
        ]
        if not matching_kana:
            continue
        has_priority = any(k.pri for k in e.kanji_forms) or any(k.pri for k in matching_kana)
        scored_entries.append(
            (
                not has_priority,  # False (has priority) sorts before True
                {
                    "idseq": e.idseq,
                    "kanji_forms": [{"text": k.text, "pri": k.pri} for k in e.kanji_forms],
                    "senses": _serialize_senses(e),
                },
            )
        )
    # Stable sort: entries JMDict marks as common (ichi1/news1/etc.) first,
    # ties broken by JMDict's own (idseq) order.
    scored_entries.sort(key=lambda pair: pair[0])
    return [entry for _, entry in scored_entries]


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
    unlike _lookup_entries, this isn't scoped to a single token's reading
    (there's no token context to key a match off of here), so every entry
    whose headword contains `query` is returned (kana_forms included so each
    entry's own reading(s) stay visible to the user), ranked exact match
    first, then prefix, then suffix, then substring.

    Exact matches are never capped — there's usually only a handful, and
    they're what the user is most likely looking for. The looser tiers
    (prefix/suffix/substring) are each capped independently at
    `max_results_per_tier`, so a broad query doesn't bury the closer matches
    under a wall of loosely-related compounds.

    Not cached in gloss_lookups: this is a manual exploration tool, not part
    of the per-document tokenization/gloss pipeline, so there's no token to
    link a cache row to and no reuse to expect across distinct pasted-in
    queries.
    """
    query = query.strip()
    if not query:
        return []

    jam = _get_jamdict()
    # lookup_chars/lookup_ne pull in per-character dictionary and
    # name-entity data we never read (only result.entries is used below) —
    # for a common character, that extra work costs *seconds* on a query
    # that would otherwise take a fraction of one, so it's disabled here.
    result = jam.lookup(f"%{query}%", lookup_chars=False, lookup_ne=False)

    # Rank first using only the cheap fields (headword text), before paying
    # for the senses/gloss extraction below — a common single-character
    # query can match well over a thousand entries, and only a handful of
    # those ever get serialized.
    scored = []
    for e in result.entries:
        has_priority = any(k.pri for k in e.kanji_forms) or any(k.pri for k in e.kana_forms)
        scored.append(((_match_tier(query, e), not has_priority), e))
    scored.sort(key=lambda pair: pair[0])

    selected = []
    tier_counts = {_PREFIX: 0, _SUFFIX: 0, _SUBSTRING: 0}
    for (tier, _priority_key), e in scored:
        if tier in tier_counts:
            if tier_counts[tier] >= max_results_per_tier:
                continue
            tier_counts[tier] += 1
        selected.append(e)
        if len(selected) >= _SEARCH_RESULT_LIMIT:
            break

    return [
        {
            "idseq": e.idseq,
            "kanji_forms": [k.text for k in e.kanji_forms],
            "kana_forms": [k.text for k in e.kana_forms],
            "senses": _serialize_senses(e),
        }
        for e in selected
    ]


# Sudachi's major part-of-speech category -> the JMDict part-of-speech
# strings (as jamdict expands them) that indicate a sense is being used the
# same way. Built from the actual vocabulary on both sides seen across a
# real document's cached glosses, not guessed — jamdict only exposes
# expanded English descriptions, not JMDict's raw 2-4 letter codes, so this
# matches on those strings directly.
_SUDACHI_TO_JMDICT_POS: dict[str, frozenset[str]] = {
    "名詞": frozenset(
        {
            "noun (common) (futsuumeishi)",
            "noun or participle which takes the aux. verb suru",
            "noun, used as a prefix",
            "noun, used as a suffix",
            "nouns which may take the genitive case particle 'no'",
            "numeric",
            "counter",
        }
    ),
    "動詞": frozenset(
        {
            "Godan verb - Iku/Yuku special class",
            "Godan verb with 'ku' ending",
            "Godan verb with 'mu' ending",
            "Godan verb with 'ru' ending",
            "Godan verb with 'su' ending",
            "Godan verb with 'u' ending",
            "Ichidan verb",
            "Kuru verb - special class",
            "intransitive verb",
            "transitive verb",
        }
    ),
    "形容詞": frozenset({"adjective (keiyoushi)", "auxiliary adjective"}),
    "形状詞": frozenset({"adjectival nouns or quasi-adjectives (keiyodoshi)"}),
    "副詞": frozenset({"adverb (fukushi)"}),
    "助詞": frozenset({"particle"}),
    "助動詞": frozenset({"auxiliary verb", "auxiliary", "copula"}),
    "接続詞": frozenset({"conjunction"}),
    "感動詞": frozenset({"interjection (kandoushi)"}),
    "代名詞": frozenset({"pronoun"}),
    "連体詞": frozenset({"pre-noun adjectival (rentaishi)"}),
    "接頭辞": frozenset({"prefix", "noun, used as a prefix"}),
    "接尾辞": frozenset({"suffix", "noun, used as a suffix", "counter"}),
}


def _sense_matches_pos(sense_pos: list[str], sudachi_major: str) -> bool:
    wanted = _SUDACHI_TO_JMDICT_POS.get(sudachi_major)
    return bool(wanted) and any(p in wanted for p in sense_pos)


def rank_senses(entries: list[dict], sudachi_major: str) -> list[dict]:
    """Flatten entries' senses into one list ranked for this specific
    token's grammatical role: senses whose own JMDict part-of-speech
    matches the token's actual Sudachi part-of-speech come first, then
    senses from an entry JMDict marks common, then JMDict's own order.
    Each returned sense carries its source entry's idseq.

    This is a display-time hint, not a claim about which exact sense a
    token means — a single JMDict entry routinely mixes senses tagged with
    different parts of speech (e.g. one entry for 空 has both a plain-noun
    sense and a 'nouns which may take の' sense), and this just surfaces
    the more grammatically-plausible ones first instead of leaving them in
    whatever order JMDict happens to list them.
    """
    scored = []
    for order, entry in enumerate(entries):
        has_priority = any(k["pri"] for k in entry["kanji_forms"])
        for sense in entry["senses"]:
            matches = _sense_matches_pos(sense["pos"], sudachi_major)
            scored.append(
                (
                    (not matches, not has_priority, order),
                    {**sense, "entry_idseq": entry["idseq"]},
                )
            )
    scored.sort(key=lambda pair: pair[0])
    return [sense for _, sense in scored]


def is_lexical(part_of_speech) -> bool:
    """False for punctuation and whitespace."""
    return part_of_speech[0] not in _SKIP_POS_MAJOR


def is_glossable(part_of_speech, has_conflicts: bool) -> bool:
    """Whether a token gets a gloss: every lexical token, plus any token with
    reading conflicts whatever its part of speech."""
    return has_conflicts or is_lexical(part_of_speech)


# A gloss_lookups cache key: (lookup_form, reading).
GlossKey = tuple[str, str]


def citation_key(normalized_form: str) -> GlossKey:
    """The cache key a token is glossed under unless a reading was picked for
    it: its normalized form and that form's own citation reading."""
    # The citation form's own reading, not the token's reading_katakana —
    # JMDict keys entries by citation reading (e.g. 揃える -> そろえる), and
    # an inflected surface's reading (揃え -> そろえ) won't match it.
    # mixed_reading (not a blind to_hiragana) because JMDict keeps katakana
    # loanword portions as katakana in its own kana_forms (無理ゲー ->
    # むりゲー, not むりげー).
    return (normalized_form, mixed_reading(normalized_form))


def gloss_key(record: TokenRecord) -> Optional[GlossKey]:
    """The cache key a newly tokenized token is glossed under, or None if it
    doesn't get a gloss."""
    if not is_glossable(record.part_of_speech, bool(record.conflict_options)):
        return None
    # For a flagged token, this is also the key of the default option
    # create_conflicts selects.
    return citation_key(record.normalized_form)


@dataclass
class GlossPlan:
    """Glosses for a set of cache keys: the ids of rows already cached, and
    newly computed (entries, source) for the rest, not yet written."""

    cached_ids: dict[GlossKey, int]
    new_rows: dict[GlossKey, tuple[object, str]]


def _cached_rows(conn, keys, *, with_entries: bool = False) -> dict:
    """The cached gloss_lookups rows for these keys, by key. Entries are only
    fetched when asked for — they're the bulk of each row."""
    if not keys:
        return {}
    forms, readings = zip(*keys)
    columns = "id, lookup_form, reading, entries, source" if with_entries else "id, lookup_form, reading"
    rows = conn.execute(
        text(
            f"""
            SELECT {columns}
            FROM gloss_lookups
            JOIN unnest(CAST(:forms AS text[]), CAST(:readings AS text[])) AS k(lookup_form, reading)
                USING (lookup_form, reading)
            """
        ),
        {"forms": list(forms), "readings": list(readings)},
    )
    return {(row.lookup_form, row.reading): row for row in rows}


def _lookup(lookup_form: str, reading: str, alt_lookup_form: Optional[str] = None) -> tuple[object, str]:
    """(entries, source) for one key, from the English stub or JMDict, trying
    alt_lookup_form too when lookup_form has no entry."""
    if is_probably_english(lookup_form):
        return _lookup_english_entries(lookup_form), "english_stub"
    found = _lookup_entries(lookup_form, reading)
    # normalized_form and dictionary_form can each be the one JMDict actually
    # has registered, depending on the word: 挟める has no JMDict headword of
    # its own (normalized_form 挟む does); さり気ない's normalized_form
    # さり気無い isn't JMDict's registered kanji spelling, though its
    # dictionary_form さり気ない is. Neither form is reliably "more correct",
    # so both get tried.
    if not found and alt_lookup_form and alt_lookup_form != lookup_form:
        found = _lookup_entries(alt_lookup_form, reading)
    return found, "jmdict"


def _add_composites(conn, keys: list[GlossKey], new_rows: dict[GlossKey, tuple[object, str]]) -> None:
    """For each key — a word with no JMDict entry of its own — replace its
    empty result in new_rows with a gloss built from its SplitMode.A pieces,
    if any piece has real content: 勝利の女神, which Sudachi's C-split merges
    into one token with no JMDict headword, decomposes into 勝利/の/女神,
    each of which does have one. Uncached pieces are added to new_rows too,
    so they're cached like any other lookup."""
    decompositions = {
        key: [
            (surface, mixed_reading(surface), pos)
            for surface, _reading_katakana, pos in a_split_decomposition(key[0])
            if is_lexical(pos)
        ]
        for key in keys
    }
    piece_keys = {(surface, reading) for pieces in decompositions.values() for surface, reading, _ in pieces}
    cached = {
        key: (row.entries, row.source)
        for key, row in _cached_rows(conn, piece_keys - new_rows.keys(), with_entries=True).items()
    }
    for piece_key in piece_keys - new_rows.keys() - cached.keys():
        # No alternate spelling or compound fallback for a piece, keeping
        # this to a single level of decomposition.
        new_rows[piece_key] = _lookup(*piece_key)

    for key, pieces in decompositions.items():
        result_pieces = []
        for surface, reading, pos in pieces:
            entries, source = cached.get((surface, reading)) or new_rows[(surface, reading)]
            result_pieces.append(
                {
                    "surface": surface,
                    "reading": reading,
                    "senses": rank_senses(entries, pos[0]) if source in ("jmdict", "english_stub") else [],
                    "ambiguous_readings": sorted({to_hiragana(r) for r in heteronym_readings(surface, pos)} - {reading}),
                }
            )
        if any(p["senses"] for p in result_pieces):
            new_rows[key] = ({"pieces": result_pieces}, "composite")


def plan_glosses(conn, requests: Iterable[tuple[GlossKey, Optional[str]]]) -> GlossPlan:
    """Resolve each requested key against the gloss cache and compute every
    miss (from JMDict, the English stub, or the compound fallback), without
    writing anything. Each request pairs a key with an alternate spelling to
    try when the key's own lookup_form has no JMDict entry; the first one
    given for a key is used."""
    alternates: dict[GlossKey, Optional[str]] = {}
    for key, alt in requests:
        alternates.setdefault(key, alt)
    cached_ids = {key: row.id for key, row in _cached_rows(conn, alternates).items()}
    new_rows = {key: _lookup(*key, alt) for key, alt in alternates.items() if key not in cached_ids}
    _add_composites(conn, [key for key, (entries, source) in new_rows.items() if source == "jmdict" and not entries], new_rows)
    return GlossPlan(cached_ids, new_rows)


def store_glosses(conn, plan: GlossPlan) -> dict[GlossKey, int]:
    """Insert the plan's newly computed rows, and return every planned key's
    gloss_lookups id."""
    ids = dict(plan.cached_ids)
    if not plan.new_rows:
        return ids
    # Sorted, so two transactions inserting overlapping keys lock them in the
    # same order and can't deadlock.
    rows = [
        {"lookup_form": form, "reading": reading, "entries": entries, "source": source}
        for (form, reading), (entries, source) in sorted(plan.new_rows.items())
    ]
    # A no-op update rather than DO NOTHING, so a row another transaction
    # inserted first still comes back from RETURNING.
    inserted = conn.execute(
        text(
            """
            INSERT INTO gloss_lookups (lookup_form, reading, entries, source)
            SELECT lookup_form, reading, entries, source
            FROM jsonb_to_recordset(CAST(:rows AS JSONB))
                AS r(lookup_form text, reading text, entries jsonb, source text)
            ON CONFLICT (lookup_form, reading) DO UPDATE
                SET lookup_form = EXCLUDED.lookup_form
            RETURNING id, lookup_form, reading
            """
        ),
        {"rows": json.dumps(rows)},
    )
    ids.update({(row.lookup_form, row.reading): row.id for row in inserted})
    return ids


def get_or_create_gloss_lookup(conn, lookup_form: str, reading: str, *, alt_lookup_form: Optional[str] = None) -> int:
    """The gloss_lookups row id for (lookup_form, reading), computing and
    caching it first if it isn't cached yet. alt_lookup_form is a second
    spelling to try when lookup_form has no JMDict entry."""
    key = (lookup_form, reading)
    return store_glosses(conn, plan_glosses(conn, [(key, alt_lookup_form)]))[key]


def attach_glosses(conn, document_id: int) -> None:
    """Look up (or reuse cached) JMDict glosses for every token in a document
    that should have one but has no gloss_lookups row linked yet, and link it.

    Deliberately only ever touches tokens with gloss_lookup_id IS NULL —
    this has to be a pure gap-filler, never a reassignment pass. A token
    can have a resolved reading that's not Sudachi's own default (a
    heteronym pick, or a user's own correction via `conflicts`), and this
    runs again any time a fetch finds even one other token still missing a
    link — if it touched already-linked tokens too, it would silently
    overwrite a resolved reading's gloss with the generic default every
    time that happens, discarding a correction that's still sitting right
    there in `conflicts`.
    """
    unlinked = conn.execute(
        text(
            """
            SELECT t.id, t.normalized_form, t.dictionary_form, t.part_of_speech,
                   COALESCE(c.value ->> 'citation_reading', c.value ->> 'reading') AS selected_reading
            FROM tokens t
            LEFT JOIN conflicts c ON c.token_id = t.id AND c.selected
            WHERE t.document_id = :document_id AND t.gloss_lookup_id IS NULL
            ORDER BY t.position
            """
        ),
        {"document_id": document_id},
    ).all()

    keys: dict[int, GlossKey] = {}
    requests = []
    for row in unlinked:
        if row.selected_reading is not None:
            # A token with a selected reading recorded (a resolved pick, or a
            # user's own correction) is glossed under THAT reading, not
            # Sudachi's default — otherwise a real correction silently
            # reverts the moment this runs again for any reason.
            key = (row.normalized_form, row.selected_reading)
        elif is_lexical(row.part_of_speech):
            key = citation_key(row.normalized_form)
        else:
            continue
        keys[row.id] = key
        requests.append((key, row.dictionary_form))
    if not keys:
        return

    ids = store_glosses(conn, plan_glosses(conn, requests))
    conn.execute(
        text(
            """
            UPDATE tokens t
            SET gloss_lookup_id = v.gloss_lookup_id
            FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS v(id int, gloss_lookup_id int)
            WHERE t.id = v.id AND t.gloss_lookup_id IS NULL
            """
        ),
        {"rows": json.dumps([{"id": token_id, "gloss_lookup_id": ids[key]} for token_id, key in keys.items()])},
    )
