"""Import legacy YAML sensors into config entries."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_NAME, CONF_PLATFORM
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import slugify

from .const import CONF_FEED_URL, DOMAIN

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

ISSUE_DEPRECATED_YAML = "deprecated_yaml"


async def async_import_yaml_sensor(
    hass: HomeAssistant,
    config: Mapping[str, Any],
) -> None:
    """Import one `sensor: - platform: feedparser` entry and raise a Repairs issue.

    Runs on every start while the YAML is still present. Already-imported sensors
    abort as `already_configured`, which keeps this idempotent.
    """
    import_data = {key: value for key, value in config.items() if key != CONF_PLATFORM}
    name = str(import_data.get(CONF_NAME, ""))

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data=import_data,
    )

    if result["type"] is FlowResultType.CREATE_ENTRY or (
        result["type"] is FlowResultType.ABORT
        and result.get("reason") == "already_configured"
    ):
        if result["type"] is FlowResultType.CREATE_ENTRY:
            _LOGGER.warning(
                "Feed %s: Imported YAML configuration into the UI. Remove the "
                "`platform: feedparser` entry from configuration.yaml",
                name,
            )
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_DEPRECATED_YAML,
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_DEPRECATED_YAML,
        )
        return

    reason = str(result.get("reason", "unknown"))
    _LOGGER.error("Feed %s: Could not import YAML configuration: %s", name, reason)
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"yaml_import_failed_{slugify(f'{name} {import_data.get(CONF_FEED_URL, "")}')}",
        is_fixable=False,
        issue_domain=DOMAIN,
        severity=ir.IssueSeverity.ERROR,
        translation_key="yaml_import_failed",
        translation_placeholders={"name": name, "reason": reason},
    )
