"""Tests for saving a document's edited line timings (PUT
/documents/{id}/timings), and for when they stop applying."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.main import (
    DocumentCreate,
    DocumentTextUpdate,
    LineTiming,
    LineTimingsUpdate,
)
from tests.fixtures.kumo_no_ito import FIRST_SENTENCE, SECOND_SENTENCE
from tests.support import (
    create_document,
    get_document,
    save_line_timings,
    update_document_text,
)

# One timing per line of a two-stanza document, the blank line between them
# untimed.
LINES = [LineTiming(start=1.0, end=4.0), None, LineTiming(start=4.0, end=9.5)]


def _document() -> tuple[int, str]:
    document = create_document(
        DocumentCreate(title="test", text=f"{FIRST_SENTENCE}\n\n{SECOND_SENTENCE}")
    )
    return document.id, document.text


def test_saved_timings_come_back_with_the_document(committed_engine):
    document_id, text = _document()

    saved = save_line_timings(document_id, LineTimingsUpdate(text=text, lines=LINES))

    assert saved.edited_lines == LINES
    assert get_document(document_id).edited_lines == LINES


def test_timings_made_for_other_lyrics_are_refused(committed_engine):
    document_id, _ = _document()

    with pytest.raises(HTTPException) as refused:
        save_line_timings(
            document_id, LineTimingsUpdate(text=FIRST_SENTENCE, lines=LINES[:1])
        )

    assert refused.value.status_code == 409
    assert get_document(document_id).edited_lines is None


def test_more_timings_than_lines_are_refused(committed_engine):
    document_id, text = _document()

    with pytest.raises(HTTPException) as refused:
        save_line_timings(
            document_id,
            LineTimingsUpdate(
                text=text, lines=[*LINES, LineTiming(start=9.5, end=12.0)]
            ),
        )

    assert refused.value.status_code == 422


@pytest.mark.parametrize(
    "lines",
    [[LINES[0], None, None], LINES[:2]],
    ids=["deleted", "missing from the end"],
)
def test_untimed_lyrics_lines_are_refused(committed_engine, lines):
    document_id, text = _document()

    with pytest.raises(HTTPException) as refused:
        save_line_timings(document_id, LineTimingsUpdate(text=text, lines=lines))

    assert refused.value.status_code == 422
    assert get_document(document_id).edited_lines is None


def test_editing_the_lyrics_drops_the_edited_timings(committed_engine):
    document_id, text = _document()
    save_line_timings(document_id, LineTimingsUpdate(text=text, lines=LINES))

    edited = update_document_text(document_id, DocumentTextUpdate(text=SECOND_SENTENCE))

    assert edited.edited_lines is None
    assert get_document(document_id).edited_lines is None


@pytest.mark.parametrize(
    "lines",
    [
        [LineTiming(start=4.0, end=9.0), None, LineTiming(start=1.0, end=4.0)],
        [LineTiming(start=-1.0, end=1.0)],
        [LineTiming(start=2.0, end=1.0)],
    ],
    ids=["out of order", "before the song", "ends before it starts"],
)
def test_unordered_or_inverted_timings_are_invalid(lines):
    with pytest.raises(ValidationError):
        LineTimingsUpdate(text="", lines=lines)
