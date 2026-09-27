"""Offline validation for accepted YouTube URL forms."""

import socket
import urllib.request

import pytest

from musicsheet_api.jobs.youtube import normalize_youtube_url


def test_normalizes_supplied_short_url() -> None:
    assert normalize_youtube_url("https://youtu.be/A9x7du4921A") == (
        "https://www.youtube.com/watch?v=A9x7du4921A"
    )


def test_normalizes_watch_url_and_drops_tracking_parameters() -> None:
    assert normalize_youtube_url(
        "https://m.youtube.com/watch?list=PL123&v=A9x7du4921A&t=30s"
    ) == "https://www.youtube.com/watch?v=A9x7du4921A"


@pytest.mark.parametrize(
    "source_url",
    [
        "http://youtu.be/A9x7du4921A",
        "https://youtube.com.evil.example/watch?v=A9x7du4921A",
        "https://evil.example/watch?v=A9x7du4921A",
        "https://youtu.be.evil.example/A9x7du4921A",
    ],
)
def test_rejects_unapproved_hosts_and_http(source_url: str) -> None:
    with pytest.raises(ValueError):
        normalize_youtube_url(source_url)


@pytest.mark.parametrize(
    "source_url",
    [
        "https://youtube.com/watch",
        "https://youtube.com/watch?v=",
        "https://youtube.com/watch?v=short",
        "https://youtu.be/short",
        "https://youtu.be/A9x7du4921A/extra",
        "https://youtube.com/shorts/A9x7du4921A",
        "https://youtube.com/watch?v=A9x7du4921A&v=B9x7du4921A",
        "https://youtu.be/A9x7du\n4921A",
        "https://youtu.be/A9x7du\t4921A",
        "https://youtu.be\\A9x7du4921A",
    ],
)
def test_rejects_malformed_or_missing_video_ids(source_url: str) -> None:
    with pytest.raises(ValueError):
        normalize_youtube_url(source_url)


@pytest.mark.parametrize(
    "source_url",
    [
        "https://user@youtu.be/A9x7du4921A",
        "https://youtu.be:444/A9x7du4921A",
        "https://youtu.be:/A9x7du4921A",
        "https://youtu.be:invalid/A9x7du4921A",
    ],
)
def test_rejects_userinfo_duplicate_v_and_nondefault_port(source_url: str) -> None:
    with pytest.raises(ValueError):
        normalize_youtube_url(source_url)


def test_parser_never_performs_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("URL registration must not perform network I/O")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)

    assert normalize_youtube_url("https://youtu.be/A9x7du4921A") == (
        "https://www.youtube.com/watch?v=A9x7du4921A"
    )
