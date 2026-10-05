"""End-to-end tests for predicate groups (see app/grammar.py): grouped and
glossed when a document is processed, split and merged again, glossed again
when a member's reading changes, and replaced by an accepted phrase that
overlaps one."""

from __future__ import annotations

from app.main import (
    ConflictResolution,
    DocumentCreate,
    PhraseAcceptance,
    TokensReading,
)
from tests.support import (
    accept_phrase_suggestions_endpoint,
    apply_tokens_reading,
    clear_gloss_links,
    create_document,
    get_document_tokens,
    pick_reading,
    resolve_token_conflict,
    round_trips,
    statements_sent,
    unmerge_phrase_tokens,
)


def _tokens(text):
    document_id = create_document(DocumentCreate(title="t", text=text)).id
    return document_id, get_document_tokens(document_id)


def _group(tokens, start):
    return [t for t in tokens if t.phrase_start_position == start]


def test_processing_glosses_a_group_as_its_word_plus_notes_on_its_grammar(
    committed_engine,
):
    _, tokens = _tokens("欲してるんだって")

    assert [t.phrase_start_position for t in tokens] == [0, 0, 0, 0, 0]
    assert {t.group_kind for t in tokens} == {"predicate"}
    gloss = tokens[0].gloss
    assert all(t.gloss == gloss for t in tokens)
    assert gloss.source == "composite"
    assert gloss.lookup_form == "欲する＋てる＋ん＋だ＋って"
    assert gloss.reading == "ほっしてるんだって"

    word, *grammar = gloss.pieces
    assert word.surface == "欲する"
    assert word.senses and word.note is None
    assert [(p.surface, p.senses) for p in grammar] == [
        ("てる", []),
        ("ん", []),
        ("だ", []),
        ("って", []),
    ]
    assert grammar[0].note.startswith("short for ている")

    # The head keeps a row to merge the group again with after a split.
    [row] = [c for c in tokens[0].conflicts if c.kind == "predicate"]
    assert row.value == {"surface": "欲してるんだって", "token_count": 5}
    assert not row.selected


def test_a_helper_verb_piece_has_its_own_senses_and_a_note(committed_engine):
    _, tokens = _tokens("猫を見てみる。")

    pieces = _group(tokens, 2)[0].gloss.pieces
    assert [p.surface for p in pieces] == ["見る", "て", "みる"]
    assert pieces[2].senses
    assert pieces[2].note == "てみる: try doing"


def test_a_group_can_be_split_and_merged_again(committed_engine):
    document_id, tokens = _tokens("欲してるんだって")
    group_gloss = tokens[0].gloss

    split = unmerge_phrase_tokens(document_id, tokens[2].id)

    assert len(split) == 5
    assert all(t.phrase_start_position is None and t.group_kind is None for t in split)
    assert len({t.gloss.lookup_form for t in split}) == 5

    row = next(c for c in tokens[0].conflicts if c.kind == "predicate")
    merged = accept_phrase_suggestions_endpoint(
        document_id, PhraseAcceptance(conflict_ids=[row.id])
    )

    assert sorted(t.position for t in merged) == [0, 1, 2, 3, 4]
    assert all(t.phrase_start_position == 0 and t.gloss == group_gloss for t in merged)
    assert not any(
        c.selected for t in merged for c in t.conflicts if c.kind == "predicate"
    )


def test_picking_a_reading_for_a_groups_head_glosses_the_group_again(committed_engine):
    # 開い is read ひらい by default, and あい is offered.
    document_id, tokens = _tokens("ドアが開いている")
    head = tokens[2]
    alternative = next(
        c for c in head.conflicts if c.kind == "heteronym" and not c.selected
    )

    resolve_token_conflict(
        document_id, head.id, ConflictResolution(conflict_id=alternative.id)
    )

    group = _group(get_document_tokens(document_id), 2)
    assert len(group) == 3
    assert all(t.group_kind == "predicate" for t in group)
    assert group[0].gloss.reading == "あいている"
    assert group[0].gloss.pieces[0].reading == "あく"
    assert all(t.gloss == group[0].gloss for t in group)


