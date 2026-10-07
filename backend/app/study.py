"""Scheduling study cards: what a review does to a card, which cards are due,
and the settings that shape both.

The spacing math is py-fsrs's; what's decided here is how an answer becomes
one of its four ratings (docs/flashcards.md, "Mapping objective results onto
FSRS's four ratings") and which cards a session is made of.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from fsrs import Card, Rating, Scheduler, State
from sqlalchemy import text

from app.card_content import (
    Queue,
    RunLine,
    load_songs,
    queue_contents,
    run_through_lines,
)
from app.cards import (
    CARD_COLUMNS,
    CARD_KEYS_JOIN_SQL,
    CardKey,
    CardKind,
    NotStudyable,
    SongWords,
    add_card,
    card_keys_param,
    is_mature,
    song_card_keys,
    song_words,
    songs_words,
    token_word,
    units_by_document,
)
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
# Apart from LATENCY_MS though both say the same of every kind today: Type C
# (docs/flashcards.md) is the first kind that differs. If it's dropped
# instead, fold the two into one table of (fast_ms, slow_ms, multiple_choice).
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
            SELECT c.id, c.kind, c.lookup_form, c.reading, c.idseq, c.state, c.step, c.stability,
                   c.difficulty, c.due, c.last_review, c.suspended, u.desired_retention
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


def _schedule_params(card: Card, prefix: str = "") -> dict:
    """py-fsrs's `card` as bind parameters named for study_cards' scheduling
    columns, each name led by `prefix`."""
    return {
        f"{prefix}state": card.state.value,
        f"{prefix}step": card.step,
        f"{prefix}stability": card.stability,
        f"{prefix}difficulty": card.difficulty,
        f"{prefix}due": card.due,
        f"{prefix}last_review": card.last_review,
    }


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
        {"id": card.card_id, **_schedule_params(card)},
    ).one()


def review_card(
    conn,
    user_id: int,
    card_id: int,
    correct: bool,
    duration_ms: int,
    document_id: int | None = None,
) -> tuple[Rating, int, object]:
    """Schedule the user's card after an answer that took `duration_ms`,
    logging the review against `document_id`, the song whose line was
    played. Returns the rating it was given, the review's id, and the card's
    new row.

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
    before = _fsrs_card(row)
    card, _ = Scheduler(desired_retention=row.desired_retention).review_card(
        before, rating, reviewed_at
    )

    review_id = conn.execute(
        text(
            """
            INSERT INTO study_reviews (
                card_id, document_id, reviewed_at, correct, duration_ms, fast_ms, slow_ms, rating,
                prev_state, prev_step, prev_stability, prev_difficulty, prev_due, prev_last_review,
                next_state, next_step, next_stability, next_difficulty, next_due, next_last_review
            )
            VALUES (
                :card_id, :document_id, :reviewed_at, :correct, :duration_ms, :fast_ms, :slow_ms, :rating,
                :prev_state, :prev_step, :prev_stability, :prev_difficulty, :prev_due, :prev_last_review,
                :next_state, :next_step, :next_stability, :next_difficulty, :next_due, :next_last_review
            )
            RETURNING id
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
            **_schedule_params(before, "prev_"),
            **_schedule_params(card, "next_"),
        },
    ).scalar_one()
    return rating, review_id, _store_schedule(conn, card)


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


class NotCorrectable(Exception):
    pass


class ReviewNotFound(Exception):
    pass


def _undo_review(conn, card_id: int, review_id: int) -> None:
    """Delete review `review_id` of card `card_id`, which the caller has
    locked, and put the card's schedule back as it was before it — unless the schedule has moved
    on since (a later review, or a push-out), in which case the review
    stands, since the schedule now builds on it.

    Raises ReviewNotFound if it isn't one of the card's reviews."""
    params = {"review_id": review_id, "card_id": card_id}
    # A review the schedule had moved on from by 0032 has no next_* to match,
    # nor has one logged before 0031, with no prior schedule to go back to.
    before = conn.execute(
        text(
            """
            DELETE FROM study_reviews r
            USING study_cards c
            WHERE r.id = :review_id AND r.card_id = :card_id AND c.id = r.card_id
              AND (c.state, c.step, c.stability, c.difficulty, c.due, c.last_review)
                  IS NOT DISTINCT FROM (r.next_state, r.next_step, r.next_stability,
                                        r.next_difficulty, r.next_due, r.next_last_review)
            RETURNING r.card_id AS id, r.prev_state AS state, r.prev_step AS step,
                      r.prev_stability AS stability, r.prev_difficulty AS difficulty,
                      r.prev_due AS due, r.prev_last_review AS last_review
            """
        ),
        params,
    ).one_or_none()
    if before is not None:
        _store_schedule(conn, _fsrs_card(before))
    elif not conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM study_reviews WHERE id = :review_id AND card_id = :card_id)"
        ),
        params,
    ).scalar_one():
        raise ReviewNotFound()


def correct_card(
    conn,
    user_id: int,
    card_id: int,
    document_id: int,
    token_id: int,
    piece: int | None,
    correct: Callable[[object], object],
    review_id: int | None = None,
) -> tuple[object | None, bool]:
    """Apply `correct(conn)`, a change to which word `token_id` of the
    document is (or `piece` of it, for a token sung in katakana; see
    cards.token_word), made while it was the line of the user's card
    `card_id`. The token then belongs to the card for the word it is now,
    which is created, or restored, if need be. `review_id`, the card's review
    from that line, is undone, since it was asked about the wrong word. The
    old card is then deleted if it has no reviews, since nothing was learned
    on it; with reviews, it stays.

    Returns the token's card now (CARD_COLUMNS), None if its word has no
    dictionary entry to study, and whether the old card was kept.

    Raises CardNotFound if the card isn't the user's, DocumentNotFound if
    the document isn't, ReviewNotFound if `review_id` isn't one of the
    card's reviews, NotCorrectable if the token's word doesn't take this
    correction (see cards.CardTokens), and as cards.token_word does if the
    token isn't part of a word."""
    row = _locked_card(conn, user_id, card_id)
    if not document_is_owned(conn, document_id, user_id):
        raise DocumentNotFound()
    old = CardKey.of(row)
    before = token_word(conn, document_id, token_id, piece)
    if before.correction != ("reading" if piece is None else "word"):
        raise NotCorrectable()
    if review_id is not None:
        _undo_review(conn, row.id, review_id)
    correct(conn)
    try:
        word = token_word(conn, document_id, token_id, piece)
        card = add_card(conn, user_id, document_id, word)
    except NotStudyable:
        word = card = None

    # Only the card the token belonged to, in case another change got there
    # first.
    if before.key != old or (word is not None and word.key == old):
        return card, True
    deleted = conn.execute(
        text(
            """
            DELETE FROM study_cards c
            WHERE c.id = :card_id
              AND NOT EXISTS (SELECT 1 FROM study_reviews r WHERE r.card_id = c.id)
            RETURNING c.id
            """
        ),
        {"card_id": card_id},
    ).one_or_none()
    return card, deleted is None


def _due_cards(conn, user_id: int, keys=None) -> list:
    """The user's unsuspended cards that are due, oldest first, with their
    alternate spellings; only those with one of `keys` if given."""
    words = "" if keys is None else CARD_KEYS_JOIN_SQL
    return conn.execute(
        text(
            f"""
            SELECT {CARD_COLUMNS}, c.alt_lookup_form FROM study_cards c {words}
            -- Not now(), the transaction's start: a card another session
            -- enrolled while this one waited on a lock has a later due.
            WHERE c.user_id = :user_id AND NOT c.suspended
              AND c.due <= statement_timestamp()
            ORDER BY c.due, c.id
            """
        ),
        {
            "user_id": user_id,
            "keys": None if keys is None else card_keys_param(keys),
        },
    ).all()


def all_songs_queue(conn, user_id: int) -> Queue:
    """The user's cards that are due, whichever songs their words are in —
    or none, which is how a card whose word left every song's lyrics stays
    reachable — each with its content, its line from any of those songs."""
    cards = _due_cards(conn, user_id)
    if not cards:
        return Queue([], {})
    return queue_contents(conn, user_id, cards, load_songs(conn, user_id), None)


def song_queue(conn, user_id: int, document_id: int) -> Queue:
    """The user's due cards whose word or grammar term is in the document,
    after enrolling new words from it up to the song's daily limit, each
    with its content, its line from the document.

    Raises DocumentNotFound if the document isn't the user's."""
    # Locked so two sessions started at once can't both find room under the
    # limit and enroll past it. NO KEY UPDATE, so that reviews and cards
    # being created against the song (foreign keys to it) needn't wait.
    per_day = conn.execute(
        text(
            """
            SELECT new_cards_per_day FROM documents
            WHERE id = :document_id AND owner_id = :user_id
            FOR NO KEY UPDATE
            """
        ),
        {"user_id": user_id, "document_id": document_id},
    ).scalar_one_or_none()
    if per_day is None:
        raise DocumentNotFound()
    # Counted in its own statement, after the lock: under READ COMMITTED a
    # statement reads from a snapshot taken before any lock wait inside it,
    # so a count in the locking statement would miss the cards the session
    # that held the lock just enrolled.
    limit = (
        per_day
        - conn.execute(
            text(
                """
            SELECT count(*) FROM study_cards
            WHERE user_id = :user_id AND first_seen_document_id = :document_id
              -- A day is the last 24 hours, not a calendar day, so it needs
              -- no time zone. A word added by hand from the song counts too:
              -- the card's row doesn't say how it began.
              AND created_at > now() - interval '1 day'
            """
            ),
            {"user_id": user_id, "document_id": document_id},
        ).scalar_one()
    )
    songs = load_songs(conn, user_id, [document_id])
    keys = song_card_keys(conn, user_id, document_id, songs[document_id].units, limit)
    cards = _due_cards(conn, user_id, keys)
    return queue_contents(conn, user_id, cards, songs, document_id)


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


@dataclass
class Readiness:
    """How much of a song is in the user's head (see song_readiness)."""

    # 0 to 1: the mean chance of recalling each of the song's words, by how
    # often it's sung, with any the user has no card for yet at zero.
    readiness: float
    words: int
    enrolled: int
    # Cards that are mature (see cards.is_mature).
    mature: int
    due: int


# Retrievability doesn't depend on a user's desired retention.
_RETRIEVABILITY_SCHEDULER = Scheduler()


def _retrievability(row, now: datetime) -> float:
    """The predicted chance the user recalls the card `row` right now; zero
    for one never reviewed."""
    return _RETRIEVABILITY_SCHEDULER.get_card_retrievability(_fsrs_card(row), now)


def song_readiness(words: SongWords, now: datetime) -> Readiness:
    """The user's readiness at `now` for a song that gives their cards
    `words`: the mean chance of recalling each of its words, weighted by how
    often the song has it. A word with no card yet counts as zero, so that
    the number is how much of the song is known rather than how well the
    part studied so far is.

    Computed from the schedule, never stored: a card's retrievability decays
    with every day that passes."""
    total = sum(w.occurrences for w, _ in words.enrolled) + sum(
        w.occurrences for w in words.unenrolled
    )
    known = sum(w.occurrences * _retrievability(row, now) for w, row in words.enrolled)
    return Readiness(
        readiness=known / total if total else 0.0,
        words=len(words.enrolled) + len(words.unenrolled),
        enrolled=len(words.enrolled),
        mature=sum(is_mature(row.state, row.stability) for _, row in words.enrolled),
        due=sum(row.due <= now for _, row in words.enrolled),
    )


def documents_readiness(
    conn, user_id: int, document_ids: list[int]
) -> dict[int, Readiness]:
    """song_readiness as of now for each of `document_ids`, documents the
    caller knows are the user's."""
    units = units_by_document(conn, document_ids)
    words = songs_words(conn, [units.get(id, []) for id in document_ids], user_id)
    now = datetime.now(UTC)
    return {
        id: song_readiness(w, now) for id, w in zip(document_ids, words, strict=True)
    }


def run_through(
    conn, user_id: int, document_id: int
) -> tuple[str | None, list[RunLine]]:
    """The song's lines in order, and its video, for playing it through:
    line with the words in it the user has a card for whose chance of being
    recalled has fallen below their desired retention, weakest first.
    Nothing is logged or rescheduled.

    Raises DocumentNotFound if the document isn't the user's."""
    songs = load_songs(conn, user_id, [document_id])
    if document_id not in songs:
        raise DocumentNotFound()
    song = songs[document_id]
    now = datetime.now(UTC)
    threshold = get_desired_retention(conn, user_id)
    weak = {}
    for word, row in song_words(conn, song.units, user_id).enrolled:
        retrievability = _retrievability(row, now)
        if retrievability < threshold:
            weak[word.key] = (row.id, retrievability)
    return song.youtube_video_id, run_through_lines(conn, song, weak)
