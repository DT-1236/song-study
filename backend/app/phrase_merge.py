"""Suggest combining consecutive tokens into longer JMDict headwords.

Sudachi's C-mode tokens are word-sized, but some of JMDict's most specific
entries are set phrases spanning several of them. The motivating case: この
(連体詞) / 期 (名詞) / に (助詞) / 及ん (動詞) / で (助詞) are five independently
tokenized words, but this exact idiom, この期に及んで ("at the last moment"),
IS a JMDict headword once those five surfaces are concatenated — and Sudachi's
own reading for 期 in isolation (き) is even the wrong reading for this idiom
(JMDict has it under ご), so gluing the surfaces together and asking JMDict for
the reading is the only way this specific entry is ever found.

This is a SUGGESTION pass only — nothing here is applied automatically.
Testing against real lyrics turned up multiple false positives from the same
greedy exact-match approach: 今日 (heteronym きょう/こんにち) + は merges into
今日は, an exact match for the entirely unrelated word こんにちは ("hello"),
and would silently overwrite a correct きょう gloss with it; し (verb stem) +
たく (auxiliary "want to") exactly matches したく ("preparations"). No POS-tag
or reading-based rule was found that reliably separates these from genuine
phrases like この期に及んで or それでも without also rejecting real ones — so
every candidate is surfaced as a conflicts row (kind='phrase', never
pre-selected) for a human to accept or ignore, the same trust model already
used for heteronym/no_kana_anchor review, rather than risking silently
corrupting an existing correct gloss. See app/conflicts.py
(create_phrase_conflicts, resolve_conflict) for how a suggestion is applied
once accepted.

Extension through any token type, auxiliaries (助動詞) included, is
deliberately unrestricted, favoring recall over precision: an earlier
version stopped at auxiliaries specifically to block し(verb stem)+たく
(auxiliary "want to") from matching したく ("preparations") — but that same
rule also made a whole common class of real idiom permanently unreachable
(お願いします "please", verb+する+ます, an actual JMDict headword — see
tests/test_phrase_merge.py for the real bug report this came from). Since
nothing here is ever applied without a human accepting it first, the right
place to filter a したく-style coincidence is the human doing that review,
not a blanket rule that also throws out real matches.

Algorithm: at each content-word token, greedily extend across the following
tokens' surfaces one at a time while the accumulated string is still a
prefix of some JMDict headword (a cheap indexed existence check —
glosses.phrase_prefix_state — not a real lookup), remembering the longest
point at which the accumulated string is itself an exact headword. The first
extension that isn't a prefix of anything stops the attempt; whichever exact
match was longest, if any, becomes that starting token's suggestion. Every
eligible starting position is evaluated independently (not skipped past
after a match), so a shorter match nested inside a longer one can also
surface as its own, separate suggestion. Capped at MAX_PHRASE_TOKENS tokens
per attempt, since JMDict's own multi-word entries don't run longer than a
handful of words in practice.

A token being appended can also complete a match through its *dictionary*
form rather than its own (possibly inflected) surface: 真/に/受け is only
真に受け as literal text — 受け is 受ける's 連用形 stem — but JMDict keys the
idiom 真に受ける ("to take at face value") by the citation form, which no
amount of further inflection (受けて, 受けた, ...) will ever spell out
verbatim. So each step also tries prefix-so-far + this token's dictionary
form as an exact match. It's checked, not just assumed, because most tokens
whose dictionary_form differs from their surface still don't complete
anything (walking past 受け into 見, whose dictionary form 見る, would try
真に受け見る, which isn't an entry either). Only the exact-match completion
counts; the running prefix-continuation state always advances by the raw
surface, not the dictionary form, since every token after this one is still
literal on-page text.

Runs once per document, after tokenize_document and before gloss lookup
(see main._process_document) — finding candidates is a property of the
token sequence, independent of which glosses end up cached.

Any noun immediately followed by a conjugated する is offered as a
suggestion too (see _suru_verb_suggestion), even with no exact-match scan
above ever finding anything: this is Japan's fully productive noun+する
verbalization (買い物する "to shop", 勉強する "to study", 遠回りする "to take
a detour", ...), not an idiom, so most such combinations were never going
to be JMDict headwords of their own no matter how the exact-match search
was tuned — only the noun itself (買い物) has an entry. There's no
dictionary gloss to look up for the combination either;
get_or_create_gloss_lookup's existing composite fallback (see
app.glosses._add_composites) already decomposes it right back into [noun,
する] via Sudachi's own SplitMode.A and glosses each piece separately, so
this only needs to point the lookup at the citation form (遠回り + する, not
the occurrence's own 遠回りし) for that fallback to fire — no new
gloss-construction code needed.

Not gated on Sudachi's own サ変可能 ("can take する") POS tag — that tag is
demonstrably incomplete (買い物 and 勉強 are tagged サ変可能, but 遠回り isn't,
despite 遠回りする being just as natural) — so this is a second, independent
trigger alongside the exact-match search above, not a replacement for it:
whenever that search already found a real dictionary entry (真に受ける, お
願いします, ...), it's used and this fallback never runs (see the `continue`
right after it), so a genuine, more specific dictionary match is always
preferred over a synthesized noun+する composite when both could apply to
the same starting token.

A te-form + light-verb chain (見てみる "to try seeing", てしまう "to finish/
end up doing", ておく "to do in advance", ている "-ing/a state", てほしい
"want someone to do", ...) is another fully productive construction, not
an idiom, detected the same way as noun+する: by Sudachi's own per-
occurrence 非自立可能 ("can be non-independent") tag on the light verb —
見る is tagged 一般 when it means "to see", 非自立可能 when it's functioning
as てみる's auxiliary (see light_verb_chain_end). Deliberately two-tier
rather than always eagerly extending through a trailing chain:

  - When nothing precedes the chain worth offering on its own (a bare verb
    with no exact-match phrase and no noun+する pattern applying), the
    chain is offered directly here (_bare_light_verb_chain_suggestion) —
    there's nothing smaller to prioritize showing first.
  - When something IS already offered on its own — an idiom (真に受け) or a
    noun+する verbalization (買い物する) — the chain is deliberately NOT
    folded into that same suggestion. Combining 真+に+受け+てみて in one step
    would mean a user can only ever get 真に受けてみて or nothing; they'd
    never see the plainer, equally valid 真に受け on its own first. Instead
    app.conflicts re-runs light_verb_chain_end after *accepting* the
    shorter suggestion, offering the chain extension as a second, separate
    suggestion at that point — see _apply_phrase_selection there. This also
    means chaining composes for free (真に受けてみてしまった would be offered
    after accepting 真に受けてみて, and so on) without any extra design here.

Every chain-involving suggestion (this fallback's, or the one
app.conflicts derives after an accept) carries a `chain_start_offset`:
how many tokens at the start of the span are the "base" being verbalized/
idiomized, with the rest being the light-verb chain. app.conflicts uses it
to gloss the base and each light verb separately and combine them, rather
than asking get_or_create_gloss_lookup to resolve the whole citation
string as one unit — that would silently re-decompose an already-specific
idiom's meaning back into its literal parts (see that module for why).
"""

