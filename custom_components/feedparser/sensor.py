"""Feedparser sensor."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .compat import vol
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
)
from .coordinator import FeedEntries, FeedparserConfigEntry, FeedparserCoordinator
from .fetch import USER_AGENT, is_valid_proxy
from .reader import compile_filter
from .source import URL_ENTITY_DOMAINS
from .yaml_import import async_import_yaml_sensor

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import (
        AddConfigEntryEntitiesCallback,
        AddEntitiesCallback,
    )
    from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

COMPONENT_REPO = "https://github.com/custom-components/feedparser/"


def _valid_pattern(value: str) -> str:
    """Validate an entry filter pattern from YAML."""
    try:
        compile_filter(value)
    except re.error as err:
        msg = f"invalid regular expression: {err}"
        raise vol.Invalid(msg) from err
    return value


def _valid_proxy(value: str) -> str:
    """Validate a proxy URL from YAML ("" means no proxy)."""
    value = value.strip()
    if value and not is_valid_proxy(value):
        msg = "invalid proxy URL, expected scheme://[user:password@]host:port"
        raise vol.Invalid(msg)
    return value


# A feed's URL is either written out (feed_url) or read from an entity's state
# on every refresh (feed_url_entity), never both.
_FEED_SOURCE = "feed_source"

_SENSOR_SCHEMA = SENSOR_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Exclusive(CONF_FEED_URL, _FEED_SOURCE): cv.string,
        vol.Exclusive(CONF_FEED_URL_ENTITY, _FEED_SOURCE): cv.entity_domain(
            URL_ENTITY_DOMAINS,
        ),
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
        vol.Optional(CONF_MATCH, default=""): vol.All(cv.string, _valid_pattern),
        vol.Optional(CONF_EXCLUDE_MATCH, default=""): vol.All(
            cv.string,
            _valid_pattern,
        ),
        vol.Optional(CONF_PROXY, default=""): vol.All(cv.string, _valid_proxy),
    },
)

PLATFORM_SCHEMA = vol.All(
    cv.has_at_least_one_key(CONF_FEED_URL, CONF_FEED_URL_ENTITY),
    _SENSOR_SCHEMA,
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,  # noqa: ARG001
    discovery_info: DiscoveryInfoType | None = None,  # noqa: ARG001
) -> None:
    """Create or update the config entry backing a YAML sensor.

    The sensor is created by that config entry (so it also shows in the UI), not
    by this platform.
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
        # Not has_entity_name: keep `sensor.<name>` so YAML sensors keep the entity
        # IDs they had before they were backed by config entries.
        self._attr_name = entry.data[CONF_NAME]
        self._attr_unique_id = entry.entry_id

    @property
    def feed_entries(self) -> FeedEntries:
        """Return the entries from the latest successful update."""
        return self.coordinator.data or []

    @property
    def native_value(self) -> int | None:
        """Return the number of entries, 0 if the feed has none (or none match).

        None (``unknown``) only while no feed has been loaded yet; a feed that
        can't be fetched makes the entity ``unavailable`` instead.
        """
        if self.coordinator.data is None:
            return None
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, FeedEntries]:
        """Return the feed entries."""
        return {"entries": self.feed_entries}
