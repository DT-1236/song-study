"""Moving a token boundary Sudachi puts in the wrong place.

青き線 ("blue line", with き the classical adjective ending on 青) comes back
as 青 + き線, because き線 is a dictionary word of its own (饋線, an
electrical feeder line). Re-tokenizing the pair with the boundary moved
gives 青き + 線.

A dictionary word spanning a boundary can misplace any of them, not only a
classical adjective's ending; that ending is where Sudachi loses often
enough to matter, and where its own 文語形容詞 tag says whether the repair
worked. Each rule in `_RULES` decides which pair it applies to and what its
new boundary must look like; _move_boundary does the re-tokenizing for all
of them, and only ever takes characters from a token with no dictionary
entry of its own.
"""

from __future__ import annotations

from collections.abc import Callable

# The classical (文語) adjective endings that can end up glued to the noun
# after them: 青き線, 青く咲く, 青し.
_ADJECTIVE_ENDINGS = ("き", "く", "し")


def _is_dictionary_word(morpheme) -> bool:
    """Whether JMDict has `morpheme` as a headword, as written or under its
    dictionary form."""
    # Imported here: app.glosses builds on app.tokenization, which builds on
    # this module.
    from app.glosses import is_headword

    return any(
        is_headword(form) for form in (morpheme.surface(), morpheme.normalized_form())
    )


def _move_boundary(
    left, right, chars: int, tokenize: Callable, accept: Callable
) -> list | None:
    """`left` and `right` re-tokenized with `chars` characters of `right`
    moved onto `left`, if that makes `left` a single morpheme `accept`
    accepts and leaves a rest that Sudachi knows. None otherwise.

    `right` has to be a word JMDict doesn't have, or its own split is the
    likelier reading: 赤きつね is 赤 + きつね ("fox"), not 赤き + つね."""
    if _is_dictionary_word(right):
        return None
    head = tokenize(left.surface() + right.surface()[:chars])
    rest = tokenize(right.surface()[chars:])
    if len(head) != 1 or not accept(head[0]):
        return None
    if not rest or any(morpheme.is_oov() for morpheme in head + rest):
        return None
    return head + rest


def _classical_adjective(left, right, tokenize: Callable) -> list | None:
    """`left` and `right` re-split with the classical adjective ending that
    starts `right` moved onto `left`: 青 + き線 becomes 青き + 線."""
    if right.surface()[0] not in _ADJECTIVE_ENDINGS:
        return None
    return _move_boundary(
        left,
        right,
        1,
        tokenize,
        lambda morpheme: (
            morpheme.part_of_speech()[0] == "形容詞"
            and morpheme.part_of_speech()[4].startswith("文語形容詞")
        ),
    )


_RULES = (_classical_adjective,)


def repair_boundaries(morphemes: list, tokenize: Callable) -> list[tuple[int, object]]:
    """Each of `morphemes` with its character offset in the text, after moving
    every boundary a rule repairs. `tokenize` turns one word's text into
    morphemes, for trying a boundary out."""
    repaired: list[tuple[int, object]] = []
    i = 0
    while i < len(morphemes):
        left = morphemes[i]
        new_split = None
        if i + 1 < len(morphemes):
            right = morphemes[i + 1]
            new_split = next(
                (split for rule in _RULES if (split := rule(left, right, tokenize))),
                None,
            )
        if new_split is None:
            repaired.append((left.begin(), left))
            i += 1
            continue
        # Each side was re-tokenized on its own, so its morphemes' offsets
        # start over: they're counted from the pair's own start instead.
        offset = left.begin()
        for morpheme in new_split:
            repaired.append((offset, morpheme))
            offset += len(morpheme.surface())
        i += 2
    return repaired
