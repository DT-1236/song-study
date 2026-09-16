"""Regression tests for app.phrase_merge's noun+する verbalization fallback
(_suru_verb_suggestion) at the full accept-and-gloss level — see
app/phrase_merge.py's module docstring for why this exists: Japanese's
noun+する verbalization (買い物する "to shop") is fully productive, so most
such combinations were never going to be JMDict headwords of their own no
matter how the exact-match phrase search was tuned, only Sudachi's own
サ変可能 ("can take する") tag identifies them.
"""

from __future__ import annotations

from app.main import DocumentCreate, PhraseAcceptance, accept_phrase_suggestions_endpoint, create_document, get_document_tokens


def test_accepting_gives_a_composite_gloss_from_the_nouns_and_surus_own_senses(committed_engine):
    document_id = create_document(DocumentCreate(title="t", text="買い物した。")).id
    tokens = get_document_tokens(document_id)
    head = next(t for t in tokens if t.surface == "買い物")
    conflict = next(c for c in head.conflicts if c.kind == "phrase")
    assert conflict.value == {
        "surface": "買い物し",
        "lookup_form": "買い物する",
        "reading": "かいものする",
        "token_count": 2,
    }

    accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[conflict.id]))

    merged = [t for t in get_document_tokens(document_id) if t.phrase_start_position == head.position]
    assert len(merged) == 2
    for token in merged:
        assert token.gloss is not None
        assert token.gloss.lookup_form == "買い物する"
        assert token.gloss.source == "composite"
        pieces = {p.surface: p for p in token.gloss.pieces}
        noun_glosses = [g for s in pieces["買い物"].senses for g in s.gloss]
        assert "shopping" in noun_glosses
        assert pieces["する"].senses  # する's own senses are present too


def test_accepting_absorbs_a_bare_trailing_connector_with_no_chain(committed_engine):
    # 買い物し directly followed by a bare て with nothing after it forming
    # a light-verb chain (帰る here is an ordinary, literal verb, not a
    # 非自立可能 light verb) — real case found live: 遠回りし+て left the
    # trailing て out of the fusion entirely (see
    # app/phrase_merge.py's _with_trailing_connector).
    document_id = create_document(DocumentCreate(title="t", text="買い物して帰る。")).id
    tokens = get_document_tokens(document_id)
    head = next(t for t in tokens if t.surface == "買い物")
    conflict = next(c for c in head.conflicts if c.kind == "phrase")
    assert conflict.value == {
        "surface": "買い物して",
        "lookup_form": "買い物して",
        "reading": "かいものするて",
        "token_count": 3,
        "base_lookup_form": "買い物する",
        "base_reading": "かいものする",
        "chain_start_offset": 2,
    }

    accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[conflict.id]))

    merged = [t for t in get_document_tokens(document_id) if t.phrase_start_position == head.position]
    assert len(merged) == 3  # 買い物, し, て — the connector shares the group's gloss
    for token in merged:
        assert token.gloss is not None
        assert token.gloss.source == "composite"
        pieces = {p.surface: p for p in token.gloss.pieces}
        # Still exactly the noun+する composition — the connector added no
        # vocabulary and gets no piece of its own.
        assert set(pieces) == {"買い物", "する"}
        assert "shopping" in [g for s in pieces["買い物"].senses for g in s.gloss]


def test_prefers_a_real_dictionary_entry_over_the_suru_fallback(committed_engine):
    # 恋する ("to fall in love") is one of the rare サ変可能 nouns whose own
    # noun+する combination really is a JMDict headword — this must resolve
    # through the ordinary exact-match path (source='jmdict', real senses)
    # rather than the suru-verbalization fallback (source='composite'),
    # which would still produce the same lookup_form but from synthesized
    # per-piece senses instead of 恋する's actual dictionary entry.
    document_id = create_document(DocumentCreate(title="t", text="彼女に恋してしまった。")).id
    tokens = get_document_tokens(document_id)
    head = next(t for t in tokens if t.surface == "恋")
    conflict = next(c for c in head.conflicts if c.kind == "phrase")
    assert conflict.value["lookup_form"] == "恋する"

    accept_phrase_suggestions_endpoint(document_id, PhraseAcceptance(conflict_ids=[conflict.id]))

    merged = [t for t in get_document_tokens(document_id) if t.phrase_start_position == head.position]
    assert len(merged) == 2
    for token in merged:
        assert token.gloss is not None
        assert token.gloss.lookup_form == "恋する"
        assert token.gloss.source == "jmdict"
        assert token.gloss.senses  # real senses, not per-piece composite ones
