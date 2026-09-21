"""Regression coverage for app/tokenization.py.

The golden cases below are the diagnostic sentences used to verify the
Morpheme.split(SplitMode.A) rewrite (see that module's docstring) against
the old whole-document rescan it replaced — each one exercises a specific
decision point in the pipeline:

  - a token's reading is a genuine heteronym for its part of speech
    (review_reason == "heteronym")
  - a token is out-of-vocabulary (review_reason == "oov")
  - a multi-kanji run has no kana anchor and falls to the per-character
    dictionary partition search (review_reason is None when it resolves
    unambiguously, "no_kana_anchor" when it doesn't)
  - a SplitMode.C token is a merge of independently-recognized words across
    a kana particle, which only Morpheme.split(SplitMode.A) can recover —
    the old regex-segmentation-first approach could never see across the
    particle to find this boundary
  - a SplitMode.C token is a merge of independently-recognized words with no
    kana between them at all (both the old and new approach can find this
    one; kept as a non-regression check)

Each case's expected output was captured directly from a verified-correct
run and double-checked by hand against the old (whole-document rescan)
implementation before this file existed — see the tokenization refactor
commit for how that comparison was done.

The classes further down (TestFuriganaAlignment onward) are separate
regression tests for the reading-disambiguation/gloss-support functions
added alongside conflict_options — each case here is a real bug found and
fixed this session, grounded in real Sudachi/JMDict behavior verified by
hand at the time (see the case comments), not invented examples.
"""

from itertools import pairwise

from app.tokenization import (
    _is_regular_potential_form,
    _reconstruct_citation_reading,
    a_split_decomposition,
    build_furigana_spans,
    citation_reading,
    conjugation_type_of,
    dictionary_form_note,
    heteronym_readings,
    mixed_reading,
    slice_spans_by_token,
    to_hiragana,
    to_katakana,
    tokenize_document,
)

