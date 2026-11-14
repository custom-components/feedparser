"""Feedparser sensor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .compat import vol
from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
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
)
from .coordinator import FeedEntries, FeedparserConfigEntry, FeedparserCoordinator
from .fetch import USER_AGENT
from .yaml_import import async_import_yaml_sensor

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import (
        AddConfigEntryEntitiesCallback,
        AddEntitiesCallback,
    )
    from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

COMPONENT_REPO = "https://github.com/custom-components/feedparser/"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_FEED_URL): cv.string,
        vol.Required(CONF_DATE_FORMAT, default=DEFAULT_DATE_FORMAT): cv.string,
        vol.Optional(CONF_LOCAL_TIME, default=DEFAULT_LOCAL_TIME): cv.boolean,
        vol.Optional(CONF_SHOW_TOPN, default=DEFAULT_TOPN): cv.positive_int,
        vol.Optional(
            CONF_REMOVE_SUMMARY_IMAGE,
            default=DEFAULT_REMOVE_SUMMARY_IMAGE,
        ): cv.boolean,
        vol.Optional(CONF_INCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_EXCLUSIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
        vol.Optional(CONF_USER_AGENT, default=USER_AGENT): cv.string,
    },
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,  # noqa: ARG001
    discovery_info: DiscoveryInfoType | None = None,  # noqa: ARG001
) -> None:
    """Import a legacy YAML sensor into a config entry.

    YAML configuration is deprecated: the sensor is created by the imported config
    entry (keeping the same entity ID), not by this platform.
    """
    await async_import_yaml_sensor(hass, config)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: FeedparserConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Feedparser sensor for a config entry."""
    async_add_entities([FeedParserSensor(entry.runtime_data)])


class FeedParserSensor(CoordinatorEntity[FeedparserCoordinator], SensorEntity):
    """Number of feed entries, with the entries themselves as an attribute."""

    # force update the entity since the number of feed entries does not necessarily
    # change, but we still want to update the extra_state_attributes
    _attr_force_update = True
    # The entries attribute regularly exceeds the recorder's 16 KiB attribute limit
    # and changes on every poll; keep it out of the database.
    _unrecorded_attributes = frozenset({"entries"})
    _attr_icon = "mdi:rss"
    _attr_attribution = "Data retrieved using RSS feedparser"

    def __init__(self, coordinator: FeedparserCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        # Not has_entity_name: keep `sensor.<name>` so imported YAML sensors keep
        # their entity IDs.
        self._attr_name = entry.data[CONF_NAME]
        self._attr_unique_id = entry.entry_id

    @property
    def feed_entries(self) -> FeedEntries:
        """Return the entries from the latest successful update."""
        return self.coordinator.data or []

    @property
    def native_value(self) -> int | None:
        """Return the number of entries, or None if the feed has none."""
        return len(self.feed_entries) or None

    @property
    def extra_state_attributes(self) -> dict[str, FeedEntries]:
        """Return the feed entries."""
        return {"entries": self.feed_entries}
