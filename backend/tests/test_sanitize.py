"""Tests for sanitize_text (app/sanitize.py) and for lyrics being sanitized
before they're stored. Characters that are invisible, combining, whitespace,
or indistinguishable from ASCII are written as escapes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.lrclib import parse_synced_lyrics
from app.main import (
    DocumentCreate,
    DocumentTextUpdate,
)
from app.sanitize import sanitize_text

# SMALL ROMAN NUMERAL ONE THOUSAND, which looks exactly like m.
ROMAN_M = "\u217f"
from tests.support import create_document, get_document_tokens


def test_latin_lookalikes_become_the_letters_they_stand_for():
    # A Roman numeral, a ligature, a mathematical letter, and a Roman
    # numeral standing for several letters.
    assert sanitize_text(f"{ROMAN_M}usic ﬁne 𝐦e Ⅻ") == "music fine me XII"


def test_full_width_letters_symbols_and_digit_variants_are_kept():
    assert sanitize_text("ＬＯＶＥ ① ² ™ ⓜ ℃") == "ＬＯＶＥ ① ² ™ ⓜ ℃"


def test_decomposed_kana_is_composed():
    # か followed by a combining voiced sound mark, as が.
    assert sanitize_text("か\u3099") == "が"


def test_invisible_characters_are_removed_but_emoji_joiners_kept():
    assert sanitize_text("mu\u200bsic\ufeff co\u00adop wo\u2060rd") == "music coop word"
    # A family emoji, joined by a zero-width joiner.
    assert sanitize_text("\U0001f468\u200d\U0001f469") == "\U0001f468\u200d\U0001f469"


def test_spacing_is_normalized_and_every_line_break_kept():
    # Tab and no-break space runs, CRLF, a Unicode line separator, a lone
    # CR, and ideographic spaces.
    text = "  a\t\u00a0 b  \r\nc \u2028\n\r\u3000d\u3000 e\n"

    assert sanitize_text(text) == "a b\nc\n\n\n\u3000d\u3000 e\n"


def test_synced_lyrics_lines_are_sanitized():
    assert (
        parse_synced_lyrics(
            f"[00:01.00]  {ROMAN_M}usic\u00a0\u00a0box\u200b ", 5.0
        ).text
        == "music box"
    )


def test_edited_text_that_sanitizes_to_nothing_is_rejected():
    with pytest.raises(ValidationError):
        DocumentTextUpdate(text="\u200b \n\t")


def test_saved_lyrics_are_sanitized_before_tokenizing(committed_engine):
    document = create_document(
        DocumentCreate(title="test", text=f"私の{ROMAN_M}usic\r\n")
    )

    assert document.text == "私のmusic\n"
    assert [t.surface for t in get_document_tokens(document.id)] == [
        "私",
        "の",
        "music",
        "\n",
    ]
