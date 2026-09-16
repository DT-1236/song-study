"""Regression test for Gloss.lookup_form (app/main.py).

Before this field existed, a merged phrase's member tokens (see
app/phrase_merge.py) all shared the phrase's gloss (senses, reading) but
GlossDetails still showed each token's OWN dictionary_form/reading/POS line
right above it — misleading, since those describe the individual token
(期, き, 名詞), not the phrase it's actually glossed as (この期に及んで, ご).
lookup_form is what lets the frontend show the phrase's own headword
instead for a merged token; this checks the API actually returns it.
"""

from __future__ import annotations

from app.main import DocumentCreate, PhraseAcceptance, accept_phrase_suggestions_endpoint, create_document, get_document_tokens


def test_merged_tokens_gloss_reports_the_phrase_headword(committed_engine):
    document_id = create_document(DocumentCreate(title="t", text="この期に及んでまだ言い訳をするのか")).id
    tokens = get_document_tokens(document_id)
    head = tokens[0]
    phrase_conflict = next(c for c in head.conflicts if c.kind == "phrase")

    accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[phrase_conflict.id]))

    merged = [t for t in get_document_tokens(document_id) if t.phrase_start_position == head.position]
    assert len(merged) == 5
    for token in merged:
        assert token.gloss is not None
        assert token.gloss.lookup_form == "この期に及んで"
        assert token.gloss.reading == "このごにおよんで"