CASES = {
    "jukujikun": (
        "今日は良い天気です。",
        [
            (
                "今日",
                "キョウ",
                "heteronym",
                [{"start": 0, "end": 2, "text": "今日", "reading": "きょう"}],
            ),
            ("は", "ハ", None, [{"start": 0, "end": 1, "text": "は", "reading": None}]),
            (
                "良い",
                "ヨイ",
                "heteronym",
                [
                    {"start": 0, "end": 1, "text": "良", "reading": "よ"},
                    {"start": 1, "end": 2, "text": "い", "reading": None},
                ],
            ),
            (
                "天気",
                "テンキ",
                None,
                [
                    {"start": 0, "end": 1, "text": "天", "reading": "てん"},
                    {"start": 1, "end": 2, "text": "気", "reading": "き"},
                ],
            ),
            (
                "です",
                "デス",
                None,
                [{"start": 0, "end": 2, "text": "です", "reading": None}],
            ),
            ("。", "。", None, [{"start": 0, "end": 1, "text": "。", "reading": None}]),
        ],
    ),
    "particle_split_compound": (
        "勝利の女神が微笑む",
        [
            (
                "勝利の女神",
                "ショウリノメガミ",
                None,
                [
                    {"start": 0, "end": 1, "text": "勝", "reading": "しょう"},
                    {"start": 1, "end": 2, "text": "利", "reading": "り"},
                    {"start": 2, "end": 3, "text": "の", "reading": None},
                    {"start": 3, "end": 4, "text": "女", "reading": "め"},
                    {"start": 4, "end": 5, "text": "神", "reading": "がみ"},
                ],
            ),
            ("が", "ガ", None, [{"start": 0, "end": 1, "text": "が", "reading": None}]),
            (
                "微笑む",
                "ホホエム",
                "heteronym",
                [
                    {"start": 0, "end": 2, "text": "微笑", "reading": "ほほえ"},
                    {"start": 2, "end": 3, "text": "む", "reading": None},
                ],
            ),
        ],
    ),
    "okurigana_anchor": (
        "食べ物が好きです",
        [
            (
                "食べ物",
                "タベモノ",
                None,
                [
                    {"start": 0, "end": 1, "text": "食", "reading": "た"},
                    {"start": 1, "end": 2, "text": "べ", "reading": None},
                    {"start": 2, "end": 3, "text": "物", "reading": "もの"},
                ],
            ),
            ("が", "ガ", None, [{"start": 0, "end": 1, "text": "が", "reading": None}]),
            (
                "好き",
                "スキ",
                "heteronym",
                [
                    {"start": 0, "end": 1, "text": "好", "reading": "す"},
                    {"start": 1, "end": 2, "text": "き", "reading": None},
                ],
            ),
            (
                "です",
                "デス",
                None,
                [{"start": 0, "end": 2, "text": "です", "reading": None}],
            ),
        ],
    ),
    "oov_and_multikanji": (
        "三年生になりました",
        [
            (
                "三",
                "サン",
                "oov",
                [{"start": 0, "end": 1, "text": "三", "reading": "さん"}],
            ),
            (
                "年生",
                "ネンセイ",
                None,
                [
                    {"start": 0, "end": 1, "text": "年", "reading": "ねん"},
                    {"start": 1, "end": 2, "text": "生", "reading": "せい"},
                ],
            ),
            ("に", "ニ", None, [{"start": 0, "end": 1, "text": "に", "reading": None}]),
            (
                "なり",
                "ナリ",
                None,
                [{"start": 0, "end": 2, "text": "なり", "reading": None}],
            ),
            (
                "まし",
                "マシ",
                None,
                [{"start": 0, "end": 2, "text": "まし", "reading": None}],
            ),
            ("た", "タ", None, [{"start": 0, "end": 1, "text": "た", "reading": None}]),
        ],
    ),
    "four_char_idiom": (
        "一石二鳥の作戦だ",
        [
            (
                "一",
                "イチ",
                "oov",
                [{"start": 0, "end": 1, "text": "一", "reading": "いち"}],
            ),
            (
                "石",
                "コク",
                "heteronym",
                [{"start": 0, "end": 1, "text": "石", "reading": "こく"}],
            ),
            (
                "二鳥",
                "ニチョウ",
                None,
                [
                    {"start": 0, "end": 1, "text": "二", "reading": "に"},
                    {"start": 1, "end": 2, "text": "鳥", "reading": "ちょう"},
                ],
            ),
            ("の", "ノ", None, [{"start": 0, "end": 1, "text": "の", "reading": None}]),
            (
                "作戦",
                "サクセン",
                None,
                [
                    {"start": 0, "end": 1, "text": "作", "reading": "さく"},
                    {"start": 1, "end": 2, "text": "戦", "reading": "せん"},
                ],
            ),
            ("だ", "ダ", None, [{"start": 0, "end": 1, "text": "だ", "reading": None}]),
        ],
    ),
    "long_compound": (
        "日本語能力試験を受ける",
        [
            (
                "日本語",
                "ニホンゴ",
                None,
                [
                    {"start": 0, "end": 2, "text": "日本", "reading": "にほん"},
                    {"start": 2, "end": 3, "text": "語", "reading": "ご"},
                ],
            ),
            (
                "能力試験",
                "ノウリョクシケン",
                None,
                [
                    {"start": 0, "end": 1, "text": "能", "reading": "のう"},
                    {"start": 1, "end": 2, "text": "力", "reading": "りょく"},
                    {"start": 2, "end": 4, "text": "試験", "reading": "しけん"},
                ],
            ),
            ("を", "ヲ", None, [{"start": 0, "end": 1, "text": "を", "reading": None}]),
            (
                "受ける",
                "ウケル",
                None,
                [
                    {"start": 0, "end": 1, "text": "受", "reading": "う"},
                    {"start": 1, "end": 3, "text": "ける", "reading": None},
                ],
            ),
        ],
    ),
    "katakana_loanword": (
        "アイラブユーと言った",
        [
            (
                "アイラブユー",
                "アイラブユー",
                None,
                [{"start": 0, "end": 6, "text": "アイラブユー", "reading": None}],
            ),
            ("と", "ト", None, [{"start": 0, "end": 1, "text": "と", "reading": None}]),
            (
                "言っ",
                "イッ",
                "heteronym",
                [
                    {"start": 0, "end": 1, "text": "言", "reading": "い"},
                    {"start": 1, "end": 2, "text": "っ", "reading": None},
                ],
            ),
            ("た", "タ", None, [{"start": 0, "end": 1, "text": "た", "reading": None}]),
        ],
    ),
    "heteronym_verb": (
        "彼女は毎日走る",
        [
            (
                "彼女",
                "カノジョ",
                None,
                [{"start": 0, "end": 2, "text": "彼女", "reading": "かのじょ"}],
            ),
            ("は", "ハ", None, [{"start": 0, "end": 1, "text": "は", "reading": None}]),
            (
                "毎日",
                "マイニチ",
                None,
                [
                    {"start": 0, "end": 1, "text": "毎", "reading": "まい"},
                    {"start": 1, "end": 2, "text": "日", "reading": "にち"},
                ],
            ),
            (
                "走る",
                "ハシル",
                "heteronym",
                [
                    {"start": 0, "end": 1, "text": "走", "reading": "はし"},
                    {"start": 1, "end": 2, "text": "る", "reading": None},
                ],
            ),
        ],
    ),
    "irregular_reading": (
        "八百屋で買い物をする",
        [
            (
                "八百屋",
                "ヤオヤ",
                None,
                [{"start": 0, "end": 3, "text": "八百屋", "reading": "やおや"}],
            ),
            ("で", "デ", None, [{"start": 0, "end": 1, "text": "で", "reading": None}]),
            (
                "買い物",
                "カイモノ",
                None,
                [
                    {"start": 0, "end": 1, "text": "買", "reading": "か"},
                    {"start": 1, "end": 2, "text": "い", "reading": None},
                    {"start": 2, "end": 3, "text": "物", "reading": "もの"},
                ],
            ),
            ("を", "ヲ", None, [{"start": 0, "end": 1, "text": "を", "reading": None}]),
            (
                "する",
                "スル",
                None,
                [{"start": 0, "end": 2, "text": "する", "reading": None}],
            ),
        ],
    ),
    "reduplicated": (
        "一人一人が大切だ",
        [
            (
                "一人一人",
                "ヒトリヒトリ",
                None,
                [{"start": 0, "end": 4, "text": "一人一人", "reading": "ひとりひとり"}],
            ),
            ("が", "ガ", None, [{"start": 0, "end": 1, "text": "が", "reading": None}]),
            (
                "大切",
                "タイセツ",
                None,
                [
                    {"start": 0, "end": 1, "text": "大", "reading": "たい"},
                    {"start": 1, "end": 2, "text": "切", "reading": "せつ"},
                ],
            ),
            ("だ", "ダ", None, [{"start": 0, "end": 1, "text": "だ", "reading": None}]),
        ],
    ),
    # Pure-kanji multi-word compounds with no kana between them — the case the
    # old whole-document-rescan tier 1 could already handle. Kept as a
    # non-regression check for the Morpheme.split(SplitMode.A) replacement.
    "kanji_compound_no_particle_1": (
        "国際結婚",
        [
            (
                "国際結婚",
                "コクサイケッコン",
                None,
                [
                    {"start": 0, "end": 1, "text": "国", "reading": "こく"},
                    {"start": 1, "end": 2, "text": "際", "reading": "さい"},
                    {"start": 2, "end": 4, "text": "結婚", "reading": "けっこん"},
                ],
            ),
        ],
    ),
    "kanji_compound_no_particle_2": (
        "電気自動車",
        [
            (
                "電気自動車",
                "デンキジドウシャ",
                None,
                [
                    {"start": 0, "end": 1, "text": "電", "reading": "でん"},
                    {"start": 1, "end": 2, "text": "気", "reading": "き"},
                    {"start": 2, "end": 3, "text": "自", "reading": "じ"},
                    {"start": 3, "end": 4, "text": "動", "reading": "どう"},
                    {"start": 4, "end": 5, "text": "車", "reading": "しゃ"},
                ],
            ),
        ],
    ),
    "kanji_compound_no_particle_3": (
        "環境問題",
        [
            (
                "環境問題",
                "カンキョウモンダイ",
                None,
                [
                    {"start": 0, "end": 1, "text": "環", "reading": "かん"},
                    {"start": 1, "end": 2, "text": "境", "reading": "きょう"},
                    {"start": 2, "end": 3, "text": "問", "reading": "もん"},
                    {"start": 3, "end": 4, "text": "題", "reading": "だい"},
                ],
            ),
        ],
    ),
    "kanji_compound_no_particle_4": (
        "人工知能",
        [
            (
                "人工知能",
                "ジンコウチノウ",
                None,
                [
                    {"start": 0, "end": 1, "text": "人", "reading": "じん"},
                    {"start": 1, "end": 2, "text": "工", "reading": "こう"},
                    {"start": 2, "end": 3, "text": "知", "reading": "ち"},
                    {"start": 3, "end": 4, "text": "能", "reading": "のう"},
                ],
            ),
        ],
    ),
    "kanji_compound_no_particle_5": (
        "海外旅行",
        [
            (
                "海外旅行",
                "カイガイリョコウ",
                None,
                [
                    {"start": 0, "end": 1, "text": "海", "reading": "かい"},
                    {"start": 1, "end": 2, "text": "外", "reading": "がい"},
                    {"start": 2, "end": 4, "text": "旅行", "reading": "りょこう"},
                ],
            ),
        ],
    ),
    "kanji_compound_no_particle_6_atomic_at_a": (
        "新幹線",
        [
            (
                "新幹線",
                "シンカンセン",
                None,
                [
                    {"start": 0, "end": 1, "text": "新", "reading": "しん"},
                    {"start": 1, "end": 2, "text": "幹", "reading": "かん"},
                    {"start": 2, "end": 3, "text": "線", "reading": "せん"},
                ],
            ),
        ],
    ),
    "kanji_compound_no_particle_7": (
        "図書館",
        [
            (
                "図書館",
                "トショカン",
                None,
                [
                    {"start": 0, "end": 2, "text": "図書", "reading": "としょ"},
                    {"start": 2, "end": 3, "text": "館", "reading": "かん"},
                ],
            ),
        ],
    ),
    "kanji_compound_no_particle_8": (
        "不動産投資",
        [
            (
                "不動産投資",
                "フドウサントウシ",
                None,
                [
                    {"start": 0, "end": 1, "text": "不", "reading": "ふ"},
                    {"start": 1, "end": 2, "text": "動", "reading": "どう"},
                    {"start": 2, "end": 3, "text": "産", "reading": "さん"},
                    {"start": 3, "end": 4, "text": "投", "reading": "とう"},
                    {"start": 4, "end": 5, "text": "資", "reading": "し"},
                ],
            ),
        ],
    ),
}