def test_applying_a_reading_to_a_grouped_token_returns_the_whole_group(
    committed_engine,
):
    document_id, tokens = _tokens("ドアが開いている")
    head = tokens[2]

    updated = apply_tokens_reading(
        document_id, TokensReading(token_ids=[head.id], reading="あい")
    )

    assert sorted(t.position for t in updated) == [2, 3, 4]
    assert all(t.gloss.reading == "あいている" for t in updated)


def test_a_typed_reading_never_selects_a_phrase_suggestion(committed_engine):
    # 今日は's phrase suggestion also has the reading こんにちは, but it isn't
    # one of 今日's reading options.
    document_id, tokens = _tokens("今日は雨です。")
    today = tokens[0]
    assert any(
        c.kind == "phrase" and c.value["reading"] == "こんにちは"
        for c in today.conflicts
    )

    [updated] = apply_tokens_reading(
        document_id, TokensReading(token_ids=[today.id], reading="こんにちは")
    )

    [selected] = [c for c in updated.conflicts if c.selected]
    assert selected.kind == "custom"
    assert updated.phrase_start_position is None


def test_repairing_cleared_links_glosses_each_group_as_before(committed_engine):
    # Two accepted phrases, one with grammar attached and one without, and
    # two predicate groups, one under a picked reading.
    document_id, tokens = _tokens(
        "この期に及んで\n真に受けてみて\n欲してるんだって\nドアが開いている"
    )
    accept_phrase_suggestions_endpoint(
        document_id,
        PhraseAcceptance(
            conflict_ids=[
                c.id
                for t in tokens
                for c in t.conflicts
                if c.kind == "phrase"
                and c.value["lookup_form"] in ("この期に及んで", "真に受ける")
            ]
        ),
    )
    pick_reading(document_id, "開い", "あい")
    before = get_document_tokens(document_id)
    groups = {(t.phrase_start_position, t.group_kind) for t in before}
    assert sum(kind == "phrase" for _, kind in groups) == 2
    assert sum(kind == "predicate" for _, kind in groups) == 2
    # A gloss of its own per group, so one linked to the wrong group shows.
    assert (
        len(
            {t.gloss.lookup_form for t in before if t.phrase_start_position is not None}
        )
        == 4
    )
    clear_gloss_links(document_id)

    statements = statements_sent(
        committed_engine, lambda: get_document_tokens(document_id)
    )

    after = get_document_tokens(document_id)
    assert [(t.id, t.phrase_start_position, t.gloss) for t in after] == [
        (t.id, t.phrase_start_position, t.gloss) for t in before
    ]
    # Every group at once, not a round trip per group.
    assert round_trips(statements, "UPDATE tokens") == 2


def test_accepting_a_phrase_replaces_the_group_it_overlaps(committed_engine):
    # 受けてみて is a group of its own until 真に受ける is accepted over it.
    document_id, tokens = _tokens("真に受けてみて")
    assert [t.phrase_start_position for t in tokens] == [None, None, 2, 2, 2, 2]
    suggestion = next(c for c in tokens[0].conflicts if c.kind == "phrase")

    accept_phrase_suggestions_endpoint(
        document_id, PhraseAcceptance(conflict_ids=[suggestion.id])
    )

    tokens = get_document_tokens(document_id)
    assert [t.phrase_start_position for t in tokens] == [0, 0, 0, 0, 0, 0]
    assert {t.group_kind for t in tokens} == {"phrase"}
    gloss = tokens[0].gloss
    assert gloss.lookup_form == "真に受ける＋て＋みる＋て"
    assert gloss.reading == "まにうけてみて"
    assert [p.surface for p in gloss.pieces] == ["真に受ける", "て", "みる", "て"]
    assert "to take seriously" in gloss.pieces[0].senses[0].gloss

    # Split again, the phrase leaves separate tokens, and the group can be
    # merged again from its own row.
    unmerge_phrase_tokens(document_id, tokens[0].id)
    tokens = get_document_tokens(document_id)
    assert all(t.phrase_start_position is None for t in tokens)
    assert any(c.kind == "predicate" for c in tokens[2].conflicts)
