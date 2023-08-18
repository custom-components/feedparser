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
    {
        "has_images": True,
        "all_entries_have_images": False,
        "has_unique_links": False,
        "sensor_config": {
            "name": "buienradar_nl",
            "feed_url": "https://data.buienradar.nl/1.0/feed/xml/rssbuienradar",
            "date_format": "%Y-%m-%d %H:%M:%S.%f",
        },
    },
    {
        "has_images": False,
        "has_unique_links": False,
        "sensor_config": {
            "name": "skolmaten_se_ede_skola",
            "feed_url": "https://skolmaten.se/ede-skola/rss/weeks/?limit=2",
            "inclusions": ["title", "link", "published", "summary"],
        },
    },
    {
        "has_images": False,
        "sensor_config": {
            "name": "api_met_no_metalerts",
            "feed_url": "https://api.met.no/weatherapi/metalerts/1.1/",
            "inclusions": ["title", "link", "published", "summary"],
        },
    },
    {
        "has_images": True,
        "has_unique_images": False,
        "has_unique_titles": False,
        "sensor_config": {
            "name": "anp_nieuws",
            "feed_url": "https://www.omnycontent.com/d/playlist/56ccbbb7-0ff7-4482-9d99-a88800f49f6c/a49c87f6-d567-4189-8692-a8e2009eaf86/9fea2041-fccd-4fcf-8cec-a8e2009eeca2/podcast.rss",
            "inclusions": ["title", "link", "published", "summary"],
        },
    },
]

DEFAULT_EXCLUSIONS: list[str] = []
DEFAULT_INCLUSIONS = ["image", "title", "link", "published"]
DATE_FORMAT = "%a, %d %b %Y %H:%M:%S UTC%z"
