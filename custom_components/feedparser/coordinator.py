"""Polling coordinator for one Feedparser config entry."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING

import requests
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUDE_MATCH,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_MATCH,
    CONF_REMOVE_SUMMARY_IMAGE,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_TOPN,
    CONF_USER_AGENT,
    DEFAULT_DATE_FORMAT,
    DEFAULT_LOCAL_TIME,
    DEFAULT_REMOVE_SUMMARY_IMAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOPN,
    DOMAIN,
)
from .fetch import USER_AGENT
from .reader import FeedReader

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

type FeedEntries = list[dict[str, object]]
type FeedparserConfigEntry = ConfigEntry[FeedparserCoordinator]


def scan_interval_to_timedelta(value: object) -> timedelta:
    """Convert a stored scan interval ({'hours', 'minutes'}) to a timedelta."""
    if isinstance(value, timedelta):
        return value
    if isinstance(value, Mapping):
        hours = value.get("hours")
        minutes = value.get("minutes")
        total_minutes = (hours if isinstance(hours, int) else 0) * 60 + (
            minutes if isinstance(minutes, int) else 0
        )
        return timedelta(minutes=max(1, total_minutes))
    return DEFAULT_SCAN_INTERVAL


class FeedparserCoordinator(DataUpdateCoordinator[FeedEntries]):
    """Fetch and parse a feed on the configured interval."""

    config_entry: FeedparserConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FeedparserConfigEntry) -> None:
        """Initialize the coordinator from the entry's data and options."""
        config = {**entry.data, **entry.options}
        self.reader = FeedReader(
            feed=config[CONF_FEED_URL],
            name=config[CONF_NAME],
            date_format=config.get(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT),
            show_topn=config.get(CONF_SHOW_TOPN, DEFAULT_TOPN),
            remove_summary_image=config.get(
                CONF_REMOVE_SUMMARY_IMAGE,
                DEFAULT_REMOVE_SUMMARY_IMAGE,
            ),
            inclusions=config.get(CONF_INCLUSIONS, []),
            exclusions=config.get(CONF_EXCLUSIONS, []),
            local_time=config.get(CONF_LOCAL_TIME, DEFAULT_LOCAL_TIME),
            # an empty value means "use the integration default"
            user_agent=config.get(CONF_USER_AGENT) or USER_AGENT,
            match=config.get(CONF_MATCH) or "",
            exclude_match=config.get(CONF_EXCLUDE_MATCH) or "",
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {config[CONF_NAME]}",
            update_interval=scan_interval_to_timedelta(
                config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
        )

    async def _async_update_data(self) -> FeedEntries:
        """Fetch the feed in the executor and build its entries."""
        try:
            return await self.hass.async_add_executor_job(self.reader.read)
        except requests.RequestException as err:
            msg = f"Unable to fetch {self.reader.feed}: {err}"
            raise UpdateFailed(msg) from err
