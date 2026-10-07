"""Migration 0032, which keeps the schedule each review gave its card."""

from __future__ import annotations

from alembic import command
from sqlalchemy import text

from app.main import PushOut, ReviewAnswer
from tests.support import (
    add_token_card,
    alembic_config,
    create_tokenized_document,
    document_tokens,
    engine,
    push_out_card,
    review_card,
)


def _card(surface: str) -> int:
    document_id = create_tokenized_document(text=surface)
    return add_token_card(document_id, document_tokens(document_id, surface)[0].id).id


def _answer(card_id: int) -> int:
    return review_card(card_id, ReviewAnswer(correct=True, duration_ms=2000)).review_id


def _kept(review_id: int) -> bool | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                """
                SELECT r.next_due = c.due AND r.next_last_review = c.last_review
                FROM study_reviews r JOIN study_cards c ON c.id = r.card_id
                WHERE r.id = :id
                """
            ),
            {"id": review_id},
        ).scalar_one()


def test_only_a_review_still_setting_its_cards_schedule_gets_it(committed_engine):
    tsurai = _card("辛い")
    first = _answer(tsurai)
    second = _answer(tsurai)
    kimi = _card("君")
    pushed = _answer(kimi)
    push_out_card(kimi, PushOut(months=1))

    config = alembic_config()
    command.downgrade(config, "0031")
    try:
        command.upgrade(config, "0032")
        assert _kept(second)
        assert _kept(first) is None
        assert _kept(pushed) is None
    finally:
        command.upgrade(config, "head")
