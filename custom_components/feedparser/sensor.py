"""
A component which allows you to parse an RSS feed into a sensor

For more details about this component, please refer to the documentation at
https://github.com/custom-components/sensor.feedparser

Following spec from https://validator.w3.org/feed/docs/rss2.html
"""
import asyncio
import re
import feedparser
import logging
import voluptuous as vol
from datetime import datetime, timedelta
from dateutil import parser
from homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.template as tm
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
CONF_SHOW_HOURS = 'show_hours'
CONF_SHOW_TIME = 'show_after_time'
CONF_REMOVE_IMAGE = 'remove_image_from_summary'
CONF_FILTER = 'filter'
CONF_FILTER_DEFAULT = 'topn'
CONF_FILTER_OPTIONS = ['topn', 'hours', 'time']

DEFAULT_SCAN_INTERVAL = timedelta(hours=1)

COMPONENT_REPO = 'https://github.com/custom-components/sensor.feedparser/'
SCAN_INTERVAL = timedelta(hours=1)
ICON = 'mdi:rss'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_FEED_URL): cv.string,
    vol.Required(CONF_DATE_FORMAT, default='%a, %b %d %I:%M %p'): cv.string,
    vol.Optional(CONF_FILTER, default=CONF_FILTER_DEFAULT): vol.All(cv.string, vol.In(CONF_FILTER_OPTIONS)),
    vol.Optional(CONF_SHOW_TOPN, default=9999): cv.positive_int,
    vol.Optional(CONF_SHOW_HOURS, default=0): cv.positive_int,
    vol.Optional(CONF_SHOW_TIME, default=''): cv.template,
    vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_REMOVE_IMAGE, default=False): cv.boolean,
})


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    async_add_devices([FeedParserSensor(hass=hass, config=config)], True)


class FeedParserSensor(Entity):
    def __init__(self, hass, config: dict = None):
        self.hass = hass
        self._config = config
        self._feed = None
        self._name = None
        self._date_format = None
        self._filter = None
        self._show_topn = 9999
        self._show_hours = None
        self._show_time = None
        self._inclusions = None
        self._exclusions = None
        self._remove_image = None
        self._state = None
        self._entries = []

        if self._config:
            self._feed = config[CONF_FEED_URL]
            self._name = config[CONF_NAME]
            self._date_format = config[CONF_DATE_FORMAT]
            if CONF_FILTER in self._config:
                self._filter = self._config[CONF_FILTER]
            if self._filter and self._filter == 'topn' and CONF_SHOW_TOPN in self._config:
                self._show_topn = self._config[CONF_SHOW_TOPN]
            if self._filter and self._filter == 'hours' and CONF_SHOW_HOURS in self._config:
                self._show_hours = self._config[CONF_SHOW_HOURS]
            if self._filter and self._filter == 'time' and CONF_SHOW_TIME in self._config:
                self._show_time = self._config[CONF_SHOW_TIME]
            if CONF_INCLUSIONS in self._config:
                self._inclusions = self._config[CONF_INCLUSIONS]
            if CONF_EXCLUSIONS in self._config:
                self._exclusions = self._config[CONF_EXCLUSIONS]
            if CONF_REMOVE_IMAGE in self._config:
                self._remove_image = self._config[CONF_REMOVE_IMAGE]


    def update(self):
        parsedFeed = feedparser.parse(self._feed)

        if not parsedFeed:
            return False
        else:
            self._state = self._show_topn if len(parsedFeed.entries) > self._show_topn else len(parsedFeed.entries)
            self._entries = []

            date_compare = None
            if self._filter == 'hours':
                date_compare = datetime.now() - timedelta(hours=self._show_hours)
            if self._filter == 'time':
                _template = self._show_time
                _template.hass = self.hass
                date_compare = parser.parse(_template.async_render())

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
                
                if self._remove_image:
                    entryValue['summary'] = re.sub(r"<img.+?src=\"(.+?)\".+?>", "", entry['summary'])
                
                if date_compare is None or datetime.strptime(entryValue['published'], self._date_format) >= date_compare:
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
