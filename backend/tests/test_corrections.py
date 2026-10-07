"""Managing cards from a song's words, and correcting which word a token is
from a card being studied: its reading, or for a token sung in katakana,
which word each of its pieces is."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.cards import CardKey
from app.glosses import with_picked_words
from app.main import (
    CardReadingCorrection,
    CardWordCorrection,
    PieceWordPick,
    ReviewAnswer,
)
from tests.support import (
    add_token_card,
    as_user,
    correct_card_reading,
    correct_card_word,
    create_tokenized_document,
    document_tokens,
    get_document_tokens,
    get_document_words,
    get_piece_words,
    pick_piece_word_endpoint,
    review_card,
    start_song_session,
    suspend_card,
)

# ボク/ノ/アイ/タイ: 僕, the の between two words, 会う, and たい attached to it.
KATAKANA_SONG = "ボクノアイタイ。"
BOKU, NO, AU, TAI = range(4)


def _cards(engine) -> dict[CardKey, object]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM study_cards")).all()
    return {CardKey(row.kind, row.lookup_form, row.reading): row for row in rows}


def _word(lookup_form: str, reading: str) -> CardKey:
    return CardKey("recognition", lookup_form, reading)


def _words(document_id: int) -> dict[tuple[str, str], object]:
    return {(w.lookup_form, w.reading): w for w in get_document_words(document_id)}


def _katakana_token(document_id: int):
    [token] = document_tokens(document_id, "ボクノアイタイ")
    return token


# The words a song offers to add


def test_each_word_of_a_song_is_offered_with_the_users_card_for_it(committed_engine):
    document_id = create_tokenized_document(text="君を呼ぶ。")
    [kimi] = document_tokens(document_id, "君")
    card = add_token_card(document_id, kimi.id)

    words = _words(document_id)

    # を is grammar, and 。 nothing at all.
    assert set(words) == {("君", "きみ"), ("呼ぶ", "よぶ")}
    assert words[("君", "きみ")].token_ids == [kimi.id]
    assert words[("君", "きみ")].card.id == card.id
    assert words[("呼ぶ", "よぶ")].card is None


def test_every_token_of_a_predicate_group_stands_for_its_head_word(committed_engine):
    document_id = create_tokenized_document(text="聞こえてるんだって")

    [word] = get_document_words(document_id)

    assert (word.lookup_form, word.reading) == ("聞こえる", "きこえる")
    assert word.token_ids == [t.id for t in get_document_tokens(document_id)]


def test_a_removed_card_is_offered_as_removed(committed_engine):
    document_id = create_tokenized_document(text="君")
    card = add_token_card(document_id, document_tokens(document_id, "君")[0].id)
    suspend_card(card.id)

    [word] = get_document_words(document_id)

    assert word.card.suspended


def test_a_word_without_a_headword_isnt_offered(committed_engine):
    document_id = create_tokenized_document(text="yeah 女神の涙")

    assert get_document_words(document_id) == []


def test_each_word_of_a_katakana_token_is_offered_as_its_piece(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    token = _katakana_token(document_id)

    words = _words(document_id)

    # Grammar isn't a word to add.
    assert set(words) == {("僕", "ぼく"), ("会う", "あう")}
    assert words[("僕", "ぼく")].piece == BOKU
    assert words[("会う", "あう")].piece == AU
    assert words[("会う", "あう")].token_ids == [token.id]


def test_offering_another_users_songs_words_is_refused(committed_engine, other_user):
    with as_user(other_user):
        theirs = create_tokenized_document(text="君")

    with pytest.raises(HTTPException) as exc:
        get_document_words(theirs)

    assert exc.value.status_code == 404


# Adding a word of a katakana token


def test_a_word_of_a_katakana_token_is_added_by_its_piece(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    card = add_token_card(document_id, _katakana_token(document_id).id, piece=AU)

    assert (card.lookup_form, card.reading) == ("会う", "あう")


@pytest.mark.parametrize(
    "piece",
    [
        None,
        # Grammar between two words, and grammar attached to one.
        NO,
        TAI,
        # Past the last piece.
        9,
    ],
)
def test_a_katakana_token_can_only_be_added_by_a_word_piece(committed_engine, piece):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    with pytest.raises(HTTPException) as exc:
        add_token_card(document_id, _katakana_token(document_id).id, piece=piece)

    assert exc.value.status_code == 422
    assert _cards(committed_engine) == {}


def test_a_token_not_sung_in_katakana_cant_be_added_by_a_piece(committed_engine):
    document_id = create_tokenized_document(text="君")

    with pytest.raises(HTTPException) as exc:
        add_token_card(document_id, document_tokens(document_id, "君")[0].id, piece=0)

    assert exc.value.status_code == 422


# Which word a piece of katakana is


def test_a_katakana_piece_offers_every_word_with_its_reading(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    options = get_piece_words(document_id, _katakana_token(document_id).id, AU)

    spellings = [option.spelling for option in options]
    assert {"会う", "合う"} <= set(spellings)
    assert len(spellings) == len(set(spellings))
    assert all(option.gloss for option in options)


def test_a_grammar_piece_offers_no_words(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    with pytest.raises(HTTPException) as exc:
        get_piece_words(document_id, _katakana_token(document_id).id, NO)

    assert exc.value.status_code == 422


def _pick(document_id: int, token_ids: list[int], spelling: str, piece: int = AU):
    return pick_piece_word_endpoint(
        document_id,
        PieceWordPick(token_ids=token_ids, piece=piece, spelling=spelling),
    )


def test_picking_another_word_for_a_piece_glosses_it_as_that_word(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    token = _katakana_token(document_id)

    [updated] = _pick(document_id, [token.id], "合う")

    piece = updated.gloss.pieces[AU]
    assert (piece.surface, piece.reading) == ("合う", "あう")
    # 合う's senses alone, no longer 会う's.
    assert {sense.entry_idseq for sense in piece.senses} == {1284430}
    # The rest are as they were.
    assert updated.gloss.pieces[BOKU].surface == "僕"
    assert get_document_tokens(document_id)[0].gloss.pieces[AU].surface == "合う"


def test_a_picked_word_is_the_one_the_song_offers_and_studies(committed_engine):
    start_song_session(create_tokenized_document(text="会いたい。合いたい。"))
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    _pick(document_id, [_katakana_token(document_id).id], "合う")

    assert ("合う", "あう") in _words(document_id)
    assert ("会う", "あう") not in _words(document_id)
    [line] = [
        card.line
        for card in start_song_session(document_id).cards
        if card.lookup_form == "合う"
    ]
    assert line.written_as == "合う"


def test_a_pick_applies_to_every_token_given(committed_engine):
    document_id = create_tokenized_document(text="ボクノアイタイ。ボクノアイタイ。")
    tokens = document_tokens(document_id, "ボクノアイタイ")

    _pick(document_id, [t.id for t in tokens], "合う")

    assert [
        t.gloss.pieces[AU].surface
        for t in document_tokens(document_id, "ボクノアイタイ")
    ] == ["合う", "合う"]


@pytest.mark.parametrize(
    "piece, spelling",
    [
        # Not a word read あう.
        (AU, "僕"),
        # Grammar.
        (TAI, "たい"),
    ],
)
def test_picking_a_word_a_piece_cant_be_is_refused(committed_engine, piece, spelling):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    token = _katakana_token(document_id)

    with pytest.raises(HTTPException) as exc:
        _pick(document_id, [token.id], spelling, piece=piece)

    assert exc.value.status_code == 422
    assert get_document_tokens(document_id)[0].gloss.pieces[AU].surface == "会う"


def test_a_pick_is_left_out_once_its_piece_reads_otherwise():
    composite = {
        "looked_up_as": "あいたい",
        "pieces": [
            {"surface": "あう", "key": ["あう", "あう"], "alt_lookup_form": None},
            {"surface": "たい", "key": None, "alt_lookup_form": None},
        ],
    }

    picked = with_picked_words(
        composite,
        # The gloss was built again and split the katakana otherwise.
        [(0, "あい", "愛"), (1, "たい", "鯛"), (5, "あう", "合う")],
    )

    assert picked == composite


# Correcting a card's word from a session


def _card_for(document_id: int, surface: str, piece: int | None = None):
    return add_token_card(
        document_id, document_tokens(document_id, surface)[0].id, piece=piece
    )


def _correct_reading(card_id: int, document_id: int, surface: str, reading: str):
    return correct_card_reading(
        card_id,
        CardReadingCorrection(
            document_id=document_id,
            token_id=document_tokens(document_id, surface)[0].id,
            reading=reading,
        ),
    )


def test_correcting_a_cards_reading_moves_the_song_to_another_card(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    assert old.reading == "つらい"

    correction = _correct_reading(old.id, document_id, "辛い", "からい")

    assert (correction.card.lookup_form, correction.card.reading) == ("辛い", "からい")
    assert correction.card.first_seen_document_id == document_id
    # Nothing was learned on it, so it's gone.
    assert not correction.kept
    assert set(_cards(committed_engine)) == {_word("辛い", "からい")}
    assert [(w.lookup_form, w.reading) for w in get_document_words(document_id)] == [
        ("辛い", "からい")
    ]


def test_a_corrected_card_with_reviews_keeps_them(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    review_card(old.id, ReviewAnswer(correct=True, duration_ms=2000))

    correction = _correct_reading(old.id, document_id, "辛い", "からい")

    assert correction.kept
    cards = _cards(committed_engine)
    assert set(cards) == {_word("辛い", "つらい"), _word("辛い", "からい")}
    assert cards[_word("辛い", "つらい")].last_review is not None
    with committed_engine.connect() as conn:
        reviewed = (
            conn.execute(text("SELECT card_id FROM study_reviews")).scalars().all()
        )
    # The correction itself is no review.
    assert reviewed == [old.id]


def test_a_correction_to_a_word_already_carded_restores_that_card(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    other = create_tokenized_document(text="辛い")
    _correct_reading(old.id, other, "辛い", "からい")
    [tsurai] = _cards(committed_engine).values()
    suspend_card(tsurai.id)
    again = _card_for(document_id, "辛い")

    correction = _correct_reading(again.id, document_id, "辛い", "からい")

    assert correction.card.id == tsurai.id
    assert not correction.card.suspended


def test_correcting_to_a_reading_with_no_entry_leaves_the_song_no_card(
    committed_engine,
):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")

    correction = _correct_reading(old.id, document_id, "辛い", "からつらい")

    assert correction.card is None
    assert not correction.kept
    assert _cards(committed_engine) == {}


def test_a_card_the_token_had_already_left_is_kept(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    # The reading changed in the reading view while the card was on screen.
    _correct_reading(
        _card_for(create_tokenized_document(text="君"), "君").id,
        document_id,
        "辛い",
        "からい",
    )

    correction = _correct_reading(old.id, document_id, "辛い", "つらい")

    assert correction.kept
    assert _word("辛い", "つらい") in _cards(committed_engine)


def test_correcting_a_katakana_cards_word_moves_the_song_to_the_picked_word(
    committed_engine,
):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    token = _katakana_token(document_id)
    old = add_token_card(document_id, token.id, piece=AU)

    correction = correct_card_word(
        old.id,
        CardWordCorrection(
            document_id=document_id, token_id=token.id, piece=AU, spelling="合う"
        ),
    )

    assert (correction.card.lookup_form, correction.card.reading) == ("合う", "あう")
    assert not correction.kept
    assert set(_cards(committed_engine)) == {_word("合う", "あう")}


def test_correcting_another_users_card_is_refused(committed_engine, other_user):
    document_id = create_tokenized_document(text="辛い")
    with as_user(other_user):
        theirs = create_tokenized_document(text="辛い")
        card = _card_for(theirs, "辛い")

    with pytest.raises(HTTPException) as exc:
        _correct_reading(card.id, document_id, "辛い", "からい")

    assert exc.value.status_code == 404
    assert document_tokens(document_id, "辛い")[0].gloss.reading == "つらい"


def test_correcting_from_another_users_song_is_refused(committed_engine, other_user):
    card = _card_for(create_tokenized_document(text="辛い"), "辛い")
    with as_user(other_user):
        theirs = create_tokenized_document(text="辛い")
        [token] = document_tokens(theirs, "辛い")

    with pytest.raises(HTTPException) as exc:
        correct_card_reading(
            card.id,
            CardReadingCorrection(
                document_id=theirs, token_id=token.id, reading="からい"
            ),
        )

    assert exc.value.status_code == 404
    with as_user(other_user):
        assert document_tokens(theirs, "辛い")[0].gloss.reading == "つらい"


def test_the_queue_says_how_each_cards_word_can_be_corrected(committed_engine):
    start_song_session(create_tokenized_document(text="会いたい。"))
    document_id = create_tokenized_document(
        text="君の声が聞こえてる。\nボクノアイタイ。"
    )

    lines = {
        card.lookup_form: card.line for card in start_song_session(document_id).cards
    }

    assert (lines["君"].correction, lines["君"].piece) == ("reading", None)
    assert lines["てる"].correction is None
    assert (lines["会う"].correction, lines["会う"].piece) == ("word", AU)
    # Grammar sung in katakana.
    assert lines["たい"].correction is None


def test_an_accepted_phrase_cant_be_corrected_from_its_card(committed_engine):
    from app.main import PhraseAcceptance
    from tests.support import accept_phrase_suggestions_endpoint

    document_id = create_tokenized_document(text="真に受けてみて")
    [suggestion] = [
        c.id
        for t in get_document_tokens(document_id)
        for c in t.conflicts
        if c.kind == "phrase"
    ]
    accept_phrase_suggestions_endpoint(
        document_id, PhraseAcceptance(conflict_ids=[suggestion])
    )

    lines = {
        card.lookup_form: card.line for card in start_song_session(document_id).cards
    }

    assert lines["真に受ける"].correction is None
