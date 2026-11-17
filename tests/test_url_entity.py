"""Tests for taking the feed URL from an entity's state (issue #60)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_integration import (
    get_state,
    import_yaml,
    options,
    setup_yaml,
    start_reconfigure,
    write_feed,
)

from custom_components.feedparser.compat import vol
from custom_components.feedparser.const import (
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_FEED_URL_ENTITY,
    CONF_INCLUSIONS,
    CONF_MANAGED_BY_YAML,
    DOMAIN,
    ENTRY_VERSION,
)
from custom_components.feedparser.sensor import PLATFORM_SCHEMA

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

URL_ENTITY = "input_text.feed_url"


async def submit_user_form(
    hass: HomeAssistant,
    name: str = "Test Feed",
    **source: str,
) -> ConfigFlowResult:
    """Run the setup form with a feed source (feed_url and/or feed_url_entity)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: name, **source} | options(),
    )
    await hass.async_block_till_done()
    return result


async def add_entity_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add and set up an entry that reads its URL from URL_ENTITY."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        title="Test Feed",
        data={CONF_NAME: "Test Feed", CONF_FEED_URL_ENTITY: URL_ENTITY},
        options={**options(), CONF_INCLUSIONS: ["title"], CONF_EXCLUSIONS: []},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def titles(hass: HomeAssistant) -> list[Any]:
    """Return the titles of the test sensor's entries."""
    return [e["title"] for e in get_state(hass).attributes["entries"]]


async def test_user_flow_with_url_entity(hass: HomeAssistant, tmp_path: Path) -> None:
    """A feed can be set up from an entity whose state is the URL."""
    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "a.xml", ["one", "two"]))

    result = await submit_user_form(hass, feed_url_entity=URL_ENTITY)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # only the entity is stored, never the URL it held at setup
    assert result["data"] == {CONF_NAME: "Test Feed", CONF_FEED_URL_ENTITY: URL_ENTITY}
    assert get_state(hass).state == "2"
    assert titles(hass) == ["one", "two"]


async def test_url_entity_can_hold_a_plain_path(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """An entity holding an absolute path reads it as a file:// URL."""
    write_feed(tmp_path / "a.xml", ["one"])
    hass.states.async_set(URL_ENTITY, str(tmp_path / "a.xml"))
    await add_entity_entry(hass)
    assert titles(hass) == ["one"]


async def test_url_change_refreshes_feed(hass: HomeAssistant, tmp_path: Path) -> None:
    """Changing the entity's value fetches the new feed right away."""
    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "a.xml", ["old"]))
    await add_entity_entry(hass)
    assert titles(hass) == ["old"]

    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "b.xml", ["new", "newer"]))
    await hass.async_block_till_done()

    assert titles(hass) == ["new", "newer"]


@pytest.mark.parametrize("value", [STATE_UNKNOWN, STATE_UNAVAILABLE])
async def test_url_entity_without_value_does_not_refresh(
    hass: HomeAssistant,
    tmp_path: Path,
    value: str,
) -> None:
    """The entity briefly losing its value (e.g. a reload) keeps the entries."""
    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "a.xml", ["one"]))
    entry = await add_entity_entry(hass)

    hass.states.async_set(URL_ENTITY, value)
    await hass.async_block_till_done()
    assert get_state(hass).state == "1"

    # the next poll can't fetch anything, so the sensor becomes unavailable
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert get_state(hass).state == STATE_UNAVAILABLE


async def test_url_entity_missing_at_setup_retries(hass: HomeAssistant) -> None:
    """If the URL entity doesn't exist yet at startup, setup is retried."""
    entry = await add_entity_entry(hass)
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_unload_stops_tracking(hass: HomeAssistant, tmp_path: Path) -> None:
    """After unloading, changes to the URL entity are ignored."""
    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "a.xml", ["one"]))
    entry = await add_entity_entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "b.xml", ["x", "y"]))
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.NOT_LOADED
    assert get_state(hass).state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("entity_value", "source", "errors"),
    [
        (None, {}, {"base": "url_or_entity"}),
        (
            None,
            {CONF_FEED_URL: "https://e.x/rss", CONF_FEED_URL_ENTITY: URL_ENTITY},
            {"base": "url_or_entity"},
        ),
        (
            None,
            {CONF_FEED_URL_ENTITY: URL_ENTITY},
            {CONF_FEED_URL_ENTITY: "entity_no_url"},
        ),
        (
            STATE_UNKNOWN,
            {CONF_FEED_URL_ENTITY: URL_ENTITY},
            {CONF_FEED_URL_ENTITY: "entity_no_url"},
        ),
        (
            "ftp://e.x/rss",
            {CONF_FEED_URL_ENTITY: URL_ENTITY},
            {CONF_FEED_URL_ENTITY: "entity_invalid_url"},
        ),
        (
            "page",
            {CONF_FEED_URL_ENTITY: URL_ENTITY},
            {CONF_FEED_URL_ENTITY: "invalid_feed"},
        ),
    ],
    ids=["neither", "both", "missing", "unknown", "bad_scheme", "not_a_feed"],
)
async def test_user_flow_source_errors(
    hass: HomeAssistant,
    tmp_path: Path,
    entity_value: str | None,
    source: dict[str, str],
    errors: dict[str, str],
) -> None:
    """Problems with the feed source are reported on the right field."""
    if entity_value == "page":
        page = tmp_path / "page.html"
        page.write_text("<html><body>hi</body></html>")
        entity_value = page.as_uri()
    if entity_value is not None:
        hass.states.async_set(URL_ENTITY, entity_value)

    result = await submit_user_form(hass, **source)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors


