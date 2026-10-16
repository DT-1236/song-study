"""Managing cards from a song's words, and correcting which word a token is
from a card being studied: its reading, or for a token sung in katakana,
which word each of its pieces is."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.glosses import with_picked_words
from app.main import (
    CardReadingCorrection,
    CardWordCorrection,
    PushOut,
    ReviewAnswer,
)
from tests.support import (
    FORMER,
    LUCK,
    ORIGIN,
    SOME,
    TO_FIT,
    YES,
    add_token_card,
    as_user,
    correct_card_reading,
    correct_card_word,
    create_tokenized_document,
    document_tokens,
    get_document_tokens,
    get_document_words,
    get_piece_words,
    pick_piece_word,
    push_out_card,
    review_card,
    start_song_session,
    suspend_card,
    user_cards,
    word_key,
)

# ボク/ノ/アイ/タイ: 僕, the の between two words, 会う, and たい attached to it.
KATAKANA_SONG = "ボクノアイタイ。"
BOKU, NO, AU, TAI = range(4)

# JMDict's entry for 僕.
_I = 1521400


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


def test_every_token_of_a_predicate_group_stands_for_its_headword_key(committed_engine):
    document_id = create_tokenized_document(text="聞こえてるんだって")

    [word] = [w for w in get_document_words(document_id) if w.kind == "recognition"]

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

    # The grammar attached to a word is offered too; the の between two
    # words isn't.
    assert set(words) == {("僕", "ぼく"), ("会う", "あう"), ("たい", None)}
    assert words[("たい", None)].piece == TAI
    assert words[("僕", "ぼく")].piece == BOKU
    assert words[("会う", "あう")].piece == AU
    assert words[("会う", "あう")].token_ids == [token.id]


# Adding a word of a katakana token


def test_a_word_of_a_katakana_token_is_added_by_its_piece(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    card = add_token_card(document_id, _katakana_token(document_id).id, piece=AU)

    assert (card.lookup_form, card.reading) == ("会う", "あう")


def test_grammar_attached_to_a_katakana_word_is_added_by_its_piece(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    card = add_token_card(document_id, _katakana_token(document_id).id, piece=TAI)

    assert (card.kind, card.lookup_form, card.reading) == ("grammar", "たい", None)


@pytest.mark.parametrize(
    "piece",
    [
        None,
        # Grammar between two words.
        NO,
        # Past the last piece.
        9,
    ],
)
def test_a_katakana_token_can_only_be_added_by_a_piece_with_a_card(
    committed_engine, piece
):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    with pytest.raises(HTTPException) as exc:
        add_token_card(document_id, _katakana_token(document_id).id, piece=piece)

    assert exc.value.status_code == 422
    assert user_cards() == {}


def test_a_token_not_sung_in_katakana_cant_be_added_by_a_piece(committed_engine):
    document_id = create_tokenized_document(text="君")

    with pytest.raises(HTTPException) as exc:
        add_token_card(document_id, document_tokens(document_id, "君")[0].id, piece=0)

    assert exc.value.status_code == 422


# Which word a piece of katakana is


def test_a_katakana_piece_offers_every_word_with_its_reading(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    options = get_piece_words(document_id, _katakana_token(document_id).id, AU)

    assert {"会う", "合う"} <= {option.spelling for option in options}
    assert all(option.gloss for option in options)


def test_words_written_alike_are_each_offered(committed_engine):
    # キミ/ノ/モト: 君, の, and もと, which is 元 for "origin" and for
    # "former", two entries.
    document_id = create_tokenized_document(text="キミノモト。")
    [token] = document_tokens(document_id, "キミノモト")

    options = get_piece_words(document_id, token.id, 2)

    assert [o.idseq for o in options if o.spelling == "元"] == [ORIGIN, FORMER]
    assert len({tuple(o.gloss) for o in options}) == len(options)


def test_the_current_word_is_the_one_marked_and_follows_a_pick(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    token = _katakana_token(document_id)

    before = get_piece_words(document_id, token.id, AU)
    [guessed] = [o for o in before if o.current]
    other = next(o for o in before if o.idseq != guessed.idseq)
    pick_piece_word(document_id, [token.id], AU, other.idseq)
    after = get_piece_words(document_id, token.id, AU)

    assert [o.idseq for o in after if o.current] == [other.idseq]


def test_a_grammar_piece_offers_no_words(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    with pytest.raises(HTTPException) as exc:
        get_piece_words(document_id, _katakana_token(document_id).id, NO)

    assert exc.value.status_code == 422


def _pick(document_id: int, token_ids: list[int], idseq: int, piece: int = AU):
    return pick_piece_word(document_id, token_ids, piece, idseq)


def test_picking_another_word_for_a_piece_glosses_it_as_thatword_key(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    token = _katakana_token(document_id)

    [updated] = _pick(document_id, [token.id], TO_FIT)

    piece = updated.gloss.pieces[AU]
    assert (piece.surface, piece.reading) == ("合う", "あう")
    # 合う's senses alone, no longer 会う's.
    assert {sense.entry_idseq for sense in piece.senses} == {TO_FIT}
    # The rest are as they were.
    assert updated.gloss.pieces[BOKU].surface == "僕"
    assert get_document_tokens(document_id)[0].gloss.pieces[AU].surface == "合う"


def test_a_picked_word_is_the_one_the_song_offers_and_studies(committed_engine):
    start_song_session(create_tokenized_document(text="会いたい。合いたい。"))
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    _pick(document_id, [_katakana_token(document_id).id], TO_FIT)

    assert ("合う", "あう") in _words(document_id)
    assert ("会う", "あう") not in _words(document_id)
    [line] = [
        card.line
        for card in start_song_session(document_id).cards
        if card.lookup_form == "合う"
    ]
    assert line.written_as == "合う"


@pytest.mark.parametrize("idseq", [YES, SOME])
def test_a_word_picked_in_kana_is_glossed_as_its_own_entry(committed_engine, idseq):
    # ボク/ノ/ウン: 僕, の, and うん, whose guess shows the senses of every
    # word read うん, 運 among them.
    document_id = create_tokenized_document(text="ボクノウン。")
    [token] = document_tokens(document_id, "ボクノウン")
    assert {YES, SOME, LUCK} <= {s.entry_idseq for s in token.gloss.pieces[2].senses}

    [updated] = _pick(document_id, [token.id], idseq, piece=2)

    piece = updated.gloss.pieces[2]
    assert piece.surface == "うん"
    assert {sense.entry_idseq for sense in piece.senses} == {idseq}
    assert ("うん", "うん") in _words(document_id)


def test_a_word_picked_from_two_written_alike_is_glossed_as_that_one(
    committed_engine,
):
    document_id = create_tokenized_document(text="キミノモト。")
    [token] = document_tokens(document_id, "キミノモト")

    [updated] = _pick(document_id, [token.id], FORMER, piece=2)

    piece = updated.gloss.pieces[2]
    assert piece.surface == "元"
    assert {sense.entry_idseq for sense in piece.senses} == {FORMER}


def test_words_picked_from_two_written_alike_are_two_cards(committed_engine):
    origin_song = create_tokenized_document(text="キミノモト。")
    former_song = create_tokenized_document(text="キミノモト。")
    [origin_token] = document_tokens(origin_song, "キミノモト")
    [former_token] = document_tokens(former_song, "キミノモト")
    _pick(origin_song, [origin_token.id], ORIGIN, piece=2)
    _pick(former_song, [former_token.id], FORMER, piece=2)

    origin = add_token_card(origin_song, origin_token.id, piece=2)
    former = add_token_card(former_song, former_token.id, piece=2)

    assert set(user_cards()) == {
        word_key("元", "もと", ORIGIN),
        word_key("元", "もと", FORMER),
    }
    assert _words(former_song)[("元", "もと")].card.id == former.id
    assert _words(origin_song)[("元", "もと")].card.id == origin.id


@pytest.mark.parametrize("idseq", [YES, SOME])
def test_a_picked_words_card_answers_with_its_entry_alone(committed_engine, idseq):
    document_id = create_tokenized_document(text="ボクノウン。")
    [token] = document_tokens(document_id, "ボクノウン")
    _pick(document_id, [token.id], idseq, piece=2)
    add_token_card(document_id, token.id, piece=2)

    [card] = start_song_session(document_id).cards

    assert card.idseq == idseq
    assert {sense.entry_idseq for sense in card.senses} == {idseq}


def test_a_pick_applies_to_every_token_given(committed_engine):
    document_id = create_tokenized_document(text="ボクノアイタイ。ボクノアイタイ。")
    tokens = document_tokens(document_id, "ボクノアイタイ")

    _pick(document_id, [t.id for t in tokens], TO_FIT)

    assert [
        t.gloss.pieces[AU].surface
        for t in document_tokens(document_id, "ボクノアイタイ")
    ] == ["合う", "合う"]


@pytest.mark.parametrize(
    "piece, idseq",
    [
        # Not a word read あう.
        (AU, _I),
        # Grammar.
        (TAI, TO_FIT),
    ],
)
def test_picking_a_word_a_piece_cant_be_is_refused(committed_engine, piece, idseq):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    token = _katakana_token(document_id)

    with pytest.raises(HTTPException) as exc:
        _pick(document_id, [token.id], idseq, piece=piece)

    assert exc.value.status_code == 422
    assert get_document_tokens(document_id)[0].gloss.pieces[AU].surface == "会う"


def test_a_pick_is_left_out_once_its_piece_reads_otherwise():
    composite = {
        "looked_up_as": "あいたい",
        "pieces": [
            {
                "surface": "あう",
                "key": ["あう", "あう"],
                "alt_lookup_form": None,
                "normalized_form": None,
            },
            {
                "surface": "たい",
                "key": None,
                "alt_lookup_form": None,
                "normalized_form": "たい",
            },
        ],
    }

    picked = with_picked_words(
        composite,
        # The gloss was built again and split the katakana otherwise.
        [(0, "あい", TO_FIT), (1, "たい", TO_FIT), (5, "あう", TO_FIT)],
    )

    assert picked == composite


# Correcting a card's word from a session


def _card_for(document_id: int, surface: str, piece: int | None = None):
    return add_token_card(
        document_id, document_tokens(document_id, surface)[0].id, piece=piece
    )


def _correct_reading(
    card_id: int,
    document_id: int,
    surface: str,
    reading: str,
    review_id: int | None = None,
):
    return correct_card_reading(
        card_id,
        CardReadingCorrection(
            document_id=document_id,
            token_id=document_tokens(document_id, surface)[0].id,
            reading=reading,
            review_id=review_id,
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
    assert set(user_cards()) == {word_key("辛い", "からい")}
    assert [(w.lookup_form, w.reading) for w in get_document_words(document_id)] == [
        ("辛い", "からい")
    ]


def _answer(card_id: int, correct: bool = True):
    return review_card(card_id, ReviewAnswer(correct=correct, duration_ms=2000))


def _reviews(engine) -> list[int]:
    with engine.connect() as conn:
        return (
            conn.execute(text("SELECT id FROM study_reviews ORDER BY id"))
            .scalars()
            .all()
        )


def _tsurai():
    return user_cards()[word_key("辛い", "つらい")]


def test_a_corrected_card_with_reviews_keeps_them(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    review = _answer(old.id)

    correction = _correct_reading(old.id, document_id, "辛い", "からい")

    assert correction.kept
    assert set(user_cards()) == {word_key("辛い", "つらい"), word_key("辛い", "からい")}
    assert _tsurai().last_review is not None
    # The correction itself is no review.
    assert _reviews(committed_engine) == [review.review_id]


def test_correcting_a_card_just_answered_undoes_its_review(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    review = _answer(old.id)

    correction = _correct_reading(
        old.id, document_id, "辛い", "からい", review.review_id
    )

    # With its one review undone, nothing was learned on it.
    assert not correction.kept
    assert set(user_cards()) == {word_key("辛い", "からい")}
    assert _reviews(committed_engine) == []


def test_undoing_a_review_restores_the_schedule_from_before_it(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    first = _answer(old.id)
    after_first = _tsurai()
    second = _answer(old.id, correct=False)

    correction = _correct_reading(
        old.id, document_id, "辛い", "からい", second.review_id
    )

    assert correction.kept
    assert _tsurai() == after_first
    assert _reviews(committed_engine) == [first.review_id]


def test_a_review_the_schedule_has_moved_on_from_stands(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    first = _answer(old.id)
    # Answered again elsewhere while this card was on screen.
    second = _answer(old.id)
    after_second = _tsurai()

    correction = _correct_reading(
        old.id, document_id, "辛い", "からい", first.review_id
    )

    assert correction.kept
    assert _tsurai() == after_second
    assert _reviews(committed_engine) == [first.review_id, second.review_id]


def test_a_review_pushed_out_since_stands(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    review = _answer(old.id)
    push_out_card(old.id, PushOut(months=1))
    pushed = _tsurai()

    _correct_reading(old.id, document_id, "辛い", "からい", review.review_id)

    assert _tsurai() == pushed
    assert _reviews(committed_engine) == [review.review_id]


def test_a_review_whose_schedule_changed_without_a_new_last_review_stands(
    committed_engine,
):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    review = _answer(old.id)
    with committed_engine.begin() as conn:
        conn.execute(
            text("UPDATE study_cards SET due = due + interval '1 day' WHERE id = :id"),
            {"id": old.id},
        )
    moved = _tsurai()

    _correct_reading(old.id, document_id, "辛い", "からい", review.review_id)

    assert _tsurai() == moved
    assert _reviews(committed_engine) == [review.review_id]


def test_undoing_another_cards_review_is_refused(committed_engine):
    document_id = create_tokenized_document(text="辛い 君")
    old = _card_for(document_id, "辛い")
    review = _answer(_card_for(document_id, "君").id)

    with pytest.raises(HTTPException) as caught:
        _correct_reading(old.id, document_id, "辛い", "からい", review.review_id)

    assert caught.value.status_code == 404
    assert set(user_cards()) == {word_key("辛い", "つらい"), word_key("君", "きみ")}
    assert _reviews(committed_engine) == [review.review_id]


def test_a_correction_to_a_word_already_carded_restores_that_card(committed_engine):
    document_id = create_tokenized_document(text="辛い")
    old = _card_for(document_id, "辛い")
    other = create_tokenized_document(text="辛い")
    _correct_reading(old.id, other, "辛い", "からい")
    [tsurai] = user_cards().values()
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
    assert user_cards() == {}


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
    assert word_key("辛い", "つらい") in user_cards()


def test_correcting_a_katakana_cards_word_moves_the_song_to_the_pickedword_key(
    committed_engine,
):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    token = _katakana_token(document_id)
    old = add_token_card(document_id, token.id, piece=AU)

    correction = correct_card_word(
        old.id,
        CardWordCorrection(
            document_id=document_id, token_id=token.id, piece=AU, idseq=TO_FIT
        ),
    )

    assert (correction.card.lookup_form, correction.card.reading) == ("合う", "あう")
    assert not correction.kept
    # No other word is 合う read あう, so it's the card of the word written in
    # kanji too.
    assert set(user_cards()) == {word_key("合う", "あう")}


def test_correcting_a_katakana_cards_word_to_one_written_alike_moves_it(
    committed_engine,
):
    document_id = create_tokenized_document(text="キミノモト。")
    [token] = document_tokens(document_id, "キミノモト")
    _pick(document_id, [token.id], ORIGIN, piece=2)
    old = add_token_card(document_id, token.id, piece=2)

    correction = correct_card_word(
        old.id,
        CardWordCorrection(
            document_id=document_id, token_id=token.id, piece=2, idseq=FORMER
        ),
    )

    assert not correction.kept
    assert set(user_cards()) == {word_key("元", "もと", FORMER)}
    assert correction.card.idseq == FORMER


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


def test_correcting_an_accepted_phrases_reading_from_its_card_is_refused(
    committed_engine,
):
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
    card = _card_for(document_id, "真")

    with pytest.raises(HTTPException) as exc:
        _correct_reading(card.id, document_id, "真", "しん")

    assert exc.value.status_code == 422
    assert get_document_tokens(document_id)[0].group_kind == "phrase"
