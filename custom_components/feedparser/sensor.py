"""Feedparser sensor"""
from __future__ import annotations

import asyncio
import re
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from dateutil import parser
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.util.dt as dt

import feedparser

__version__ = "0.1.11"

COMPONENT_REPO = "https://github.com/custom-components/sensor.feedparser/"

REQUIREMENTS = ["feedparser"]

CONF_FEED_URL = "feed_url"
CONF_DATE_FORMAT = "date_format"
CONF_LOCAL_TIME  = "local_time"
CONF_INCLUSIONS = "inclusions"
CONF_EXCLUSIONS = "exclusions"
CONF_SHOW_TOPN = "show_topn"

DEFAULT_SCAN_INTERVAL = timedelta(hours=1)

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
    }
)


"""@asyncio.coroutine"""
async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    async_add_devices(
        [
            FeedParserSensor(
                feed=config[CONF_FEED_URL],
                name=config[CONF_NAME],
                date_format=config[CONF_DATE_FORMAT],
                local_time=config[CONF_LOCAL_TIME],
                show_topn=config[CONF_SHOW_TOPN],
                inclusions=config[CONF_INCLUSIONS],
                exclusions=config[CONF_EXCLUSIONS],
                scan_interval=config[CONF_SCAN_INTERVAL],
            )
        ],
        True,
    )


class FeedParserSensor(SensorEntity):
    def __init__(
        self,
        feed: str,
        name: str,
        date_format: str,
        local_time: bool,
        show_topn: str,
        exclusions: str,
        inclusions: str,
        scan_interval: int,
    ) -> None:
        self._feed = feed
        self._attr_name = name
        self._attr_icon = "mdi:rss"
        self._date_format = date_format
        self._show_topn = show_topn
        self._local_time = local_time
        self._inclusions = inclusions
        self._exclusions = exclusions
        self._scan_interval = scan_interval
        self._attr_state = None
        self._entries = []
        self._attr_extra_state_attributes = {"entries": self._entries}

    def update(self):
        parsed_feed = feedparser.parse(self._feed)

        if not parsed_feed:
            return False
        else:
            self._attr_state = (
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
                        value = parser.parse(value)
                        if self._local_time:
                            value = dt.as_local(value)
                        value = value.strftime(self._date_format)

                    entry_value[key] = value

                if "image" in self._inclusions and "image" not in entry_value.keys():
                    images = []
                    if "summary" in entry.keys():
                        images = re.findall(
                            r"<img.+?src=\"(.+?)\".+?>", entry["summary"]
                        )
                    if images:
                        entry_value["image"] = images[0]
                    else:
                        entry_value[
                            "image"
                        ] = "https://www.home-assistant.io/images/favicon-192x192-full.png"

                self._entries.append(entry_value)

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def extra_state_attributes(self):
        return {"entries": self._entries}
