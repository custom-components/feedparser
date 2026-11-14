"""Feedparser sensor."""

from __future__ import annotations

import calendar
import contextlib
import email.utils
import logging
import re
import time
import warnings
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Protocol, cast

import feedparser  # type: ignore[import]
import homeassistant.helpers.config_validation as cv
import requests
from dateutil import parser
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity_platform import async_get_current_platform
from homeassistant.util import dt

from .compat import vol
from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_REMOVE_SUMMARY_IMAGE,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_TOPN,
    CONF_USER_AGENT,
    DEFAULT_DATE_FORMAT,
    DEFAULT_LOCAL_TIME,
    DEFAULT_REMOVE_SUMMARY_IMAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOPN,
)
from .fetch import USER_AGENT, fetch_feed
from .yaml_import import async_import_yaml_sensor

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import (
        AddConfigEntryEntitiesCallback,
        AddEntitiesCallback,
    )
    from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType


COMPONENT_REPO = "https://github.com/custom-components/feedparser/"

DEFAULT_THUMBNAIL = "https://www.home-assistant.io/images/favicon-192x192-full.png"
# Matches a whole <img> tag (so it can be stripped from summaries) and captures its
# src. Handles single or double quotes, any attribute order and tags spanning lines.
IMAGE_REGEX = r"""(?is)<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["'][^>]*>"""
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg")
DATE_KEYS = ("published", "updated", "created", "expired")

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_FEED_URL): cv.string,
        vol.Required(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): cv.string,
        vol.Optional(CONF_LOCAL_TIME, default=DEFAULT_LOCAL_TIME): cv.boolean,
        vol.Optional(CONF_SHOW_TOPN, default=DEFAULT_TOPN): cv.positive_int,
        vol.Optional(
            CONF_REMOVE_SUMMARY_IMAGE,
            default=DEFAULT_REMOVE_SUMMARY_IMAGE,
        ): cv.boolean,
        vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
        vol.Optional(CONF_USER_AGENT, default=USER_AGENT): cv.string,
    },
)

_LOGGER: logging.Logger = logging.getLogger(__name__)


class ParsedFeed(Protocol):
    """Protocol for parsed feed object."""

    entries: list[Mapping[str, object]]


class FeedparserEntityPlatform(Protocol):
    """Protocol for entity platform poll interval fields used by this integration."""

    scan_interval: timedelta
    scan_interval_seconds: float


