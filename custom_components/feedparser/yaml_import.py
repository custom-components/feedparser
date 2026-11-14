"""Keep `sensor: - platform: feedparser` YAML in sync with config entries.

Each YAML sensor is backed by a config entry, so it shows up in the UI like any
other feed. configuration.yaml stays the source of truth for those entries: they
are updated from it on every start and removed when the YAML is removed. A user
can move a YAML feed to the UI from its options; after that the YAML is ignored.
Feeds added in the UI never touch configuration.yaml.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config import config_per_platform
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_NAME, CONF_PLATFORM
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import slugify

from .const import CONF_FEED_URL, CONF_MANAGED_BY_YAML, DOMAIN

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

# Raised by 1.0.0, which deprecated YAML; cleared on start.
ISSUE_DEPRECATED_YAML = "deprecated_yaml"

# Abort reasons of the import flow.
REASON_SYNCED = "already_configured"
REASON_MANAGED_IN_UI = "managed_in_ui"


def yaml_unique_id(name: str) -> str:
    """Return the config entry unique ID for the YAML sensor with this name.

    The name identifies a YAML sensor (it sets the entity ID), so the URL and
    every option can change in YAML without creating a new entry.
    """
    return f"yaml_{slugify(name)}"


def is_yaml_managed(entry: ConfigEntry) -> bool:
    """Return whether the entry follows configuration.yaml."""
    return entry.data.get(CONF_MANAGED_BY_YAML) is True


def _yaml_issue_suffix(name: str, feed_url: str) -> str:
    return slugify(f"{name} {feed_url}")


async def async_import_yaml_sensor(
    hass: HomeAssistant,
    config: Mapping[str, Any],
) -> None:
    """Create or update the config entry for one YAML sensor.

    Runs on every start. Raises a Repairs issue if the sensor could not be
    imported, or if the feed was moved to the UI but is still in the YAML.
    """
    import_data = {key: value for key, value in config.items() if key != CONF_PLATFORM}
    name = str(import_data.get(CONF_NAME, ""))
    feed_url = str(import_data.get(CONF_FEED_URL, ""))

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data=import_data,
    )

    if result["type"] is FlowResultType.CREATE_ENTRY:
        _LOGGER.info("Feed %s: Added from configuration.yaml", name)
        return

    reason = str(result.get("reason", "unknown"))
    if result["type"] is FlowResultType.ABORT and reason == REASON_SYNCED:
        return

    if result["type"] is FlowResultType.ABORT and reason == REASON_MANAGED_IN_UI:
        _LOGGER.warning(
            "Feed %s: This feed is managed in the UI, so its entry in "
            "configuration.yaml is ignored. Remove it from configuration.yaml",
            name,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"yaml_ignored_{_yaml_issue_suffix(name, feed_url)}",
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key="yaml_ignored",
            translation_placeholders={"name": name},
        )
        return

    _LOGGER.error("Feed %s: Could not import YAML configuration: %s", name, reason)
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"yaml_import_failed_{_yaml_issue_suffix(name, feed_url)}",
        is_fixable=False,
        issue_domain=DOMAIN,
        severity=ir.IssueSeverity.ERROR,
        translation_key="yaml_import_failed",
        translation_placeholders={"name": name, "reason": reason},
    )


def _yaml_unique_ids(config: ConfigType) -> set[str]:
    """Return the unique IDs of the feedparser sensors in configuration.yaml."""
    return {
        yaml_unique_id(str(item[CONF_NAME]))
        for platform, item in config_per_platform(config, "sensor")
        if platform == DOMAIN and isinstance(item, dict) and item.get(CONF_NAME)
    }


async def async_remove_stale_yaml_entries(
    hass: HomeAssistant,
    config: ConfigType,
) -> None:
    """Remove YAML-managed entries whose sensor is no longer in configuration.yaml.

    Runs before the sensor platform imports the current YAML. Entries created in
    the UI, moved to the UI, or imported by 1.0.0 are never removed here.
    """
    ir.async_delete_issue(hass, DOMAIN, ISSUE_DEPRECATED_YAML)

    in_yaml = _yaml_unique_ids(config)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if is_yaml_managed(entry) and entry.unique_id not in in_yaml:
            _LOGGER.info(
                "Feed %s: Removed because it is no longer in configuration.yaml",
                entry.title,
            )
            await hass.config_entries.async_remove(entry.entry_id)
