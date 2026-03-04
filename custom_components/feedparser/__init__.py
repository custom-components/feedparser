"""The Feedparser integration."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_REMOVE_SUMMARY_IMAGE,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_TOPN,
    DEFAULT_DATE_FORMAT,
    DEFAULT_LOCAL_TIME,
    DEFAULT_REMOVE_SUMMARY_IMAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOPN,
    ENTRY_VERSION,
    OPTION_KEYS,
    PLATFORMS,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


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


async def async_setup(hass: HomeAssistant, config: dict) -> bool:  # noqa: ARG001
    """Set up Feedparser from YAML (legacy path)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Feedparser from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


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
