"""The Feedparser integration."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
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
    ENTRY_VERSION,
    OPTION_KEYS,
    PLATFORMS,
)
from .coordinator import FeedparserConfigEntry, FeedparserCoordinator
from .yaml_import import async_remove_stale_yaml_entries

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType


CONFIG_SCHEMA = cv.platform_only_config_schema(DOMAIN)


def _normalize_list(value: object) -> list[str]:
    """Normalize option values to list[str]."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _normalize_scan_interval(value: object) -> dict[str, int]:
    """Normalize scan_interval to {'hours': int, 'minutes': int}."""
    if isinstance(value, timedelta):
        total_minutes = max(1, int(value.total_seconds() // 60))
        return {
            "hours": total_minutes // 60,
            "minutes": total_minutes % 60,
        }

    if isinstance(value, dict):
        raw_hours = value.get("hours")
        raw_minutes = value.get("minutes")

        hours = raw_hours if isinstance(raw_hours, int) else 0
        minutes = raw_minutes if isinstance(raw_minutes, int) else 0
        total_minutes = max(1, (hours * 60) + minutes)
        return {
            "hours": total_minutes // 60,
            "minutes": total_minutes % 60,
        }

    default_minutes = int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)
    return {
        "hours": default_minutes // 60,
        "minutes": default_minutes % 60,
    }


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Feedparser.

    The YAML sensors themselves are imported by the sensor platform; here, entries
    whose YAML sensor was removed are cleaned up.
    """
    await async_remove_stale_yaml_entries(hass, config)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FeedparserConfigEntry) -> bool:
    """Set up Feedparser from a config entry.

    The first refresh raises ConfigEntryNotReady if the feed cannot be fetched, so
    Home Assistant retries with backoff instead of slowing down startup.
    """
    coordinator = FeedparserCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FeedparserConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the latest schema."""
    if entry.version > ENTRY_VERSION:
        return False

    if entry.version < ENTRY_VERSION:
        data = dict(entry.data)
        options = dict(entry.options)

        merged = {**data, **options}
        normalized_options = {
            CONF_DATE_FORMAT: str(merged.get(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT)),
            CONF_LOCAL_TIME: bool(merged.get(CONF_LOCAL_TIME, DEFAULT_LOCAL_TIME)),
            CONF_SCAN_INTERVAL: _normalize_scan_interval(
                merged.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
            CONF_SHOW_TOPN: int(merged.get(CONF_SHOW_TOPN, DEFAULT_TOPN)),
            CONF_REMOVE_SUMMARY_IMAGE: bool(
                merged.get(
                    CONF_REMOVE_SUMMARY_IMAGE,
                    DEFAULT_REMOVE_SUMMARY_IMAGE,
                ),
            ),
            CONF_INCLUSIONS: _normalize_list(merged.get(CONF_INCLUSIONS, [])),
            CONF_EXCLUSIONS: _normalize_list(merged.get(CONF_EXCLUSIONS, [])),
            CONF_USER_AGENT: str(merged.get(CONF_USER_AGENT) or "").strip(),
        }

        for key in OPTION_KEYS:
            data.pop(key, None)

        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=normalized_options,
            version=ENTRY_VERSION,
        )

    return True
