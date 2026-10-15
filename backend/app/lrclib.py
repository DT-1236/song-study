"""Lyrics and line timings from LRCLIB (https://lrclib.net/docs).

A record's `syncedLyrics` is LRC: one `[mm:ss.xx] text` line per sung line,
timed per line only. LRCLIB doesn't serve word-level timing in practice (its
newer `lyricsfile` field has a per-line `words` list, empty on every record
checked), so lyrics are timed, and highlighted, by line.

A track id's lyrics can change — publishing to LRCLIB adds a new version to
the same track — so a linked document is re-fetched when loaded, at most
once a day, and compared against what was stored (see app/main.py).

Tracks are found by a song's artist and cleaned title, then ranked by length
(search_tracks). LRCLIB's search ignores length, so the length matching
happens here.
"""

from __future__ import annotations

import email.utils
import json
import logging
import math
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.sanitize import sanitize_text

logger = logging.getLogger(__name__)

# LRCLIB asks every client to identify itself this way.
USER_AGENT = "song-study (https://github.com/DT-1236/song-study)"

_API_GET = "https://lrclib.net/api/get"
_API_SEARCH = "https://lrclib.net/api/search"
_TIMEOUT_SECONDS = 5


class LrclibError(Exception):
    """LRCLIB refusing a request for lyrics — a bad address, no such track,
    or no lyrics — with a message that's shown to the user."""


class LrclibUnavailable(Exception):
    """LRCLIB couldn't be reached or failed, rather than refusing the
    request."""


class LrclibRateLimited(LrclibUnavailable):
    """LRCLIB telling us, or us remembering it told us, to wait
    `retry_after_seconds` before the next request."""

    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            "LRCLIB is rate-limiting requests — try again in "
            f"{math.ceil(retry_after_seconds)} seconds."
        )


class _RateLimit:
    """When LRCLIB's last rate limit ends. Requests before then aren't sent,
    since they would only extend the limit. Each process learns the limit
    for itself."""

    def __init__(self):
        # Handlers run in the threadpool, so a 429 can land while another
        # request is checking.
        self._lock = threading.Lock()
        # On the monotonic clock.
        self._until = 0.0

    def check(self) -> None:
        """Raise LrclibRateLimited if LRCLIB's rate limit hasn't ended."""
        with self._lock:
            remaining = self._until - time.monotonic()
        if remaining > 0:
            raise LrclibRateLimited(remaining)

    def start(self, seconds: float) -> None:
        """Remember that LRCLIB asked for no requests for `seconds`, unless
        an earlier answer already asked for longer."""
        with self._lock:
            self._until = max(self._until, time.monotonic() + seconds)

    def reset(self) -> None:
        with self._lock:
            self._until = 0.0


_rate_limit = _RateLimit()


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """The seconds a `Retry-After` header `value` asks for, whether it's a
    number of seconds or an HTTP date; None if it's absent or unreadable."""
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return float(value)
    try:
        date = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return max(0.0, (date - (now or datetime.now(UTC))).total_seconds())


_TRACK_ID_RE = re.compile(r"\d+")
_GET_BY_ID_PATH_RE = re.compile(r"/api/get/(\d+)/?")


def normalize_lrclib_uri(value: str) -> str:
    """The canonical LRCLIB API address for `value`, a track id or an
    lrclib.net/api/get/{id} URL. Nothing else is accepted, since the server
    fetches whatever this returns."""
    value = value.strip()
    if _TRACK_ID_RE.fullmatch(value):
        return _track_uri(value)
    parsed = urllib.parse.urlsplit(value if "://" in value else f"https://{value}")
    if (
        parsed.scheme in ("http", "https")
        and parsed.hostname in ("lrclib.net", "www.lrclib.net")
        and (match := _GET_BY_ID_PATH_RE.fullmatch(parsed.path))
    ):
        return _track_uri(match.group(1))
    raise LrclibError(
        "Enter an LRCLIB track ID, or its https://lrclib.net/api/get/… address."
    )


def _track_uri(track_id: int | str) -> str:
    return f"{_API_GET}/{track_id}"


@dataclass(frozen=True)
class LrclibLyrics:
    text: str
    # One {"start", "end"} per line of `text`, in seconds, or None when the
    # record only has unsynced lyrics.
    lines: list[dict] | None


# [mm:ss], [mm:ss.x…], or the [mm:ss:xx] some LRC writers use.
_LINE_TIMESTAMP_RE = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d+)?)\]")
# Enhanced LRC's per-word timestamps.
_WORD_TIMESTAMP_RE = re.compile(r"<\d+:\d{1,2}(?:[.:]\d+)?>")
# How long the last line lasts when the track's duration doesn't say.
_LAST_LINE_FALLBACK_SECONDS = 5.0