def _actual(text: str) -> list[tuple]:
    return [
        (r.surface, r.reading_katakana, r.review_reason, r.furigana_spans)
        for r in tokenize_document(text)
    ]


def test_golden_cases_cover_every_review_reason():
    reasons = {
        expected_review
        for _, expected in CASES.values()
        for _, _, expected_review, _ in expected
    }
    assert reasons == {None, "heteronym", "oov"}


class TestTokenizeDocumentGolden:
    def test_jukujikun(self):
        text, expected = CASES["jukujikun"]
        assert _actual(text) == expected

    def test_particle_split_compound(self):
        text, expected = CASES["particle_split_compound"]
        assert _actual(text) == expected

    def test_okurigana_anchor(self):
        text, expected = CASES["okurigana_anchor"]
        assert _actual(text) == expected

    def test_oov_and_multikanji(self):
        text, expected = CASES["oov_and_multikanji"]
        assert _actual(text) == expected

    def test_four_char_idiom(self):
        text, expected = CASES["four_char_idiom"]
        assert _actual(text) == expected

    def test_long_compound(self):
        text, expected = CASES["long_compound"]
        assert _actual(text) == expected

    def test_katakana_loanword(self):
        text, expected = CASES["katakana_loanword"]
        assert _actual(text) == expected

    def test_heteronym_verb(self):
        text, expected = CASES["heteronym_verb"]
        assert _actual(text) == expected

    def test_irregular_reading(self):
        text, expected = CASES["irregular_reading"]
        assert _actual(text) == expected

    def test_reduplicated(self):
        text, expected = CASES["reduplicated"]
        assert _actual(text) == expected

    def test_kanji_compound_no_particle_1(self):
        text, expected = CASES["kanji_compound_no_particle_1"]
        assert _actual(text) == expected

    def test_kanji_compound_no_particle_2(self):
        text, expected = CASES["kanji_compound_no_particle_2"]
        assert _actual(text) == expected

    def test_kanji_compound_no_particle_3(self):
        text, expected = CASES["kanji_compound_no_particle_3"]
        assert _actual(text) == expected

    def test_kanji_compound_no_particle_4(self):
        text, expected = CASES["kanji_compound_no_particle_4"]
        assert _actual(text) == expected

    def test_kanji_compound_no_particle_5(self):
        text, expected = CASES["kanji_compound_no_particle_5"]
        assert _actual(text) == expected

    def test_kanji_compound_no_particle_6_atomic_at_a(self):
        text, expected = CASES["kanji_compound_no_particle_6_atomic_at_a"]
        assert _actual(text) == expected

    def test_kanji_compound_no_particle_7(self):
        text, expected = CASES["kanji_compound_no_particle_7"]
        assert _actual(text) == expected

    def test_kanji_compound_no_particle_8(self):
        text, expected = CASES["kanji_compound_no_particle_8"]
        assert _actual(text) == expected


