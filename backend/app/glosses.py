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
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from jamdict import Jamdict
from sqlalchemy import text

from app.grammar import grammar_note, is_helper_verb
from app.tokenization import (
    TokenRecord,
    a_split_decomposition,
    citation_reading,
    conflict_option_value,
    conjugation_family,
    conjugation_type_of,
    furigana_spans_for_reading,
    headword_reading,
    heteronym_readings,
    mixed_reading,
    project_citation_reading,
    to_hiragana,
    to_katakana,
)

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


def get_jamdict() -> Jamdict:
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
    jam = get_jamdict()
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
        has_priority = any(k.pri for k in e.kanji_forms) or any(
            k.pri for k in matching_kana
        )
        scored_entries.append(
            (
                not has_priority,  # False (has priority) sorts before True
                {
                    "idseq": e.idseq,
                    "kanji_forms": [
                        {"text": k.text, "pri": k.pri} for k in e.kanji_forms
                    ],
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

    jam = get_jamdict()
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
        has_priority = any(k.pri for k in e.kanji_forms) or any(
            k.pri for k in e.kana_forms
        )
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
# matches on those strings directly. 動詞 isn't here: see _is_verb_sense.
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


# JMDict tags a verb's sense with its conjugation class, of which there are
# dozens (archaic Nidan and Yodan ones included), and often with its
# transitivity as well, but not always: する's "to do" carries only "suru
# verb - included". So for 動詞 every tag naming a verb counts, but these.
_VERB_RE = re.compile(r"\bverb\b")
_NOT_VERB_SENSES = frozenset(
    {
        "auxiliary verb",
        "noun or participle which takes the aux. verb suru",
        "noun or verb acting prenominally",
    }
)


def _is_verb_sense(pos: str) -> bool:
    return bool(_VERB_RE.search(pos)) and pos not in _NOT_VERB_SENSES


def _sense_matches_pos(sense_pos: list[str], sudachi_major: str) -> bool:
    if sudachi_major == "動詞":
        return any(_is_verb_sense(p) for p in sense_pos)
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


def get_raw_conn() -> sqlite3.Connection:
    """A thread-local connection straight to jamdict's sqlite database, for
    queries too frequent to pay for Jamdict building whole entries."""
    conn = getattr(_jam_local, "raw_conn", None)
    if conn is None:
        conn = sqlite3.connect(get_jamdict().db_file)
        _jam_local.raw_conn = conn
    return conn


@dataclass(frozen=True)
class KanjidicRow:
    """One kanji's KANJIDIC2 columns, as the database stores them."""

    # Both as text; None for a kanji without it.
    grade: str | None
    freq: str | None
    classical_radical: str | None
    # (r_type, value) pairs, on and kun only.
    readings: list[list[str]]
    meanings: list[str]


def _grouped(conn, sql: str, ids: dict[int, str]) -> dict[str, list]:
    marks = ",".join("?" * len(ids))
    found: dict[str, list] = {}
    for cid, *rest in conn.execute(sql.format(marks=marks), list(ids)):
        found.setdefault(ids[cid], []).append(rest[0] if len(rest) == 1 else rest)
    return found


def kanjidic_rows(literals: Iterable[str]) -> dict[str, KanjidicRow]:
    """KANJIDIC2's row for each of `literals` it has an entry for, in as few
    queries as the number of tables involved rather than one per kanji."""
    literals = sorted(set(literals))
    if not literals:
        return {}
    conn = get_raw_conn()
    marks = ",".join("?" * len(literals))
    rows = conn.execute(
        f"SELECT ID, literal, grade, freq FROM character WHERE literal IN ({marks})",
        literals,
    ).fetchall()
    ids = {id_: literal for id_, literal, _, _ in rows}
    classical = _grouped(
        conn,
        "SELECT cid, value FROM radical "
        "WHERE rad_type = 'classical' AND cid IN ({marks})",
        ids,
    )
    # rowid order is KANJIDIC2's own order, which the readings and meanings
    # are shown in.
    readings = _grouped(
        conn,
        "SELECT g.cid, r.r_type, r.value FROM rm_group g "
        "JOIN reading r ON r.gid = g.ID "
        "WHERE g.cid IN ({marks}) AND r.r_type IN ('ja_on', 'ja_kun') "
        "ORDER BY g.ID, r.rowid",
        ids,
    )
    meanings = _grouped(
        conn,
        "SELECT g.cid, m.value FROM rm_group g "
        "JOIN meaning m ON m.gid = g.ID "
        # KANJIDIC2 also carries French, Spanish and Portuguese meanings.
        "WHERE g.cid IN ({marks}) AND m.m_lang = '' "
        "ORDER BY g.ID, m.rowid",
        ids,
    )
    return {
        literal: KanjidicRow(
            grade,
            freq,
            classical.get(literal, [None])[0],
            readings.get(literal, []),
            meanings.get(literal, []),
        )
        for _, literal, grade, freq in rows
    }


def _prefix_upper_bound(s: str) -> str:
    """The smallest string that sorts after every string starting with `s`."""
    return s[:-1] + chr(ord(s[-1]) + 1)


def phrase_prefix_state(candidate: str) -> tuple[bool, bool]:
    """Whether `candidate` is a JMDict headword, and whether a longer headword
    starts with it."""
    conn = get_raw_conn()
    # A range scan rather than LIKE 'x%', which SQLite only runs as one for
    # ASCII: on Japanese text it was ~1000x slower.
    hi = _prefix_upper_bound(candidate)
    is_exact = (
        conn.execute(
            "SELECT 1 FROM Kanji WHERE text = ? UNION ALL SELECT 1 FROM Kana WHERE text = ? LIMIT 1",
            (candidate, candidate),
        ).fetchone()
        is not None
    )
    has_longer = (
        conn.execute(
            "SELECT 1 FROM Kanji WHERE text > ? AND text < ? "
            "UNION ALL SELECT 1 FROM Kana WHERE text > ? AND text < ? LIMIT 1",
            (candidate, hi, candidate, hi),
        ).fetchone()
        is not None
    )
    return is_exact, has_longer


def is_headword(text: str) -> bool:
    """Whether JMDict has `text` as a headword, written either way."""
    return phrase_prefix_state(text)[0]


def _scored_headword_kana(text: str) -> list[tuple[bool, int, str, str]]:
    """Every kana form JMDict lists for the entries with `text` as a headword,
    as (not common, entry order, kana form, its entry's conjugation type as
    _jmdict_conjugation_class gives it), so sorting puts common readings
    first."""
    jam = get_jamdict()
    result = jam.lookup(text, lookup_chars=False, lookup_ne=False)
    scored: list[tuple[bool, int, str, str]] = []
    for order, e in enumerate(result.entries):
        matches_kanji = any(k.text == text for k in e.kanji_forms)
        matches_kana = any(k.text == text for k in e.kana_forms)
        if not matches_kanji and not matches_kana:
            continue
        conjugation = _jmdict_conjugation_class(
            [pos for sense in e.senses for pos in sense.pos]
        )
        if matches_kana and not matches_kanji:
            candidates = [k for k in e.kana_forms if k.text == text]
        else:
            candidates = [
                k for k in e.kana_forms if not k.restr or text in k.restr
            ] or e.kana_forms
        for k in candidates:
            has_priority = bool(k.pri) or any(
                kj.pri for kj in e.kanji_forms if kj.text == text
            )
            scored.append((not has_priority, order, k.text, conjugation))
    return scored


def resolve_phrase_reading(surface: str) -> str | None:
    """The hiragana reading JMDict gives `surface` as a headword, common ones
    first, or None if it isn't one. It can differ from its tokens' readings:
    期 alone reads き, but この期に及んで has ご."""
    scored = _scored_headword_kana(surface)
    if not scored:
        return None
    _, _, kana_text, _ = min(scored, key=lambda row: row[:2])
    return to_hiragana(kana_text)


def search_readings(dictionary_form: str) -> dict[str, str]:
    """Every distinct katakana reading JMDict lists for `dictionary_form` as
    a headword, in any part of speech, common ones first, each with the
    conjugation type of the entry it's listed under (see
    _jmdict_conjugation_class). Broader than heteronym_readings, which keeps
    to the token's part of speech and so misses 期 read ご."""
    scored = sorted(_scored_headword_kana(dictionary_form), key=lambda row: row[:2])
    readings: dict[str, str] = {}
    for _, _, kana_text, conjugation in scored:
        readings.setdefault(to_katakana(kana_text), conjugation)
    return readings


def _jmdict_conjugation_class(part_of_speech: list[str]) -> str:
    """The conjugation tag, in Sudachi's naming, that JMDict's `part_of_speech`
    glosses for a verb: '五段' for godan, '下一段' for ichidan, '' for anything
    else (including the irregular verbs)."""
    for pos in part_of_speech:
        # jamdict spells out JMDict's v5* and v1 codes, each starting so.
        if pos.startswith("Godan verb"):
            return "五段"
        if pos.startswith("Ichidan verb"):
            return "下一段"
    return ""


def alternate_reading_options(
    surface: str,
    reading_katakana: str,
    dictionary_form: str,
    normalized_form: str,
) -> list[dict]:
    """Every other reading JMDict has for `dictionary_form`, as reading
    options for an occurrence of it on `surface`, which can be inflected."""
    dict_form_citation = citation_reading(dictionary_form)
    conjugation_type = conjugation_type_of(normalized_form)
    # Written as its dictionary form, the occurrence can be read as another
    # of the word's readings (方 as かた, not ほう), so its own is the one to
    # leave out. Inflected, its own is the dictionary form's, which
    # projecting doesn't always reproduce (美しく isn't read うつくしい).
    own_citation = (
        reading_katakana if surface == dictionary_form else dict_form_citation
    )

    needs_projection = (
        surface != dictionary_form and reading_katakana != dict_form_citation
    )
    family = conjugation_family(conjugation_type)

    options = []
    for alt_citation, alt_conjugation in search_readings(dictionary_form).items():
        if alt_citation == own_citation:
            continue
        # The token's conjugation type is its own reading's; another reading
        # of the headword can be a different verb class (来る as きたる). Its
        # inflected ending can only be carried over from a token of the same
        # class, so any other is left out rather than offered unprojected.
        # If a missing alternate here becomes a real problem (きたる on 来た,
        # an inflected い-adjective), the fix is to generate the alternate's
        # reading from its own paradigm: a table keyed by its JMDict class
        # (alt_conjugation) and the token's Sudachi inflection form
        # (part_of_speech[5]), replacing project_citation_reading, which
        # conflicts._project_onto_member also uses.
        if needs_projection and (
            family is None or conjugation_family(alt_conjugation) != family
        ):
            continue
        alt_surface_reading = project_citation_reading(
            alt_citation, reading_katakana, dict_form_citation, alt_conjugation
        )
        alt_spans = furigana_spans_for_reading(surface, alt_surface_reading)
        options.append(
            conflict_option_value(
                to_hiragana(alt_surface_reading), alt_spans, to_hiragana(alt_citation)
            )
        )
    return options


def is_lexical(part_of_speech) -> bool:
    """False for punctuation and whitespace."""
    return part_of_speech[0] not in _SKIP_POS_MAJOR


def is_glossable(part_of_speech, has_conflicts: bool) -> bool:
    """Whether a token gets a gloss: every lexical token, plus any token with
    reading conflicts whatever its part of speech."""
    return has_conflicts or is_lexical(part_of_speech)


# A gloss_lookups cache key: (lookup_form, reading).
GlossKey = tuple[str, str]


def citation_key(normalized_form: str, dictionary_form: str) -> GlossKey:
    """The cache key a token with these forms is glossed under unless a
    reading was picked for it: its normalized form and the citation reading
    of the word it is."""
    # The citation form's reading, not the token's reading_katakana —
    # JMDict keys entries by citation reading (e.g. 揃える -> そろえる), and
    # an inflected surface's reading (揃え -> そろえ) won't match it.
    return (normalized_form, headword_reading(normalized_form, dictionary_form))


def gloss_key(record: TokenRecord) -> GlossKey | None:
    """The cache key a newly tokenized token is glossed under, or None if it
    doesn't get a gloss."""
    if not is_glossable(record.part_of_speech, bool(record.conflict_options)):
        return None
    # For a flagged token, this is also the key of the default option
    # create_conflicts selects.
    return citation_key(record.normalized_form, record.dictionary_form)


def own_gloss_key(
    normalized_form: str,
    dictionary_form: str,
    part_of_speech,
    selected_reading: str | None,
) -> GlossKey | None:
    """The gloss key for a stored token: under `selected_reading`, if a
    reading was picked, else its citation form's, or None if it isn't
    glossable."""
    if selected_reading is not None:
        return (normalized_form, selected_reading)
    if is_lexical(part_of_speech):
        return citation_key(normalized_form, dictionary_form)
    return None


@dataclass
class GlossPlan:
    """Glosses for a set of cache keys: the ids and sources of rows already
    cached, and newly computed (entries, source) for the rest, not yet
    written."""

    cached_ids: dict[GlossKey, int]
    cached_sources: dict[GlossKey, str]
    new_rows: dict[GlossKey, tuple[object, str]]

    def sources(self) -> dict[GlossKey, str]:
        """The source of every planned key's gloss, cached or new."""
        return self.cached_sources | {
            key: source for key, (_, source) in self.new_rows.items()
        }


def _cached_rows(conn, keys, *, with_entries: bool = False) -> dict:
    """The cached gloss_lookups rows for these keys, by key, with their id
    and source. Entries are only fetched when asked for — they're the bulk
    of each row."""
    if not keys:
        return {}
    forms, readings = zip(*keys)
    columns = "id, lookup_form, reading, source"
    if with_entries:
        columns += ", entries"
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


def _lookup(
    lookup_form: str, reading: str, alt_lookup_form: str | None = None
) -> tuple[object, str]:
    """(entries, source) for one key, from the English stub or JMDict, trying
    alt_lookup_form too when lookup_form has no entry. A JMDict lookup that
    finds nothing has a source of its own, "jmdict_miss", so `source` alone
    tells a found headword apart without reading `entries`."""
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
    return found, "jmdict" if found else "jmdict_miss"


def _kanji_spelling(entries, senses) -> str | None:
    """How the entry the first of `senses` comes from is usually written, if
    it's written with kanji at all (こころのこえ -> 心の声)."""
    entry = (
        next((e for e in entries if e["idseq"] == senses[0]["entry_idseq"]), None)
        if senses
        else None
    )
    return _usual_kanji_form(entry) if entry else None


def _usual_kanji_form(entry: dict) -> str | None:
    """How a JMDict entry is usually written with kanji, if it is at all: a
    form it marks common, or else the one it lists first."""
    forms = entry["kanji_forms"]
    if not forms:
        return None
    return next((form["text"] for form in forms if form["pri"]), forms[0]["text"])


def gloss_piece(
    surface: str,
    reading: str,
    key: GlossKey,
    alt_lookup_form: str | None,
    part_of_speech,
    *,
    senses_pos_major: str | None = None,
    normalized_form: str | None = None,
    flags_readings: bool = False,
) -> dict:
    """A composite gloss piece for `surface` read as `reading`, as stored:
    glossed from the lookup under `key` (with `alt_lookup_form` as its
    alternate spelling), its senses to be ranked for `part_of_speech`, a full
    Sudachi tag, or for `senses_pos_major` when the piece's role differs from
    its tag (a helper verb like the みる of 見てみる, ranked as 助動詞).
    `normalized_form` marks a grammar word, which is shown with a note
    explaining it. `flags_readings` shows the other readings its surface
    could have, for a piece whose word has no token of its own to show them.

    The lookup's entries, their ranking, the spelling that follows from it,
    the note and the other readings are all left to shown_pieces, so a change
    to any of them reaches every cached composite."""
    return {
        "surface": surface,
        "reading": reading,
        "key": list(key),
        "alt_lookup_form": alt_lookup_form,
        # The whole tag, not just the major class it's ranked by today, so a
        # ranking that reads more of it needs no migration.
        "part_of_speech": list(part_of_speech),
        "senses_pos_major": senses_pos_major,
        "normalized_form": normalized_form,
        "flags_readings": flags_readings,
    }


def piece_lookups(
    conn, composites: Iterable[dict], *, cache_only: bool = False
) -> dict[GlossKey, tuple]:
    """The (entries, source) of every lookup the pieces of `composites`,
    composite glosses' entries, are glossed from. One that isn't cached is
    looked up and cached first, so deleting a lookup's row is enough to
    refresh every composite built on it — unless `cache_only`, for a caller
    that can't write: it is left out of the result instead.
    """
    requests = [
        (tuple(piece["key"]), piece["alt_lookup_form"])
        for composite in composites
        for piece in composite["pieces"]
        if piece["key"] is not None
    ]
    if cache_only:
        return _cached_entries(conn, {key for key, _ in requests})
    return gloss_entries(conn, requests)


def piece_pos_major(piece: dict) -> str:
    """The part of speech a composite gloss piece's senses are ranked for."""
    return piece["senses_pos_major"] or piece["part_of_speech"][0]


def _ranked_senses(
    piece: dict, lookups: dict[GlossKey, tuple]
) -> tuple[list, list[dict]] | None:
    """The entries `piece`'s senses come from, and the senses ranked for its
    role, or None if its lookup isn't in `lookups`."""
    if piece["key"] is None:
        entries, source = [], None
    elif tuple(piece["key"]) in lookups:
        entries, source = lookups[tuple(piece["key"])]
    else:
        return None
    # Only a JMDict or English lookup's entries are senses: a composite's
    # are its own pieces.
    if source not in ("jmdict", "english_stub"):
        entries = []
    # A word picked for the piece is one of its lookup's entries.
    entries = picked_entries(entries, piece.get("idseq"))
    return entries, rank_senses(entries, piece_pos_major(piece))


def picked_entries(entries: list, idseq: int | None) -> list:
    """`entries`, a lookup's, as a word picked as entry `idseq` is glossed:
    that entry alone, or all of them when `idseq` is None."""
    if idseq is None:
        return entries
    return [entry for entry in entries if entry["idseq"] == idseq]


def _spelling(composite: dict, piece: dict, entries, senses) -> str:
    """How `piece` of `composite` is written when shown."""
    # A katakana word's gloss is written as the words usually are (心の声),
    # not as the katakana spells them out (こころのこえ).
    spelling = "looked_up_as" in composite and _kanji_spelling(entries, senses)
    return spelling or piece["surface"]


# A word picked for a piece of a katakana token: (piece index, the piece's
# reading when it was picked, the word's JMDict entry).
KatakanaPick = tuple[int, str, int]

# The picks of token `t` as KatakanaPick arrays, as with_picked_words takes
# them; NULL for a token with none.
KATAKANA_PICKS_SQL = """
    (
        SELECT jsonb_agg(jsonb_build_array(kp.piece, kp.reading, kp.idseq))
        FROM katakana_picks kp WHERE kp.token_id = t.id
    )
"""


def is_word_piece(piece: dict) -> bool:
    """Whether a piece of a katakana token's gloss is a word, rather than
    grammar: the pieces a card can be for, and a word picked."""
    return piece["key"] is not None and piece["normalized_form"] is None


def with_picked_words(composite: dict, picks: Iterable[KatakanaPick] | None) -> dict:
    """`composite`, a katakana token's gloss, with each piece the user picked
    a word for glossed as that word's JMDict entry alone. A pick for a piece
    that no longer has the reading it was picked for, as after the gloss was
    built again, is left out."""
    if not picks:
        return composite
    pieces = list(composite["pieces"])
    for index, reading, idseq in picks:
        if not (
            index < len(pieces)
            and is_word_piece(pieces[index])
            and pieces[index]["key"][1] == reading
        ):
            continue
        pieces[index] = {
            **pieces[index],
            # Spelled as its entry is (see _spelling), or in kana for an entry
            # with no kanji.
            "surface": reading,
            # The lookup word_options offered the entry from, so it's there.
            "key": [reading, reading],
            "alt_lookup_form": None,
            "idseq": idseq,
        }
    return {**composite, "pieces": pieces}


def piece_current_idseq(
    conn,
    composite: dict,
    picks: Iterable[KatakanaPick] | None,
    piece: int,
    lookups: dict[GlossKey, tuple] | None = None,
) -> int | None:
    """The JMDict entry piece `piece` of `composite`, a katakana token's
    gloss, is shown as given the token's `picks`: the one picked for it, or
    else the one its first sense comes from. None if it has no senses.

    `lookups` are lookups the caller already has; the piece's own is read
    only if they lack it."""
    shown = with_picked_words(composite, picks)["pieces"][piece]
    key = tuple(shown["key"])
    if lookups is None or key not in lookups:
        # Only the piece's own lookup, not the rest of the token's. A word
        # piece always has one.
        lookups = gloss_entries(conn, [(key, shown["alt_lookup_form"])])
    ranked = _ranked_senses(shown, lookups)
    # gloss_entries looks up what it's missing, so the lookup is there.
    assert ranked is not None
    _, senses = ranked
    return senses[0]["entry_idseq"] if senses else None


def word_options(conn, reading: str, lookup: tuple | None = None) -> list[dict]:
    """The words JMDict has that are read `reading` (hiragana), common ones
    first: what a piece of katakana read that way could be. Each is its
    entry's idseq, its usual spelling, and the glosses of its first sense,
    which tell apart two written alike.

    `lookup` is the (entries, source) of `reading`'s own lookup, if the
    caller already has it."""
    if lookup is None:
        key = (reading, reading)
        lookup = gloss_entries(conn, [(key, None)])[key]
    entries, source = lookup
    if source != "jmdict":
        return []
    return [
        {
            "idseq": entry["idseq"],
            # As a katakana word's piece is spelled, or in kana for a word
            # with no kanji.
            "spelling": _usual_kanji_form(entry) or reading,
            "gloss": next((s["gloss"] for s in entry["senses"] if s["gloss"]), []),
        }
        for entry in entries
    ]


def shown_spellings(
    composite: dict, lookups: dict[GlossKey, tuple]
) -> list[str] | None:
    """How each piece of `composite` is written when shown (see
    shown_pieces), or None if a piece's lookup isn't in `lookups`."""
    spellings = []
    for piece in composite["pieces"]:
        ranked = _ranked_senses(piece, lookups)
        if ranked is None:
            return None
        spellings.append(_spelling(composite, piece, *ranked))
    return spellings


def shown_pieces(composite: dict, lookups: dict[GlossKey, tuple]) -> list[dict] | None:
    """The pieces of `composite`, a composite gloss's entries, as shown, given
    the (entries, source) of their lookups (see piece_lookups): each with its
    lookup's senses ranked for its role. None if a piece's lookup isn't in
    `lookups`, as under piece_lookups' cache_only."""
    shown = []
    for piece in composite["pieces"]:
        ranked = _ranked_senses(piece, lookups)
        if ranked is None:
            return None
        entries, senses = ranked
        shown.append(
            {
                "surface": _spelling(composite, piece, entries, senses),
                "reading": piece["reading"],
                "senses": senses,
                "ambiguous_readings": _ambiguous_readings(piece),
                "is_word": is_word_piece(piece),
                "note": (
                    grammar_note(piece["normalized_form"], piece["part_of_speech"])
                    if piece["normalized_form"] is not None
                    else None
                ),
            }
        )
    return shown


def _ambiguous_readings(piece: dict) -> list[str]:
    """The hiragana readings other than its own that `piece`'s surface could
    have, if it's to flag them."""
    if not piece["flags_readings"]:
        return []
    return sorted(
        {
            to_hiragana(r)
            for r in heteronym_readings(
                piece["surface"], tuple(piece["part_of_speech"])
            )
        }
        - {piece["reading"]}
    )


def _add_composites(
    conn, keys: list[GlossKey], new_rows: dict[GlossKey, tuple[object, str]]
) -> None:
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
    piece_keys = {
        (surface, reading)
        for pieces in decompositions.values()
        for surface, reading, _ in pieces
    }
    sources = {key: source for key, (_, source) in new_rows.items()} | {
        key: row.source
        for key, row in _cached_rows(conn, piece_keys - new_rows.keys()).items()
    }
    for piece_key in piece_keys - sources.keys():
        # No alternate spelling or compound fallback for a piece, keeping
        # this to a single level of decomposition.
        new_rows[piece_key] = _lookup(*piece_key)
        sources[piece_key] = new_rows[piece_key][1]

    for key, pieces in decompositions.items():
        if any(
            sources[(surface, reading)] == "jmdict" for surface, reading, _ in pieces
        ):
            new_rows[key] = (
                {
                    "pieces": [
                        gloss_piece(
                            surface,
                            reading,
                            (surface, reading),
                            None,
                            pos,
                            flags_readings=True,
                        )
                        for surface, reading, pos in pieces
                    ]
                },
                "composite",
            )


@dataclass(frozen=True)
class GroupPart:
    """A token attached to the word a group gloss is built on."""

    dictionary_form: str
    normalized_form: str
    part_of_speech: tuple
    # Hiragana, as read on the page.
    reading: str

    @classmethod
    def of(cls, token, reading: str) -> GroupPart:
        """The part for `token`, a token or token row, read as `reading`."""
        return cls(
            token.dictionary_form,
            token.normalized_form,
            tuple(token.part_of_speech),
            reading,
        )


@dataclass(frozen=True)
class GroupGlossRequest:
    """A composite gloss for a word plus the grammar attached to it
    (欲し + てる/ん/だ/って): the word's own gloss as the first piece, then a
    piece per attached token."""

    # The word's own gloss key (a verb's citation key, or an idiom's
    # headword), and an alternate spelling to try for it.
    base_key: GlossKey
    base_alt: str | None
    base_part_of_speech: tuple
    attached: tuple[GroupPart, ...]
    # The whole group's reading, as on the page.
    reading: str

    @property
    def key(self) -> GlossKey:
        # "＋" never appears in a JMDict headword, so this can't collide with
        # a plain lookup's key. Dictionary forms keep apart groups spelled
        # the same with different grammar (ん as ぬ vs as の).
        return (
            "＋".join(
                [self.base_key[0], *(part.dictionary_form for part in self.attached)]
            ),
            self.reading,
        )


def predicate_group_request(
    members, readings: list[str], head_key: GlossKey
) -> GroupGlossRequest:
    """The gloss request for a predicate group of `members`, tokens or token
    rows read as `readings` in hiragana, with its head glossed under
    `head_key`."""
    head = members[0]
    return GroupGlossRequest(
        base_key=head_key,
        base_alt=head.dictionary_form,
        base_part_of_speech=tuple(head.part_of_speech),
        attached=tuple(
            GroupPart.of(member, reading)
            for member, reading in zip(members[1:], readings[1:])
        ),
        reading="".join(readings),
    )


def _group_pieces(
    request: GroupGlossRequest,
    found: dict[GlossKey, tuple[object, str]],
) -> list[dict]:
    """The composite pieces for `request`, with its base's (entries,
    source) from `found`."""
    return _base_pieces(request, found) + [
        _attached_piece(part) for part in request.attached
    ]


def _base_pieces(
    request: GroupGlossRequest,
    found: dict[GlossKey, tuple[object, str]],
) -> list[dict]:
    """The composite pieces for the word `request` is built on: one, or one
    per word of a base that's a composite itself."""
    entries, source = found[request.base_key]
    if source == "composite":
        # The base's words keep their own reading options on their tokens.
        return [{**piece, "flags_readings": False} for piece in entries["pieces"]]
    return [
        gloss_piece(
            request.base_key[0],
            request.base_key[1],
            request.base_key,
            request.base_alt,
            request.base_part_of_speech,
        )
    ]


def _attached_piece(part: GroupPart) -> dict:
    """The composite piece for `part`, attached to a group's word."""
    if is_helper_verb(part):
        return gloss_piece(
            part.dictionary_form,
            mixed_reading(part.dictionary_form),
            citation_key(part.normalized_form, part.dictionary_form),
            part.dictionary_form,
            part.part_of_speech,
            senses_pos_major="助動詞",
            normalized_form=part.normalized_form,
        )
    return _grammar_piece(part)


def _grammar_piece(part: GroupPart) -> dict:
    """A composite gloss piece for a grammar word, as stored: the form its
    note is worked out from, and no senses."""
    return {
        "surface": part.dictionary_form,
        "reading": part.reading,
        "key": None,
        "alt_lookup_form": None,
        "part_of_speech": list(part.part_of_speech),
        "senses_pos_major": None,
        "normalized_form": part.normalized_form,
        "flags_readings": False,
    }


def _piece_sources(
    conn, groups: Iterable[GroupGlossRequest], new_rows: dict
) -> dict[GlossKey, tuple[object, str]]:
    """The (entries, source) of every base and helper verb in `groups`, from
    the cache or else looked up, adding each lookup to `new_rows`."""
    alternates: dict[GlossKey, str | None] = {}
    for group in groups:
        alternates.setdefault(group.base_key, group.base_alt)
        for part in group.attached:
            if is_helper_verb(part):
                alternates.setdefault(
                    citation_key(part.normalized_form, part.dictionary_form),
                    part.dictionary_form,
                )

    found = _cached_entries(conn, alternates.keys() - new_rows.keys())
    uncached = {
        key: _lookup(*key, alt)
        for key, alt in alternates.items()
        if key not in found and key not in new_rows
    }
    _add_composites(
        conn,
        [key for key, (_, source) in uncached.items() if source == "jmdict_miss"],
        uncached,
    )
    new_rows.update(uncached)
    found.update({key: new_rows[key] for key in alternates.keys() - found.keys()})
    return found


def _add_group_glosses(
    conn, groups: list[GroupGlossRequest], cached_ids: dict, new_rows: dict
) -> None:
    """Add a composite row to `new_rows` for each of `groups` not in
    `cached_ids`, and a row for each of their pieces' lookups not cached."""
    missing = {group.key: group for group in groups if group.key not in cached_ids}
    if not missing:
        return
    found = _piece_sources(conn, missing.values(), new_rows)
    for key, group in missing.items():
        new_rows[key] = ({"pieces": _group_pieces(group, found)}, "composite")


def _add_katakana_readings(
    conn, keys: list[GlossKey], new_rows: dict[GlossKey, tuple[object, str]]
) -> None:
    """For each key written in katakana with no JMDict entry of its own
    (ココロノコエ), replace its empty result in `new_rows` with a gloss of it
    looked up as hiragana (こころのこえ), when every word of the hiragana has
    an entry. Each piece also records where in the katakana it is, as
    "span", which of the hiragana's words, phrases, groups or stand-alone
    grammar words it belongs to, as "unit", and whether it is grammar attached
    to a word, as "attached": the の between two words is grammar of its own,
    but attached to a verb it's the verb's."""
    # Imported here: app.katakana builds on this module.
    from app.katakana import hiragana_units, is_katakana_word

    readings = {
        key: units
        for key in keys
        if is_katakana_word(key[0]) and (units := hiragana_units(key[0]))
    }
    if not readings:
        return
    requests = [
        unit
        for units in readings.values()
        for unit, _ in units
        if isinstance(unit, GroupGlossRequest)
    ]
    found = _piece_sources(conn, requests, new_rows)
    for key, units in readings.items():
        words = [unit for unit, _ in units if isinstance(unit, GroupGlossRequest)]
        if any(found[word.base_key][1] == "jmdict_miss" for word in words):
            continue
        pieces = []
        for index, (unit, spans) in enumerate(units):
            if isinstance(unit, GroupGlossRequest):
                # A base glossed as a composite gives a piece per word of it,
                # each placed over the whole base.
                base = _base_pieces(unit, found)
                placed = [(piece, spans[0], False) for piece in base] + [
                    (_attached_piece(part), span, True)
                    for part, span in zip(unit.attached, spans[1:], strict=True)
                ]
            else:
                placed = [(_grammar_piece(unit), spans[0], False)]
            pieces += [
                {**piece, "span": list(span), "unit": index, "attached": attached}
                for piece, span, attached in placed
            ]
        new_rows[key] = (
            {"pieces": pieces, "looked_up_as": to_hiragana(key[0])},
            "composite",
        )


def plan_glosses(
    conn,
    requests: Iterable[tuple[GlossKey, str | None]],
    groups: Iterable[GroupGlossRequest] = (),
) -> GlossPlan:
    """Resolve each requested key, and each of `groups`' composite keys,
    against the gloss cache and compute every miss (from JMDict, the English
    stub, or the compound and katakana fallbacks), without writing anything.
    Each request pairs a key with an alternate spelling to try when the key's
    own lookup_form has no JMDict entry; the first one given for a key is
    used."""
    groups = list(groups)
    alternates: dict[GlossKey, str | None] = {}
    for key, alt in requests:
        alternates.setdefault(key, alt)
    cached = _cached_rows(conn, alternates.keys() | {g.key for g in groups})
    cached_ids = {key: row.id for key, row in cached.items()}
    new_rows = {
        key: _lookup(*key, alt)
        for key, alt in alternates.items()
        if key not in cached_ids
    }
    _add_composites(
        conn,
        [key for key, (_, source) in new_rows.items() if source == "jmdict_miss"],
        new_rows,
    )
    _add_katakana_readings(
        conn,
        [key for key, (_, source) in new_rows.items() if source == "jmdict_miss"],
        new_rows,
    )
    _add_group_glosses(conn, groups, cached_ids, new_rows)
    return GlossPlan(
        cached_ids, {key: row.source for key, row in cached.items()}, new_rows
    )


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


def _cached_entries(conn, keys) -> dict[GlossKey, tuple[object, str]]:
    """The (entries, source) of each of `keys` that is cached."""
    rows = _cached_rows(conn, keys, with_entries=True)
    return {key: (row.entries, row.source) for key, row in rows.items()}


def gloss_entries(
    conn, requests: Iterable[tuple[GlossKey, str | None]]
) -> dict[GlossKey, tuple[object, str]]:
    """The (entries, source) of each requested key's gloss, each key paired
    with an alternate spelling as plan_glosses takes it. A key that isn't
    cached is looked up and cached first."""
    requests = list(requests)
    found = _cached_entries(conn, {key for key, _ in requests})
    missing = [(key, alt) for key, alt in requests if key not in found]
    if missing:
        store_glosses(conn, plan_glosses(conn, missing))
        # Read back rather than taken from the plan, which leaves out a key
        # another transaction cached in the meantime.
        found |= _cached_entries(conn, {key for key, _ in missing})
    return found


def get_or_create_gloss_lookup(
    conn, lookup_form: str, reading: str, *, alt_lookup_form: str | None = None
) -> int:
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

    Tokens in a predicate group or accepted phrase are left alone too: each
    shares its group's gloss, which only the group as a whole can produce.
    """
    # A group member is any token with a phrase_start_position.
    unlinked = conn.execute(
        text(
            """
            SELECT t.id, t.normalized_form, t.dictionary_form, t.part_of_speech,
                   COALESCE(c.value ->> 'citation_reading', c.value ->> 'reading') AS selected_reading
            FROM tokens t
            LEFT JOIN conflicts c ON c.token_id = t.id AND c.selected
            WHERE t.document_id = :document_id AND t.gloss_lookup_id IS NULL
              AND t.phrase_start_position IS NULL
            ORDER BY t.position
            """
        ),
        {"document_id": document_id},
    ).all()

    keys: dict[int, GlossKey] = {}
    requests = []
    for row in unlinked:
        # Under a picked reading, or a correction would revert whenever this
        # runs.
        key = own_gloss_key(
            row.normalized_form,
            row.dictionary_form,
            row.part_of_speech,
            row.selected_reading,
        )
        if key is None:
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
        {
            "rows": json.dumps(
                [
                    {"id": token_id, "gloss_lookup_id": ids[key]}
                    for token_id, key in keys.items()
                ]
            )
        },
    )
