"""Regression tests for the te-form + light-verb chain feature end to end:
app/phrase_merge.py's two-tier detection (bare-verb chains offered directly,
idiom/noun+する chains revealed only after their base is accepted — see that
module's docstring) through app/conflicts.py's chain-aware gloss composition
(_chain_extension_gloss_lookup, _offer_chain_extension).

Real cases found live while building this feature, not invented:
  - create_phrase_conflicts used to persist only a hand-picked subset of a
    phrase_suggestion's keys, silently dropping chain_start_offset — so a
    chain suggestion looked fine in the initial API response (built from the
    in-memory TokenRecord) but glossed wrong once actually accepted (the
    round trip through the conflicts table lost the field that told
    _apply_phrase_selection to route it through the chain-aware pipeline at
    all). 受けて回る is the case that caught it: accepting it produced a
    meaningless 3-piece decomposition (受け as an unrelated noun "popularity",
    て as a particle with random senses, 回る on its own) instead of the
    correct 2-piece [受ける, 回る] composition.
  - The revealed extension's own reading used to be built by concatenating
    the base's citation-style gloss reading (まにうける, dictionary-form-
    completed beyond what's on the page) directly onto the chain's reading,
    producing まにうけるてみ instead of the correct まにうけてみ.
  - 回る's grammaticalized て回る meaning ("around", "repeatedly") isn't its
    own distinct JMDict sense at all (its entry only has literal senses:
    "to turn", "to revolve", ...) — unlike 見る's てみる use, which really is
    JMDict's own separate 'auxiliary verb'-tagged sense. Both need surfacing
    to a reviewer, which is why light_verb_note's curated table exists
    alongside (not instead of) rank_senses's auxiliary-sense reprioritizing.
  - Accepting 真に受け (真/に/受け, positions 0-2) never updated 真/受け's own
    furigana at all: build_furigana_spans tried to align the merged surface
    真に受け against the idiom's own citation-style gloss reading まにうける
    directly, found a trailing る with no on-page character to attach it
    to, and bailed out entirely rather than partially aligning. Fixed by
    projecting the reading onto the on-page surface first (see
    _project_onto_last_member) before ever handing it to
    build_furigana_spans.
  - 受け (position 2) is independently a valid tier-3 bare-verb-chain
    suggestion on its own (受けてみ, treating 受け itself as a base verb
    with a following light-verb chain) — this coexists, by design, with
    真に受け's own idiom suggestion starting two tokens earlier and
    covering the same 受け token (see app/phrase_merge.py's module
    docstring on why overlapping suggestions at different starting
    positions aren't suppressed). But accepting one after the other used to
    corrupt state instead of just superseding cleanly, in both orders:
    accepting the idiom first left 受け's own stray suggestion sitting
    there, ready to silently re-split the just-created fusion if accepted
    later; accepting 受け's smaller suggestion first and the idiom
    afterward left て/み stranded under a phrase_start_position whose own
    first-position member (受け) had just been reassigned into the idiom's
    group instead.
  - Repeated accept/unmerge/accept cycles on the same idiom piled up
    duplicate, identical "reveal" conflicts (_offer_chain_extension used to
    insert unconditionally, never checking for — or replacing — a stale one
    already left over from an earlier cycle).
"""

from __future__ import annotations

from app.main import (
    DocumentCreate,
    PhraseAcceptance,
    accept_phrase_suggestions_endpoint,
    create_document,
    get_document_tokens,
    unmerge_phrase_tokens,
)


def _unselected_phrase_conflict(tokens, surface):
    token = next(t for t in tokens if t.surface == surface)
    return next(c for c in token.conflicts if c.kind == "phrase" and not c.selected)


class TestBareVerbChain:
    """The tier-3 suggestion offered directly at initial scan (見てみる) —
    see app/phrase_merge.py's _bare_light_verb_chain_suggestion."""

    def test_accepting_composes_base_and_light_verb_as_separate_pieces(self, committed_engine):
        # 追い風/を/受け/て/回る: 受け (base, "to receive") + て/回る (light-verb
        # chain, tagged 非自立可能 for this occurrence) — regression case for
        # the chain_start_offset persistence bug (see module docstring).
        document_id = create_document(DocumentCreate(title="t", text="追い風を受けて回る日々")).id
        tokens = get_document_tokens(document_id)
        conflict = _unselected_phrase_conflict(tokens, "受け")
        assert conflict.value["chain_start_offset"] == 1

        accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[conflict.id]))

        tokens = get_document_tokens(document_id)
        uke = next(t for t in tokens if t.surface == "受け")
        assert uke.gloss.reading == "うけてまわる"
        assert uke.gloss.source == "composite"
        pieces = uke.gloss.pieces
        assert len(pieces) == 2
        assert pieces[0].surface == "受ける"
        assert any("to receive" in g for s in pieces[0].senses for g in s.gloss)
        assert pieces[1].surface == "回る"
        # 回る's grammaticalized て回る sense has no dictionary entry of its
        # own (see module docstring) — the curated note fills that gap.
        assert pieces[1].note == "て回る: to do something all around, here and there, or repeatedly"