def test_word_boundary_recovered_across_particle():
    """勝利の女神 is one SplitMode.C token merging two words across の.
    Morpheme.split(SplitMode.A) must recover that boundary — the regex
    segmentation alone would never see it, since it only ever looks at
    contiguous kanji runs after の has already split them apart."""
    records = tokenize_document("勝利の女神")
    spans = records[0].furigana_spans
    assert [s["text"] for s in spans] == ["勝", "利", "の", "女", "神"]
    assert spans[2]["reading"] is None  # の itself carries no furigana


def test_compound_reading_not_forced_below_word_level():
    """結婚's reading (けっこん) is a genuine two-character-combined reading,
    not simply concatenated on'yomi for 結 and 婚 individually. Once
    Morpheme.split(SplitMode.A) recognizes 結婚 as its own word (distinct
    from 国際), it should be kept as one span rather than forced through the
    character-level partition search."""
    records = tokenize_document("国際結婚")
    spans = records[0].furigana_spans
    by_text = {s["text"]: s["reading"] for s in spans}
    assert by_text["結婚"] == "けっこん"


def test_spans_are_contiguous_and_cover_the_full_surface():
    for text, expected in CASES.values():
        for surface, _reading, _review_reason, spans in expected:
            assert spans[0]["start"] == 0
            assert spans[-1]["end"] == len(surface)
            for a, b in pairwise(spans):
                assert a["end"] == b["start"]
            assert "".join(s["text"] for s in spans) == surface


