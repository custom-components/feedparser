"""Tests for the Feedparser config flow helpers."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import OptionsFlowWithReload

from custom_components.feedparser.compat import vol
from custom_components.feedparser.config_flow import (
    FeedparserConfigFlow,
    FeedparserOptionsFlow,
    _scan_interval_from_input,
    _schema_with_defaults,
    _user_agent_from_input,
)
from custom_components.feedparser.const import CONF_SCAN_INTERVAL, CONF_USER_AGENT
from custom_components.feedparser.fetch import USER_AGENT


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("  Custom/1.0 ", "Custom/1.0"),
    ],
)
def test_user_agent_from_input(value: str | None, expected: str) -> None:
    """Blank User-Agent input means "use the default"; other input is trimmed."""
    assert _user_agent_from_input({CONF_USER_AGENT: value}) == expected


@pytest.mark.parametrize("include_feed_identity", [True, False])
def test_schema_has_optional_user_agent(include_feed_identity: bool) -> None:
    """Both the setup and options forms offer an optional User-Agent."""
    schema = _schema_with_defaults(
        include_feed_identity=include_feed_identity,
        user_agent="Saved/1.0",
    )
    marker = next(key for key in schema.schema if key == CONF_USER_AGENT)
    assert isinstance(marker, vol.Optional)
    default = marker.default
    assert callable(default)
    assert default() == "Saved/1.0"


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [(None, USER_AGENT), ("Custom/1.0", "Custom/1.0")],
)
def test_validate_feed_url_sends_user_agent(
    tmp_path: Path,
    user_agent: str | None,
    expected: str,
) -> None:
    """Setup validation sends the same User-Agent the sensor will use."""
    feed = tmp_path / "feed.xml"
    feed.write_text('<rss version="2.0"><channel></channel></rss>', encoding="utf-8")
    args = (feed.as_uri(),) if user_agent is None else (feed.as_uri(), user_agent)

    with patch(
        "custom_components.feedparser.config_flow.fetch_feed",
        return_value=feed.read_bytes(),
    ) as fetch:
        FeedparserConfigFlow._validate_feed_url(*args)  # noqa: SLF001
    fetch.assert_called_once_with(feed.as_uri(), expected)