def _scan_interval_to_timedelta(value: object) -> timedelta:
    """Convert stored scan interval values to timedelta."""
    if isinstance(value, timedelta):
        return value

    if isinstance(value, Mapping):
        raw_hours = value.get("hours")
        raw_minutes = value.get("minutes")
        hours = raw_hours if isinstance(raw_hours, int) else 0
        minutes = raw_minutes if isinstance(raw_minutes, int) else 0
        total_minutes = max(1, (hours * 60) + minutes)
        return timedelta(minutes=total_minutes)

    return DEFAULT_SCAN_INTERVAL


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,  # noqa: ARG001
    discovery_info: DiscoveryInfoType | None = None,  # noqa: ARG001
) -> None:
    """Import a legacy YAML sensor into a config entry.

    YAML configuration is deprecated: the sensor is created by the imported config
    entry (keeping the same entity ID), not by this platform.
    """
    await async_import_yaml_sensor(hass, config)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Feedparser sensor from a config entry."""
    data = {**entry.data, **entry.options}
    scan_interval = _scan_interval_to_timedelta(
        data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    current_platform = cast("FeedparserEntityPlatform", async_get_current_platform())
    current_platform.scan_interval = scan_interval
    current_platform.scan_interval_seconds = scan_interval.total_seconds()

    async_add_entities(
        [
            FeedParserSensor(
                feed=data[CONF_FEED_URL],
                name=data[CONF_NAME],
                date_format=data.get(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT),
                show_topn=data.get(CONF_SHOW_TOPN, DEFAULT_TOPN),
                remove_summary_image=data.get(
                    CONF_REMOVE_SUMMARY_IMAGE,
                    DEFAULT_REMOVE_SUMMARY_IMAGE,
                ),
                inclusions=data.get(CONF_INCLUSIONS, []),
                exclusions=data.get(CONF_EXCLUSIONS, []),
                scan_interval=scan_interval,
                local_time=data.get(CONF_LOCAL_TIME, DEFAULT_LOCAL_TIME),
                unique_id=entry.entry_id,
                # an empty value means "use the integration default"
                user_agent=data.get(CONF_USER_AGENT) or USER_AGENT,
            ),
        ],
        update_before_add=True,
    )


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


class FeedParserSensor(SensorEntity):
    """Representation of a Feedparser sensor."""

    # force update the entity since the number of feed entries does not necessarily
    # change, but we still want to update the extra_state_attributes
    _attr_force_update = True
    # The entries attribute regularly exceeds the recorder's 16 KiB attribute limit
    # and changes on every poll; keep it out of the database.
    _unrecorded_attributes = frozenset({"entries"})

    def __init__(
        self: FeedParserSensor,
        feed: str,
        name: str,
        date_format: str,
        show_topn: int,
        remove_summary_image: bool,
        exclusions: list[str | None],
        inclusions: list[str | None],
        scan_interval: timedelta,
        local_time: bool,
        unique_id: str | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        """Initialize the Feedparser sensor."""
        self._feed = feed
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:rss"
        self._date_format = date_format
        self._show_topn: int = show_topn
        self._remove_summary_image = remove_summary_image
        self._inclusions = inclusions
        self._exclusions = exclusions
        self._scan_interval = scan_interval
        self._local_time = local_time
        self._user_agent = user_agent
        self._entries: list[dict[str, object]] = []
        self._attr_attribution = "Data retrieved using RSS feedparser"
        _LOGGER.debug("Feed %s: FeedParserSensor initialized - %s", self.name, self)

    @property
    def scan_interval(self: FeedParserSensor) -> timedelta:
        """Return polling interval."""
        return self._scan_interval

    def __repr__(self: FeedParserSensor) -> str:
        """Return the representation."""
        return (
            f'FeedParserSensor(name="{self.name}", feed="{self._feed}", '
            f"show_topn={self._show_topn}, "
            f"remove_summary_image={self._remove_summary_image}, "
            f"inclusions={self._inclusions}, "
            f"exclusions={self._exclusions}, scan_interval={self._scan_interval}, "
            f'local_time={self._local_time}, date_format="{self._date_format}", '
            f'user_agent="{self._user_agent}")'
        )

    def update(self: FeedParserSensor) -> None:
        """Parse the feed and update the state of the sensor."""
        _LOGGER.debug("Feed %s: Polling feed data from %s", self.name, self._feed)
        try:
            content = fetch_feed(self._feed, self._user_agent)
        except requests.RequestException as err:
            if self._attr_available:
                _LOGGER.warning(
                    "Feed %s: Unable to fetch %s: %s",
                    self.name,
                    self._feed,
                    err,
                )
            self._attr_available = False
            return

        if not self._attr_available:
            _LOGGER.info("Feed %s: Feed is reachable again", self.name)
        self._attr_available = True
        parsed_feed = cast("ParsedFeed", feedparser.parse(content))

        if not parsed_feed.entries:
            self._attr_native_value = None
            _LOGGER.warning("Feed %s: No data received.", self.name)
            return

        _LOGGER.debug("Feed %s: Feed data fetched successfully", self.name)
        # set the sensor value to the amount of entries
        self._attr_native_value = (
            self._show_topn
            if len(parsed_feed.entries) > self._show_topn
            else len(parsed_feed.entries)
        )
        _LOGGER.debug(
            "Feed %s: %s entries is going to be added to the sensor",
            self.name,
            self.native_value,
        )
        # Replace the list instead of mutating it in place. Home Assistant
        # keeps references to nested attribute values in previous State objects, so
        # in-place mutation would also change the previous state snapshot and hide
        # genuine `entries` attribute changes from state triggers.
        self._entries = self._generate_entries(parsed_feed)
        _LOGGER.debug(
            "Feed %s: Sensor state updated - %s entries",
            self.name,
            len(self.feed_entries),
        )

    def _generate_entries(
        self: FeedParserSensor,
        parsed_feed: ParsedFeed,
    ) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for feed_entry in parsed_feed.entries[: self.native_value]:  # type: ignore[misc]
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
        self: FeedParserSensor,
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

    def _should_skip_key(self: FeedParserSensor, key: str) -> bool:
        """Return whether a feed key should be skipped."""
        return bool(
            (self._inclusions and key not in self._inclusions)
            or ("parsed" in key)
            or (key in self._exclusions),
        )

    def _store_sensor_entry_value(
        self: FeedParserSensor,
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
        self: FeedParserSensor,
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
        self: FeedParserSensor,
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

        if self._local_time:
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

    def _process_image(self: FeedParserSensor, feed_entry: Mapping[str, object]) -> str:
        """Return the best image URL for an entry, or the default thumbnail.

        Sources, in order: image enclosures, Media RSS ``media:content`` and
        ``media:thumbnail`` (BBC, Mastodon, many news sites), then the first
        ``<img>`` in the summary.
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

        _LOGGER.debug(
            "Feed %s: Image is in inclusions, but no image was found for %s",
            self.name,
            feed_entry,
        )
        return DEFAULT_THUMBNAIL  # use default image if no image found

    def _process_link(self: FeedParserSensor, feed_entry: Mapping[str, object]) -> str:
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

    @property
    def feed_entries(self: FeedParserSensor) -> list[dict[str, object]]:
        """Return feed entries."""
        if hasattr(self, "_entries"):
            return self._entries
        return []

    @property
    def local_time(self: FeedParserSensor) -> bool:
        """Return local_time."""
        return self._local_time

    @local_time.setter
    def local_time(self: FeedParserSensor, value: bool) -> None:
        """Set local_time."""
        self._local_time = value

    @property
    def extra_state_attributes(
        self: FeedParserSensor,
    ) -> dict[str, list[dict[str, object]]]:
        """Return entity specific state attributes."""
        return {"entries": self.feed_entries}
