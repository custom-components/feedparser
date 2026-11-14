"""Tests for the Feedparser config flow helpers."""

from datetime import timedelta

import pytest
import voluptuous as vol
from homeassistant.config_entries import OptionsFlowWithReload

from custom_components.feedparser.config_flow import (
    FeedparserOptionsFlow,
    _scan_interval_from_input,
)
from custom_components.feedparser.const import CONF_SCAN_INTERVAL


def test_options_flow_reloads_config_entry() -> None:
    """Test that saving options uses Home Assistant automatic reload support."""
    assert issubclass(FeedparserOptionsFlow, OptionsFlowWithReload)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"hours": 0, "minutes": 1}, {"hours": 0, "minutes": 1}),
        ({"hours": 1, "minutes": 30}, {"hours": 1, "minutes": 30}),
        (timedelta(hours=2), {"hours": 2, "minutes": 0}),
    ],
)
def test_scan_interval_normalization(value: object, expected: dict[str, int]) -> None:
    """Test refresh interval normalization."""
    assert _scan_interval_from_input({CONF_SCAN_INTERVAL: value}) == expected


def test_scan_interval_rejects_zero() -> None:
    """Test that a zero refresh interval is rejected instead of silently changed."""
    with pytest.raises(vol.Invalid):
        _scan_interval_from_input(
            {CONF_SCAN_INTERVAL: {"hours": 0, "minutes": 0}},
        )
