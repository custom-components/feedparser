""""Tests the feedparser sensor."""

import re
from contextlib import nullcontext, suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import feedparser
import pytest
from constants import DATE_FORMAT, URLS_HEADERS_REQUIRED
from feedsource import FeedSource

from custom_components.feedparser.sensor import (
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_THUMBNAIL,
    IMAGE_REGEX,
    FeedParserSensor,
)

if TYPE_CHECKING:
    import time


def test_simple(feed_sensor: FeedParserSensor) -> None:
    """Test simple."""
    feed_sensor.update()
    assert feed_sensor.feed_entries


def test_update_sensor(feed: FeedSource) -> None:
    """Test instantiate sensor."""
    feed_sensor = FeedParserSensor(
        feed=feed.path.absolute().as_uri(),
        name=feed.name,
        date_format=feed.sensor_config.date_format,
        local_time=feed.sensor_config.local_time,
        show_topn=feed.sensor_config.show_topn,
        remove_summary_image=feed.sensor_config.remove_summary_image,
        inclusions=feed.sensor_config.inclusions,
        exclusions=feed.sensor_config.exclusions,
        scan_interval=feed.sensor_config.scan_interval,
    )
    feed_sensor.update()
    assert feed_sensor.feed_entries

    # assert that the sensor value is equal to the number of entries
    assert feed_sensor.native_value == len(feed_sensor.feed_entries)

    # assert that all entries have a title
    assert all(e["title"] for e in feed_sensor.feed_entries)

    # assert that all entries have a link
    assert all(e["link"] for e in feed_sensor.feed_entries)

    # assert that all entries have a published date
    assert all(e["published"] for e in feed_sensor.feed_entries)

    # assert that all entries have non-default image
    if feed.all_entries_have_images and "image" in feed.sensor_config.inclusions:
        if feed.has_images:
            assert all(
                e["image"] != DEFAULT_THUMBNAIL for e in feed_sensor.feed_entries
            ), "Default image found for entry that should have an image"
        else:
            assert all(
                e["image"] == DEFAULT_THUMBNAIL for e in feed_sensor.feed_entries
            ), "Non-default image found for entry that should not have an image"

    # assert that all entries have a unique link
    if feed.has_unique_links:
        assert len({e["link"] for e in feed_sensor.feed_entries}) == len(
            feed_sensor.feed_entries,
        ), "Duplicate links found"

    # assert that all entries have a unique title
    if feed.has_unique_titles:
        assert len({e["title"] for e in feed_sensor.feed_entries}) == len(
            feed_sensor.feed_entries,
        ), "Duplicate titles found"

    # assert that all entries have a unique published date
    if feed.has_unique_dates:
        assert len({e["published"] for e in feed_sensor.feed_entries}) == len(
            feed_sensor.feed_entries,
        ), "Duplicate published dates found"

    # assert that all entries have a unique image
    if feed.has_images and feed.has_unique_images:
        assert len({e["image"] for e in feed_sensor.feed_entries}) == len(
            feed_sensor.feed_entries,
        ), "Duplicate images found"


def test_update_sensor_with_topn(feed: FeedSource) -> None:
    """Test that the sensor stores only the topn entries."""
    show_topn = 1
    feed_sensor = FeedParserSensor(
        feed=feed.path.absolute().as_uri(),
        name=feed.name,
        date_format=DATE_FORMAT,
        local_time=False,
        show_topn=show_topn,
        remove_summary_image=False,
        inclusions=["image", "title", "link", "published"],
        exclusions=[],
        scan_interval=DEFAULT_SCAN_INTERVAL,
    )
    feed_sensor.update()
    assert feed_sensor.feed_entries

    # assert that the sensor value is equal to the number of
    # entries and that only top N entries are stored
    assert feed_sensor.native_value == show_topn == len(feed_sensor.feed_entries)


@pytest.mark.parametrize(
    "local_time",
    [True, False],
    ids=["local_time", "default_time"],
)
def test_update_sensor_entries_time(
    feed: FeedSource,
    feed_sensor: FeedParserSensor,
    local_time: bool,
) -> None:
    """Test that the sensor converts the published date to local time."""
    feed_sensor.local_time = local_time
    feed_sensor.update()
    assert feed_sensor.feed_entries

    # load the feed with feedparser
    parsed_feed: feedparser.FeedParserDict = feedparser.parse(
        feed.path.absolute().as_uri(),
    )

    # get the first entry
    entry = parsed_feed.entries[0]

    # get the time of the first entry
    first_entry_struct_time: time.struct_time = entry.published_parsed
    first_entry_time: datetime = datetime(*first_entry_struct_time[:6], tzinfo=UTC)

    # get the time of the first entry in the sensor
    first_sensor_entry_time: datetime = datetime.strptime(  # noqa: DTZ007
        feed_sensor.feed_entries[0]["published"],
        feed.sensor_config.date_format,
    )

    if not first_sensor_entry_time.tzinfo:
        first_sensor_entry_time = first_sensor_entry_time.replace(tzinfo=UTC)

    # assert that the time of the first entry in the sensor is equal to
    # the time of the first entry in the feed
    assert first_entry_time == first_sensor_entry_time


def test_check_duplicates(feed_sensor: FeedParserSensor) -> None:
    """Test that the sensor stores only unique entries."""
    feed_sensor.update()
    assert feed_sensor.extra_state_attributes["entries"]
    after_first_update = len(feed_sensor.feed_entries)
    feed_sensor.update()
    after_second_update = len(feed_sensor.feed_entries)
    assert after_first_update == after_second_update


@pytest.mark.parametrize(
    "online_feed",
    URLS_HEADERS_REQUIRED,
    ids=lambda feed_url: feed_url["name"],
)
def test_fetch_data_headers_required(online_feed: dict) -> None:
    """Test fetching feed from remote server that requires request with headers."""
    feed_sensor = FeedParserSensor(
        feed=online_feed["url"],
        name=online_feed["name"],
        date_format=DATE_FORMAT,
        local_time=False,
        show_topn=9999,
        remove_summary_image=False,
        inclusions=["image", "title", "link", "published"],
        exclusions=[],
        scan_interval=DEFAULT_SCAN_INTERVAL,
    )
    feed_sensor.update()
    assert feed_sensor.feed_entries


def test_remove_summary_image(
    feed_with_image_in_summary: FeedSource,
) -> None:
    """Test that the sensor removes the image from the summary."""
    feed = feed_with_image_in_summary
    feed_sensor = FeedParserSensor(
        **feed.sensor_config_local_feed | {"remove_summary_image": False},
    )
    feed_sensor.update()
    assert feed_sensor.feed_entries

    # assert that the sensor does not remove the image from the summary
    assert any(
        re.search(IMAGE_REGEX, e["summary"]) is not None
        for e in feed_sensor.feed_entries
    )

    feed_sensor = FeedParserSensor(
        **feed.sensor_config_local_feed | {"remove_summary_image": True},
    )
    feed_sensor.update()
    assert feed_sensor.feed_entries

    with nullcontext() if feed.all_entries_have_summary else suppress(KeyError):
        assert all("img" not in e["summary"] for e in feed_sensor.feed_entries)


def test_image_not_in_entries(feed: FeedSource) -> None:
    """Test that the sensor does not include the image in any feed entry."""
    # keep only the title in the inclusions
    feed_sensor = FeedParserSensor(
        **feed.sensor_config_local_feed | {"inclusions": ["title"]},
    )
    feed_sensor.update()
    assert feed_sensor.feed_entries
    # assert that the sensor does not include the image in its feed entries
    assert all("image" not in e for e in feed_sensor.feed_entries)
