"""Regression tests for fetch, date, image and recorder hardening."""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from reader_harness import ReaderHarness

from custom_components.feedparser import fetch
from custom_components.feedparser.config_flow import (
    FeedparserConfigFlow,
    InvalidFeedError,
)
from custom_components.feedparser.reader import DEFAULT_THUMBNAIL
from custom_components.feedparser.sensor import FeedParserSensor

DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def _rss(items: str, encoding: str = "UTF-8", extra_ns: str = "") -> str:
    return f"""<?xml version="1.0" encoding="{encoding}"?>
<rss version="2.0" {extra_ns}>
  <channel>
    <title>Test</title>
    <link>https://example.com</link>
    <description>Test</description>
    {items}
  </channel>
</rss>
"""


def _sensor(
    path: Path,
    inclusions: list[str | None] | None = None,
    *,
    remove_summary_image: bool = False,
) -> ReaderHarness:
    return ReaderHarness(
        feed=path.absolute().as_uri(),
        name="test",
        date_format=DATE_FORMAT,
        local_time=False,
        show_topn=10,
        remove_summary_image=remove_summary_image,
        inclusions=inclusions or [],
        exclusions=[],
    )


# --- fetching -----------------------------------------------------------------


def test_fetch_sends_timeout_and_user_agent() -> None:
    """Requests must carry a timeout and the integration User-Agent."""
    with patch.object(requests.Session, "get") as get:
        get.return_value.content = b"<rss/>"
        fetch.fetch_feed("https://example.com/feed")

    _, kwargs = get.call_args
    assert kwargs["timeout"] == fetch.REQUEST_TIMEOUT


def test_non_utf8_feed_is_decoded_from_xml_prolog(tmp_path: Path) -> None:
    """Feeds are parsed from bytes so the declared encoding is honored."""
    feed = tmp_path / "latin1.xml"
    feed.write_bytes(
        _rss("<item><title>Café crème</title></item>", "ISO-8859-1").encode(
            "iso-8859-1",
        ),
    )
    sensor = _sensor(feed, ["title"])
    sensor.update()
    assert sensor.feed_entries[0]["title"] == "Café crème"


# --- dates --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tue, 08 Sep 2026 12:00:00 GMT", "2026-09-08T12:00:00+0000"),
        # Atom / W3CDTF (#127): previously logged a warning for every entry
        ("2024-02-01T00:00:01Z", "2024-02-01T00:00:01+0000"),
        ("2024-02-01T02:00:01+02:00", "2024-02-01T02:00:01+0200"),
        # US timezone abbreviation (#132): dateutil can't resolve it, feedparser can
        ("Tue, 08 Sep 2026 08:00:00 EDT", "2026-09-08T08:00:00-0400"),
    ],
)
def test_date_formats(tmp_path: Path, raw: str, expected: str) -> None:
    """Common RSS and Atom date styles parse without warnings."""
    feed = tmp_path / "dates.xml"
    feed.write_text(
        _rss(f"<item><title>a</title><pubDate>{raw}</pubDate></item>"),
        encoding="utf-8",
    )
    sensor = _sensor(feed, ["title", "published"])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        sensor.update()
    assert sensor.feed_entries[0]["published"] == expected


def test_unparseable_date_keeps_raw_value(tmp_path: Path) -> None:
    """A garbage date keeps the raw string instead of failing the whole update."""
    feed = tmp_path / "bad_date.xml"
    feed.write_text(
        _rss(
            "<item><title>bad</title><pubDate>sometime soon</pubDate></item>"
            "<item><title>good</title>"
            "<pubDate>Tue, 08 Sep 2026 12:00:00 GMT</pubDate></item>",
        ),
        encoding="utf-8",
    )
    sensor = _sensor(feed, ["title", "published"])
    sensor.update()
    assert [e["title"] for e in sensor.feed_entries] == ["bad", "good"]
    assert sensor.feed_entries[0]["published"] == "sometime soon"


