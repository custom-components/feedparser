"""Generate Home Assistant sensors config from test feeds."""
from constants import TEST_FEEDS
from feedsource import FeedSource

fsources = [FeedSource(fs) for fs in TEST_FEEDS]
FeedSource.create_ha_sensors_config_file([fs for fs in fsources])