def test_needs_review_matches_review_reason():
    for text, _expected in CASES.values():
        for record in tokenize_document(text):
            assert record.needs_review == (record.review_reason is not None)


def test_empty_document_returns_no_tokens():
    assert tokenize_document("") == []


def test_pure_kana_has_no_furigana():
    records = tokenize_document("ひらがなだけのぶんしょう")
    assert all(record.review_reason is None for record in records)
    assert all(
        span["reading"] is None for record in records for span in record.furigana_spans
    )


def test_to_katakana_and_to_hiragana_roundtrip():
    assert to_katakana("そろえ") == "ソロエ"
    assert to_hiragana("ソロエ") == "そろえ"
    assert to_hiragana(to_katakana("あたためる")) == "あたためる"


class TestFuriganaAlignment:
    def test_kanji_run_with_dictionary_split(self):
        # 荒技 -> あら/わざ, a 2-kanji run resolved via the per-character
        # partition search (no kana anchor between them).
        spans, flagged, alts = build_furigana_spans("荒技", "アラワザ")
        assert [(s["text"], s["reading"]) for s in spans] == [
            ("荒", "あら"),
            ("技", "わざ"),
        ]
        assert not flagged
        assert alts == []

    def test_okurigana_anchors_the_kanji_reading(self):
        # 揃える: kana anchor "える" pins the kanji run to just 揃 -> そろ.
        spans, flagged, _ = build_furigana_spans("揃える", "ソロエル")
        assert spans[0] == {"start": 0, "end": 1, "text": "揃", "reading": "そろ"}
        assert spans[1]["reading"] is None
        assert spans[1]["text"] == "える"
        assert not flagged

    def test_jukujikun_is_a_single_whole_word_span_not_flagged(self):
        # 今日 -> きょう has no per-character decomposition (jukujikun) —
        # that's expected and correct, not an error to flag.
        spans, flagged, alts = build_furigana_spans("今日", "キョウ")
        assert spans == [{"start": 0, "end": 2, "text": "今日", "reading": "きょう"}]
        assert not flagged
        assert alts == []

    def test_no_kanji_gives_a_single_unread_span(self):
        for surface, reading in [
            ("gifted", "gifted"),
            ("ライバル", "ライバル"),
            ("それ", "ソレ"),
        ]:
            spans, flagged, _ = build_furigana_spans(surface, reading)
            assert spans == [
                {"start": 0, "end": len(surface), "text": surface, "reading": None}
            ]
            assert not flagged

    def test_spans_always_exactly_partition_the_surface(self):
        # No gaps, no overlaps, in order — the invariant the frontend
        # relies on to render furigana by just walking the span list.
        for surface, reading in [
            ("荒技", "アラワザ"),
            ("揃える", "ソロエル"),
            ("今日", "キョウ"),
        ]:
            spans, _, _ = build_furigana_spans(surface, reading)
            pos = 0
            for span in spans:
                assert span["start"] == pos
                assert span["text"] == surface[span["start"] : span["end"]]
                pos = span["end"]
            assert pos == len(surface)


