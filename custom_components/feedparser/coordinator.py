"""Polling coordinator for one Feedparser config entry."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import TYPE_CHECKING

import requests
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUDE_MATCH,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_FEED_URL_ENTITY,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_MATCH,
    CONF_PROXY,
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
from .fetch import USER_AGENT, redact_text
from .reader import FeedReader
from .source import FeedUrlError, feed_url_from_entity

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
        # set when the feed URL is read from this entity's state on every poll
        self.url_entity: str | None = config.get(CONF_FEED_URL_ENTITY) or None
        self.reader = FeedReader(
            feed=config.get(CONF_FEED_URL) or "",
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
            proxy=config.get(CONF_PROXY) or "",
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

    def feed_url(self) -> str:
        """Return the URL to fetch now, reading the URL entity if there is one.

        Raises ``UpdateFailed`` if the URL entity has no usable URL.
        """
        if self.url_entity is None:
            return self.reader.feed
        try:
            return feed_url_from_entity(self.hass, self.url_entity)
        except FeedUrlError as err:
            msg = f"No feed URL to fetch: {err}"
            raise UpdateFailed(msg) from err

    async def _async_update_data(self) -> FeedEntries:
        """Fetch the feed in the executor and build its entries."""
        url = self.feed_url()
        try:
            return await self.hass.async_add_executor_job(self.reader.read, url)
        except requests.RequestException as err:
            # the error may quote the proxy URL; never log its password
            reason = redact_text(str(err), self.reader.proxy)
            msg = f"Unable to fetch {url}: {reason}"
            raise UpdateFailed(msg) from err

    @callback
    def async_track_url_entity(self) -> Callable[[], None] | None:
        """Refresh as soon as the URL entity's value changes.

        Returns the function that stops tracking, or None without a URL entity.
        """
        if self.url_entity is None:
            return None

        @callback
        def _url_changed(event: Event[EventStateChangedData]) -> None:
            new_state = event.data["new_state"]
            old_state = event.data["old_state"]
            if new_state is None or new_state.state in (
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            ):
                # e.g. the helper reloading; keep the entries until the next poll
                return
            if old_state is not None and old_state.state == new_state.state:
                return  # only an attribute changed
            self.config_entry.async_create_task(
                self.hass,
                self.async_request_refresh(),
                f"{DOMAIN} feed URL changed",
            )

        return async_track_state_change_event(
            self.hass,
            self.url_entity,
            _url_changed,
        )
