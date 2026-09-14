"""Lyrics and line timings from LRCLIB (https://lrclib.net/docs).

A record's `syncedLyrics` is LRC: one `[mm:ss.xx] text` line per sung line,
timed per line only. LRCLIB doesn't serve word-level timing in practice (its
newer `lyricsfile` field has a per-line `words` list, empty on every record
checked), so lyrics are timed, and highlighted, by line.

A track id's lyrics can change — publishing to LRCLIB adds a new version to
the same track — so a linked document is re-fetched on each load and
compared against what was stored (see app/main.py).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from app.sanitize import sanitize_text

# LRCLIB asks every client to identify itself this way.
USER_AGENT = "song-study (https://github.com/DT-1236/song-study)"

_API_GET = "https://lrclib.net/api/get"
_TIMEOUT_SECONDS = 5


class LrclibError(Exception):
    """A failure to get lyrics from LRCLIB — a bad address, no such track,
    or no lyrics — whose message is shown to the user."""


class LrclibUnavailable(LrclibError):
    """LRCLIB couldn't be reached or failed, rather than refusing the
    request."""


_TRACK_ID_RE = re.compile(r"\d+")
_GET_BY_ID_PATH_RE = re.compile(r"/api/get/(\d+)/?")


def normalize_lrclib_uri(value: str) -> str:
    """The canonical LRCLIB API address for `value`, a track id or an
    lrclib.net/api/get/{id} URL. Nothing else is accepted, since the server
    fetches whatever this returns."""
    value = value.strip()
    if _TRACK_ID_RE.fullmatch(value):
        return f"{_API_GET}/{value}"
    parsed = urllib.parse.urlsplit(value if "://" in value else f"https://{value}")
    if parsed.scheme in ("http", "https") and parsed.hostname in ("lrclib.net", "www.lrclib.net"):
        if match := _GET_BY_ID_PATH_RE.fullmatch(parsed.path):
            return f"{_API_GET}/{match.group(1)}"
    raise LrclibError("Enter an LRCLIB track ID, or its https://lrclib.net/api/get/… address.")


@dataclass(frozen=True)
class LrclibLyrics:
    text: str
    # One {"start", "end"} per line of `text`, in seconds, or None when the
    # record only has unsynced lyrics.
    lines: Optional[list[dict]]


# [mm:ss], [mm:ss.x…], or the [mm:ss:xx] some LRC writers use.
_LINE_TIMESTAMP_RE = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d+)?)\]")
# Enhanced LRC's per-word timestamps.
_WORD_TIMESTAMP_RE = re.compile(r"<\d+:\d{1,2}(?:[.:]\d+)?>")
# How long the last line lasts when the track's duration doesn't say.
_LAST_LINE_FALLBACK_SECONDS = 5.0


def parse_synced_lyrics(lrc: str, duration: Optional[float]) -> LrclibLyrics:
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
    return LrclibLyrics("\n".join(text for text, _ in lines), [timing for _, timing in lines])


def _get_json(uri: str) -> dict:
    request = urllib.request.Request(uri, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return json.load(response)
    # HTTPError is a URLError, so it has to be caught first.
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LrclibError("LRCLIB has no track at that address.") from exc
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After")
            wait = f" in {retry_after} seconds" if retry_after else " later"
            raise LrclibUnavailable(f"LRCLIB is rate-limiting requests — try again{wait}.") from exc
        raise LrclibUnavailable(f"LRCLIB responded with an error ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise LrclibUnavailable("Couldn't reach LRCLIB.") from exc


def fetch_lyrics(uri: str) -> LrclibLyrics:
    """The lyrics the LRCLIB record at `uri` (as normalize_lrclib_uri
    returns it) currently has: its synced lyrics if any, else its plain
    ones."""
    record = _get_json(uri)
    if record.get("syncedLyrics"):
        lyrics = parse_synced_lyrics(record["syncedLyrics"], record.get("duration"))
        if lyrics.text:
            return lyrics
    plain = sanitize_text(record.get("plainLyrics") or "").strip("\n")
    if plain:
        return LrclibLyrics(plain, None)
    if record.get("instrumental"):
        raise LrclibError("That LRCLIB track is marked instrumental, so it has no lyrics.")
    raise LrclibError("That LRCLIB track has no lyrics.")