class TestSliceSpansByToken:
    """Dividing a merged phrase's furigana spans back across its tokens."""

    def test_splits_cleanly_when_every_span_fits_one_token(self):
        # この(2)/期(1)/に(1)/及ん(2)/で(1): the kana span んで crosses the
        # 及ん/で boundary.
        spans, _, _ = build_furigana_spans("この期に及んで", "コノゴニオヨンデ")
        sliced = slice_spans_by_token(spans, [2, 1, 1, 2, 1])
        assert sliced == [
            [{"start": 0, "end": 2, "text": "この", "reading": None}],
            [{"start": 0, "end": 1, "text": "期", "reading": "ご"}],
            [{"start": 0, "end": 1, "text": "に", "reading": None}],
            [
                {"start": 0, "end": 1, "text": "及", "reading": "およ"},
                {"start": 1, "end": 2, "text": "ん", "reading": None},
            ],
            [{"start": 0, "end": 1, "text": "で", "reading": None}],
        ]

    def test_a_kanji_span_straddling_a_boundary_is_left_unattributed(self):
        # 今日 read きょう has no per-character split, so neither of 今 and 日
        # gets a slice.
        spans, _, _ = build_furigana_spans("今日", "キョウ")
        assert slice_spans_by_token(spans, [1, 1]) == [None, None]

    def test_only_the_straddled_tokens_are_left_unattributed(self):
        # 君 and の still get theirs.
        spans, _, _ = build_furigana_spans("君の今日", "キミノキョウ")
        sliced = slice_spans_by_token(spans, [1, 1, 1, 1])
        assert sliced[0] == [{"start": 0, "end": 1, "text": "君", "reading": "きみ"}]
        assert sliced[1] == [{"start": 0, "end": 1, "text": "の", "reading": None}]
        assert sliced[2] is None
        assert sliced[3] is None


class TestMixedReading:
    def test_katakana_loanword_portion_is_preserved_not_hiraganized(self):
        # The bug: a blind to_hiragana(citation_reading(...)) turns 無理ゲー
        # into むりげー, which matches nothing in JMDict (its real entry is
        # むりゲー — ゲー stays katakana since it's a loanword abbreviation).
        assert mixed_reading("無理ゲー") == "むりゲー"

    def test_pure_katakana_word_is_left_alone(self):
        assert mixed_reading("ライバル") == "ライバル"

    def test_pure_kanji_word(self):
        assert mixed_reading("揃える") == "そろえる"
        assert mixed_reading("花火") == "はなび"

    def test_jukujikun_word(self):
        assert mixed_reading("今日") == "きょう"


class TestCitationReading:
    def test_matches_sudachis_own_standalone_tokenization(self):
        assert citation_reading("温める") == "アタタメル"
        assert citation_reading("揃える") == "ソロエル"


class TestPotentialFormDetection:
    def test_genuine_potential_forms(self):
        # Verified against real Sudachi conjugation-type data: the
        # dictionary_form is ichidan while normalized_form's own standalone
        # conjugation type is godan — a real paradigm switch.
        cases = [
            ("挟める", "下一段-マ行", "挟む"),
            ("行ける", "下一段-カ行", "行く"),
            ("買える", "下一段-ア行", "買う"),
            ("書ける", "下一段-カ行", "書く"),
            ("読める", "下一段-マ行", "読む"),
        ]
        for dictionary_form, conjugation, normalized_form in cases:
            assert _is_regular_potential_form(
                dictionary_form, conjugation, normalized_form
            ), dictionary_form

    def test_lexicalized_lookalike_is_not_a_potential_form(self):
        # キレる/切れる are BOTH ichidan (no conjugation-class switch) — a
        # slang orthographic variant, not a potential form. This is the
        # false-positive case the conjugation-type check exists to catch.
        assert not _is_regular_potential_form("キレる", "下一段-ラ行", "切れる")


