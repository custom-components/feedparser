"""Feedparser sensor."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
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

DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
DEFAULT_THUMBNAIL = "https://www.home-assistant.io/images/favicon-192x192-full.png"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_FEED_URL): cv.string,
        vol.Required(CONF_DATE_FORMAT, default="%a, %b %d %I:%M %p"): cv.string,
        vol.Optional(CONF_LOCAL_TIME, default=False): cv.boolean,
        vol.Optional(CONF_SHOW_TOPN, default=9999): cv.positive_int,
        vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    },
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
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

    def update(self: FeedParserSensor) -> None:
        """Parse the feed and update the state of the sensor."""
        parsed_feed: FeedParserDict = feedparser.parse(self._feed)

        if not parsed_feed:
            self._attr_native_value = None
            return

        self._attr_native_value = (
            self._show_topn
            if len(parsed_feed.entries) > self._show_topn
            else len(parsed_feed.entries)
        )
        self._entries = []

        for entry in parsed_feed.entries[: self._attr_state]:
            entry_value = {}

            for key, value in entry.items():
                if (
                    (self._inclusions and key not in self._inclusions)
                    or ("parsed" in key)
                    or (key in self._exclusions)
                ):
                    continue
                if key in ["published", "updated", "created", "expired"]:
                    time: datetime = parser.parse(value)
                    if self._local_time:
                        time = dt.as_local(time)
                    entry_value[key] = time.strftime(self._date_format)
                else:
                    entry_value[key] = value

                if "image" in self._inclusions and "image" not in entry_value.keys():
                    if "enclosures" in entry:
                        images = [
                            enc
                            for enc in entry["enclosures"]
                            if enc.type.startswith("image/")
                        ]
                    else:
                        images = []
                    if images:
                        entry_value["image"] = images[0][
                            "href"
                        ]  # pick the first image found
                    else:
                        entry_value[
                            "image"
                        ] = DEFAULT_THUMBNAIL  # use default image if no image found

            self._entries.append(entry_value)

    @property
    def extra_state_attributes(self: FeedParserSensor) -> dict[str, list]:
        """Return entity specific state attributes."""
        return {"entries": self._entries}
