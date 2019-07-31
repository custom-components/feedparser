"""
A component which allows you to parse an RSS feed into a sensor

For more details about this component, please refer to the documentation at
https://github.com/custom-components/sensor.feedparser

Following spec from https://validator.w3.org/feed/docs/rss2.html
"""
import re
import feedparser
import logging
import voluptuous as vol
from datetime import timedelta
from dateutil import parser
from time import strftime
from subprocess import check_output
from homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import (PLATFORM_SCHEMA)
from homeassistant.const import (CONF_NAME)

__version__ = '0.0.6'
_LOGGER = logging.getLogger(__name__)

REQUIREMENTS = ['feedparser']

CONF_FEED_URL = 'feed_url'
CONF_DATE_FORMAT = 'date_format'
CONF_INCLUSIONS = 'inclusions'
CONF_EXCLUSIONS = 'exclusions'
CONF_SHOW_TOPN  = 'show_topn'

DEFAULT_SCAN_INTERVAL = timedelta(hours=1)

COMPONENT_REPO = 'https://github.com/custom-components/sensor.feedparser/'
SCAN_INTERVAL = timedelta(hours=1)
ICON = 'mdi:rss'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_FEED_URL): cv.string,
    vol.Required(CONF_DATE_FORMAT, default='%a, %b %d %I:%M %p'): cv.string,
    vol.Optional(CONF_SHOW_TOPN, default=9999): cv.positive_int,
    vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
})

def setup_platform(hass, config, add_devices, discovery_info=None):
    add_devices([FeedParserSensor(hass, config)])

class FeedParserSensor(Entity):
    def __init__(self, hass, config):
        self.hass = hass
        self._feed = config[CONF_FEED_URL]
        self._name = config[CONF_NAME]
        self._date_format = config[CONF_DATE_FORMAT]
        self._show_topn = config[CONF_SHOW_TOPN]
        self._inclusions = config[CONF_INCLUSIONS]
        self._exclusions = config[CONF_EXCLUSIONS]
        self._state = None
        self._entries = []
        self.update()

    def update(self):
        parsedFeed = feedparser.parse(self._feed)

        if not parsedFeed:
            return False
        else:
            self._state = self._show_topn if len(parsedFeed.entries) > self._show_topn else len(parsedFeed.entries)
            self._entries = []

            for entry in parsedFeed.entries[:self._state]:
                entryValue = {}

                for key, value in entry.items():
                    if (self._inclusions and key not in self._inclusions) or ('parsed' in key) or (key in self._exclusions):
                        continue
                    if key in ['published', 'updated', 'created', 'expired']:
                        value = parser.parse(value).strftime(self._date_format)

                    entryValue[key] = value

                if 'image' in self._inclusions and 'image' not in entryValue.keys():
                    images = []
                    if 'summary' in entry.keys():
                        images = re.findall(r"<img.+?src=\"(.+?)\".+?>", entry['summary'])
                    if images:
                        entryValue['image'] = images[0]
                    else:
                        entryValue['image'] = "https://www.home-assistant.io/images/favicon-192x192-full.png"

                self._entries.append(entryValue)

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
        return {
            'entries': self._entries
        }