class TestChainExtensionReveal:
    """The post-accept "reveal" tier — accepting an idiom or noun+する
    verbalization offers its own following te+light-verb chain as a new
    conflict, rather than requiring both to be offered up front (see
    app/phrase_merge.py's module docstring on why). 真に受けてみて is the
    motivating case: 真に受ける is a real idiom whose meaning ("to take
    seriously") the light-verb chain must not destroy."""

    def _accept_idiom(self, document_id):
        tokens = get_document_tokens(document_id)
        conflict = _unselected_phrase_conflict(tokens, "真")
        accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[conflict.id]))

    def test_accepting_the_idiom_reveals_the_following_chain(self, committed_engine):
        document_id = create_document(DocumentCreate(title="t", text="真に受けてみて。")).id
        self._accept_idiom(document_id)

        tokens = get_document_tokens(document_id)
        shin = next(t for t in tokens if t.surface == "真")
        assert shin.gloss.lookup_form == "真に受ける"  # the idiom's own gloss survives, untouched
        revealed = [c for c in shin.conflicts if c.kind == "phrase" and not c.selected]
        assert len(revealed) == 1
        assert revealed[0].value == {
            # The trailing て (真に受け/て/み/て, the last token) is swept in
            # too — light_verb_chain_end absorbs a bare trailing て/で right
            # after the chain's last light verb, since it's still that
            # light verb's own unfinished conjunctive form, not a separate
            # word (see app/phrase_merge.py's docstring).
            "surface": "真に受けてみて",
            "lookup_form": "真に受けてみて",
            # Regression: not まにうけるてみて (the idiom's own citation-style
            # gloss reading, まにうける, concatenated verbatim) — る there
            # belongs to 受ける's citation form, not to any on-page character.
            "reading": "まにうけてみて",
            "token_count": 6,
            "chain_start_offset": 3,
        }

    def test_accepting_the_revealed_extension_preserves_the_idioms_own_meaning(self, committed_engine):
        document_id = create_document(DocumentCreate(title="t", text="真に受けてみて。")).id
        self._accept_idiom(document_id)
        tokens = get_document_tokens(document_id)
        shin = next(t for t in tokens if t.surface == "真")
        extension = next(c for c in shin.conflicts if c.kind == "phrase" and not c.selected)

        accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[extension.id]))

        tokens = get_document_tokens(document_id)
        shin = next(t for t in tokens if t.surface == "真")
        assert shin.gloss.reading == "まにうけてみて"
        pieces = shin.gloss.pieces
        assert len(pieces) == 2
        # The idiom's own real JMDict sense, not a piece-by-piece
        # re-decomposition of 真/に/受ける that would lose it.
        assert pieces[0].surface == "真に受ける"
        assert any("to take seriously" in g for s in pieces[0].senses for g in s.gloss)
        # み's auxiliary "to try" sense ranked first, not its literal "to
        # see" senses — see gloss_piece's senses_pos_major override. The
        # trailing て gets no piece of its own (plain grammar, same as
        # every other connector in the chain), but its own token still
        # shares this merged span's gloss (checked in the group-membership
        # tests below).
        assert pieces[1].surface == "み"
        assert pieces[1].senses[0].gloss[0] == "to try ..."
        assert pieces[1].note == "てみる: to try doing something"
        trailing_te = next(t for t in tokens if t.position == shin.position + 5)
        assert trailing_te.gloss.lookup_form == "真に受けてみて"

    def test_no_extension_offered_when_nothing_follows(self, committed_engine):
        document_id = create_document(DocumentCreate(title="t", text="真に受けた。")).id
        self._accept_idiom(document_id)

        tokens = get_document_tokens(document_id)
        shin = next(t for t in tokens if t.surface == "真")
        assert [c for c in shin.conflicts if c.kind == "phrase" and not c.selected] == []

    def test_accepting_the_idiom_updates_its_own_furigana(self, committed_engine):
        # Regression: build_furigana_spans used to be handed the idiom's raw
        # citation-style reading (まにうける) directly against the merged
        # on-page surface (真に受け) — the trailing る has no on-page
        # character to attach to, so alignment failed outright and no
        # furigana_override was ever written at all, leaving 真 stuck
        # showing its default heteronym reading (しん) instead of the
        # idiom's real one (ま).
        document_id = create_document(DocumentCreate(title="t", text="真に受けてみて。")).id
        self._accept_idiom(document_id)

        tokens = get_document_tokens(document_id)
        shin = next(t for t in tokens if t.surface == "真")
        uke = next(t for t in tokens if t.surface == "受け")
        assert shin.furigana_override == [{"start": 0, "end": 1, "text": "真", "reading": "ま"}]
        assert uke.furigana_override == [
            {"start": 0, "end": 1, "text": "受", "reading": "う"},
            {"start": 1, "end": 2, "text": "け", "reading": None},
        ]

    def test_repeated_accept_unmerge_cycles_never_duplicate_the_reveal(self, committed_engine):
        document_id = create_document(DocumentCreate(title="t", text="真に受けてみて。")).id
        tokens = get_document_tokens(document_id)
        shin_id = next(t for t in tokens if t.surface == "真").id
        idiom = _unselected_phrase_conflict(tokens, "真")

        for _ in range(3):
            accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[idiom.id]))
            unmerge_phrase_tokens(document_id, shin_id)

        tokens = get_document_tokens(document_id)
        shin = next(t for t in tokens if t.surface == "真")
        reveals = [c for c in shin.conflicts if c.kind == "phrase" and not c.selected and c.id != idiom.id]
        assert len(reveals) == 1


