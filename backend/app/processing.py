"""Processing a document — tokenizing its text and glossing the tokens — as
a background job, which at most one runs per document at a time, however
many requests ask for its tokens meanwhile."""

import dataclasses
import json
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import text

from app.conflicts import create_conflicts, create_phrase_conflicts
from app.db import engine
from app.glosses import (
    GlossKey,
    GlossPlan,
    gloss_key,
    plan_glosses,
    predicate_group_request,
    store_glosses,
)
from app.grammar import find_predicate_groups
from app.phrase_merge import find_phrase_suggestions
from app.tokenization import TokenRecord, to_hiragana, tokenize_document

logger = logging.getLogger(__name__)

# How long a job's claim on a document holds: one older than this is a job
# that died with its process (a deploy restarting the server, say), so the
# next request starts the document over. Far longer than processing takes:
# under half a second for the browser checks' 800-character seed, with no
# glosses cached and the tokenizer not yet loaded.
LEASE = timedelta(minutes=5)

# Two at a time, as requests processed concurrently before there were jobs.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="processing")


@dataclasses.dataclass
class ProcessedDocument:
    records: list[TokenRecord]
    # Each predicate group's index range (see app.grammar).
    groups: list[range]
    # The gloss key of each record, by index: its group's, if it's in one.
    gloss_keys: list[GlossKey | None]
    gloss_plan: GlossPlan


def process_document(document_text: str) -> ProcessedDocument:
    """Tokenize a document and resolve its glosses against the cache — the
    slow part of first processing — without writing anything."""
    records = tokenize_document(document_text)
    groups = find_predicate_groups(records)
    find_phrase_suggestions(records)

    gloss_keys = [gloss_key(record) for record in records]
    group_requests = []
    for group in groups:
        members = records[group.start : group.stop]
        request = predicate_group_request(
            members,
            [to_hiragana(member.reading_katakana) for member in members],
            gloss_keys[group.start],
        )
        group_requests.append(request)
        for i in group:
            gloss_keys[i] = request.key
    grouped = {i for group in groups for i in group}
    # A token's dictionary_form is the alternate spelling for its key.
    requests = (
        (key, record.dictionary_form)
        for i, (record, key) in enumerate(zip(records, gloss_keys))
        if key is not None and i not in grouped
    )
    # Autocommit, so no transaction is held open through the dictionary
    # lookups.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        return ProcessedDocument(
            records, groups, gloss_keys, plan_glosses(conn, requests, group_requests)
        )


def write_processed_document(
    conn, document_id: int, processed: ProcessedDocument
) -> None:
    """Insert a processed document's new gloss rows, its tokens (already
    linked to their glosses), and its conflicts, one statement each."""
    gloss_ids = store_glosses(conn, processed.gloss_plan)
    rows = []
    for record, key in zip(processed.records, processed.gloss_keys):
        rows.append(
            {
                # Not dataclasses.asdict, which would deep-copy every field,
                # including the two that aren't columns, only to discard them.
                **{
                    f.name: getattr(record, f.name)
                    for f in dataclasses.fields(record)
                    if f.name not in ("conflict_options", "phrase_suggestion")
                },
                "gloss_lookup_id": gloss_ids[key] if key is not None else None,
            }
        )
    conn.execute(
        text(
            """
            INSERT INTO tokens (
                document_id, position, char_begin, char_end, surface,
                dictionary_form, normalized_form, reading_katakana,
                part_of_speech, is_oov, furigana_spans, needs_review,
                review_reason, gloss_lookup_id, phrase_start_position
            )
            SELECT :document_id, position, char_begin, char_end, surface,
                   dictionary_form, normalized_form, reading_katakana,
                   part_of_speech, is_oov, furigana_spans, needs_review,
                   review_reason, gloss_lookup_id, phrase_start_position
            FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS r(
                position int, char_begin int, char_end int, surface text,
                dictionary_form text, normalized_form text, reading_katakana text,
                part_of_speech jsonb, is_oov boolean, furigana_spans jsonb,
                needs_review boolean, review_reason text, gloss_lookup_id int,
                phrase_start_position int
            )
            ORDER BY position
            """
        ),
        {"document_id": document_id, "rows": json.dumps(rows)},
    )
    create_conflicts(conn, document_id, processed.records)
    create_phrase_conflicts(conn, document_id, processed.records, processed.groups)