def parse_synced_lyrics(lrc: str, duration: float | None) -> LrclibLyrics:
    """The text of LRC-format lyrics, one line per timed line in time order,
    each timed from its timestamp to the next line's — the last line's to
    `duration`, the track's length in seconds."""
    timed: list[tuple[float, str]] = []
    for raw_line in lrc.splitlines():
        stamps = []
        rest = raw_line
        while match := _LINE_TIMESTAMP_RE.match(rest):
            minutes, seconds = match.groups()
            stamps.append(int(minutes) * 60 + float(seconds.replace(":", ".")))
            rest = rest[match.end() :]
        # Untimed lines (metadata tags like [ar: …]) aren't lyrics. A line
        # with several timestamps (a repeated chorus) is sung at each.
        # `raw_line` has no line breaks left, so sanitizing keeps it one line.
        text = sanitize_text(_WORD_TIMESTAMP_RE.sub("", rest))
        timed.extend((stamp, text) for stamp in stamps)
    timed.sort(key=lambda pair: pair[0])

    lines = []
    for index, (start, text) in enumerate(timed):
        if index + 1 < len(timed):
            end = timed[index + 1][0]
        elif duration is not None and duration > start:
            end = duration
        else:
            end = start + _LAST_LINE_FALLBACK_SECONDS
        lines.append((text, {"start": round(start, 3), "end": round(end, 3)}))

    # A blank timed line marks where the line before it ends (an
    # instrumental break), so blank lines only leave the text after the
    # timings are worked out — and only at either end, since the ones in
    # between separate stanzas.
    while lines and not lines[0][0]:
        lines.pop(0)
    while lines and not lines[-1][0]:
        lines.pop()
    return LrclibLyrics(
        "\n".join(text for text, _ in lines), [timing for _, timing in lines]
    )


