"""JMDict-backed gloss lookup, run as a second pass after furigana tokenization.

Cached per (lookup_form, reading) pair in `gloss_lookups` — the same word
recurring across a document (or across documents) is only looked up once.
JMDict lookups run ~20ms each and don't benefit from being repeated in the
same process, so this pass is deliberately synchronous and run once per
unique word rather than once per token occurrence.

Lookups are keyed off normalized_form, not Sudachi's dictionary_form.
dictionary_form is the grammatically precise lemma for whatever conjugation
paradigm actually matched (e.g. 挟める, the lexicalized potential of 挟む),
but JMDict often doesn't carry that paradigm as its own headword the way
Sudachi's own dictionary does. normalized_form collapses exactly this kind
of derived/variant spelling back to the form JMDict actually has an entry
for. Tested against a batch of genuine potential forms (書ける->書く,
読める->読む, ...) and independent -める verbs that only superficially
resemble potentials (決める, 集める, 込める, ...): normalization only ever
fires for true derivational/orthographic variants — independent verbs keep
normalized_form == dictionary_form, it never substitutes an unrelated word.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Optional

from jamdict import Jamdict
from sqlalchemy import text

from app.tokenization import a_split_decomposition, heteronym_readings, mixed_reading, to_hiragana

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


def _lookup_entries(lookup_form: str, reading_hiragana: str) -> list[dict]:
    jam = _get_jamdict()
    result = jam.lookup(lookup_form)
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
            "senses": [
                {
                    "pos": s.pos,
                    "misc": s.misc,
                    "field": s.field,
                    "gloss": [g.text for g in s.gloss if g.lang == "eng"],
                }
                for s in e.senses
            ],
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


def needs_gloss_pass(conn, document_id: int) -> bool:
    """True if this document has lexical tokens that were never linked to a
    gloss lookup (either newly tokenized, or tokenized before gloss support
    existed)."""

    return conn.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM tokens
                WHERE document_id = :document_id
                  AND gloss_lookup_id IS NULL
                  AND NOT (part_of_speech ->> 0 = ANY(:skip_pos))
            )
            """
        ),
        {"document_id": document_id, "skip_pos": list(_SKIP_POS_MAJOR)},
    ).scalar_one()


def _lookup_composite(conn, word: str) -> Optional[dict]:
    """Fallback for a word with no JMDict entry of its own: decompose it
    with SplitMode.A and gloss each piece independently (勝利の女神, which
    Sudachi's C-split merges into one token with no JMDict headword, decomposes
    into 勝利/の/女神 — each of which does have one). Returns None if the word
    doesn't decompose, or decomposes but not a single piece resolves to real
    content (in which case this fallback is no better than the direct miss).

    Piece lookups go through get_or_create_gloss_lookup too (same caching,
    same English-stub routing), but with allow_composite=False — a piece is
    deliberately not allowed to recurse into its own composite fallback, to
    keep this a single level of decomposition rather than arbitrarily deep.
    """
    pieces = a_split_decomposition(word)
    if not pieces:
        return None

    result_pieces = []
    for surface, _reading_katakana, pos in pieces:
        if pos[0] in _SKIP_POS_MAJOR:
            continue

        reading = mixed_reading(surface)
        piece_id = get_or_create_gloss_lookup(conn, surface, reading, allow_composite=False)
        piece_entries, piece_source = conn.execute(
            text("SELECT entries, source FROM gloss_lookups WHERE id = :id"),
            {"id": piece_id},
        ).one()

        senses = rank_senses(piece_entries, pos[0]) if piece_source in ("jmdict", "english_stub") else []
        alt_readings = sorted({to_hiragana(r) for r in heteronym_readings(surface, pos)} - {reading})

        result_pieces.append(
            {
                "surface": surface,
                "reading": reading,
                "senses": senses,
                "ambiguous_readings": alt_readings,
            }
        )

    if not any(p["senses"] for p in result_pieces):
        return None

    return {"pieces": result_pieces}