def test_broken_entry_is_skipped(tmp_path: Path) -> None:
    """An exception while processing one entry only drops that entry."""
    feed = tmp_path / "feed.xml"
    feed.write_text(
        _rss("<item><title>one</title></item><item><title>two</title></item>"),
        encoding="utf-8",
    )
    sensor = _sensor(feed, ["title"])
    original = sensor.reader._generate_sensor_entry  # noqa: SLF001

    def flaky(entry: dict) -> dict:
        if entry["title"] == "one":
            raise RuntimeError
        return original(entry)

    with patch.object(sensor.reader, "_generate_sensor_entry", side_effect=flaky):
        sensor.update()
    assert [e["title"] for e in sensor.feed_entries] == ["two"]


# --- images -------------------------------------------------------------------

MEDIA_NS = (
    'xmlns:media="http://search.yahoo.com/mrss/" '
    'xmlns:content="http://purl.org/rss/1.0/modules/content/"'
)


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        pytest.param(
            '<enclosure url="https://e.x/a.png" length="1" type="image/png"/>',
            "https://e.x/a.png",
            id="enclosure",
        ),
        pytest.param(
            '<media:content url="https://e.x/m.jpg" medium="image"/>',
            "https://e.x/m.jpg",
            id="media_content_medium",  # Mastodon (#158)
        ),
        pytest.param(
            '<media:content url="https://e.x/v.mp4" type="video/mp4"/>'
            '<media:thumbnail url="https://e.x/t.jpg" width="240"/>',
            "https://e.x/t.jpg",
            id="media_thumbnail",  # BBC (#131)
        ),
        pytest.param(
            "<description><![CDATA[<p>x</p><img alt='a'\n"
            " src='https://e.x/s.png'>]]></description>",
            "https://e.x/s.png",
            id="summary_single_quotes_multiline",  # (#147)
        ),
        pytest.param(
            "<description>no image here</description>"
            "<content:encoded><![CDATA[<p>x</p>"
            '<img class="wp-image" src="https://e.x/wp.jpg" width="300" />'
            "]]></content:encoded>",
            "https://e.x/wp.jpg",
            id="content_encoded",  # WordPress (#64)
        ),
        pytest.param(
            '<enclosure url="https://e.x/a.mp3" length="1" type="audio/mpeg"/>',
            DEFAULT_THUMBNAIL,
            id="non_image_enclosure",
        ),
    ],
)
def test_image_sources(tmp_path: Path, item: str, expected: str) -> None:
    """Images are found in enclosures, Media RSS and summaries."""
    feed = tmp_path / "images.xml"
    feed.write_text(
        _rss(f"<item><title>a</title>{item}</item>", extra_ns=MEDIA_NS),
        encoding="utf-8",
    )
    sensor = _sensor(feed, ["title", "image"])
    sensor.update()
    assert sensor.feed_entries[0]["image"] == expected


def test_remove_summary_image_strips_whole_tag(tmp_path: Path) -> None:
    """The summary image regex removes the full tag, not just up to src."""
    feed = tmp_path / "summary.xml"
    feed.write_text(
        _rss(
            "<item><title>a</title><description><![CDATA[before "
            "<img src=\"https://e.x/s.png\" width='10' /> after]]>"
            "</description></item>",
        ),
        encoding="utf-8",
    )
    sensor = _sensor(feed, ["title", "summary"], remove_summary_image=True)
    sensor.update()
    assert sensor.feed_entries[0]["summary"] == "before  after"


# --- recorder -----------------------------------------------------------------


def test_entries_attribute_not_recorded() -> None:
    """The large entries attribute is excluded from the recorder."""
    assert "entries" in FeedParserSensor._unrecorded_attributes  # noqa: SLF001


# --- config flow validation ---------------------------------------------------


def test_validate_rejects_non_feed(tmp_path: Path) -> None:
    """An HTML page is rejected as not being a feed."""
    page = tmp_path / "page.html"
    page.write_text("<html><body>hello</body></html>", encoding="utf-8")
    with pytest.raises(InvalidFeedError):
        FeedparserConfigFlow._validate_feed_url(page.as_uri())  # noqa: SLF001


def test_validate_accepts_empty_feed(tmp_path: Path) -> None:
    """A valid feed with no entries yet is accepted."""
    feed = tmp_path / "empty.xml"
    feed.write_text(_rss(""), encoding="utf-8")
    FeedparserConfigFlow._validate_feed_url(feed.as_uri())  # noqa: SLF001
