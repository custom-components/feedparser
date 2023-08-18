"""Feedparser sensor."""
from __future__ import annotations

import email.utils
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import feedparser  # type: ignore[import]
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from dateutil import parser
from feedparser import FeedParserDict
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.util import dt

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

__version__ = "0.1.11"

COMPONENT_REPO = "https://github.com/custom-components/feedparser/"

REQUIREMENTS = ["feedparser"]

CONF_FEED_URL = "feed_url"
CONF_DATE_FORMAT = "date_format"
CONF_LOCAL_TIME = "local_time"
CONF_INCLUSIONS = "inclusions"
CONF_EXCLUSIONS = "exclusions"
CONF_SHOW_TOPN = "show_topn"

DEFAULT_DATE_FORMAT = "%a, %b %d %I:%M %p"
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
DEFAULT_THUMBNAIL = "https://www.home-assistant.io/images/favicon-192x192-full.png"
DEFAULT_TOPN = 9999

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_FEED_URL): cv.string,
        vol.Required(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): cv.string,
        vol.Optional(CONF_LOCAL_TIME, default=False): cv.boolean,
        vol.Optional(CONF_SHOW_TOPN, default=DEFAULT_TOPN): cv.positive_int,
        vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    },
)

_LOGGER: logging.Logger = logging.getLogger(__name__)


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
                inclusions=config[CONF_INCLUSIONS],
                exclusions=config[CONF_EXCLUSIONS],
                scan_interval=config[CONF_SCAN_INTERVAL],
                local_time=config[CONF_LOCAL_TIME],
            ),
        ],
        update_before_add=True,
    )


class FeedParserSensor(SensorEntity):
    """Representation of a Feedparser sensor."""

    def __init__(
        self: FeedParserSensor,
        feed: str,
        name: str,
        date_format: str,
        show_topn: int,
        exclusions: list[str | None],
        inclusions: list[str | None],
        scan_interval: timedelta,
        local_time: bool,
    ) -> None:
        """Initialize the Feedparser sensor."""
        self._feed = feed
        self._attr_name = name
        self._attr_icon = "mdi:rss"
        self._date_format = date_format
        self._show_topn: int = show_topn
        self._inclusions = inclusions
        self._exclusions = exclusions
        self._scan_interval = scan_interval
        self._local_time = local_time
        self._entries: list[dict[str, str]] = []
        self._attr_extra_state_attributes = {"entries": self._entries}
        _attr_attribution = "Data retrieved using RSS feedparser"
        _LOGGER.debug("Feed %s: FeedParserSensor initialized - %s", self.name, self)

    def __repr__(self: FeedParserSensor) -> str:
        """Return the representation."""
        return (
            f'FeedParserSensor(name="{self.name}", feed="{self._feed}", '
            f"show_topn={self._show_topn}, inclusions={self._inclusions}, "
            f"exclusions={self._exclusions}, scan_interval={self._scan_interval}, "
            f'local_time={self._local_time}, date_format="{self._date_format}")'
        )

    def update(self: FeedParserSensor) -> None:
        """Parse the feed and update the state of the sensor."""
        _LOGGER.debug("Feed %s: Polling feed data from %s", self.name, self._feed)
        parsed_feed: FeedParserDict = feedparser.parse(self._feed)

        if not parsed_feed:
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
        parsed_feed: FeedParserDict,
    ) -> list[dict[str, str]]:
        return [
            self._generate_sensor_entry(feed_entry)
            for feed_entry in parsed_feed.entries[
                : self.native_value  # type: ignore[misc]
            ]
        ]

    def _generate_sensor_entry(
        self: FeedParserSensor,
        feed_entry: FeedParserDict,
    ) -> dict[str, str]:
        _LOGGER.debug("Feed %s: Generating sensor entry for %s", self.name, feed_entry)
        sensor_entry = {}
        for key, value in feed_entry.items():
            if (
                (self._inclusions and key not in self._inclusions)
                or ("parsed" in key)
                or (key in self._exclusions)
            ):
                continue
            if key in ["published", "updated", "created", "expired"]:
                parsed_date: datetime = self._parse_date(value)
                sensor_entry[key] = parsed_date.strftime(self._date_format)
            elif key == "image":
                sensor_entry["image"] = value.get("href")
            else:
                sensor_entry[key] = value

            if "image" in self._inclusions and "image" not in sensor_entry:
                sensor_entry["image"] = self._process_image(feed_entry)
            if (
                "link" in self._inclusions
                and "link" not in sensor_entry
                and (processed_link := self._process_link(feed_entry))
            ):
                sensor_entry["link"] = processed_link
        _LOGGER.debug("Feed %s: Generated sensor entry: %s", self.name, sensor_entry)
        return sensor_entry

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

    def _process_image(self: FeedParserSensor, feed_entry: FeedParserDict) -> str:
        if "enclosures" in feed_entry and feed_entry["enclosures"]:
            images = [
                enc for enc in feed_entry["enclosures"] if enc.type.startswith("image/")
            ]
            if images:
                # pick the first image found
                return images[0]["href"]
        elif "summary" in feed_entry:
            images = re.findall(
                r"<img.+?src=\"(.+?)\".+?>",
                feed_entry["summary"],
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

    def _process_link(self: FeedParserSensor, feed_entry: FeedParserDict) -> str:
        """Return link from feed entry."""
        if "links" in feed_entry:
            if len(feed_entry["links"]) > 1:
                _LOGGER.warning(
                    "Feed %s: More than one link found for %s. Using the first link.",
                    self.name,
                    feed_entry,
                )
            return feed_entry["links"][0]["href"]
        return ""

    @property
    def feed_entries(self: FeedParserSensor) -> list[dict[str, str]]:
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