def get_or_create_gloss_lookup(
    conn,
    lookup_form: str,
    reading: str,
    *,
    allow_composite: bool = True,
    alt_lookup_form: Optional[str] = None,
) -> int:
    """The gloss_lookups row id for (lookup_form, reading), fetching from
    JMDict (or routing to the English stub, or the composite fallback) and
    caching it if this exact pair hasn't been looked up before. Shared by
    the bulk per-document pass, a one-off re-lookup after a user corrects a
    token's reading, and (with allow_composite=False) composite piece
    lookups themselves.

    alt_lookup_form is a second spelling to try (same reading) when the
    primary one comes back empty — normalized_form and dictionary_form can
    each be the one JMDict actually has registered, depending on the word:
    挟める has no JMDict headword of its own (normalized_form 挟む does);
    さり気ない's normalized_form さり気無い isn't JMDict's registered kanji
    spelling even though dictionary_form さり気ない (identical to the
    surface here) is exactly the one JMDict lists. Neither form is reliably
    "more correct" in general, so both get tried rather than committing to
    one and silently missing the other's cases.
    """

    existing = conn.execute(
        text(
            """
            SELECT id FROM gloss_lookups
            WHERE lookup_form = :lookup_form AND reading = :reading
            """
        ),
        {"lookup_form": lookup_form, "reading": reading},
    ).one_or_none()

    if existing is not None:
        return existing.id

    if is_probably_english(lookup_form):
        entries: object = _lookup_english_entries(lookup_form)
        source = "english_stub"
    else:
        found = _lookup_entries(lookup_form, reading)
        if not found and alt_lookup_form and alt_lookup_form != lookup_form:
            found = _lookup_entries(alt_lookup_form, reading)
        composite = _lookup_composite(conn, lookup_form) if not found and allow_composite else None
        if composite is not None:
            entries, source = composite, "composite"
        else:
            entries, source = found, "jmdict"

    return conn.execute(
        text(
            """
            INSERT INTO gloss_lookups (lookup_form, reading, entries, source)
            VALUES (:lookup_form, :reading, CAST(:entries AS JSONB), :source)
            ON CONFLICT (lookup_form, reading) DO UPDATE
                SET lookup_form = EXCLUDED.lookup_form
            RETURNING id
            """
        ),
        {
            "lookup_form": lookup_form,
            "reading": reading,
            "entries": json.dumps(entries),
            "source": source,
        },
    ).scalar_one()


def attach_glosses(conn, document_id: int) -> None:
    """Look up (or reuse cached) JMDict glosses for every lexical token in a
    document that doesn't have one linked yet, and link it to its
    gloss_lookups row.

    Deliberately only ever touches tokens with gloss_lookup_id IS NULL —
    this has to be a pure gap-filler, never a reassignment pass. A token
    can have a resolved reading that's not Sudachi's own default (a
    heteronym pick, or a user's own correction via `conflicts`), and this
    runs again any time needs_gloss_pass finds even one other token still
    missing a link — if it touched already-linked tokens too, it would
    silently overwrite a resolved reading's gloss with the generic default
    every time that happens, discarding a correction that's still sitting
    right there in `conflicts`.
    """

    # Tokens that already have a selected reading recorded (a resolved
    # heteronym/no_kana_anchor pick, or a user's own correction) but lost
    # their gloss link some other way should get glossed under THAT
    # reading, not Sudachi's own default — otherwise a real correction
    # silently reverts the moment this function runs again for any reason.
    selected_readings = conn.execute(
        text(
            """
            SELECT t.id AS token_id, t.normalized_form, t.dictionary_form,
                   COALESCE(c.value ->> 'citation_reading', c.value ->> 'reading') AS reading
            FROM tokens t
            JOIN conflicts c ON c.token_id = t.id AND c.selected
            WHERE t.document_id = :document_id AND t.gloss_lookup_id IS NULL
            """
        ),
        {"document_id": document_id},
    ).all()

    for token_id, normalized_form, dictionary_form, reading in selected_readings:
        gloss_lookup_id = get_or_create_gloss_lookup(
            conn, normalized_form, reading, alt_lookup_form=dictionary_form
        )
        conn.execute(
            text("UPDATE tokens SET gloss_lookup_id = :gloss_lookup_id WHERE id = :token_id"),
            {"gloss_lookup_id": gloss_lookup_id, "token_id": token_id},
        )

    normalized_forms = conn.execute(
        text(
            """
            SELECT normalized_form, (array_agg(dictionary_form))[1] AS dictionary_form
            FROM tokens
            WHERE document_id = :document_id
              AND gloss_lookup_id IS NULL
              AND NOT (part_of_speech ->> 0 = ANY(:skip_pos))
            GROUP BY normalized_form
            """
        ),
        {"document_id": document_id, "skip_pos": list(_SKIP_POS_MAJOR)},
    ).all()

    for normalized_form, dictionary_form in normalized_forms:
        # The citation form's own reading, not any inflected token's
        # reading_katakana — JMDict keys entries by citation reading (e.g.
        # 揃える -> そろえる), and an inflected surface's reading (揃え ->
        # そろえ) won't match it. mixed_reading (not a blind to_hiragana)
        # because JMDict keeps katakana loanword portions as katakana in
        # its own kana_forms (無理ゲー -> むりゲー, not むりげー).
        reading = mixed_reading(normalized_form)
        gloss_lookup_id = get_or_create_gloss_lookup(
            conn, normalized_form, reading, alt_lookup_form=dictionary_form
        )

        conn.execute(
            text(
                """
                UPDATE tokens
                SET gloss_lookup_id = :gloss_lookup_id
                WHERE document_id = :document_id
                  AND normalized_form = :normalized_form
                  AND gloss_lookup_id IS NULL
                """
            ),
            {
                "gloss_lookup_id": gloss_lookup_id,
                "document_id": document_id,
                "normalized_form": normalized_form,
            },
        )
