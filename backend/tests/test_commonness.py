"""How common a word is, and the order new words enroll in by it.

The expected bands are JMDict's own tags as jamdict-data pins them."""

from __future__ import annotations

from app.cards import CardKey, HarvestedWord, enrollment_order
from app.commonness import (
    COMMON_UNRANKED_BAND,
    UNRANKED_KANJI,
    UNTAGGED_BAND,
    jmdict_bands,
    rarest_kanji_ranks,
)
from tests.support import word_key


def _band(lookup_form: str, reading: str, idseq: int | None = None) -> int:
    [band] = jmdict_bands([(lookup_form, None, reading, idseq)])
    return band


# Bands


def test_a_word_marked_common_without_an_nf_band_ranks_ahead_of_every_band():
    # 君 is ichi1 only: the newspaper count the nf bands come from skips it.
    assert _band("君", "きみ") == COMMON_UNRANKED_BAND


def test_a_word_has_its_nf_band():
    assert _band("夢", "ゆめ") == 2


def test_an_nf_band_wins_over_a_bare_common_tag():
    # 消える is ichi1 as well as nf39.
    assert _band("消える", "きえる") == 39


def test_the_reading_s_tags_count_when_the_spelling_has_none():
    # 抱きしめる's kanji form is untagged; だきしめる is nf47.
    assert _band("抱きしめる", "だきしめる") == 47


def test_an_untagged_word_ranks_last():
    assert _band("煌めく", "きらめく") == UNTAGGED_BAND


def test_a_word_with_no_jmdict_entry_ranks_last():
    assert _band("無い言葉", "ないことば") == UNTAGGED_BAND


def test_the_alternate_spelling_is_tried_too():
    [band] = jmdict_bands([("無い言葉", "夢", "ゆめ", None)])
    assert band == 2


def test_a_kana_word_takes_its_most_common_entry():
    # たい is 対 (ichi1), 帯 (nf09), 鯛 (nf30) and 他意 (nf37), among others.
    assert _band("たい", "たい") == COMMON_UNRANKED_BAND


def test_a_word_keyed_by_its_entry_takes_only_that_entry_s_band():
    assert _band("たい", "たい", idseq=1406940) == 37  # 他意


def test_bands_come_back_in_the_order_asked():
    assert jmdict_bands(
        [("煌めく", None, "きらめく", None), ("夢", None, "ゆめ", None)]
    ) == [UNTAGGED_BAND, 2]


# Kanji


def test_a_word_s_kanji_rank_is_its_least_used_kanji_s():
    # 聞 is 319th, 呼 498th.
    assert rarest_kanji_ranks(["聞こえる", "呼ぶ"]) == [319, 498]


def test_a_kana_word_has_no_kanji_to_rank():
    assert rarest_kanji_ranks(["ずっと"]) == [0]


def test_a_kanji_kanjidic_doesn_t_rank_is_rarer_than_every_ranked_one():
    assert rarest_kanji_ranks(["儚い"]) == [UNRANKED_KANJI]


def test_the_repeat_mark_doesn_t_count():
    assert rarest_kanji_ranks(["時々"]) == rarest_kanji_ranks(["時"])


# Enrollment order


def _word(key, occurrences: int, first_position: int) -> HarvestedWord:
    return HarvestedWord(key, None, occurrences, first_position)


def test_enrollment_order():
    yume = _word(word_key("夢", "ゆめ"), 1, 0)  # nf02, 夢 943rd
    yobu = _word(word_key("呼ぶ", "よぶ"), 1, 1)  # nf02, 呼 498th
    kirameku = _word(word_key("煌めく", "きらめく"), 5, 2)  # untagged
    kimi = _word(word_key("君", "きみ"), 1, 3)  # common, 君 947th
    zutto = _word(word_key("ずっと", "ずっと"), 1, 4)  # common, no kanji
    mou = _word(word_key("もう", "もう"), 2, 5)  # common, no kanji
    teru = _word(CardKey("grammar", "てる", None), 1, 6)

    assert enrollment_order([yume, yobu, kirameku, kimi, zutto, mou, teru]) == [
        # Grammar first, whatever its count.
        teru,
        # Band 0, kana before kanji; between kana words, the more sung first.
        mou,
        zutto,
        kimi,
        # nf02, the more used kanji first.
        yobu,
        yume,
        # Untagged, however often it's sung.
        kirameku,
    ]
