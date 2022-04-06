"""Feedsparser sensor"""
from __future__ import annotations

import asyncio
import re
from datetime import timedelta
import logging
import voluptuous as vol
from dateutil import parser
from time import strftime
from subprocess import check_output
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from fuzzywuzzy import process

import feedparser

__version__ = "0.1.1"
_LOGGER = logging.getLogger(__name__)

COMPONENT_REPO = 'https://github.com/ad/feedsparser'

REQUIREMENTS = ["feedparser", 'fuzzywuzzy']

CONF_FEEDS_URL = "feeds_url"
CONF_DATE_FORMAT = "date_format"
CONF_INCLUSIONS = "inclusions"
CONF_EXCLUSIONS = "exclusions"
CONF_SHOW_TOPN = "show_topn"
CONF_STOP_WORDS = 'stop_words'

DEFAULT_SCAN_INTERVAL = timedelta(hours=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_FEEDS_URL, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Required(CONF_SHOW_TOPN, default=3): cv.positive_int,
    vol.Required(CONF_DATE_FORMAT, default='%a, %b %d %I:%M %p'): cv.string,
    vol.Optional(CONF_STOP_WORDS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
})


@asyncio.coroutine
def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    async_add_devices(
        [
            FeedsParserSensor(
                feeds=config[CONF_FEEDS_URL],
                name=config[CONF_NAME],
                date_format=config[CONF_DATE_FORMAT],
                show_topn=config[CONF_SHOW_TOPN],
                stop_words=config[CONF_STOP_WORDS],
                inclusions=config[CONF_INCLUSIONS],
                exclusions=config[CONF_EXCLUSIONS],
                scan_interval=config[CONF_SCAN_INTERVAL],
            )
        ],
        True,
    )


class FeedsParserSensor(SensorEntity):
    def __init__(
        self,
        feeds: str,
        name: str,
        date_format: str,
        show_topn: str,
        stop_words: list,
        exclusions: str,
        inclusions: str,
        scan_interval: int,
    ) -> None:
        self._feeds = feeds
        self._attr_name = name
        self._attr_icon = "mdi:rss"
        self._date_format = date_format
        self._show_topn = show_topn
        self._stop_words = list(map(lambda x:x.lower(), stop_words))
        self._inclusions = inclusions
        self._exclusions = exclusions
        self._scan_interval = scan_interval
        self._attr_state = None
        self._entries = []
        self._attr_extra_state_attributes = {"entries": self._entries}

    def update(self):
        self._entries = []

        for feed in self._feeds:
            count = 0

            parsed_feed = feedparser.parse(feed)
            if not parsed_feed:
                continue
            else:
                for entry in parsed_feed.entries:
                    title = entry['title'] if entry['title'] else entry['description']

                    if not title or title in self._entries:
                        continue
                    
                    if len(self._entries) > 0:
                        (highest_title, highest) = process.extractOne(title, [*self._entries.keys()])
                        if highest > 75:
                            #_LOGGER.error("%s is very similar to: %s" % (title, highest_title))
                            continue

                    if count < self._show_topn:
                        skip_title = False
                        if self._stop_words:
                            lower_title = title.lower()
                            for test_word in self._stop_words:
                                if test_word in lower_title:
                                    skip_title = True
                                    # _LOGGER.error("%s found in: %s"  % (test_word, title))
                                    continue
                        
                        if skip_title != True:    
                            self._entries[title] = {}

                            for key, value in entry.items():
                                if (self._inclusions and key not in self._inclusions) or ('parsed' in key) or (key in self._exclusions):
                                    continue

                                if key in ['published', 'updated', 'created', 'expired']:
                                    value = parser.parse(value).strftime(self._date_format)

                                self._entries[title][key] = value
                            count += 1

                        self._entries.append(entry_value) 
        self._attr_state = (
            len(self._entries)
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def extra_state_attributes(self):
        return {"entries": self._entries}
