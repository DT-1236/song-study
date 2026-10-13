"""Tests for loading lyrics and line timings from LRCLIB (app/lrclib.py), and
for keeping a linked document in step with them. LRCLIB's API is replaced
by a fake, so no test reaches the network, and the lyrics served are
public-domain text (tests/fixtures/kumo_no_ito.py) or short test sentences.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app import lrclib
from app.db import owned_document_row
from app.lrclib import (
    LrclibError,
    LrclibLyrics,
    LrclibUnavailable,
    fetch_lyrics,
    normalize_lrclib_uri,
    parse_synced_lyrics,
    search_tracks,
)
from app.main import (
    DocumentCreate,
    DocumentTextUpdate,
    LineTiming,
    LrclibLink,
)
from app.tokenization import tokenize_document
from tests.fixtures.kumo_no_ito import FIRST_SENTENCE, SECOND_SENTENCE
from tests.support import (
    TEST_USER_ID,
    as_session_user,
    create_document,
    document_tokens,
    get_document,
    get_document_tokens,
    link_lrclib,
    lrclib_search,
    lrclib_track_lyrics,
    pick_reading,
    unlink_lrclib,
    update_document_text,
)

URI = "https://lrclib.net/api/get/1"
WEATHER = "今日は良い天気です。"


def _synced_record(lines: Sequence[tuple[float, str]], duration: float) -> dict:
    """An LRCLIB record with `lines`, (seconds, text) pairs, as synced
    lyrics."""
    return {
        "syncedLyrics": "\n".join(
            f"[{int(start // 60):02d}:{start % 60:05.2f}]{text}"
            for start, text in lines
        ),
        "plainLyrics": "\n".join(text for _, text in lines),
        "duration": duration,
        "instrumental": False,
    }


def _search_params(uri: str) -> frozenset | None:
    """The query parameters of `uri` if it's a search, else None."""
    parts = urllib.parse.urlsplit(uri)
    if parts.path != "/api/search":
        return None
    return frozenset(urllib.parse.parse_qsl(parts.query))


class FakeLrclib:
    """Stands in for LRCLIB's API: serves `records` by address and
    `searches` by query, or raises `error` if one is set."""

    def __init__(self):
        self.records: dict[str, dict] = {}
        # Keyed by a search's query parameters; an unknown search finds
        # nothing, as LRCLIB's does.
        self.searches: dict[frozenset, list[dict] | Exception] = {}
        self.error: Exception | None = None
        self.requests: list[str] = []

    def __call__(self, uri: str) -> dict | list | None:
        self.requests.append(uri)
        if self.error is not None:
            raise self.error
        if (params := _search_params(uri)) is not None:
            results = self.searches.get(params)
            if isinstance(results, Exception):
                raise results
            return results or []
        return self.records.get(uri)

    def publish(
        self, uri: str, lines: list[tuple[float, str]], duration: float = 60.0
    ) -> None:
        """Serve `lines`, (seconds, text) pairs, at `uri` as synced lyrics."""
        self.records[uri] = _synced_record(lines, duration)

    def answer(self, results: list[dict] | Exception, **params: str) -> None:
        """Answer a search for exactly `params` with `results`, or fail it
        with that error."""
        self.searches[frozenset(params.items())] = results

    def searched(self) -> list[dict[str, str]]:
        """The query parameters of each search made, in no particular order
        since they're sent concurrently."""
        return sorted(
            (
                dict(params)
                for uri in self.requests
                if (params := _search_params(uri)) is not None
            ),
            key=lambda params: sorted(params.items()),
        )


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
    lyrics = parse_synced_lyrics(
        "[00:30]最後\n[00:10.5][00:20.123]繰り返し\n[00:05:25]<00:05.25>最<00:06.00>初\n",
        40.0,
    )

    assert lyrics.text == "最初\n繰り返し\n繰り返し\n最後"
    assert lyrics.lines == [
        {"start": 5.25, "end": 10.5},
        {"start": 10.5, "end": 20.123},
        {"start": 20.123, "end": 30.0},
        {"start": 30.0, "end": 40.0},
    ]


