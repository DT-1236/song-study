"""Scheduling study cards: what a review does to a card, which cards are due,
and the settings that shape both.

The spacing math is py-fsrs's; what's decided here is how an answer becomes
one of its four ratings (docs/flashcards.md, "Mapping objective results onto
FSRS's four ratings") and which cards a session is made of.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from fsrs import Card, Rating, Scheduler, State
from sqlalchemy import text

from app.cards import CARD_COLUMNS, CardKind, document_card_keys, enroll_new_words
from app.users import document_is_owned

# Answering under `fast` is fast, and over `slow` is slow, for a card of each
# kind. Flat constants until there's a review log to take a personal median
# from; each review records the pair it was rated with.
LATENCY_MS: dict[CardKind, tuple[int, int]] = {
    "recognition": (3_000, 10_000),
    "grammar": (3_000, 10_000),
}

# The kinds answered by picking one of a few options, whose blind-guess floor
# keeps a fast answer from counting as Easy.
MULTIPLE_CHOICE_KINDS: set[CardKind] = {"recognition", "grammar"}

# The "I know this" ladder: how many days out each rung, in months, pushes a
# card.
PushOutMonths = Literal[1, 3, 6]
PUSH_OUT_DAYS: dict[PushOutMonths, int] = {1: 30, 3: 90, 6: 180}

# Retention targets the settings offer.
MIN_RETENTION, MAX_RETENTION = 0.75, 0.95


class CardNotFound(Exception):
    pass


class CardSuspended(Exception):
    pass


class DocumentNotFound(Exception):
    pass


def rating_for(
    correct: bool,
    duration_ms: int,
    fast_ms: int,
    slow_ms: int,
    multiple_choice: bool,
) -> Rating:
    """The FSRS rating for an answer: wrong is Again; correct is Hard when
    slower than `slow_ms`, Easy when faster than `fast_ms`, else Good.
    Multiple choice never earns Easy, since a lucky guess would otherwise
    compound into a long interval."""
    if not correct:
        return Rating.Again
    if duration_ms > slow_ms:
        return Rating.Hard
    if duration_ms < fast_ms and not multiple_choice:
        return Rating.Easy
    return Rating.Good


def _fsrs_card(row) -> Card:
    return Card(
        card_id=row.id,
        state=State(row.state),
        step=row.step,
        stability=row.stability,
        difficulty=row.difficulty,
        due=row.due,
        last_review=row.last_review,
    )


def _locked_card(conn, user_id: int, card_id: int):
    """The user's card `card_id` with the user's desired retention, locked
    against a concurrent review of it. Raises CardNotFound if it isn't
    theirs."""
    row = conn.execute(
        text(
            """
            SELECT c.id, c.kind, c.state, c.step, c.stability, c.difficulty, c.due,
                   c.last_review, c.suspended, u.desired_retention
            FROM study_cards c
            JOIN users u ON u.id = c.user_id
            WHERE c.id = :card_id AND c.user_id = :user_id
            FOR UPDATE OF c
            """
        ),
        {"card_id": card_id, "user_id": user_id},
    ).one_or_none()
    if row is None:
        raise CardNotFound()
    return row


def _store_schedule(conn, card: Card):
    """Write py-fsrs's `card` back to its row and return the row."""
    return conn.execute(
        text(
            f"""
            UPDATE study_cards
            SET state = :state, step = :step, stability = :stability,
                difficulty = :difficulty, due = :due, last_review = :last_review
            WHERE id = :id
            RETURNING {CARD_COLUMNS}
            """
        ),
        {
            "id": card.card_id,
            "state": card.state.value,
            "step": card.step,
            "stability": card.stability,
            "difficulty": card.difficulty,
            "due": card.due,
            "last_review": card.last_review,
        },
    ).one()


def review_card(
    conn,
    user_id: int,
    card_id: int,
    correct: bool,
    duration_ms: int,
    document_id: int | None = None,
) -> tuple[Rating, object]:
    """Schedule the user's card after an answer that took `duration_ms`,
    logging the review against `document_id`, the song whose line was
    played. Returns the rating it was given and the card's new row.

    Raises CardNotFound if the card isn't the user's, CardSuspended if it was
    removed from study, and DocumentNotFound if `document_id` isn't one of
    theirs."""
    row = _locked_card(conn, user_id, card_id)
    if row.suspended:
        raise CardSuspended()
    if document_id is not None and not document_is_owned(conn, document_id, user_id):
        raise DocumentNotFound()

    fast_ms, slow_ms = LATENCY_MS[row.kind]
    rating = rating_for(
        correct, duration_ms, fast_ms, slow_ms, row.kind in MULTIPLE_CHOICE_KINDS
    )
    reviewed_at = datetime.now(UTC)
    card, _ = Scheduler(desired_retention=row.desired_retention).review_card(
        _fsrs_card(row), rating, reviewed_at
    )

    conn.execute(
        text(
            """
            INSERT INTO study_reviews (
                card_id, document_id, reviewed_at, correct, duration_ms, fast_ms, slow_ms, rating
            )
            VALUES (:card_id, :document_id, :reviewed_at, :correct, :duration_ms, :fast_ms, :slow_ms, :rating)
            """
        ),
        {
            "card_id": card_id,
            "document_id": document_id,
            "reviewed_at": reviewed_at,
            "correct": correct,
            "duration_ms": duration_ms,
            "fast_ms": fast_ms,
            "slow_ms": slow_ms,
            "rating": int(rating),
        },
    )
    return rating, _store_schedule(conn, card)


