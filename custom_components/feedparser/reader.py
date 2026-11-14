"""Fetch a feed and turn its entries into sensor attribute dicts.

Plain synchronous code with no Home Assistant entity state, so it can run in an
executor job from the coordinator and be unit tested directly.
"""

from __future__ import annotations

import calendar
import contextlib
import email.utils
import logging
import re
import time
import warnings
from collections.abc import Mapping
from datetime import UTC, datetime, timezone
from typing import Protocol, cast

import feedparser  # type: ignore[import]
from dateutil import parser
from homeassistant.util import dt

from .fetch import USER_AGENT, fetch_feed

_LOGGER: logging.Logger = logging.getLogger(__name__)

DEFAULT_THUMBNAIL = "https://www.home-assistant.io/images/favicon-192x192-full.png"
# Matches a whole <img> tag (so it can be stripped from summaries) and captures its
# src. Handles single or double quotes, any attribute order and tags spanning lines.
IMAGE_REGEX = r"""(?is)<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["'][^>]*>"""
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg")
DATE_KEYS = ("published", "updated", "created", "expired")


class ParsedFeed(Protocol):
    """Protocol for parsed feed object."""

    entries: list[Mapping[str, object]]


def _first_image(items: object, untyped_is_image: bool) -> str | None:
    """Return the first image URL from a list of enclosure/media dicts.

    Items with a MIME ``type`` or Media RSS ``medium`` are judged by it. Items with
    neither are accepted if ``untyped_is_image`` (``media:thumbnail`` is always an
    image) or if the URL has an image file extension.
    """
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        url = item.get("href") or item.get("url")
        if not isinstance(url, str) or not url:
            continue
        mime = item.get("type")
        medium = item.get("medium")
        if isinstance(mime, str) and mime:
            if mime.lower().startswith("image/"):
                return url
            continue
        if isinstance(medium, str) and medium:
            if medium.lower() == "image":
                return url
            continue
        if untyped_is_image or _looks_like_image(url):
            return url
    return None


def _looks_like_image(url: str) -> bool:
    """Return whether a URL path ends in a known image extension."""
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(IMAGE_EXTENSIONS)


