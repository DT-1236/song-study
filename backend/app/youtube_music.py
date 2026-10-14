"""Song search on YouTube Music, whose "songs" results carry clean title,
artist and duration metadata rather than an uploader's decorated video
title."""

from __future__ import annotations

from dataclasses import dataclass

from ytmusicapi import YTMusic


class YouTubeMusicUnavailable(Exception):
    """YouTube Music couldn't be searched; the message is shown to the
    user."""


@dataclass(frozen=True)
class Song:
    video_id: str
    title: str
    artists: str
    album: str | None
    duration_seconds: int | None
    thumbnail_url: str | None


_client: YTMusic | None = None


def _ytmusic() -> YTMusic:
    global _client
    if _client is None:
        _client = YTMusic()
    return _client


def search_songs(query: str, videos: bool = False) -> list[Song]:
    """Up to ten YouTube Music songs matching `query`, best match first — or,
    when `videos` is set, up to ten matching videos instead (for music with
    no song entry, such as live recordings or covers).
    """
    try:
        # ytmusicapi is unofficial and scrapes YouTube Music's own web
        # client API, so it can break whenever YouTube changes that; any
        # failure from it is reported as the service being unavailable.
        # `limit` is only a minimum: a page of results comes back whole, so
        # it's cut to ten here.
        results = _ytmusic().search(
            query, filter="videos" if videos else "songs", limit=10
        )[:10]
    except Exception as exc:
        raise YouTubeMusicUnavailable(
            "Couldn't search YouTube Music right now. Try again later."
        ) from exc
    return [_song(result) for result in results if result.get("videoId")]


def _song(result: dict) -> Song:
    thumbnails = result.get("thumbnails") or []
    smallest = min(thumbnails, key=lambda t: t.get("width", 0), default=None)
    return Song(
        video_id=result["videoId"],
        title=result.get("title") or "",
        artists="、".join(a["name"] for a in result.get("artists") or []),
        album=(result.get("album") or {}).get("name"),
        duration_seconds=result.get("duration_seconds"),
        thumbnail_url=smallest["url"] if smallest else None,
    )
