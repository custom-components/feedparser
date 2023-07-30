"""Constants for tests."""
from pathlib import Path

TESTS_PATH = Path(__file__).parent
DATA_PATH = TESTS_PATH / "data"
TEST_HASS_PATH = Path(__file__).parents[1] / "test_hass"

TEST_FEEDS = [
    {
        "has_images": True,
        "sensor_config": {
            "name": "CTK",
            "feed_url": "https://www.ceskenoviny.cz/sluzby/rss/cr.php",
            "scan_interval": {"hours": 1, "minutes": 30},
        },
    },
    {
        "has_images": True,
        "sensor_config": {
            "name": "nu_nl",
            "feed_url": "https://www.nu.nl/rss",
        },
    },
    {
        "has_images": True,
        "sensor_config": {
            "name": "nu_nl_algemeen",
            "feed_url": "https://www.nu.nl/rss/Algemeen",
        },
    },
    {
        "has_images": True,
        "sensor_config": {
            "name": "ct24",
            "feed_url": "https://ct24.ceskatelevize.cz/rss/hlavni-zpravy",
        },
    },
    {
        "has_images": False,
        "sensor_config": {
            "name": "bbc_europe",
            "feed_url": "http://feeds.bbci.co.uk/news/world/europe/rss.xml",
            "date_format": "%a, %d %b %Y %H:%M:%S %z",
        },
    },
    {
        "has_images": False,
        "sensor_config": {
            "name": "zive",
            "feed_url": "https://www.zive.cz/rss/sc-47/",
            "show_topn": 1,
        },
    },
]

DEFAULT_EXCLUSIONS: list[str] = []
DEFAULT_INCLUSIONS = ["image", "title", "link", "published"]
DATE_FORMAT = "%a, %d %b %Y %H:%M:%S UTC%z"