# "processed" once a job has finished with the document's current text.
Progress = Literal["processing", "processed", "failed"]


def start(document_id: int, *, retry: bool) -> Progress | None:
    """Start a job processing the document, unless it's processed, a job is
    already processing it, or — unless `retry` — its last job failed, and
    say which; None if there's no such document."""
    params = {"id": document_id, "lease": LEASE, "retry": retry}
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        while True:
            # Read before claiming, so a poll during a job costs one
            # statement and writes nothing.
            document = _read_progress(conn, params)
            if document is None:
                return None
            if document.progress is not None:
                return document.progress
            if (claim := _claim(conn, params)) is not None:
                break
            # The state changed since the read (another request claimed it,
            # a job released it, its text changed): read it again to say how.

    # Once the claim is committed, for the job to see it.
    _executor.submit(
        _run, document_id, claim.processing_started_at, claim.text
    ).add_done_callback(_log_failure)
    return "processing"


# What `start` reports for a document in each state, or NULL if it should
# claim the document. Shared by the read and the claim, so the claim takes
# exactly the documents the read found claimable.
_PROGRESS = """
    CASE
        WHEN processed_at IS NOT NULL THEN 'processed'
        WHEN processing_started_at > now() - :lease THEN 'processing'
        WHEN processing_failed AND NOT :retry THEN 'failed'
    END
"""


def _read_progress(conn, params: dict):
    """The document's row, with what `start` reports for it as `progress`
    (None if it should claim the document); None if there's no such
    document."""
    return conn.execute(
        text(f"SELECT {_PROGRESS} AS progress FROM documents WHERE id = :id"),
        params,
    ).one_or_none()


def _claim(conn, params: dict):
    """Claim the document for a job if `start` should, returning its text
    and when it was claimed; None, with nothing changed, otherwise."""
    # One statement, so the check can't go stale before the claim: an UPDATE
    # that waits on another request's claim, a job's release or a text edit
    # re-checks its WHERE against the row they committed.
    return conn.execute(
        text(
            f"""
            UPDATE documents
            SET processing_started_at = now(), processing_failed = FALSE
            WHERE id = :id AND ({_PROGRESS}) IS NULL
            RETURNING text, processing_started_at
            """
        ),
        params,
    ).one_or_none()


def _run(document_id: int, claimed_at: datetime, document_text: str) -> None:
    """Process `document_text`, the document's text when it was claimed at
    `claimed_at`, and write its tokens if the claim still holds; release the
    claim either way, recording that the job failed if it did."""
    try:
        processed = process_document(document_text)
        with engine.begin() as conn:
            # Changing the text drops the claim (by the trigger from
            # migration 0034), so one that still holds is for this text.
            if _release(conn, document_id, claimed_at, failed=False):
                write_processed_document(conn, document_id, processed)
    except Exception:
        with engine.begin() as conn:
            _release(conn, document_id, claimed_at, failed=True)
        raise


def _release(conn, document_id: int, claimed_at: datetime, *, failed: bool) -> bool:
    """Release the claim made at `claimed_at` on the document, recording
    whether its job `failed` and, if not, that the document is processed;
    False, with nothing changed, if the claim no longer holds."""
    released = conn.execute(
        text(
            """
            UPDATE documents
            SET processing_started_at = NULL, processing_failed = :failed,
                processed_at = CASE WHEN :failed THEN NULL ELSE now() END
            WHERE id = :id AND processing_started_at = :claimed_at
            """
        ),
        {"id": document_id, "claimed_at": claimed_at, "failed": failed},
    )
    return released.rowcount == 1


def _log_failure(job: Future) -> None:
    """Log the exception a job raised, if any, which would otherwise go
    unseen."""
    if (exc := job.exception()) is not None:
        logger.error("Processing a document failed", exc_info=exc)
