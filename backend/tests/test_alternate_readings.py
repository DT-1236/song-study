"""Tests for GET /documents/{id}/tokens/{token_id}/alternate-readings, the
"look for other readings" action."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.conflicts import NON_READING_KINDS
from app.main import (
    DocumentCreate,
    ReadingCorrection,
)
from tests.support import (
    correct_token_reading,
    create_document,
    get_alternate_readings,
    get_document_tokens,
)


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

    assert options
    assert all("phrase_token_count" not in o for o in options)
    assert all("furigana_spans" in o for o in options)


@pytest.mark.parametrize(
    ("text", "surface", "reading", "citation"),
    [
        # An inflected adjective, and irregular verbs, whose readings on the
        # page can't be worked out from their dictionary form's.
        ("美しく咲いた", "美しく", "うつくしく", "うつくしい"),
        ("来た", "来", "き", "くる"),
        ("した", "し", "し", "する"),
        # JMDict keys this word's reading with its katakana kept.
        ("無理ゲーだ", "無理ゲー", "むりげー", "むりゲー"),
    ],
)
def test_offers_the_reading_a_token_was_tokenized_with_first(
    committed_engine, text, surface, reading, citation
):
    document_id = create_document(DocumentCreate(title="t", text=text)).id
    token = next(t for t in get_document_tokens(document_id) if t.surface == surface)

    options = get_alternate_readings(document_id, token.id)

    assert (options[0]["reading"], options[0]["citation_reading"]) == (
        reading,
        citation,
    )
    readings = [o["reading"] for o in options]
    assert len(readings) == len(set(readings))


def test_offers_a_corrected_tokens_own_options_first(committed_engine):
    document_id = create_document(DocumentCreate(title="t", text="来た")).id
    token = next(t for t in get_document_tokens(document_id) if t.surface == "来")
    corrected = correct_token_reading(
        document_id, token.id, ReadingCorrection(reading="こ")
    )
    own = [c.value for c in corrected.conflicts if c.kind not in NON_READING_KINDS]

    options = get_alternate_readings(document_id, token.id)

    # Its original reading, き, then the correction, then JMDict's others (きたる
    # doesn't project onto 来た).
    assert options[: len(own)] == [{**o, "own": True} for o in own]
    assert [(o["reading"], o["own"]) for o in options] == [
        ("き", True),
        ("こ", True),
    ]
