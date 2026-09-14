"""Tests for loading lyrics and line timings from LRCLIB (app/lrclib.py), and
for keeping a linked document in step with them. LRCLIB's API is replaced
by a fake, so no test reaches the network, and the lyrics served are
public-domain text (tests/fixtures/kumo_no_ito.py) or short test sentences.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import lrclib
from app.lrclib import (
    LrclibError,
    LrclibLyrics,
    LrclibUnavailable,
    fetch_lyrics,
    normalize_lrclib_uri,
    parse_synced_lyrics,
)
from app.main import (
    DocumentCreate,
    DocumentTextUpdate,
    LineTiming,
    LrclibLink,
    create_document,
    get_document,
    get_document_tokens,
    link_lrclib,
    unlink_lrclib,
    update_document_text,
)
from app.tokenization import tokenize_document
from tests.fixtures.kumo_no_ito import FIRST_SENTENCE, SECOND_SENTENCE
from tests.support import document_tokens, pick_reading

URI = "https://lrclib.net/api/get/1"
WEATHER = "今日は良い天気です。"


class FakeLrclib:
    """Stands in for LRCLIB's API: serves `records` by address, or raises
    `error` if one is set."""

    def __init__(self):
        self.records: dict[str, dict] = {}
        self.error: Exception | None = None
        self.requests: list[str] = []

    def __call__(self, uri: str) -> dict:
        self.requests.append(uri)
        if self.error is not None:
            raise self.error
        if uri not in self.records:
            raise LrclibError("LRCLIB has no track at that address.")
        return self.records[uri]

    def publish(self, uri: str, lines: list[tuple[float, str]], duration: float = 60.0) -> None:
        """Serve `lines`, (seconds, text) pairs, at `uri` as synced lyrics."""
        self.records[uri] = {
            "syncedLyrics": "\n".join(f"[{int(start // 60):02d}:{start % 60:05.2f}]{text}" for start, text in lines),
            "plainLyrics": "\n".join(text for _, text in lines),
            "duration": duration,
            "instrumental": False,
        }


@pytest.fixture
def fake_lrclib(monkeypatch):
    fake = FakeLrclib()
    monkeypatch.setattr(lrclib, "_get_json", fake)
    return fake


def test_each_synced_line_runs_until_the_next_one():
    lyrics = parse_synced_lyrics(
        "[ar: someone]\n[00:00.00]\n[00:01.00]一行目\n[00:03.50] 二行目 \n[00:07.25]\n[00:08.00]三行目\n[00:11.00]\n",
        60.0,
    )

    # The blank lines at either end only time the lines next to them; the
    # one in between stays, separating stanzas.
    assert lyrics.text == "一行目\n二行目\n\n三行目"
    assert lyrics.lines == [
        {"start": 1.0, "end": 3.5},
        {"start": 3.5, "end": 7.25},
        {"start": 7.25, "end": 8.0},
        {"start": 8.0, "end": 11.0},
    ]


def test_synced_lyrics_timestamp_variants():
    lyrics = parse_synced_lyrics("[00:30]最後\n[00:10.5][00:20.123]繰り返し\n[00:05:25]<00:05.25>最<00:06.00>初\n", 40.0)

    assert lyrics.text == "最初\n繰り返し\n繰り返し\n最後"
    assert lyrics.lines == [
        {"start": 5.25, "end": 10.5},
        {"start": 10.5, "end": 20.123},
        {"start": 20.123, "end": 30.0},
        {"start": 30.0, "end": 40.0},
    ]


def test_last_line_without_a_usable_duration_gets_a_fixed_length():
    # Some LRCLIB records have a duration shorter than their lyrics.
    assert parse_synced_lyrics("[00:10.00]一行目\n[00:20.00]二行目", 3.0).lines[-1] == {"start": 20.0, "end": 25.0}
    assert parse_synced_lyrics("[00:10.00]一行目", None).lines[-1] == {"start": 10.0, "end": 15.0}


@pytest.mark.parametrize(
    "value",
    ["123", " 123 ", "https://lrclib.net/api/get/123", "http://www.lrclib.net/api/get/123/", "lrclib.net/api/get/123"],
)
def test_lrclib_uri_normalization(value):
    assert normalize_lrclib_uri(value) == "https://lrclib.net/api/get/123"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "abc",
        "https://example.com/api/get/123",
        "https://lrclib.net.example.com/api/get/123",
        "https://lrclib.net@example.com/api/get/123",
        "https://lrclib.net/api/search?q=x",
        "ftp://lrclib.net/api/get/123",
    ],
)
def test_lrclib_uri_must_be_an_lrclib_track(value):
    with pytest.raises(LrclibError):
        normalize_lrclib_uri(value)


def test_plain_only_record_gives_untimed_lyrics(fake_lrclib):
    fake_lrclib.records[URI] = {"syncedLyrics": None, "plainLyrics": "一行目\r\n二行目\n", "duration": 60.0}

    assert fetch_lyrics(URI) == LrclibLyrics("一行目\n二行目", None)


def test_record_without_lyrics_is_an_error(fake_lrclib):
    fake_lrclib.records[URI] = {"syncedLyrics": None, "plainLyrics": None, "instrumental": True, "duration": 60.0}

    with pytest.raises(LrclibError):
        fetch_lyrics(URI)


def test_requests_identify_the_app(monkeypatch):
    sent = []

    def urlopen(request, timeout):
        sent.append(request)
        return io.BytesIO(b'{"id": 1}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert lrclib._get_json(URI) == {"id": 1}
    assert sent[0].get_header("User-agent") == lrclib.USER_AGENT


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (urllib.error.HTTPError(URI, 404, "Not Found", {}, None), LrclibError),
        (urllib.error.HTTPError(URI, 429, "Too Many Requests", {"Retry-After": "3"}, None), LrclibUnavailable),
        (urllib.error.HTTPError(URI, 503, "Service Unavailable", {}, None), LrclibUnavailable),
        (urllib.error.URLError("no route to host"), LrclibUnavailable),
        (TimeoutError(), LrclibUnavailable),
    ],
)
def test_request_failures(monkeypatch, error, expected):
    def urlopen(request, timeout):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    with pytest.raises(expected) as raised:
        lrclib._get_json(URI)
    # Exactly, since LrclibUnavailable is an LrclibError too.
    assert raised.type is expected


def test_a_document_needs_lyrics_or_an_lrclib_track():
    with pytest.raises(ValidationError):
        DocumentCreate(title="test", text="  ")


@pytest.mark.parametrize("uri", ["not a track", "2"])
def test_creating_from_an_unusable_track_is_rejected(fake_lrclib, uri):
    with pytest.raises(HTTPException) as rejected:
        create_document(DocumentCreate(title="test", lrclib_uri=uri))

    assert rejected.value.status_code == 422


def test_creating_while_lrclib_is_unreachable_fails(fake_lrclib):
    fake_lrclib.error = LrclibUnavailable("Couldn't reach LRCLIB.")

    with pytest.raises(HTTPException) as rejected:
        create_document(DocumentCreate(title="test", lrclib_uri="1"))

    assert rejected.value.status_code == 502


def test_document_created_from_lrclib_uses_its_lyrics_and_timings(committed_engine, fake_lrclib):
    fake_lrclib.publish(URI, [(1.0, FIRST_SENTENCE), (9.0, SECOND_SENTENCE)], duration=20.0)

    document = create_document(DocumentCreate(title="test", text="ignored", lrclib_uri="1"))

    assert (document.text, document.lrclib_uri) == (f"{FIRST_SENTENCE}\n{SECOND_SENTENCE}", URI)
    assert document.lrclib_lines == [LineTiming(start=1.0, end=9.0), LineTiming(start=9.0, end=20.0)]


def _linked_document(fake_lrclib, lines, duration=60.0) -> int:
    fake_lrclib.publish(URI, lines, duration)
    return create_document(DocumentCreate(title="test", lrclib_uri=URI)).id


def test_loading_keeps_picked_readings_while_lrclib_is_unchanged(committed_engine, fake_lrclib):
    document_id = _linked_document(fake_lrclib, [(1.0, WEATHER)])
    pick_reading(document_id, "今日", "こんにち")

    assert get_document(document_id).text == WEATHER
    assert document_tokens(document_id, "今日")[0].gloss.reading == "こんにち"


def test_timing_update_on_lrclib_keeps_picked_readings(committed_engine, fake_lrclib):
    document_id = _linked_document(fake_lrclib, [(1.0, WEATHER)], duration=10.0)
    pick_reading(document_id, "今日", "こんにち")
    before = document_tokens(document_id, "今日")[0]

    fake_lrclib.publish(URI, [(2.0, WEATHER)], duration=10.0)
    document = get_document(document_id)
    after = document_tokens(document_id, "今日")[0]

    assert document.lrclib_lines == [LineTiming(start=2.0, end=10.0)]
    assert after.id == before.id
    assert after.gloss.reading == "こんにち"


def test_text_update_on_lrclib_replaces_the_lyrics_and_resets_readings(committed_engine, fake_lrclib):
    document_id = _linked_document(fake_lrclib, [(1.0, WEATHER)])
    pick_reading(document_id, "今日", "こんにち")

    fake_lrclib.publish(URI, [(1.0, "今日は雨です。")])

    assert get_document(document_id).text == "今日は雨です。"
    assert document_tokens(document_id, "今日")[0].gloss.reading == "きょう"


def test_unreachable_lrclib_serves_the_stored_lyrics(committed_engine, fake_lrclib):
    document_id = _linked_document(fake_lrclib, [(1.0, FIRST_SENTENCE)])
    fake_lrclib.error = LrclibUnavailable("Couldn't reach LRCLIB.")

    document = get_document(document_id)

    assert document.text == FIRST_SENTENCE
    assert document.lrclib_sync_error.startswith("Couldn't reach LRCLIB.")


def test_linked_lyrics_are_only_editable_once_unlinked(committed_engine, fake_lrclib):
    document_id = _linked_document(fake_lrclib, [(1.0, FIRST_SENTENCE)])

    with pytest.raises(HTTPException) as refused:
        update_document_text(document_id, DocumentTextUpdate(text=SECOND_SENTENCE))
    assert refused.value.status_code == 409

    unlinked = unlink_lrclib(document_id)
    # The line timings still match the unchanged text, until it's edited.
    assert (unlinked.lrclib_uri, unlinked.lrclib_lines) == (None, [LineTiming(start=1.0, end=60.0)])
    assert update_document_text(document_id, DocumentTextUpdate(text=SECOND_SENTENCE)).lrclib_lines is None
    requests_before = len(fake_lrclib.requests)
    assert get_document(document_id).text == SECOND_SENTENCE
    assert len(fake_lrclib.requests) == requests_before


def test_linking_can_keep_the_lyrics_and_readings(committed_engine, fake_lrclib):
    document_id = create_document(DocumentCreate(title="test", text=WEATHER)).id
    pick_reading(document_id, "今日", "こんにち")
    fake_lrclib.publish(URI, [(1.0, "今日は雨です。")], duration=10.0)

    document = link_lrclib(document_id, LrclibLink(uri="1", replace_text=False))

    # LRCLIB's lyrics differ, so its timings don't fit these.
    assert (document.text, document.lrclib_uri, document.lrclib_lines) == (WEATHER, URI, None)
    assert document_tokens(document_id, "今日")[0].gloss.reading == "こんにち"

    # Once they match, LRCLIB's timings are used, and the lyrics and
    # readings still stay.
    fake_lrclib.publish(URI, [(2.0, WEATHER)], duration=10.0)
    document = get_document(document_id)

    assert (document.text, document.lrclib_lines) == (WEATHER, [LineTiming(start=2.0, end=10.0)])
    assert document_tokens(document_id, "今日")[0].gloss.reading == "こんにち"


def test_kept_lyrics_stay_editable_and_untimed_at_a_trailing_blank_line(committed_engine, fake_lrclib):
    document_id = create_document(DocumentCreate(title="test", text=f"{WEATHER}\n")).id
    fake_lrclib.publish(URI, [(1.0, WEATHER)], duration=10.0)

    document = link_lrclib(document_id, LrclibLink(uri="1", replace_text=False))
    edited = update_document_text(document_id, DocumentTextUpdate(text=SECOND_SENTENCE))

    assert (document.text, document.lrclib_lines) == (f"{WEATHER}\n", [LineTiming(start=1.0, end=10.0)])
    assert (edited.text, edited.lrclib_uri, edited.lrclib_lines) == (SECOND_SENTENCE, URI, None)


def test_linking_replaces_the_lyrics_and_times_the_tokens(committed_engine, fake_lrclib):
    document_id = create_document(DocumentCreate(title="test", text=FIRST_SENTENCE)).id
    get_document_tokens(document_id)
    fake_lrclib.publish(URI, [(4.0, SECOND_SENTENCE)])

    document = link_lrclib(document_id, LrclibLink(uri="1"))
    tokens = get_document_tokens(document_id)

    assert (document.text, document.lrclib_uri) == (SECOND_SENTENCE, URI)
    assert [t.surface for t in tokens] == [r.surface for r in tokenize_document(SECOND_SENTENCE)]
    assert document.lrclib_lines == [LineTiming(start=4.0, end=60.0)]