def _get_json(uri: str) -> Any | None:
    """The JSON at `uri`, or None when LRCLIB answers 404."""
    try:
        _rate_limit.check()
    except LrclibRateLimited as exc:
        logger.info(
            "LRCLIB request skipped, rate-limited for %.1fs: %s",
            exc.retry_after_seconds,
            uri,
        )
        raise

    request = urllib.request.Request(
        uri, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    logger.info("LRCLIB request: GET %s", uri)
    started = time.monotonic()
    try:
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                result, status = json.load(response), response.status
        # HTTPError is a URLError, so it has to be caught first.
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            result, status = None, 404
    except urllib.error.HTTPError as exc:
        logger.warning(
            "LRCLIB error: %s %s in %.2fs, Retry-After %s, body %r",
            exc.code,
            uri,
            time.monotonic() - started,
            exc.headers.get("Retry-After"),
            _error_body(exc),
        )
        if exc.code == 429:
            wait = parse_retry_after(exc.headers.get("Retry-After"))
            if wait is None:
                raise LrclibUnavailable(
                    "LRCLIB is rate-limiting requests — try again later."
                ) from exc
            _rate_limit.start(wait)
            raise LrclibRateLimited(wait) from exc
        raise LrclibUnavailable(
            f"LRCLIB responded with an error ({exc.code})."
        ) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning(
            "LRCLIB request failed: %s after %.2fs: %s: %s",
            uri,
            time.monotonic() - started,
            type(exc).__name__,
            exc,
        )
        raise LrclibUnavailable("Couldn't reach LRCLIB.") from exc
    logger.info(
        "LRCLIB response: %s %s in %.2fs", status, uri, time.monotonic() - started
    )
    return result


def _error_body(exc: urllib.error.HTTPError) -> str:
    """The start of the body LRCLIB sent with an error, for the log."""
    try:
        return exc.read(500).decode("utf-8", errors="replace")
    except OSError:
        return ""


def fetch_lyrics(uri: str) -> LrclibLyrics:
    """The lyrics the LRCLIB record at `uri` (as normalize_lrclib_uri
    returns it) currently has: its synced lyrics if any, else its plain
    ones."""
    record = _get_json(uri)
    if record is None:
        raise LrclibError("LRCLIB has no track at that address.")
    return _record_lyrics(record)


def _record_lyrics(record: dict) -> LrclibLyrics:
    if record.get("syncedLyrics"):
        lyrics = parse_synced_lyrics(record["syncedLyrics"], record.get("duration"))
        if lyrics.text:
            return lyrics
    plain = sanitize_text(record.get("plainLyrics") or "").strip("\n")
    if plain:
        return LrclibLyrics(plain, None)
    if record.get("instrumental"):
        raise LrclibError(
            "That LRCLIB track is marked instrumental, so it has no lyrics."
        )
    raise LrclibError("That LRCLIB track has no lyrics.")


# LRCLIB's own /api/get accepts durations within about 2 seconds, and
# YouTube Music rounds a song's to whole seconds.
_DURATION_TOLERANCE_SECONDS = 3


@dataclass(frozen=True)
class LrclibCandidate:
    id: int
    uri: str
    track_name: str
    artist_name: str
    album_name: str | None
    duration: float | None
    synced: bool
    # "whole" when the titles are the same once normalized, "partial" when
    # one contains the other.
    title_match: Literal["whole", "partial"]
    # The track's length minus the song's, in seconds, or None when either
    # is unknown — in which case it isn't within tolerance.
    duration_delta: float | None
    within_tolerance: bool
    # The first two lyric lines, to tell versions of a song apart.
    preview: list[str]


def search_tracks(
    title: str, artist: str = "", duration: float | None = None
) -> list[LrclibCandidate]:
    """LRCLIB tracks with lyrics for the song `title` by `artist` (either may
    be empty, not both), `duration` seconds long, whose title is the song's,
    contains it, or is contained in it. Best match first: the right length, then synced, then the same
    title, then the closest length."""
    title, artist = title.strip(), artist.strip()
    query = urllib.parse.urlencode(_search_query(title, artist))
    results = _get_json(f"{_API_SEARCH}?{query}")
    if results is None:
        raise LrclibUnavailable("Couldn't search LRCLIB.")

    records: dict[int, dict] = {record["id"]: record for record in results}
    wanted = _title_key(title)
    candidates = [
        candidate
        for record in records.values()
        if (candidate := _candidate(record, wanted, duration)) is not None
    ]
    candidates.sort(
        key=lambda c: (
            not c.within_tolerance,
            not c.synced,
            c.title_match != "whole",
            math.inf if c.duration_delta is None else abs(c.duration_delta),
        )
    )
    return candidates


def _search_query(title: str, artist: str) -> dict[str, str]:
    # LRCLIB matches whole words only, and a Japanese title with no spaces is
    # one word, so a decorated title ("… (TV Size)") never finds the plain
    # one: the title is cleaned before it's searched.
    if not title:
        # LRCLIB's search needs a track name or a free-text query.
        return {"q": artist}
    query = {"track_name": _clean_title(title) or title}
    if artist:
        query["artist_name"] = artist
    return query


# A trailing bracketed part: "(TV Size)", "[Remix]", "（feat. …）", "【MV】".
_TRAILING_BRACKETS_RE = re.compile(
    r"\s*[(\[（［【][^()\[\]（）［］【】]*[)\]）］】]\s*$"
)
# A trailing " - …" subtitle: ' - From "THE FIRST TAKE"', " - Into The Night".
_TRAILING_SUBTITLE_RE = re.compile(r"\s+[-–—]\s+.*$")
_TRAILING_FEATURING_RE = re.compile(r"\s+(?:feat\.|ft\.|featuring)\s.*$", re.IGNORECASE)
_APOSTROPHES = "'’"


def _clean_title(title: str) -> str:
    """`title` without trailing version or credit decorations, or
    punctuation other than apostrophes."""
    previous = None
    while title != previous:
        previous = title
        for pattern in (
            _TRAILING_BRACKETS_RE,
            _TRAILING_SUBTITLE_RE,
            _TRAILING_FEATURING_RE,
        ):
            title = pattern.sub("", title)
    # Replaced by a space rather than dropped, so "Re-Start" stays two words.
    title = "".join(
        " "
        if unicodedata.category(char).startswith("P") and char not in _APOSTROPHES
        else char
        for char in title
    )
    return " ".join(title.split())


def _title_key(title: str) -> str:
    """`title` reduced to what tells titles apart: width, case, spacing,
    punctuation and brackets ignored."""
    text = unicodedata.normalize("NFKC", title).casefold()
    # Letters, numbers, combining marks and pictorial symbols like ♡ and ★
    # stay; punctuation, spaces and operators like ~ go, since titles
    # are written with 〜 and ~ interchangeably.
    key = "".join(
        char
        for char in text
        if (category := unicodedata.category(char))[0] in "LNM" or category == "So"
    )
    # An empty key would be contained in every title.
    return key or "".join(text.split())


def _candidate(
    record: dict, wanted: str, duration: float | None
) -> LrclibCandidate | None:
    found = _title_key(record.get("trackName") or "")
    if found == wanted:
        title_match = "whole"
    elif found and (found in wanted or wanted in found):
        title_match = "partial"
    else:
        return None
    if record.get("instrumental"):
        return None
    try:
        lyrics = _record_lyrics(record)
    except LrclibError:
        return None

    track_duration = record.get("duration")
    delta = (
        None
        if duration is None or track_duration is None
        else track_duration - duration
    )
    return LrclibCandidate(
        id=record["id"],
        uri=_track_uri(record["id"]),
        track_name=record.get("trackName") or "",
        artist_name=record.get("artistName") or "",
        album_name=record.get("albumName"),
        duration=track_duration,
        synced=lyrics.lines is not None,
        title_match=title_match,
        duration_delta=delta,
        within_tolerance=delta is not None
        and abs(delta) <= _DURATION_TOLERANCE_SECONDS,
        preview=[line for line in lyrics.text.splitlines() if line][:2],
    )
