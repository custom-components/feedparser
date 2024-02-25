"""Pytest configuration."""

import pytest
from constants import TEST_FEEDS
from feedsource import FeedSource

from custom_components.feedparser.sensor import FeedParserSensor


def get_feeds() -> list[FeedSource]:
    """Return list of feeds represented by FeedSource objects."""
    return [FeedSource(feed) for feed in TEST_FEEDS]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Generate tests and fixtures."""
    feeds = get_feeds()
    if "feed" in metafunc.fixturenames:
        metafunc.parametrize("feed", feeds, ids=[f.name for f in feeds], indirect=True)
    if "feed_with_image_in_summary" in metafunc.fixturenames:
        feeds_with_image_in_summary = [
            pytest.param(
                feed,
                id=feed.name,
            )
            for feed in feeds
            if feed.has_images_in_summary
        ]
        metafunc.parametrize(
            "feed_with_image_in_summary",
            feeds_with_image_in_summary,
            indirect=True,
        )


@pytest.fixture()
def feed(request: pytest.FixtureRequest) -> FeedSource:
    """Return feed file source."""
    return request.param


@pytest.fixture()
def feed_sensor(feed: FeedSource) -> FeedParserSensor:
    """Return feed sensor initialized with the local RSS feed."""
    return FeedParserSensor(**feed.sensor_config_local_feed)


@pytest.fixture()
def feed_with_image_in_summary(
    request: pytest.FixtureRequest,
) -> FeedSource:
    """Return feed sensor with images in summary of its entries."""
    return request.param