def test_last_line_without_a_usable_duration_gets_a_fixed_length():
    # Some LRCLIB records have a duration shorter than their lyrics.
    assert parse_synced_lyrics("[00:10.00]一行目\n[00:20.00]二行目", 3.0).lines[-1] == {
        "start": 20.0,
        "end": 25.0,
    }
    assert parse_synced_lyrics("[00:10.00]一行目", None).lines[-1] == {
        "start": 10.0,
        "end": 15.0,
    }


@pytest.mark.parametrize(
    "value",
    [
        "123",
        " 123 ",
        "https://lrclib.net/api/get/123",
        "http://www.lrclib.net/api/get/123/",
        "lrclib.net/api/get/123",
    ],
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
    fake_lrclib.records[URI] = {
        "syncedLyrics": None,
        "plainLyrics": "一行目\r\n二行目\n",
        "duration": 60.0,
    }

    assert fetch_lyrics(URI) == LrclibLyrics("一行目\n二行目", None)


def test_record_without_lyrics_is_an_error(fake_lrclib):
    fake_lrclib.records[URI] = {
        "syncedLyrics": None,
        "plainLyrics": None,
        "instrumental": True,
        "duration": 60.0,
    }

    with pytest.raises(LrclibError):
        fetch_lyrics(URI)


def test_a_missing_track_is_a_refusal_not_an_outage(fake_lrclib):
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
        (
            urllib.error.HTTPError(
                URI, 429, "Too Many Requests", {"Retry-After": "3"}, None
            ),
            LrclibUnavailable,
        ),
        (
            urllib.error.HTTPError(URI, 503, "Service Unavailable", {}, None),
            LrclibUnavailable,
        ),
        (urllib.error.URLError("no route to host"), LrclibUnavailable),
        (TimeoutError(), LrclibUnavailable),
    ],
)
def test_request_failures(monkeypatch, error, expected):
    def urlopen(request, timeout):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    with pytest.raises(expected):
        lrclib._get_json(URI)