def push_out(conn, user_id: int, card_id: int, months: PushOutMonths):
    """Reschedule the user's card to fall due `months` from now, as though
    it had been recalled across that whole interval, and return its new row.
    The card's history is untouched and nothing is logged, since this is the
    user overriding the schedule, not an answer to rate.

    Raises CardNotFound if the card isn't the user's."""
    row = _locked_card(conn, user_id, card_id)
    now = datetime.now(UTC)
    days = PUSH_OUT_DAYS[months]

    card = _fsrs_card(row)
    if card.difficulty is None:
        # A card never reviewed has no difficulty to keep; this is the one an
        # Easy answer to it would start with, which is what knowing the word
        # already amounts to.
        card.difficulty = (
            Scheduler(desired_retention=row.desired_retention)
            .review_card(card, Rating.Easy, now)[0]
            .difficulty
        )
    card.state = State.Review
    card.step = None
    # Stability is the days until recall falls to 90%, so a card meant to
    # come back after `days` is one whose stability is `days`.
    card.stability = float(days)
    card.last_review = now
    card.due = now + timedelta(days=days)
    return _store_schedule(conn, card)


def suspend_card(conn, user_id: int, card_id: int):
    """Remove the user's card from study, keeping it and its history so
    adding the word again restores it, and return its row.

    Raises CardNotFound if the card isn't the user's."""
    row = conn.execute(
        text(
            f"""
            UPDATE study_cards SET suspended = TRUE
            WHERE id = :card_id AND user_id = :user_id
            RETURNING {CARD_COLUMNS}
            """
        ),
        {"card_id": card_id, "user_id": user_id},
    ).one_or_none()
    if row is None:
        raise CardNotFound()
    return row


def _due_cards(conn, user_id: int, keys=None) -> list:
    """The user's unsuspended cards that are due, oldest first; only those
    with one of `keys` if given."""
    words = (
        ""
        if keys is None
        else """
            JOIN jsonb_to_recordset(CAST(:keys AS JSONB))
                AS k(key_kind text, key_lookup_form text, key_reading text)
              ON c.kind = k.key_kind AND c.lookup_form = k.key_lookup_form
             AND c.reading IS NOT DISTINCT FROM k.key_reading
        """
    )
    return conn.execute(
        text(
            f"""
            SELECT {CARD_COLUMNS} FROM study_cards c {words}
            WHERE c.user_id = :user_id AND NOT c.suspended AND c.due <= now()
            ORDER BY c.due, c.id
            """
        ),
        {
            "user_id": user_id,
            "keys": None
            if keys is None
            else json.dumps(
                [
                    {
                        "key_kind": k.kind,
                        "key_lookup_form": k.lookup_form,
                        "key_reading": k.reading,
                    }
                    for k in keys
                ]
            ),
        },
    ).all()


def all_songs_queue(conn, user_id: int) -> list:
    """The user's cards that are due, whichever songs their words are in —
    or none, which is how a card whose word left every song's lyrics stays
    reachable."""
    return _due_cards(conn, user_id)


def song_queue(conn, user_id: int, document_id: int) -> list:
    """The user's due cards whose word or grammar term is in the document,
    after enrolling new words from it up to the song's daily limit.

    Raises DocumentNotFound if the document isn't the user's."""
    # Locked so two sessions started at once can't both find room under the
    # limit and enroll past it. NO KEY UPDATE, so that reviews and cards
    # being created against the song (foreign keys to it) needn't wait.
    limit = conn.execute(
        text(
            """
            SELECT d.new_cards_per_day - (
                SELECT count(*) FROM study_cards c
                WHERE c.user_id = :user_id AND c.first_seen_document_id = d.id
                  -- A day is the last 24 hours, not a calendar day, so it
                  -- needs no time zone. A word added by hand from the song
                  -- counts too: the card's row doesn't say how it began.
                  AND c.created_at > now() - interval '1 day'
            )
            FROM documents d
            WHERE d.id = :document_id AND d.owner_id = :user_id
            FOR NO KEY UPDATE OF d
            """
        ),
        {"user_id": user_id, "document_id": document_id},
    ).scalar_one_or_none()
    if limit is None:
        raise DocumentNotFound()
    if limit > 0:
        enroll_new_words(conn, user_id, document_id, limit)
    return _due_cards(conn, user_id, document_card_keys(conn, document_id))


def get_desired_retention(conn, user_id: int) -> float:
    """The user's desired retention."""
    return conn.execute(
        text("SELECT desired_retention FROM users WHERE id = :id"), {"id": user_id}
    ).scalar_one()


def set_desired_retention(conn, user_id: int, desired_retention: float) -> float:
    """Set the user's desired retention, which applies from each card's next
    review; due dates already set stay as they are."""
    return conn.execute(
        text(
            "UPDATE users SET desired_retention = :value WHERE id = :id RETURNING desired_retention"
        ),
        {"id": user_id, "value": desired_retention},
    ).scalar_one()


def get_new_cards_per_day(conn, user_id: int, document_id: int) -> int:
    """How many new cards the user's document may introduce a day.

    Raises DocumentNotFound if the document isn't the user's."""
    limit = conn.execute(
        text(
            "SELECT new_cards_per_day FROM documents WHERE id = :id AND owner_id = :user_id"
        ),
        {"id": document_id, "user_id": user_id},
    ).scalar_one_or_none()
    if limit is None:
        raise DocumentNotFound()
    return limit


def set_new_cards_per_day(conn, user_id: int, document_id: int, limit: int) -> int:
    """Set how many new cards the user's document may introduce a day.

    Raises DocumentNotFound if the document isn't the user's."""
    saved = conn.execute(
        text(
            """
            UPDATE documents SET new_cards_per_day = :limit
            WHERE id = :id AND owner_id = :user_id
            RETURNING new_cards_per_day
            """
        ),
        {"id": document_id, "user_id": user_id, "limit": limit},
    ).scalar_one_or_none()
    if saved is None:
        raise DocumentNotFound()
    return saved
