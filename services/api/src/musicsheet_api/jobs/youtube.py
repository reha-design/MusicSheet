"""Offline validation and canonicalization for supported YouTube URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit


_ALLOWED_HOSTS = frozenset(
    {
        "youtu.be",
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    }
)
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def normalize_youtube_url(source_url: str) -> str:
    """Return the canonical watch URL for a supported HTTPS YouTube URL.

    This function deliberately performs no network requests. It validates only
    the URL shape and video ID; availability is checked by a future worker.
    """
    if (
        not isinstance(source_url, str)
        or not source_url
        or len(source_url) > 2048
        or source_url != source_url.strip()
        or any(
            character == "\\" or ord(character) <= 0x20 or ord(character) == 0x7F
            for character in source_url
        )
        or _INVALID_PERCENT_ESCAPE.search(source_url)
    ):
        raise ValueError("invalid YouTube URL")

    try:
        parsed = urlsplit(source_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("invalid YouTube URL") from error

    if (
        parsed.scheme.lower() != "https"
        or hostname not in _ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or port not in (None, 443)
    ):
        raise ValueError("invalid YouTube URL")

    if hostname == "youtu.be":
        path_segments = parsed.path.split("/")
        if len(path_segments) != 2 or path_segments[0] != "":
            raise ValueError("invalid YouTube URL")
        video_id = path_segments[1]
    else:
        if parsed.path != "/watch":
            raise ValueError("invalid YouTube URL")
        try:
            query_items = parse_qsl(
                parsed.query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=100,
            )
        except ValueError as error:
            raise ValueError("invalid YouTube URL") from error
        video_ids = [value for key, value in query_items if key == "v"]
        if len(video_ids) != 1:
            raise ValueError("invalid YouTube URL")
        video_id = video_ids[0]

    if _VIDEO_ID.fullmatch(video_id) is None:
        raise ValueError("invalid YouTube URL")

    return f"https://www.youtube.com/watch?v={video_id}"
