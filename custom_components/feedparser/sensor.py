"""Feedparser sensor"""
from __future__ import annotations

import asyncio
import re
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from dateutil import parser
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType, DiscoverInfoType

import feedparser

__version__ = "0.1.6"

REQUIREMENTS = ["feedparser"]

CONF_FEED_URL = "feed_url"
CONF_DATE_FORMAT = "date_format"
CONF_INCLUSIONS = "inclusions"
CONF_EXCLUSIONS = "exclusions"
CONF_SHOW_TOPN = "show_topn"

DEFAULT_SCAN_INTERVAL = timedelta(hours=1)

COMPONENT_REPO = "https://github.com/custom-components/sensor.feedparser/"
SCAN_INTERVAL = timedelta(hours=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_FEED_URL): cv.string,
        vol.Required(CONF_DATE_FORMAT, default="%a, %b %d %I:%M %p"): cv.string,
        vol.Optional(CONF_SHOW_TOPN, default=9999): cv.positive_int,
        vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    }
)


@asyncio.coroutine
def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices,
    discovery_info: DiscoverInfoType | None = None,
) -> None:
    async_add_devices(
        [
            FeedParserSensor(
                feed=config[CONF_FEED_URL],
                name=config[CONF_NAME],
                date_format=config[CONF_DATE_FORMAT],
                show_topn=config[CONF_SHOW_TOPN],
                inclusions=config[CONF_INCLUSIONS],
                exclusions=config[CONF_EXCLUSIONS],
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
        show_topn: str,
        exclusions: str,
        inclusions: str,
    ) -> None:
        self._feed = feed
        self._attr_name = name
        self._attr_icon = "mdi:rss"
        self._date_format = date_format
        self._show_topn = show_topn
        self._inclusions = inclusions
        self._exclusions = exclusions
        self._attr_state = None
        self._entries = []

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
                        value = parser.parse(value).strftime(self._date_format)

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
    def device_state_attributes(self):
        return {"entries": self._entries}