from __future__ import annotations

from typing import Optional

from app.glosses import phrase_prefix_state, resolve_phrase_reading
from app.tokenization import TokenRecord, mixed_reading

# JMDict's own multi-word entries are set phrases (proverbs, fixed
# expressions) a handful of words long at most; nothing in practice runs
# longer than this, so it bounds the worst-case scan per start position.
MAX_PHRASE_TOKENS = 8

# Content-word major POS categories only — deliberately narrower than
# glosses.is_lexical, which also counts particles/auxiliaries as glossable.
# A merge attempt starting at a short particle or auxiliary routinely finds
# an unrelated, coincidentally-real headword instead of a real expression
# (see module docstring). Restricting where a scan can *start* (not what it
# can extend through — に/で/を etc. inside a real expression like この期に
# 及んで are still fine) cuts out a lot of that risk, though not all of it
# (今日は -> こんにちは starts from 今日, a perfectly good noun) — hence this
# whole pass being suggestion-only rather than auto-applied.
_PHRASE_START_POS = frozenset(
    {"名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "感動詞", "代名詞", "接頭辞"}
)

# What a te-form + light-verb chain's own verb/adjective can be — see
# light_verb_chain_end.
_LIGHT_VERB_POS = frozenset({"動詞", "形容詞"})

# Short, human-curated explanations for the grammaticalized (非自立可能)
# meaning of common light verbs, keyed by normalized_form — see
# light_verb_note. Not derivable from JMDict: some of these light verbs
# (見る, しまう) do have a distinct "auxiliary verb"-tagged sense JMDict
# itself lists, but others (回る, 行く, 来る) attach a grammaticalized
# meaning through pure construction, with no dictionary sense of their own
# for it at all — verified live for 回る (て回る, "around/repeatedly"), whose
# only JMDict senses are all literal ("to turn", "to revolve", ...).
_LIGHT_VERB_NOTES: dict[str, str] = {
    "見る": "てみる: to try doing something",
    "仕舞う": "てしまう: to finish completely, or do something unintentionally/regrettably",
    "置く": "ておく: to do something in advance, or leave something as is for later",
    "行く": "ていく: an action or change continuing on from now",
    "来る": "てくる: an action or change that has been continuing up to now",
    "居る": "ている: an ongoing action, or the resulting state of one",
    "貰う": "てもらう: to have or get someone do something",
    "呉れる": "てくれる: someone does something for you",
    "上げる": "てあげる: to do something for someone",
    "欲しい": "てほしい: wanting someone to do something",
    "回る": "て回る: to do something all around, here and there, or repeatedly",
}


def light_verb_note(normalized_form: str) -> str:
    """A short explanation of this light verb's grammaticalized meaning in
    a te-form + light-verb chain (see light_verb_chain_end), for the
    gloss's light-verb piece. Always returns something (unlike an ordinary
    dict.get) — even a light verb outside the curated table above is, by
    construction, always used in its grammaticalized sense here (that's
    exactly what light_verb_chain_end's 非自立可能 check selected for), so
    the frontend still needs a note to mark it as one, just a generic one
    instead of a specific gloss."""
    return _LIGHT_VERB_NOTES.get(
        normalized_form, "used here as a grammaticalized auxiliary after て/で, not its literal meaning"
    )


def _can_start_phrase(part_of_speech) -> bool:
    return part_of_speech[0] in _PHRASE_START_POS


def light_verb_chain_end(records: list[TokenRecord], start: int, limit: int) -> Optional[int]:
    """If `records[start]` begins a te-form + light-verb chain — て/で
    (助詞,接続助詞) immediately followed by a verb or adjective Sudachi
    itself tags 非自立可能 for this occurrence (its own per-occurrence
    marker for grammaticalized te-form + light-verb usage, distinct from
    that same verb's ordinary 一般 tag when used with its literal meaning
    — see module docstring) — returns the index just past the chain's last
    light verb. Absorbs a further te+light-verb chain immediately after
    that too (見てみてしまう), capped at `limit`. None if `records[start]`
    doesn't begin a chain link at all.

    Shared between this module (offering a chain on a bare verb/adjective
    with no other suggestion — see _bare_light_verb_chain_suggestion) and
    app.conflicts (offering it as a follow-up once whatever precedes it has
    itself already been accepted) — both need identical detection, since a
    light-verb chain means the same thing regardless of what it follows.
    Works on anything exposing `.surface`/`.part_of_speech` (a TokenRecord,
    or a plain DB row with those columns selected), not just TokenRecord
    specifically, since app.conflicts calls it against freshly-fetched rows.

    Also absorbs one trailing bare て/で right after the chain's last light
    verb, when nothing follows it forms another chain link — real case:
    真に受けてみて (受け/て/み/て) leaves the final て dangling on its own
    otherwise, glossed (if at all) as a meaningless standalone particle,
    when it's actually still that same light verb's own unfinished
    conjunctive form (common in lyrics trailing off mid-clause, or
    connecting to a following independent clause the fusion doesn't need
    to include). A lone て/で never has a real gloss of its own regardless
    of what comes after it, so sweeping it in is safe either way.
    """
    if start + 1 >= limit:
        return None
    connector, light_verb = records[start], records[start + 1]
    if connector.part_of_speech[0] != "助詞" or connector.surface not in ("て", "で"):
        return None
    if light_verb.part_of_speech[0] not in _LIGHT_VERB_POS or light_verb.part_of_speech[1] != "非自立可能":
        return None
    end = start + 2
    further = light_verb_chain_end(records, end, limit)
    return further if further is not None else _absorb_trailing_connector(records, end, limit)


def _absorb_trailing_connector(records: list, end: int, limit: int) -> int:
    """`end`, or `end + 1` if `records[end]` is a bare て/で connector with
    nothing after it forming its own light-verb chain link. A lone て/で
    never has a real gloss of its own regardless of what precedes or
    follows it, so it belongs grouped with whatever verbal chain it's
    still the unfinished conjunctive form of — shared by light_verb_chain_end
    (its own trailing connector, after the last light verb it absorbed) and
    find_phrase_suggestions (an idiom or noun+する match directly followed
    by a bare connector with no light verb at all, real case: 遠回りし+て,
    "took a detour and...", trailing off with nothing further)."""
    if end < limit and records[end].part_of_speech[0] == "助詞" and records[end].surface in ("て", "で"):
        return end + 1
    return end


def _bare_light_verb_chain_suggestion(records: list[TokenRecord], i: int, limit: int) -> Optional[dict]:
    """A phrase_suggestion for `records[i]` alone plus whatever te+light-verb
    chain immediately follows it (見てみる "to try seeing"), for when
    `records[i]` isn't otherwise part of any suggestion above — the tier
    that offers a chain directly, without requiring some other suggestion
    to be accepted first (see module docstring). None if `records[i]`
    isn't a verb/adjective, or nothing following it forms a chain.

    Unlike the exact-match/noun+する suggestions above, `lookup_form` here
    is just the literal on-page surface (真 of dictionary-form completion
    doesn't apply): the base verb's own occurrence — 見 in 見てみる, already
    its 連用形 stem — is exactly the form that correctly precedes て, so
    there's nothing to complete the way 受け needed completing to 受ける.
    """
    base = records[i]
    if base.part_of_speech[0] not in _LIGHT_VERB_POS:
        return None
    chain_end = light_verb_chain_end(records, i + 1, limit)
    if chain_end is None:
        return None

    surface = "".join(r.surface for r in records[i:chain_end])
    return {
        "surface": surface,
        "lookup_form": surface,
        "reading": mixed_reading(surface),
        "token_count": chain_end - i,
        # How many tokens at the start are the "base" (here, just this one
        # verb/adjective) versus the light-verb chain — see module
        # docstring and app.conflicts._apply_phrase_selection, which uses
        # this to gloss the two parts separately instead of re-decomposing
        # the whole citation string from scratch.
        "chain_start_offset": 1,
    }


def _suru_verb_suggestion(noun: TokenRecord, following: TokenRecord) -> Optional[dict]:
    """A phrase_suggestion for `noun` + `following`, if `noun` is any noun
    and `following` is directly, immediately a conjugated form of する
    (normalized_form 為る) — Japan's fully productive noun+する
    verbalization, not a dictionary idiom (see module docstring). None
    otherwise.

    Not gated on Sudachi's own サ変可能 ("can take する") tag: that tag is
    demonstrably incomplete (遠回りする is natural Japanese — 買い物する,
    "to shop", is too — but Sudachi's dictionary only tags 買い物 サ変可能,
    leaving 遠回り as a plain 一般 noun) and this whole pass already relies
    on a human reviewing every suggestion rather than a filter here catching
    everything, so under-triggering to match Sudachi's own tag would cost
    more real matches than the extra suggestion noise from over-triggering
    on a coincidental adjacency costs in review effort."""
    if noun.part_of_speech[0] != "名詞":
        return None
    if following.part_of_speech[0] != "動詞" or following.normalized_form != "為る":
        return None

    lookup_form = noun.dictionary_form + following.dictionary_form
    return {
        "surface": noun.surface + following.surface,
        "lookup_form": lookup_form,
        "reading": mixed_reading(lookup_form),
        "token_count": 2,
    }


def _with_trailing_connector(suggestion: dict, records: list[TokenRecord], start: int, limit: int) -> dict:
    """`suggestion` (an exact-match or noun+する suggestion, ending at
    `start + suggestion["token_count"]`), extended by one token if a bare
    て/で connector with nothing forming its own light-verb chain
    immediately follows it (see _absorb_trailing_connector) — real case:
    遠回りし (noun+する verbalization) directly followed by a bare て with
    nothing after it, which used to leave that て out of the fusion
    entirely and glossed (if at all) as a meaningless standalone particle.

    `lookup_form`/`reading` stay untouched under new base_lookup_form/
    base_reading keys, and chain_start_offset marks where they end — the
    connector contributes no vocabulary of its own, so
    app.conflicts._chain_extension_gloss_lookup resolves the base fresh
    from those and adds no extra piece for the connector, same as any
    other lone connector inside a chain (see that function). Only
    `surface`/`reading` (the whole span, for display and furigana) grow to
    include it.

    Deliberately narrower than absorbing a real light-verb chain here too
    (light_verb_chain_end(records, end, limit) is not None): that's left
    for the existing post-accept "reveal" step instead (see module
    docstring on why folding a chain directly into the base suggestion
    would deny a user ever seeing the plainer suggestion on its own first)
    — this only ever fires for a bare connector with no chain at all
    following it, which has no smaller suggestion worth prioritizing.
    """
    end = start + suggestion["token_count"]
    if light_verb_chain_end(records, end, limit) is not None:
        return suggestion
    new_end = _absorb_trailing_connector(records, end, limit)
    if new_end == end:
        return suggestion
    connector_surface = records[end].surface
    return {
        **suggestion,
        "surface": suggestion["surface"] + connector_surface,
        "reading": suggestion["reading"] + mixed_reading(connector_surface),
        "lookup_form": suggestion["surface"] + connector_surface,
        "base_lookup_form": suggestion["lookup_form"],
        "base_reading": suggestion["reading"],
        "token_count": new_end - start,
        "chain_start_offset": suggestion["token_count"],
    }


def find_phrase_suggestions(records: list[TokenRecord]) -> None:
    """Mutates `records` in place, setting phrase_suggestion on every token
    that could start a multi-token JMDict match."""
    n = len(records)
    for i in range(n):
        if not _can_start_phrase(records[i].part_of_speech):
            continue

        current = records[i].surface
        best_end: int | None = None
        best_candidate: str | None = None
        limit = min(i + MAX_PHRASE_TOKENS, n)
        for j in range(i + 1, limit):
            # Only the longest exact match ever gets used (best_candidate
            # keeps getting overwritten), so resolving each intermediate
            # hit's reading against JMDict here — real entry hydration, not
            # the cheap existence check phrase_prefix_state does — would be
            # wasted work whenever a nested match is found along the way
            # (見て回っ inside 見て回っている, say). Deferred to a single
            # resolve_phrase_reading call below, on whichever candidate
            # actually wins.
            if records[j].dictionary_form != records[j].surface:
                citation_candidate = current + records[j].dictionary_form
                citation_exact, _ = phrase_prefix_state(citation_candidate)
                if citation_exact:
                    best_end = j + 1
                    best_candidate = citation_candidate

            current += records[j].surface
            is_exact, has_longer = phrase_prefix_state(current)
            if is_exact:
                best_end = j + 1
                best_candidate = current
            if not has_longer:
                break

        if best_candidate is not None:
            reading = resolve_phrase_reading(best_candidate)
            if reading is not None:
                suggestion = {
                    # The literal on-page text (真に受け) — for display and
                    # for grouping the actual tokens being merged.
                    "surface": "".join(r.surface for r in records[i:best_end]),
                    # The string actually verified as a JMDict headword
                    # (真に受ける, when a dictionary-form completion won) —
                    # what the gloss lookup has to use. Distinct from
                    # `surface` whenever that happened: the raw on-page text
                    # alone (真に受け) has no entry of its own no matter how
                    # much further inflection follows it, so looking it up
                    # directly would silently miss and fall back to a
                    # meaningless per-character composite instead of the
                    # idiom's real gloss.
                    "lookup_form": best_candidate,
                    "reading": reading,
                    "token_count": best_end - i,
                }
                records[i].phrase_suggestion = _with_trailing_connector(suggestion, records, i, limit)
                continue

        # No exact-match phrase found starting here — try the productive
        # noun+する verbalization instead (see module docstring and
        # _suru_verb_suggestion), which was never going to be a JMDict
        # headword of its own regardless of how the search above was
        # tuned. Real dictionary entries always win when one exists; this
        # only ever fills in where the exact-match search found nothing.
        suggestion = _suru_verb_suggestion(records[i], records[i + 1]) if i + 1 < n else None
        if suggestion is not None:
            suggestion = _with_trailing_connector(suggestion, records, i, limit)
        if suggestion is None:
            # Still nothing — a bare verb/adjective with no idiom and no
            # noun+する pattern can still have a te+light-verb chain
            # offered directly (見てみる), since there's nothing smaller to
            # prioritize showing first (see module docstring).
            suggestion = _bare_light_verb_chain_suggestion(records, i, limit)
        records[i].phrase_suggestion = suggestion