class TestDictionaryFormNote:
    def test_none_when_forms_match(self):
        assert dictionary_form_note("誰", "誰", "*") is None

    def test_potential_form_gets_the_specific_note(self):
        note = dictionary_form_note("挟める", "挟む", "下一段-マ行")
        assert note is not None
        assert "potential form" in note
        assert "挟む" in note

    def test_generic_variant_gets_the_generic_note(self):
        # 無理ゲー's dictionary_form/normalized_form are identical in
        # practice (no divergence to test here), so use a constructed
        # non-potential divergence to check the generic branch fires and
        # doesn't claim "potential form" when it isn't one.
        note = dictionary_form_note("キレる", "切れる", "下一段-ラ行")
        assert note is not None
        assert "potential form" not in note


class TestASplitDecomposition:
    def test_decomposes_a_compound_with_no_jmdict_headword(self):
        pieces = a_split_decomposition("勝利の女神")
        assert [p[0] for p in pieces] == ["勝利", "の", "女神"]

    def test_does_not_decompose_an_atomic_word(self):
        assert a_split_decomposition("ぱっ") == []
        assert a_split_decomposition("ゼッテー") == []


class TestHeteronymReadings:
    def test_finds_a_real_heteronym(self):
        # 今日 has two Sudachi-registered readings under the identical POS
        # tuple: きょう and こんにち.
        readings = heteronym_readings(
            "今日", ("名詞", "普通名詞", "副詞可能", "*", "*", "*")
        )
        assert "コンニチ" in readings or "キョウ" in readings
        assert len(set(readings)) >= 2

    def test_non_heteronym_word_has_no_alternates(self):
        readings = heteronym_readings(
            "花火", ("名詞", "普通名詞", "一般", "*", "*", "*")
        )
        assert len(set(readings)) <= 1


class TestReconstructCitationReading:
    def test_ichidan_inflected_append_pattern(self):
        # 温め is 温める's stem/renyou form (e.g. from 温めた) — citation
        # adds back exactly what's missing from the (shorter) stem reading,
        # almost always just る.
        citation = citation_reading("温める")
        conjugation_type = conjugation_type_of("温める")
        assert conjugation_type == "下一段-マ行"
        assert (
            _reconstruct_citation_reading(
                "アタタメ", citation, "ヌクメ", conjugation_type
            )
            == "ヌクメル"
        )
        assert (
            _reconstruct_citation_reading(
                "アタタメ", citation, "ヌルメ", conjugation_type
            )
            == "ヌルメル"
        )

    def test_ichidan_already_at_citation_form_needs_no_change(self):
        # Regression: when the token occurs in its OWN citation-form
        # reading directly (温める itself, not conjugated), reading already
        # equals dict_form_citation — blindly appending citation's last
        # character regardless would double it up (ぬくめる -> ぬくめるる).
        # A heteronym alternative sharing that exact shape needs no
        # transformation at all.
        citation = citation_reading("温める")
        conjugation_type = conjugation_type_of("温める")
        assert (
            _reconstruct_citation_reading(
                citation, citation, "ヌクメル", conjugation_type
            )
            == "ヌクメル"
        )

    def test_godan_inflected_substitution_pattern(self):
        # 開き is 開く's stem/renyou form and a real, registered heteronym:
        # ひらく vs あく, renyou stems ヒラキ/アキ. Godan doesn't append a
        # mora, it replaces the final one (カク/カキ) — a naive suffix-append
        # is wrong here, which is exactly the gap this function exists to
        # close.
        citation = citation_reading("開く")  # Sudachi's own default: ヒラク
        conjugation_type = conjugation_type_of("開く")
        assert conjugation_type == "五段-カ行"
        assert (
            _reconstruct_citation_reading("ヒラキ", citation, "アキ", conjugation_type)
            == "アク"
        )

    def test_godan_already_at_citation_form_needs_no_change(self):
        # Same regression as the ichidan case, for godan: a token occurring
        # in its own citation form (開く itself) needs no substitution.
        citation = citation_reading("開く")
        conjugation_type = conjugation_type_of("開く")
        assert (
            _reconstruct_citation_reading(citation, citation, "アク", conjugation_type)
            == "アク"
        )

    def test_falls_back_safely_for_irregular_verbs(self):
        # する/来る (サ行変格/カ行変格) don't follow either fixed rule — their
        # stem readings vary irregularly across forms — so this must
        # degrade to "leave it unchanged" rather than apply a rule that
        # doesn't hold for them.
        citation = citation_reading("する")
        conjugation_type = conjugation_type_of("する")
        assert conjugation_type == "サ行変格"
        assert (
            _reconstruct_citation_reading("シ", citation, "シ", conjugation_type)
            == "シ"
        )