async def test_same_entity_and_name_is_rejected(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Two sensors on one URL entity need different names, like typed URLs."""
    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "a.xml", ["one"]))
    await add_entity_entry(hass)

    result = await submit_user_form(hass, "test feed", feed_url_entity=URL_ENTITY)
    assert result["errors"] == {CONF_NAME: "already_configured"}

    result = await submit_user_form(hass, "Other", feed_url_entity=URL_ENTITY)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_reconfigure_switches_between_url_and_entity(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Reconfigure can move a feed to a URL entity and back, keeping one source."""
    url = write_feed(tmp_path / "a.xml", ["typed"])
    hass.states.async_set(
        URL_ENTITY,
        write_feed(tmp_path / "b.xml", ["from", "entity"]),
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        title="Test Feed",
        data={CONF_NAME: "Test Feed", CONF_FEED_URL: url},
        options={**options(), CONF_INCLUSIONS: ["title"], CONF_EXCLUSIONS: []},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert titles(hass) == ["typed"]

    result = await start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Test Feed", CONF_FEED_URL_ENTITY: URL_ENTITY},
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data == {CONF_NAME: "Test Feed", CONF_FEED_URL_ENTITY: URL_ENTITY}
    assert titles(hass) == ["from", "entity"]

    result = await start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Test Feed", CONF_FEED_URL: url},
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data == {CONF_NAME: "Test Feed", CONF_FEED_URL: url}
    assert titles(hass) == ["typed"]

    # no longer tracking the entity
    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "c.xml", ["ignored"]))
    await hass.async_block_till_done()
    assert titles(hass) == ["typed"]


async def test_yaml_feed_with_url_entity(hass: HomeAssistant, tmp_path: Path) -> None:
    """A YAML sensor can read its URL from an entity and follows its changes."""
    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "a.xml", ["one"]))
    await setup_yaml(hass, {"name": "Test Feed", "feed_url_entity": URL_ENTITY})

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data == {
        CONF_NAME: "Test Feed",
        CONF_FEED_URL_ENTITY: URL_ENTITY,
        CONF_MANAGED_BY_YAML: True,
    }
    assert titles(hass) == ["one"]

    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "b.xml", ["two", "x"]))
    await hass.async_block_till_done()
    assert titles(hass) == ["two", "x"]


async def test_yaml_switches_from_url_to_entity(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Changing a YAML sensor from feed_url to feed_url_entity replaces the URL."""
    url = write_feed(tmp_path / "a.xml", ["typed"])
    hass.states.async_set(URL_ENTITY, write_feed(tmp_path / "b.xml", ["entity"]))
    await setup_yaml(hass, {"name": "Test Feed", "feed_url": url})
    assert titles(hass) == ["typed"]

    await import_yaml(hass, name="Test Feed", feed_url_entity=URL_ENTITY)

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert CONF_FEED_URL not in entry.data
    assert entry.data[CONF_FEED_URL_ENTITY] == URL_ENTITY
    assert titles(hass) == ["entity"]


@pytest.mark.parametrize(
    "source",
    [
        {},
        {"feed_url": "https://e.x/rss", "feed_url_entity": URL_ENTITY},
        {"feed_url_entity": "light.kitchen"},
        {"feed_url_entity": "not an entity"},
    ],
    ids=["neither", "both", "wrong_domain", "malformed"],
)
def test_yaml_schema_rejects_bad_source(source: dict[str, str]) -> None:
    """YAML needs exactly one of feed_url and an input_text/text/sensor entity."""
    with pytest.raises(vol.Invalid):
        PLATFORM_SCHEMA({"platform": DOMAIN, "name": "Test Feed", **source})
