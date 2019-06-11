"""
A component which allows you to parse an RSS feed into a sensor

For more details about this component, please refer to the documentation at
https://github.com/custom-components/sensor.feedparser

Following spec from https://validator.w3.org/feed/docs/rss2.html
"""

import logging
import voluptuous as vol
from datetime import timedelta
from dateutil import parser
from time import strftime
from subprocess import check_output
from homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import (PLATFORM_SCHEMA)

from fuzzywuzzy import process

__version__ = '0.0.3'
_LOGGER = logging.getLogger(__name__)

REQUIREMENTS = ['feedparser', 'fuzzywuzzy']

CONF_NAME = 'name'
CONF_FEEDS_URL = 'feeds_url'
CONF_LIMIT_PER_FEED = 'limit_per_feed'
CONF_DATE_FORMAT = 'date_format'
CONF_STOP_WORDS = 'stop_words'
CONF_INCLUSIONS = 'inclusions'
CONF_EXCLUSIONS = 'exclusions'

DEFAULT_SCAN_INTERVAL = timedelta(hours=1)

COMPONENT_REPO = 'https://github.com/ad/feedparser'
SCAN_INTERVAL = timedelta(minutes=15)
ICON = 'mdi:rss'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_FEEDS_URL, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Required(CONF_LIMIT_PER_FEED, default=3): cv.positive_int,
    vol.Required(CONF_DATE_FORMAT, default='%a, %b %d %I:%M %p'): cv.string,
    vol.Optional(CONF_STOP_WORDS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
})

def setup_platform(hass, config, add_devices, discovery_info=None):
    add_devices([FeedParserSensor(hass, config)])

class FeedParserSensor(Entity):
    def __init__(self, hass, config):
        self.hass = hass
        self._feeds = config[CONF_FEEDS_URL]
        self._name = config[CONF_NAME]
        self._limit_per_feed = config[CONF_LIMIT_PER_FEED]
        self._date_format = config[CONF_DATE_FORMAT]
        self._stop_words = list(map(lambda x:x.lower(), config[CONF_STOP_WORDS]))
        self._inclusions = config[CONF_INCLUSIONS]
        self._exclusions = config[CONF_EXCLUSIONS]
        self._state = None
        self.hass.data[self._name] = {}
        self.update()

    def update(self):
        import feedparser

        self.hass.data[self._name] = {}

        for feed in self._feeds:
            count = 0
            parsedFeed = feedparser.parse(feed)

            if not parsedFeed:
                continue
            else:
                for entry in parsedFeed.entries:
                    title = entry['title'] if entry['title'] else entry['description']

                    if not title or title in self.hass.data[self._name]:
                        continue
                    
                    if len(self.hass.data[self._name]) > 0:
                        (highest_title, highest) = process.extractOne(title, [*self.hass.data[self._name].keys()])
                        if highest > 90:
                            #_LOGGER.error("%s is very similar to: %s" % (title, highest_title))
                            continue

                    if count < self._limit_per_feed:
                        skip_title = False
                        if self._stop_words:
                            lower_title = title.lower()
                            for test_word in self._stop_words:
                                if test_word in lower_title:
                                    skip_title = True
                                    # _LOGGER.error("%s found in: %s"  % (test_word, title))
                                    continue
                        
                        if skip_title != True:    
                            self.hass.data[self._name][title] = {}

                            for key, value in entry.items():
                                if (self._inclusions and key not in self._inclusions) or ('parsed' in key) or (key in self._exclusions):
                                    continue

                                if key in ['published', 'updated', 'created', 'expired']:
                                    value = parser.parse(value).replace(tzinfo=None).strftime(self._date_format)

                                self.hass.data[self._name][title][key] = value
                            count += 1

        self._state = len(self.hass.data[self._name])

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def icon(self):
        return ICON

    @property
    def device_state_attributes(self):
        return self.hass.data[self._name]