def test_a_missing_track_is_none(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.HTTPError(URI, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert lrclib._get_json(URI) is None


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


def test_document_created_from_lrclib_uses_its_lyrics_and_timings(
    committed_engine, fake_lrclib
):
    fake_lrclib.publish(
        URI, [(1.0, FIRST_SENTENCE), (9.0, SECOND_SENTENCE)], duration=20.0
    )

    document = create_document(
        DocumentCreate(title="test", text="ignored", lrclib_uri="1")
    )

    assert (document.text, document.lrclib_uri) == (
        f"{FIRST_SENTENCE}\n{SECOND_SENTENCE}",
        URI,
    )
    assert document.lrclib_lines == [
        LineTiming(start=1.0, end=9.0),
        LineTiming(start=9.0, end=20.0),
    ]


def _linked_document(fake_lrclib, lines, duration=60.0) -> int:
    fake_lrclib.publish(URI, lines, duration)
    return create_document(DocumentCreate(title="test", lrclib_uri=URI)).id


def test_loading_keeps_picked_readings_while_lrclib_is_unchanged(
    committed_engine, fake_lrclib
):
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


def test_text_update_on_lrclib_replaces_the_lyrics_and_resets_readings(
    committed_engine, fake_lrclib
):
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
    assert (unlinked.lrclib_uri, unlinked.lrclib_lines) == (
        None,
        [LineTiming(start=1.0, end=60.0)],
    )
    assert (
        update_document_text(
            document_id, DocumentTextUpdate(text=SECOND_SENTENCE)
        ).lrclib_lines
        is None
    )
    requests_before = len(fake_lrclib.requests)
    assert get_document(document_id).text == SECOND_SENTENCE
    assert len(fake_lrclib.requests) == requests_before


def test_linking_can_keep_the_lyrics_and_readings(committed_engine, fake_lrclib):
    document_id = create_document(DocumentCreate(title="test", text=WEATHER)).id
    pick_reading(document_id, "今日", "こんにち")
    fake_lrclib.publish(URI, [(1.0, "今日は雨です。")], duration=10.0)

    document = link_lrclib(document_id, LrclibLink(uri="1", replace_text=False))

    # LRCLIB's lyrics differ, so its timings don't fit these.
    assert (document.text, document.lrclib_uri, document.lrclib_lines) == (
        WEATHER,
        URI,
        None,
    )
    assert document_tokens(document_id, "今日")[0].gloss.reading == "こんにち"

    # Once they match, LRCLIB's timings are used, and the lyrics and
    # readings still stay.
    fake_lrclib.publish(URI, [(2.0, WEATHER)], duration=10.0)
    document = get_document(document_id)

    assert (document.text, document.lrclib_lines) == (
        WEATHER,
        [LineTiming(start=2.0, end=10.0)],
    )
    assert document_tokens(document_id, "今日")[0].gloss.reading == "こんにち"


def test_kept_lyrics_stay_editable_and_untimed_at_a_trailing_blank_line(
    committed_engine, fake_lrclib
):
    document_id = create_document(DocumentCreate(title="test", text=f"{WEATHER}\n")).id
    fake_lrclib.publish(URI, [(1.0, WEATHER)], duration=10.0)

    document = link_lrclib(document_id, LrclibLink(uri="1", replace_text=False))
    edited = update_document_text(document_id, DocumentTextUpdate(text=SECOND_SENTENCE))

    assert (document.text, document.lrclib_lines) == (
        f"{WEATHER}\n",
        [LineTiming(start=1.0, end=10.0)],
    )
    assert (edited.text, edited.lrclib_uri, edited.lrclib_lines) == (
        SECOND_SENTENCE,
        URI,
        None,
    )


def test_timings_are_hidden_once_any_writer_changes_the_text(
    committed_engine, fake_lrclib
):
    document_id = create_document(DocumentCreate(title="test", text=WEATHER)).id
    fake_lrclib.publish(URI, [(1.0, WEATHER)], duration=10.0)
    link_lrclib(document_id, LrclibLink(uri="1", replace_text=False))

    # A writer that doesn't clear the timings itself.
    with committed_engine.begin() as conn:
        conn.execute(
            text("UPDATE documents SET text = :text WHERE id = :id"),
            {"id": document_id, "text": SECOND_SENTENCE},
        )

    with committed_engine.connect() as conn:
        row = owned_document_row(conn, document_id, TEST_USER_ID)
    assert row.lrclib_lines is None


def test_linking_replaces_the_lyrics_and_times_the_tokens(
    committed_engine, fake_lrclib
):
    document_id = create_document(DocumentCreate(title="test", text=FIRST_SENTENCE)).id
    get_document_tokens(document_id)
    fake_lrclib.publish(URI, [(4.0, SECOND_SENTENCE)])

    document = link_lrclib(document_id, LrclibLink(uri="1"))
    tokens = get_document_tokens(document_id)

    assert (document.text, document.lrclib_uri) == (SECOND_SENTENCE, URI)
    assert [t.surface for t in tokens] == [
        r.surface for r in tokenize_document(SECOND_SENTENCE)
    ]
    assert document.lrclib_lines == [LineTiming(start=4.0, end=60.0)]


# Searching for tracks. The titles are invented.
SONG = "架空の歌"


def _track(
    track_id: int,
    name: str = SONG,
    duration: float = 200.0,
    *,
    lines: Sequence[tuple[float, str]] = (
        (1.0, FIRST_SENTENCE),
        (9.0, SECOND_SENTENCE),
    ),
    **fields,
) -> dict:
    """A search result for track `track_id`, synced to `lines` unless
    `fields` say otherwise."""
    return {
        **_synced_record(lines, duration),
        "id": track_id,
        "trackName": name,
        "artistName": "歌手",
        "albumName": "アルバム",
        **fields,
    }


def _ids(candidates) -> list[int]:
    return [candidate.id for candidate in candidates]


def test_search_sends_each_query_variant_once(fake_lrclib):
    search_tracks(f"{SONG} (TV Size)", "歌手", 200)

    assert fake_lrclib.searched() == [
        {"artist_name": "歌手", "track_name": f"{SONG} (TV Size)"},
        {"q": SONG},
        {"q": f"{SONG} (TV Size)"},
        {"q": f"{SONG} (TV Size) 歌手"},
    ]


def test_search_skips_variants_that_repeat_another(fake_lrclib):
    # No artist, and nothing to clean off the title.
    search_tracks(f" {SONG} ", "", 200)

    assert fake_lrclib.searched() == [{"q": SONG}, {"track_name": SONG}]


@pytest.mark.parametrize(
    ("title", "cleaned"),
    [
        (f"{SONG} (TV Size)", SONG),
        (f"{SONG}（TVサイズ）", SONG),
        (f"{SONG}【MV】", SONG),
        (f"{SONG} [Remix] (feat. 歌手)", SONG),
        (f'{SONG} - From "THE FIRST TAKE"', SONG),
        (f"{SONG} - Into The Night", SONG),
        (f"{SONG} feat. 歌手", SONG),
        (f"{SONG} FT. 歌手", SONG),
        # Brackets at the start or a hyphen inside a word aren't decoration.
        (f"(秘密){SONG}", f"(秘密){SONG}"),
        ("Re-Start", "Re-Start"),
    ],
)
def test_cleaned_title_drops_trailing_decorations(title, cleaned):
    assert lrclib._clean_title(title) == cleaned


def test_a_title_that_is_all_decoration_isnt_searched_bare(fake_lrclib):
    search_tracks("【MV】", "", 200)

    assert {"q": ""} not in fake_lrclib.searched()


def test_search_merges_variants_by_track(fake_lrclib):
    fake_lrclib.answer([_track(1), _track(2)], q=SONG)
    fake_lrclib.answer([_track(2), _track(3)], track_name=SONG, artist_name="歌手")

    assert sorted(_ids(search_tracks(SONG, "歌手", 200))) == [1, 2, 3]


def test_a_match_found_only_by_the_cleaned_title_is_kept(fake_lrclib):
    fake_lrclib.answer([_track(1)], q=SONG)

    [candidate] = search_tracks(f"{SONG} (TV Size)", "", 200)

    assert (candidate.id, candidate.title_match) == (1, "partial")


@pytest.mark.parametrize(
    ("name", "match"),
    [
        ("Fake Song", "whole"),
        # Width, case, spacing and punctuation aren't told apart.
        ("ＦＡＫＥ ＳＯＮＧ", "whole"),
        ("fake-song!", "whole"),
        # Containing the title, or contained in it, either way round.
        ("歌手「Fake Song」 Official Music Video", "partial"),
        ("fake", "partial"),
        ("Other Song", None),
        # A title of only punctuation isn't contained in every other one.
        ("!!!", None),
    ],
)
def test_search_keeps_only_matching_titles(fake_lrclib, name, match):
    fake_lrclib.answer([_track(1, name)], q="Fake Song")

    candidates = search_tracks("Fake Song", "", 200)

    assert [c.title_match for c in candidates] == ([match] if match else [])


def test_decorated_titles_match_however_theyre_written(fake_lrclib):
    title = f'{SONG} (From "THE FIRST TAKE")'
    fake_lrclib.answer([_track(1, f"{SONG} - From THE FIRST TAKE")], q=title)

    assert [c.title_match for c in search_tracks(title, "", 200)] == ["whole"]


def test_search_drops_tracks_without_lyrics(fake_lrclib):
    fake_lrclib.answer(
        [
            _track(1, instrumental=True),
            _track(2, syncedLyrics=None, plainLyrics=None),
            _track(3, syncedLyrics="[ar: 歌手]", plainLyrics=""),
            _track(4, syncedLyrics=None),
        ],
        q=SONG,
    )

    [candidate] = search_tracks(SONG, "", 200)

    assert (candidate.id, candidate.synced) == (4, False)


def test_candidate_fields(fake_lrclib):
    fake_lrclib.answer(
        [
            _track(
                7,
                duration=201.5,
                lines=[(0.0, ""), (1.0, FIRST_SENTENCE), (5.0, ""), (9.0, "二行目")],
            )
        ],
        q=SONG,
    )

    [candidate] = search_tracks(SONG, "", 200)

    assert candidate == lrclib.LrclibCandidate(
        id=7,
        uri=normalize_lrclib_uri("7"),
        track_name=SONG,
        artist_name="歌手",
        album_name="アルバム",
        duration=201.5,
        synced=True,
        title_match="whole",
        duration_delta=1.5,
        within_tolerance=True,
        preview=[FIRST_SENTENCE, "二行目"],
    )


def test_plain_lyrics_preview(fake_lrclib):
    fake_lrclib.answer(
        [_track(1, syncedLyrics=None, plainLyrics="\n一行目\n\n二行目\n三行目")],
        q=SONG,
    )

    assert search_tracks(SONG, "", 200)[0].preview == ["一行目", "二行目"]


def test_search_ranks_length_then_sync_then_title_then_closeness(fake_lrclib):
    fake_lrclib.answer(
        [
            _track(1, duration=230),  # too long
            _track(2, f"{SONG} (TV Size)", duration=202),
            _track(3, duration=203, syncedLyrics=None),
            _track(4, duration=197),
            _track(5, duration=201),
            _track(6, duration=203.5),  # just past the tolerance
        ],
        q=SONG,
    )

    candidates = search_tracks(SONG, "", 200)

    assert _ids(candidates) == [5, 4, 2, 3, 6, 1]
    assert [c.within_tolerance for c in candidates] == [True] * 4 + [False] * 2


def test_search_without_a_duration_is_never_within_tolerance(fake_lrclib):
    fake_lrclib.answer([_track(1), _track(2, duration=None)], q=SONG)

    candidates = search_tracks(SONG, "", None)

    assert [(c.duration_delta, c.within_tolerance) for c in candidates] == [
        (None, False),
        (None, False),
    ]


def test_search_tolerates_a_failed_variant(fake_lrclib):
    fake_lrclib.answer(LrclibUnavailable("Couldn't reach LRCLIB."), track_name=SONG)
    fake_lrclib.answer([_track(1)], q=SONG)

    assert _ids(search_tracks(SONG, "", 200)) == [1]


def test_search_fails_when_every_variant_does(fake_lrclib):
    fake_lrclib.error = LrclibUnavailable(
        "LRCLIB is rate-limiting requests — try again later."
    )

    with pytest.raises(LrclibUnavailable):
        search_tracks(SONG, "歌手", 200)


def test_search_endpoint_returns_candidates(fake_lrclib):
    fake_lrclib.answer([_track(1, duration=262)], q=f"{SONG} 歌手")

    [candidate] = lrclib_search(title=SONG, artist="歌手", duration=261)

    assert (candidate.id, candidate.within_tolerance) == (1, True)


def test_search_endpoint_duration_is_optional(fake_lrclib):
    fake_lrclib.answer([_track(1)], q=SONG)

    [candidate] = lrclib_search(title=SONG)

    assert candidate.duration_delta is None


def test_search_endpoint_maps_unavailable_to_502(fake_lrclib):
    fake_lrclib.error = LrclibUnavailable("Couldn't reach LRCLIB.")

    with pytest.raises(HTTPException) as rejected:
        lrclib_search(title=SONG)
    assert rejected.value.status_code == 502


def test_search_endpoint_requires_login(fake_lrclib):
    with as_session_user(), pytest.raises(HTTPException) as rejected:
        lrclib_search(title=SONG)
    assert rejected.value.status_code == 401
    assert fake_lrclib.requests == []


def test_track_lyrics_endpoint_returns_synced_lines(fake_lrclib):
    fake_lrclib.publish(URI, [(1.0, FIRST_SENTENCE), (4.5, SECOND_SENTENCE)], 10.0)

    lyrics = lrclib_track_lyrics(track_id=1)

    assert lyrics.text == f"{FIRST_SENTENCE}\n{SECOND_SENTENCE}"
    assert lyrics.lines == [
        LineTiming(start=1.0, end=4.5),
        LineTiming(start=4.5, end=10.0),
    ]


def test_track_lyrics_endpoint_returns_plain_lyrics_untimed(fake_lrclib):
    fake_lrclib.records[URI] = {"syncedLyrics": None, "plainLyrics": WEATHER}

    lyrics = lrclib_track_lyrics(track_id=1)

    assert (lyrics.text, lyrics.lines) == (WEATHER, None)


def test_track_lyrics_endpoint_rejects_a_missing_track(fake_lrclib):
    with pytest.raises(HTTPException) as rejected:
        lrclib_track_lyrics(track_id=2)
    assert rejected.value.status_code == 422


def test_track_lyrics_endpoint_maps_unavailable_to_502(fake_lrclib):
    fake_lrclib.error = LrclibUnavailable("Couldn't reach LRCLIB.")

    with pytest.raises(HTTPException) as rejected:
        lrclib_track_lyrics(track_id=1)
    assert rejected.value.status_code == 502


def test_track_lyrics_endpoint_requires_login(fake_lrclib):
    fake_lrclib.publish(URI, [(1.0, FIRST_SENTENCE)])

    with as_session_user(), pytest.raises(HTTPException) as rejected:
        lrclib_track_lyrics(track_id=1)
    assert rejected.value.status_code == 401
    assert fake_lrclib.requests == []
