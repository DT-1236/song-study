"""Tests for song search on YouTube Music (app/youtube_music.py). The
ytmusicapi client is replaced by a fake, so no test reaches the network."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import youtube_music
from app.youtube_music import Song, search_songs
from tests.support import as_session_user, songs_search


class FakeClient:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def search(self, query, filter=None, limit=None):
        self.calls.append((query, filter, limit))
        if self.error:
            raise self.error
        return self.results


@pytest.fixture
def fake_client(monkeypatch):
    def install(**kwargs):
        client = FakeClient(**kwargs)
        monkeypatch.setattr(youtube_music, "_client", client)
        return client

    return install


FULL = {
    "videoId": "abc123",
    "title": "テスト曲",
    "artists": [{"name": "歌手A", "id": "1"}, {"name": "歌手B", "id": "2"}],
    "album": {"name": "アルバム", "id": "3"},
    "duration_seconds": 261,
    "thumbnails": [
        {"url": "https://img/large", "width": 226, "height": 226},
        {"url": "https://img/small", "width": 60, "height": 60},
    ],
}


def test_maps_fields_and_picks_smallest_thumbnail(fake_client):
    client = fake_client(results=[FULL])
    assert search_songs("テスト") == [
        Song(
            video_id="abc123",
            title="テスト曲",
            artists="歌手A、歌手B",
            album="アルバム",
            duration_seconds=261,
            thumbnail_url="https://img/small",
        )
    ]
    assert client.calls == [("テスト", "songs", 10)]


def test_missing_album_duration_and_thumbnails(fake_client):
    fake_client(results=[{"videoId": "x", "title": "t", "artists": [], "album": None}])
    assert search_songs("t") == [
        Song("x", "t", "", None, None, None),
    ]


def test_skips_results_without_a_video_id(fake_client):
    fake_client(results=[{**FULL, "videoId": None}, {"title": "no id"}, FULL])
    assert [song.video_id for song in search_songs("t")] == ["abc123"]


def test_videos_are_searched_instead_of_songs(fake_client):
    client = fake_client(results=[FULL])
    assert [song.video_id for song in search_songs("t", videos=True)] == ["abc123"]
    assert client.calls == [("t", "videos", 10)]


def test_results_are_cut_to_ten(fake_client):
    fake_client(results=[{**FULL, "videoId": f"v{i}"} for i in range(20)])
    assert len(search_songs("t")) == 10


def test_endpoint_returns_songs(fake_client):
    fake_client(results=[FULL])
    [song] = songs_search(q="テスト")
    assert song.video_id == "abc123"
    assert song.duration_seconds == 261


def test_endpoint_maps_unavailable_to_502(fake_client):
    fake_client(error=RuntimeError("boom"))
    with pytest.raises(HTTPException) as exc:
        songs_search(q="t")
    assert exc.value.status_code == 502


def test_endpoint_requires_login(fake_client):
    fake_client(results=[FULL])
    with as_session_user(), pytest.raises(HTTPException) as exc:
        songs_search(q="t")
    assert exc.value.status_code == 401
