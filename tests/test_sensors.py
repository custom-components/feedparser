""""Tests the feedparser sensor."""


import time
from datetime import UTC, datetime

import feedparser
import pytest
from constants import DATE_FORMAT
from feedsource import FeedSource

from custom_components.feedparser.sensor import (
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_THUMBNAIL,
    FeedParserSensor,
)


def test_simple(feed_sensor: FeedParserSensor) -> None:
    """Test simple."""
    feed_sensor.update()
    assert feed_sensor._entries


def test_update_sensor(feed: FeedSource) -> None:
    """Test instantiate sensor."""
    feed_sensor = FeedParserSensor(
        feed=feed.path.absolute().as_uri(),
        name=feed.name,
        date_format=DATE_FORMAT,
        local_time=False,
        show_topn=9999,
        inclusions=["image", "title", "link", "published"],
        exclusions=[],
        scan_interval=DEFAULT_SCAN_INTERVAL,
    )
    feed_sensor.update()
    assert feed_sensor._entries

    # assert that the sensor value is equal to the number of entries
    assert feed_sensor._attr_native_value == len(feed_sensor._entries)

    # assert that all entries have a title
    assert all(e["title"] for e in feed_sensor._entries)

    # assert that all entries have a link
    assert all(e["link"] for e in feed_sensor._entries)

    # assert that all entries have a published date
    assert all(e["published"] for e in feed_sensor._entries)

    # assert that all entries have non-default image
    if feed.has_images:
        assert all(e["image"] != DEFAULT_THUMBNAIL for e in feed_sensor._entries)
    else:
        assert all(e["image"] == DEFAULT_THUMBNAIL for e in feed_sensor._entries)

    # assert that all entries have a unique link
    assert len({e["link"] for e in feed_sensor._entries}) == len(
        feed_sensor._entries
    ), "Duplicate links found"

    # assert that all entries have a unique title
    assert len({e["title"] for e in feed_sensor._entries}) == len(
        feed_sensor._entries
    ), "Duplicate titles found"

    # assert that all entries have a unique published date
    assert len({e["published"] for e in feed_sensor._entries}) == len(
        feed_sensor._entries
    ), "Duplicate published dates found"

    # assert that all entries have a unique image
    if feed.has_images:
        assert len({e["image"] for e in feed_sensor._entries}) == len(
            feed_sensor._entries
        ), "Duplicate images found"


def test_update_sensor_with_topn(feed: FeedSource) -> None:
    """Test that the sensor stores only the topn entries."""
    show_topn = 3
    feed_sensor = FeedParserSensor(
        feed=feed.path.absolute().as_uri(),
        name=feed.name,
        date_format=DATE_FORMAT,
        local_time=False,
        show_topn=show_topn,
        inclusions=["image", "title", "link", "published"],
        exclusions=[],
        scan_interval=DEFAULT_SCAN_INTERVAL,
    )
    feed_sensor.update()
    assert feed_sensor._entries

    # assert that the sensor value is equal to the number of
    # entries and that only top N entries are stored
    assert feed_sensor._attr_native_value == show_topn == len(feed_sensor._entries)


@pytest.mark.parametrize(
    "local_time", [True, False], ids=["local_time", "default_time"]
)
def test_update_sensor_entries_time(
    feed: FeedSource, feed_sensor: FeedParserSensor, local_time: bool
) -> None:
    """Test that the sensor converts the published date to local time."""
    feed_sensor._local_time = local_time
    feed_sensor.update()
    assert feed_sensor._entries

    # load the feed with feedparser
    parsed_feed: feedparser.FeedParserDict = feedparser.parse(
        feed.path.absolute().as_uri()
    )

    # get the first entry
    entry = parsed_feed.entries[0]

    # get the time of the first entry
    first_entry_struct_time: time.struct_time = entry.published_parsed
    first_entry_time: datetime = datetime(*first_entry_struct_time[:6], tzinfo=UTC)

    # get the time of the first entry in the sensor
    first_sensor_entry_time: datetime = datetime.strptime(
        feed_sensor._entries[0]["published"], feed.sensor_config.date_format
    )

    # assert that the time of the first entry in the sensor is equal to
    # the time of the first entry in the feed
    assert first_entry_time == first_sensor_entry_time
