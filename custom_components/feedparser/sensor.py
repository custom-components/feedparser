"""Feedparser sensor."""

from __future__ import annotations

import email.utils
import logging
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Protocol, cast

import feedparser  # type: ignore[import]
import homeassistant.helpers.config_validation as cv
import requests
import voluptuous as vol
from dateutil import parser
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.helpers.entity_platform import async_get_current_platform
from homeassistant.util import dt
from requests_file import FileAdapter

from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_REMOVE_SUMMARY_IMAGE,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_TOPN,
    DEFAULT_DATE_FORMAT,
    DEFAULT_LOCAL_TIME,
    DEFAULT_REMOVE_SUMMARY_IMAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOPN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

__version__ = "1.0.0"

COMPONENT_REPO = "https://github.com/custom-components/feedparser/"

REQUIREMENTS = ["feedparser"]

DEFAULT_THUMBNAIL = "https://www.home-assistant.io/images/favicon-192x192-full.png"
USER_AGENT = f"Home Assistant Feed-parser Integration {__version__}"
IMAGE_REGEX = r"<img.+?src=\"(.+?)\".+?>"

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
    hass: HomeAssistant,  # noqa: ARG001
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,  # noqa: ARG001
) -> None:
    """Set up the Feedparser sensor."""
    async_add_devices(
        [
            FeedParserSensor(
                feed=config[CONF_FEED_URL],
                name=config[CONF_NAME],
                date_format=config[CONF_DATE_FORMAT],
                show_topn=config[CONF_SHOW_TOPN],
                remove_summary_image=config[CONF_REMOVE_SUMMARY_IMAGE],
                inclusions=config[CONF_INCLUSIONS],
                exclusions=config[CONF_EXCLUSIONS],
                scan_interval=config[CONF_SCAN_INTERVAL],
                local_time=config[CONF_LOCAL_TIME],
            ),
        ],
        update_before_add=True,
    )


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
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
            ),
        ],
        update_before_add=True,
    )


class FeedParserSensor(SensorEntity):
    """Representation of a Feedparser sensor."""

    # force update the entity since the number of feed entries does not necessarily
    # change, but we still want to update the extra_state_attributes
    _attr_force_update = True

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
        self._entries: list[dict[str, object]] = []
        self._attr_extra_state_attributes = {"entries": self._entries}
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
            f'local_time={self._local_time}, date_format="{self._date_format}")'
        )

    def update(self: FeedParserSensor) -> None:
        """Parse the feed and update the state of the sensor."""
        _LOGGER.debug("Feed %s: Polling feed data from %s", self.name, self._feed)
        s: requests.Session = requests.Session()
        s.mount("file://", FileAdapter())
        s.headers.update({"User-Agent": USER_AGENT})
        res: requests.Response = s.get(self._feed)
        res.raise_for_status()
        parsed_feed = cast("ParsedFeed", feedparser.parse(res.text))

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
        self._entries.clear()  # clear the entries to avoid duplicates
        self._entries.extend(self._generate_entries(parsed_feed))
        _LOGGER.debug(
            "Feed %s: Sensor state updated - %s entries",
            self.name,
            len(self.feed_entries),
        )

    def _generate_entries(
        self: FeedParserSensor,
        parsed_feed: ParsedFeed,
    ) -> list[dict[str, object]]:
        return [
            self._generate_sensor_entry(feed_entry)
            for feed_entry in parsed_feed.entries[
                : self.native_value  # type: ignore[misc]
            ]
        ]

    def _generate_sensor_entry(
        self: FeedParserSensor,
        feed_entry: Mapping[str, object],
    ) -> dict[str, object]:
        _LOGGER.debug("Feed %s: Generating sensor entry for %s", self.name, feed_entry)
        sensor_entry: dict[str, object] = {}
        for key, value in feed_entry.items():
            if not isinstance(key, str) or self._should_skip_key(key):
                continue
            self._store_sensor_entry_value(sensor_entry, key, value)

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
    ) -> None:
        """Store a normalized entry value."""
        if key in ["published", "updated", "created", "expired"]:
            if isinstance(value, str):
                parsed_date: datetime = self._parse_date(value)
                sensor_entry[key] = parsed_date.strftime(self._date_format)
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

    def _parse_date(self: FeedParserSensor, date: str) -> datetime:
        try:
            parsed_time: datetime = email.utils.parsedate_to_datetime(date)
        except ValueError:
            _LOGGER.warning(
                (
                    "Feed %s: Unable to parse RFC-822 date from %s. "
                    "This could be caused by incorrect pubDate format "
                    "in the RSS feed or due to a leapp second"
                ),
                self.name,
                date,
            )
            # best effort to parse the date using dateutil
            parsed_time = parser.parse(date)

        if not parsed_time.tzinfo:
            # best effort to parse the date using dateutil
            parsed_time = parser.parse(date)
            if not parsed_time.tzinfo:
                msg = (
                    f"Feed {self.name}: Unable to parse date {date}, "
                    "caused by an incorrect date format"
                )
                raise ValueError(msg)
        if not parsed_time.tzname():
            # replace tzinfo with UTC offset if tzinfo does not contain a TZ name
            parsed_time = parsed_time.replace(
                tzinfo=timezone(parsed_time.utcoffset()),  # type: ignore[arg-type]
            )

        if self._local_time:
            parsed_time = dt.as_local(parsed_time)
        _LOGGER.debug("Feed %s: Parsed date: %s", self.name, parsed_time)
        return parsed_time

    def _process_image(self: FeedParserSensor, feed_entry: Mapping[str, object]) -> str:
        enclosures = feed_entry.get("enclosures")
        if isinstance(enclosures, list):
            for enclosure in enclosures:
                if not isinstance(enclosure, dict):
                    continue
                enclosure_type = enclosure.get("type")
                href = enclosure.get("href")
                if (
                    isinstance(enclosure_type, str)
                    and enclosure_type.startswith("image/")
                    and isinstance(href, str)
                ):
                    return href

        summary = feed_entry.get("summary")
        if isinstance(summary, str):
            images = re.findall(
                IMAGE_REGEX,
                summary,
            )
            if images:
                # pick the first image found
                return images[0]
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
    def extra_state_attributes(self: FeedParserSensor) -> dict[str, list]:
        """Return entity specific state attributes."""
        return {"entries": self.feed_entries}
