"""Tests for GET /documents/{id}/tokens/{token_id}/alternate-readings, the
"look for other readings" action."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.main import (
    DocumentCreate,
)
from tests.support import create_document, get_alternate_readings, get_document_tokens


def test_finds_a_reading_a_heteronym_flag_would_miss(committed_engine):
    # 期 read ご is a different part of speech from 期 read き, so it's never
    # flagged as a heteronym.
    document_id = create_document(DocumentCreate(title="t", text="この期に及んで")).id
    period_token = next(
        t for t in get_document_tokens(document_id) if t.surface == "期"
    )

    options = get_alternate_readings(document_id, period_token.id)

    # The default is offered too, so a hand-picked reading can be undone.
    assert [o["reading"] for o in options] == ["き", "ご"]
    assert options[1]["citation_reading"] == "ご"


def test_404s_for_a_token_id_outside_the_document(committed_engine):
    document_id = create_document(DocumentCreate(title="t", text="今日は雨です。")).id
    other_document_id = create_document(
        DocumentCreate(title="t2", text="別の文章。")
    ).id
    other_token = get_document_tokens(other_document_id)[0]

    with pytest.raises(HTTPException) as exc_info:
        get_alternate_readings(document_id, other_token.id)
    assert exc_info.value.status_code == 404


@pytest.mark.parametrize(
    ("text", "surface"),
    [
        # A predicate group's head, and a phrase's first token: their own
        # conflicts include ones that aren't readings.
        ("聞こえてるんだって", "聞こえ"),
        ("この期に及んで", "この"),
    ],
)
def test_offers_only_reading_options_of_the_tokens_own(committed_engine, text, surface):
    document_id = create_document(DocumentCreate(title="t", text=text)).id
    token = next(t for t in get_document_tokens(document_id) if t.surface == surface)

    options = get_alternate_readings(document_id, token.id)

    assert all("phrase_token_count" not in o for o in options)
    assert all("furigana_spans" in o for o in options)
