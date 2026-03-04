"""Constants for the Feedparser integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "feedparser"
PLATFORMS: list[Platform] = [Platform.SENSOR]

CONF_FEED_URL = "feed_url"
CONF_DATE_FORMAT = "date_format"
CONF_LOCAL_TIME = "local_time"
CONF_INCLUSIONS = "inclusions"
CONF_EXCLUSIONS = "exclusions"
CONF_SHOW_TOPN = "show_topn"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_REMOVE_SUMMARY_IMAGE = "remove_summary_image"

DEFAULT_DATE_FORMAT = "%a, %b %d %I:%M %p"
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)
DEFAULT_TOPN = 9999
DEFAULT_LOCAL_TIME = False
DEFAULT_REMOVE_SUMMARY_IMAGE = False

DEFAULT_NAME = "Feed"

ENTRY_VERSION = 2

OPTION_KEYS: list[str] = [
    CONF_DATE_FORMAT,
    CONF_LOCAL_TIME,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_TOPN,
    CONF_REMOVE_SUMMARY_IMAGE,
    CONF_INCLUSIONS,
    CONF_EXCLUSIONS,
]
