"""Tests for GET /documents/{id}/tokens/{token_id}/alternate-readings — the
"look for other readings" action that replaces free-text reading
correction for anything Sudachi actually recognizes (see
app.glosses.alternate_reading_options; free-text stays for OOV tokens,
which have no dictionary entry for a search to find anything in).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.main import DocumentCreate, create_document, get_alternate_readings, get_document_tokens


def test_finds_a_reading_a_heteronym_flag_would_miss(committed_engine):
    # 期 read ご (一般) never gets flagged as a heteronym of 期 read き
    # (助数詞可能) — see app/glosses.py's heteronym_readings docstring — so
    # this is the only route to it.
    document_id = create_document(DocumentCreate(title="t", text="この期に及んで")).id
    period_token = next(t for t in get_document_tokens(document_id) if t.surface == "期")

    options = get_alternate_readings(document_id, period_token.id)

    assert {o["reading"] for o in options} == {"ご"}
    assert options[0]["citation_reading"] == "ご"


def test_404s_for_a_token_id_outside_the_document(committed_engine):
    document_id = create_document(DocumentCreate(title="t", text="今日は雨です。")).id
    other_document_id = create_document(DocumentCreate(title="t2", text="別の文章。")).id
    other_token = get_document_tokens(other_document_id)[0]

    with pytest.raises(HTTPException) as exc_info:
        get_alternate_readings(document_id, other_token.id)
    assert exc_info.value.status_code == 404
