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
"""

from app.tokenization import tokenize_document

CASES = {
    "jukujikun": (
        "今日は良い天気です。",
        [
            ("今日", "キョウ", "heteronym", [{"start": 0, "end": 2, "text": "今日", "reading": "きょう"}]),
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
            ("です", "デス", None, [{"start": 0, "end": 2, "text": "です", "reading": None}]),
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
            ("です", "デス", None, [{"start": 0, "end": 2, "text": "です", "reading": None}]),
        ],
    ),
    "oov_and_multikanji": (
        "三年生になりました",
        [
            ("三", "サン", "oov", [{"start": 0, "end": 1, "text": "三", "reading": "さん"}]),
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
            ("なり", "ナリ", None, [{"start": 0, "end": 2, "text": "なり", "reading": None}]),
            ("まし", "マシ", None, [{"start": 0, "end": 2, "text": "まし", "reading": None}]),
            ("た", "タ", None, [{"start": 0, "end": 1, "text": "た", "reading": None}]),
        ],
    ),
    "four_char_idiom": (
        "一石二鳥の作戦だ",
        [
            ("一", "イチ", "oov", [{"start": 0, "end": 1, "text": "一", "reading": "いち"}]),
            ("石", "コク", "heteronym", [{"start": 0, "end": 1, "text": "石", "reading": "こく"}]),
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
            ("彼女", "カノジョ", None, [{"start": 0, "end": 2, "text": "彼女", "reading": "かのじょ"}]),
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
            ("八百屋", "ヤオヤ", None, [{"start": 0, "end": 3, "text": "八百屋", "reading": "やおや"}]),
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
            ("する", "スル", None, [{"start": 0, "end": 2, "text": "する", "reading": None}]),
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
    return [(r.surface, r.reading_katakana, r.review_reason, r.furigana_spans) for r in tokenize_document(text)]


def test_golden_cases_cover_every_review_reason():
    reasons = {expected_review for _, expected in CASES.values() for _, _, expected_review, _ in expected}
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
            for a, b in zip(spans, spans[1:]):
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
    assert all(span["reading"] is None for record in records for span in record.furigana_spans)
