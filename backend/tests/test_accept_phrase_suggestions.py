"""Regression tests for app.conflicts.accept_phrase_suggestions — accepting
several phrase suggestions (see app/phrase_merge.py) in one call, e.g. every
matching instance of the same word's suggestion at once (see
DocumentViewPage.tsx's matchingPhraseSuggestions / "Apply to all").
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.main import DocumentCreate, PhraseAcceptance, accept_phrase_suggestions_endpoint, create_document, get_document_tokens

TEXT = "それでも僕は行く。それでも彼は行かない。"


def _unselected_phrase_conflict_ids(document_id) -> list[int]:
    tokens = get_document_tokens(document_id)
    return [c.id for t in tokens for c in t.conflicts if c.kind == "phrase" and not c.selected]


def test_accepts_every_matching_instance_in_one_call(committed_engine):
    document_id = create_document(DocumentCreate(title="t", text=TEXT)).id
    # Both それでも occurrences offer the exact same suggestion (see
    # matchingPhraseSuggestions in the frontend) — one conflict row each.
    conflict_ids = _unselected_phrase_conflict_ids(document_id)
    assert len(conflict_ids) == 2

    affected = accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=conflict_ids))

    assert len(affected) == 6  # two それでも occurrences, 3 tokens each
    merged = [t for t in get_document_tokens(document_id) if t.phrase_start_position is not None]
    assert len(merged) == 6
    assert all(t.gloss is not None and t.gloss.lookup_form == "それでも" for t in merged)
    # Two independent groups, not one six-token run.
    assert len({t.phrase_start_position for t in merged}) == 2


def test_raises_for_a_conflict_id_outside_the_document(committed_engine):
    document_id = create_document(DocumentCreate(title="t", text=TEXT)).id
    other_document_id = create_document(DocumentCreate(title="t2", text=TEXT)).id
    other_conflict_id = _unselected_phrase_conflict_ids(other_document_id)[0]

    with pytest.raises(HTTPException) as exc_info:
        accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[other_conflict_id]))
    assert exc_info.value.status_code == 404
