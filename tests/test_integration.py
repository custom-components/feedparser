"""End-to-end tests running the integration inside a Home Assistant instance."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feedparser.const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_REMOVE_SUMMARY_IMAGE,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_TOPN,
    CONF_USER_AGENT,
    DOMAIN,
    ENTRY_VERSION,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def write_feed(path: Path, titles: list[str]) -> str:
    """Write a small RSS feed and return its file:// URL."""
    items = "".join(
        f"<item><title>{t}</title><link>https://e.x/{i}</link>"
        "<pubDate>Tue, 08 Sep 2026 12:00:00 GMT</pubDate></item>"
        for i, t in enumerate(titles)
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>T</title><link>https://e.x</link><description>T</description>{items}"
        "</channel></rss>",
        encoding="utf-8",
    )
    return path.absolute().as_uri()


def get_state(hass: HomeAssistant, entity_id: str = "sensor.test_feed") -> State:
    """Return an entity's state, failing the test if it does not exist."""
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} does not exist"
    return state


def options(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    """Return a full options form submission."""
    return {
        CONF_DATE_FORMAT: "%Y-%m-%d",
        CONF_LOCAL_TIME: False,
        CONF_SCAN_INTERVAL: {"hours": 1, "minutes": 0},
        CONF_SHOW_TOPN: 10,
        CONF_REMOVE_SUMMARY_IMAGE: False,
        CONF_INCLUSIONS: "title, link",
        CONF_EXCLUSIONS: "",
        CONF_USER_AGENT: "",
    } | overrides


def user_input(name: str, url: str, **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    """Return a full user-step form submission."""
    return {CONF_NAME: name, CONF_FEED_URL: url} | options(**overrides)


async def add_entry(hass: HomeAssistant, name: str, url: str) -> MockConfigEntry:
    """Add and set up a config entry for a feed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        title=name,
        data={CONF_NAME: name, CONF_FEED_URL: url},
        options={
            **options(),
            CONF_INCLUSIONS: ["title", "link"],
            CONF_EXCLUSIONS: [],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_user_flow_creates_working_sensor(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """The setup form creates an entry whose sensor exposes the feed entries."""
    url = write_feed(tmp_path / "feed.xml", ["one", "two", "three"])

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input("Test Feed", url),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_INCLUSIONS] == ["title", "link"]
    await hass.async_block_till_done()

    state = hass.states.get("sensor.test_feed")
    assert state is not None
    assert state.state == "3"
    assert [e["title"] for e in state.attributes["entries"]] == ["one", "two", "three"]


@pytest.mark.parametrize(
    ("make_url", "field", "error"),
    [
        (lambda _p: "ftp://example.com/feed", CONF_FEED_URL, "invalid_url"),
        (lambda p: (p / "missing.xml").as_uri(), "base", "cannot_connect"),
        (
            lambda p: (p / "page.html").as_uri(),
            CONF_FEED_URL,
            "invalid_feed",
        ),
    ],
    ids=["bad_scheme", "unreachable", "not_a_feed"],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    tmp_path: Path,
    make_url: Any,  # noqa: ANN401
    field: str,
    error: str,
) -> None:
    """Invalid, unreachable and non-feed URLs are reported on the form."""
    (tmp_path / "page.html").write_text("<html><body>hi</body></html>")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input("Test Feed", make_url(tmp_path)),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: error}


async def test_options_change_reloads_entry(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Saving options reloads the entry so the new settings take effect."""
    url = write_feed(tmp_path / "feed.xml", ["one", "two", "three"])
    entry = await add_entry(hass, "Test Feed", url)
    assert get_state(hass).state == "3"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        options(**{CONF_SHOW_TOPN: 1}),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_SHOW_TOPN] == 1
    assert get_state(hass).state == "1"


async def test_unload_entry(hass: HomeAssistant, tmp_path: Path) -> None:
    """Unloading an entry removes its sensor from service."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    entry = await add_entry(hass, "Test Feed", url)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert get_state(hass).state == "unavailable"
