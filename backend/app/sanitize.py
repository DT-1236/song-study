"""Cleanup for lyrics text, applied before it's stored and tokenized."""

from __future__ import annotations

import re
import unicodedata
from functools import cache

# Every line break str.splitlines recognizes.
_LINE_BREAK_RE = re.compile("\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]")
# Zero-width space, word joiner, byte order mark, soft hyphen. Zero-width
# joiners are kept, since emoji sequences are built from them.
_INVISIBLE_RE = re.compile("[\u200b\u2060\ufeff\u00ad]")
# Whitespace within a line, except the ideographic space (U+3000), which
# Japanese text uses deliberately.
_SPACE_RUN_RE = re.compile(r"[^\S\u3000]+")


@cache
def _fold_latin_lookalike(ch: str) -> str:
    """The plain Latin letters `ch` is a compatibility variant of (U+217F,
    the Roman numeral one thousand, as m; ﬁ as fi), or `ch` itself if it
    isn't one."""
    # Full-width letters are left alone: they're a deliberate style in
    # Japanese text, and Sudachi already reads them as the letters they are.
    if ch.isascii() or "\uff00" <= ch <= "\uffef":
        return ch
    # Letters and letter-like numerals only, so symbols that decompose to
    # letters (™, ⓜ) and digit variants (①, ²) keep their meaning.
    category = unicodedata.category(ch)
    if not (category.startswith("L") or category == "Nl"):
        return ch
    folded = unicodedata.normalize("NFKC", ch)
    return folded if folded.isascii() and folded.isalpha() else ch


def sanitize_text(text: str) -> str:
    r"""`text` with look-alikes of Latin letters replaced by those letters,
    invisible characters removed, each run of spaces within a line made one
    space, and spaces at either end of each line removed. Each line break
    becomes "\n", one for one; ideographic spaces are kept.

    Sudachi splits words at an unexpected character: "music" spelled with
    the Roman numeral U+217F for its m tokenizes as two unknown words."""
    # Composes decomposed kana (か followed by the combining U+3099 into
    # が), which Sudachi can't read.
    text = unicodedata.normalize("NFC", text)
    text = "".join(map(_fold_latin_lookalike, _INVISIBLE_RE.sub("", text)))
    return "\n".join(
        _SPACE_RUN_RE.sub(" ", line).strip(" ") for line in _LINE_BREAK_RE.split(text)
    )