class TestOverlappingSuggestionsResolveCleanly:
    """真に受け's idiom suggestion (positions 0-2) and 受け's own,
    independently-generated tier-3 bare-verb-chain suggestion (受けてみ,
    starting at position 2, the idiom's own last token) legitimately
    coexist — see app/phrase_merge.py's module docstring on why overlapping
    suggestions at different starting positions aren't suppressed. Accepting
    either one must still leave a fully consistent result regardless of
    which order they're accepted in — real corruption found live in both
    directions (see module docstring)."""

    def test_accepting_the_idiom_first_cancels_the_smaller_overlapping_suggestion(self, committed_engine):
        document_id = create_document(DocumentCreate(title="t", text="真に受けてみて。")).id
        tokens = get_document_tokens(document_id)
        idiom = _unselected_phrase_conflict(tokens, "真")

        accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[idiom.id]))

        tokens = get_document_tokens(document_id)
        uke = next(t for t in tokens if t.surface == "受け")
        # 受け's own 受けてみ suggestion is gone, not left dangling to
        # silently re-split the idiom if accepted later.
        assert [c for c in uke.conflicts if c.kind == "phrase" and not c.selected] == []

    def test_accepting_the_smaller_suggestion_first_then_the_idiom_leaves_no_stranded_tokens(self, committed_engine):
        document_id = create_document(DocumentCreate(title="t", text="真に受けてみて。")).id
        tokens = get_document_tokens(document_id)
        shin_position = next(t for t in tokens if t.surface == "真").position
        small = _unselected_phrase_conflict(tokens, "受け")
        # 受け's own suggestion absorbs the trailing て too, same as the
        # idiom's revealed extension does (see TestChainExtensionReveal) —
        # both go through the same light_verb_chain_end.
        assert small.value["surface"] == "受けてみて"

        accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[small.id]))
        tokens = get_document_tokens(document_id)
        idiom = _unselected_phrase_conflict(tokens, "真")
        accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[idiom.id]))

        tokens = get_document_tokens(document_id)
        by_position = {t.position - shin_position: t for t in tokens if shin_position <= t.position <= shin_position + 5}
        idiom_members = [by_position[0], by_position[1], by_position[2]]  # 真, に, 受け
        assert {t.phrase_start_position for t in idiom_members} == {shin_position}
        assert all(t.gloss.lookup_form == "真に受ける" for t in idiom_members)
        # て/み/て, no longer part of any group (受けてみて's own merge was
        # reverted to make room for the idiom), are back to their own
        # ordinary, independent glosses — not stranded under a
        # phrase_start_position whose own first member just moved away.
        for offset in (3, 4, 5):
            assert by_position[offset].phrase_start_position is None
        assert by_position[4].gloss.lookup_form == "見る"
