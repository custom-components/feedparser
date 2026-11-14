"""Test helper that drives FeedReader the way the old synchronous sensor was used."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from custom_components.feedparser.reader import FeedReader


class ReaderHarness:
    """Hold the entries from the last `update()` like the pre-coordinator sensor.

    Keeps the fixture-driven feed tests readable: `update()` reads the feed and
    `feed_entries` / `native_value` mirror what the sensor would expose.
    """

    def __init__(
        self: ReaderHarness,
        *,
        scan_interval: timedelta | int | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        """Create the reader; `scan_interval` is accepted and ignored."""
        self.reader = FeedReader(**kwargs)
        self.feed_entries: list[dict[str, object]] = []

    def update(self: ReaderHarness) -> None:
        """Read the feed."""
        self.feed_entries = self.reader.read()

    @property
    def native_value(self: ReaderHarness) -> int | None:
        """Return the entry count the sensor would show."""
        return len(self.feed_entries) or None

    @property
    def local_time(self: ReaderHarness) -> bool:
        """Return whether dates are converted to local time."""
        return self.reader.local_time

    @local_time.setter
    def local_time(self: ReaderHarness, value: bool) -> None:
        self.reader.local_time = value