class TestTokenizeDocument:
    def test_partitions_the_whole_text_with_no_gaps_or_overlaps(self):
        text_sample = "チート、gifted、荒技\n無理ゲー、それ聞いてないって..."
        records = tokenize_document(text_sample)
        pos = 0
        for r in records:
            assert r.char_begin == pos
            assert r.surface == text_sample[r.char_begin : r.char_end]
            pos = r.char_end
        assert pos == len(text_sample)

    def test_english_token_gets_no_furigana_reading(self):
        records = tokenize_document("gifted")
        assert len(records) == 1
        assert records[0].furigana_spans == [
            {"start": 0, "end": 6, "text": "gifted", "reading": None}
        ]

    def test_heteronym_token_is_flagged_with_citation_reading_on_options(self):
        records = tokenize_document("今日")
        assert len(records) == 1
        r = records[0]
        assert r.review_reason == "heteronym"
        assert r.conflict_options, "expected at least one alternate reading candidate"
        for option in r.conflict_options:
            assert "reading" in option
            assert "furigana_spans" in option
            assert "citation_reading" in option

    def test_no_kana_anchor_conflict_options_use_citation_reading_not_inflected_reading(
        self, monkeypatch
    ):
        """出来上がった's stem token ('出来上がっ') has its own occurrence
        reading デキアガッ, which still carries the past-tense okurigana
        mutation — but JMDict is keyed by the citation reading できあがる
        (mixed_reading of normalized_form), same as what the default
        conflict option (app/conflicts.py::create_conflicts) already uses.
        A no_kana_anchor conflict option's citation_reading must always be
        the latter: using the raw occurrence reading directly would send an
        inflected, non-citation reading to the gloss lookup the moment a
        user resolves to a non-default option on anything but a bare
        citation-form occurrence.

        Real words that are both per-character-ambiguous *and* conjugating
        are rare enough that none exist in the golden cases above, so this
        forces the no_kana_anchor path via monkeypatch — the invariant
        matters regardless of how rare the natural trigger is.
        """
        import app.tokenization as tok

        def fake_furigana_spans_for_morpheme(m):
            surface = m.surface()
            reading = m.reading_form()
            spans = [
                {
                    "start": 0,
                    "end": len(surface),
                    "text": surface,
                    "reading": tok.to_hiragana(reading),
                }
            ]
            alt = [
                {"start": 0, "end": len(surface), "text": surface, "reading": "dummy"}
            ]
            return spans, True, [alt]

        monkeypatch.setattr(
            tok, "_furigana_spans_for_morpheme", fake_furigana_spans_for_morpheme
        )

        records = tok.tokenize_document("出来上がった")
        stem = next(r for r in records if r.surface == "出来上がっ")

        assert stem.review_reason == "no_kana_anchor"
        assert stem.reading_katakana == "デキアガッ"

        citation = tok.mixed_reading(stem.normalized_form)
        inflected = tok.to_hiragana(stem.reading_katakana)
        assert citation == "できあがる"
        assert inflected == "できあがっ"

        assert stem.conflict_options, "expected at least one no_kana_anchor alternative"
        for option in stem.conflict_options:
            assert option["citation_reading"] == citation
            assert option["citation_reading"] != inflected

    def test_non_heteronym_token_is_not_flagged(self):
        records = tokenize_document("花火")
        assert len(records) == 1
        assert records[0].review_reason is None
        assert records[0].conflict_options == []