class FeedReader:
    """Download one feed and build its entries according to the sensor options."""

    def __init__(
        self: FeedReader,
        *,
        feed: str,
        name: str,
        date_format: str,
        show_topn: int,
        remove_summary_image: bool,
        inclusions: list[str],
        exclusions: list[str],
        local_time: bool,
        user_agent: str = USER_AGENT,
    ) -> None:
        """Initialize the reader."""
        self.feed = feed
        self.name = name
        self.local_time = local_time
        self._date_format = date_format
        self._show_topn = show_topn
        self._remove_summary_image = remove_summary_image
        self._inclusions = inclusions
        self._exclusions = exclusions
        self._user_agent = user_agent

    def __repr__(self: FeedReader) -> str:
        """Return the representation."""
        return (
            f'FeedReader(name="{self.name}", feed="{self.feed}", '
            f"show_topn={self._show_topn}, "
            f"remove_summary_image={self._remove_summary_image}, "
            f"inclusions={self._inclusions}, exclusions={self._exclusions}, "
            f'local_time={self.local_time}, date_format="{self._date_format}", '
            f'user_agent="{self._user_agent}")'
        )

    def read(self: FeedReader) -> list[dict[str, object]]:
        """Fetch the feed and return a new list of at most `show_topn` entries.

        Raises ``requests.RequestException`` if the feed cannot be downloaded.
        A new list is returned on every call: Home Assistant keeps references to
        nested attribute values in previous states, so reusing (mutating) a list
        would hide `entries` changes from state triggers.
        """
        _LOGGER.debug("Feed %s: Polling feed data from %s", self.name, self.feed)
        parsed_feed = cast(
            "ParsedFeed",
            feedparser.parse(fetch_feed(self.feed, self._user_agent)),
        )
        if not parsed_feed.entries:
            _LOGGER.warning("Feed %s: No data received.", self.name)
            return []
        entries = self.build_entries(parsed_feed)
        _LOGGER.debug("Feed %s: %s entries built", self.name, len(entries))
        return entries

    def build_entries(
        self: FeedReader,
        parsed_feed: ParsedFeed,
    ) -> list[dict[str, object]]:
        """Build sensor entries from a parsed feed, skipping broken ones."""
        entries: list[dict[str, object]] = []
        for feed_entry in parsed_feed.entries[: self._show_topn]:
            try:
                entries.append(self._generate_sensor_entry(feed_entry))
            except Exception:
                # One malformed entry must not take down the whole sensor.
                _LOGGER.exception(
                    "Feed %s: Skipping entry that could not be processed: %s",
                    self.name,
                    feed_entry.get("id") or feed_entry.get("link"),
                )
        return entries

    def _generate_sensor_entry(
        self: FeedReader,
        feed_entry: Mapping[str, object],
    ) -> dict[str, object]:
        _LOGGER.debug("Feed %s: Generating sensor entry for %s", self.name, feed_entry)
        sensor_entry: dict[str, object] = {}
        for key, value in feed_entry.items():
            if not isinstance(key, str) or self._should_skip_key(key):
                continue
            self._store_sensor_entry_value(sensor_entry, key, value, feed_entry)

        self._add_derived_values(sensor_entry, feed_entry)
        _LOGGER.debug("Feed %s: Generated sensor entry: %s", self.name, sensor_entry)
        return sensor_entry

    def _should_skip_key(self: FeedReader, key: str) -> bool:
        """Return whether a feed key should be skipped."""
        return bool(
            (self._inclusions and key not in self._inclusions)
            or ("parsed" in key)
            or (key in self._exclusions),
        )

    def _store_sensor_entry_value(
        self: FeedReader,
        sensor_entry: dict[str, object],
        key: str,
        value: object,
        feed_entry: Mapping[str, object],
    ) -> None:
        """Store a normalized entry value."""
        if key in DATE_KEYS:
            if isinstance(value, str):
                parsed_date = self._parse_date(value, feed_entry.get(f"{key}_parsed"))
                # keep the raw value if the date could not be understood at all
                sensor_entry[key] = (
                    parsed_date.strftime(self._date_format) if parsed_date else value
                )
            return

        if key == "image":
            if isinstance(value, Mapping):
                href = value.get("href")
                if isinstance(href, str):
                    sensor_entry["image"] = href
            return

        sensor_entry[key] = value

    def _add_derived_values(
        self: FeedReader,
        sensor_entry: dict[str, object],
        feed_entry: Mapping[str, object],
    ) -> None:
        """Add values derived from feed content and options."""
        if "image" in self._inclusions and "image" not in sensor_entry:
            sensor_entry["image"] = self._process_image(feed_entry)
        if (
            "link" in self._inclusions
            and "link" not in sensor_entry
            and (processed_link := self._process_link(feed_entry))
        ):
            sensor_entry["link"] = processed_link
        if self._remove_summary_image and "summary" in sensor_entry:
            summary = sensor_entry.get("summary")
            if isinstance(summary, str):
                sensor_entry["summary"] = re.sub(
                    IMAGE_REGEX,
                    "",
                    summary,
                )

    def _parse_date(
        self: FeedReader,
        date: str,
        parsed: object = None,
    ) -> datetime | None:
        """Parse a feed date into an aware datetime, or None if impossible.

        Tried in order, keeping the feed's own UTC offset where possible:
        RFC 822 (RSS), ISO 8601 / W3CDTF (Atom), feedparser's own normalized UTC
        ``*_parsed`` value, and finally dateutil as a best effort.
        """
        parsed_time = self._parse_date_string(date)
        if parsed_time is None and isinstance(parsed, time.struct_time):
            parsed_time = datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)

        if parsed_time is None:
            _LOGGER.debug(
                "Feed %s: Unable to parse date %s, keeping the raw value",
                self.name,
                date,
            )
            return None

        if not parsed_time.tzname():
            # replace tzinfo with UTC offset if tzinfo does not contain a TZ name
            parsed_time = parsed_time.replace(
                tzinfo=timezone(parsed_time.utcoffset()),  # type: ignore[arg-type]
            )

        if self.local_time:
            parsed_time = dt.as_local(parsed_time)
        _LOGGER.debug("Feed %s: Parsed date: %s", self.name, parsed_time)
        return parsed_time

    @staticmethod
    def _parse_date_string(date: str) -> datetime | None:
        """Parse a date string with the stdlib, then dateutil. Return aware or None."""
        candidates = []
        with contextlib.suppress(TypeError, ValueError, IndexError):
            candidates.append(email.utils.parsedate_to_datetime(date))
        with contextlib.suppress(ValueError):
            candidates.append(datetime.fromisoformat(date.strip()))
        for candidate in candidates:
            if candidate.tzinfo is not None:
                return candidate

        # dateutil warns (UnknownTimezoneWarning) on abbreviations such as EDT and
        # returns a naive datetime; a naive result is treated as unparseable.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                fallback = parser.parse(date)
            except (ValueError, OverflowError):
                return None
        return fallback if fallback.tzinfo is not None else None

    def _process_image(self: FeedReader, feed_entry: Mapping[str, object]) -> str:
        """Return the best image URL for an entry, or the default thumbnail.

        Sources, in order: image enclosures, Media RSS ``media:content`` and
        ``media:thumbnail`` (BBC, Mastodon, many news sites), the first ``<img>``
        in the summary, then the first ``<img>`` in the full content
        (``content:encoded``, used by WordPress feeds).
        """
        for source, untyped_is_image in (
            ("enclosures", False),
            ("media_content", False),
            ("media_thumbnail", True),
        ):
            if url := _first_image(feed_entry.get(source), untyped_is_image):
                return url

        summary = feed_entry.get("summary")
        if isinstance(summary, str) and (match := re.search(IMAGE_REGEX, summary)):
            return match.group(1)

        content = feed_entry.get("content")
        if isinstance(content, list):
            for part in content:
                value = part.get("value") if isinstance(part, Mapping) else None
                if isinstance(value, str) and (match := re.search(IMAGE_REGEX, value)):
                    return match.group(1)

        _LOGGER.debug(
            "Feed %s: Image is in inclusions, but no image was found for %s",
            self.name,
            feed_entry,
        )
        return DEFAULT_THUMBNAIL  # use default image if no image found

    def _process_link(self: FeedReader, feed_entry: Mapping[str, object]) -> str:
        """Return link from feed entry."""
        links = feed_entry.get("links")
        if isinstance(links, list) and links:
            if len(links) > 1:
                _LOGGER.debug(
                    "Feed %s: More than one link found for %s. Using the first link.",
                    self.name,
                    feed_entry,
                )
            first_link = links[0]
            if isinstance(first_link, dict):
                href = first_link.get("href")
                if isinstance(href, str):
                    return href
        return ""
