"""Pytest configuration."""

import pytest
from constants import TEST_FEEDS
from feedsource import FeedSource
from pytest import FixtureRequest

from custom_components.feedparser.sensor import FeedParserSensor


def get_feeds() -> list[FeedSource]:
    """Return list of feeds represented by FeedSource objects."""
    return [FeedSource(feed) for feed in TEST_FEEDS]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Generate tests and fixtures."""
    if "feed" in metafunc.fixturenames:
        feeds = get_feeds()
        metafunc.parametrize("feed", feeds, ids=[f.name for f in feeds], indirect=True)


@pytest.fixture
def feed(request: FixtureRequest) -> FeedSource:
    """Return feed file source."""
    return request.param


@pytest.fixture
def feed_sensor(feed: FeedSource) -> FeedParserSensor:
    """Return feed sensor initialized with the local RSS feed."""
    return FeedParserSensor(**feed.sensor_config_local_feed)
