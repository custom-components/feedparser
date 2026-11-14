"""End-to-end tests running the integration inside a Home Assistant instance."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
import requests
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.feedparser.const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUDE_MATCH,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_MANAGED_BY_YAML,
    CONF_MATCH,
    CONF_REMOVE_SUMMARY_IMAGE,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_TOPN,
    CONF_USER_AGENT,
    DOMAIN,
    ENTRY_VERSION,
)
from custom_components.feedparser.sensor import PLATFORM_SCHEMA
from custom_components.feedparser.yaml_import import (
    async_import_yaml_sensor,
    async_remove_stale_yaml_entries,
)

if TYPE_CHECKING:
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant, State

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

TOP_N = 2


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


async def test_user_flow_filters_entries(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """The setup form stores the filters and the sensor counts matching entries."""
    url = write_feed(tmp_path / "feed.xml", ["rain one", "snow", "rain two", "fog"])

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input(
            "Test Feed",
            url,
            **{CONF_MATCH: "rain|fog", CONF_EXCLUDE_MATCH: "two"},
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_MATCH] == "rain|fog"
    assert result["options"][CONF_EXCLUDE_MATCH] == "two"
    await hass.async_block_till_done()

    state = get_state(hass)
    assert state.state == "2"
    assert [e["title"] for e in state.attributes["entries"]] == ["rain one", "fog"]


@pytest.mark.parametrize("key", [CONF_MATCH, CONF_EXCLUDE_MATCH])
async def test_user_flow_rejects_invalid_pattern(
    hass: HomeAssistant,
    tmp_path: Path,
    key: str,
) -> None:
    """An invalid regular expression is reported on its field."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input("Test Feed", url, **{key: "(unclosed"}),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {key: "invalid_pattern"}


async def test_options_set_and_validate_filter(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Options reject an invalid pattern, then apply a valid one on reload."""
    url = write_feed(tmp_path / "feed.xml", ["rain", "snow", "fog"])
    entry = await add_entry(hass, "Test Feed", url)
    assert get_state(hass).state == "3"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        options(**{CONF_MATCH: "[bad"}),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_MATCH: "invalid_pattern"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        options(**{CONF_MATCH: "SNOW"}),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_MATCH] == "SNOW"
    state = get_state(hass)
    assert state.state == "1"
    assert [e["title"] for e in state.attributes["entries"]] == ["snow"]


async def test_yaml_filter_is_imported(hass: HomeAssistant, tmp_path: Path) -> None:
    """`match` and `exclude_match` from YAML are applied to the sensor."""
    url = write_feed(tmp_path / "feed.xml", ["rain", "snow", "fog"])
    await setup_yaml(
        hass,
        {"name": "Yaml Feed", "feed_url": url, "exclude_match": "rain|fog"},
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.options[CONF_MATCH] == ""
    assert entry.options[CONF_EXCLUDE_MATCH] == "rain|fog"
    assert get_state(hass, "sensor.yaml_feed").state == "1"


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


async def test_same_feed_with_different_name_is_allowed(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """The same URL can be added twice under different names, not the same one."""
    url = write_feed(tmp_path / "feed.xml", ["one", "two"])
    await add_entry(hass, "Test Feed", url)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input("test feed", url),  # same name, different case
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "already_configured"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input("Test Feed Titles", url, **{CONF_SHOW_TOPN: 1}),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert sorted(e.title for e in hass.config_entries.async_entries(DOMAIN)) == [
        "Test Feed",
        "Test Feed Titles",
    ]
    assert get_state(hass).state == "2"
    assert get_state(hass, "sensor.test_feed_titles").state == "1"


async def start_reconfigure(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> ConfigFlowResult:
    """Start a reconfigure flow for an entry and return its first form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return result


async def test_reconfigure_changes_name_and_url(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Reconfigure renames the sensor and switches its feed, keeping the entity ID."""
    old_url = write_feed(tmp_path / "old.xml", ["one"])
    new_url = write_feed(tmp_path / "new.xml", ["a", "b", "c"])
    entry = await add_entry(hass, "Test Feed", old_url)
    assert get_state(hass).state == "1"

    result = await start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: " Renamed Feed ", CONF_FEED_URL: f" {new_url} "},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert entry.title == "Renamed Feed"
    assert entry.data == {CONF_NAME: "Renamed Feed", CONF_FEED_URL: new_url}
    state = get_state(hass)  # same entity ID as before
    assert state.state == "3"
    assert state.attributes["friendly_name"] == "Renamed Feed"
    assert hass.states.get("sensor.renamed_feed") is None


async def test_reconfigure_keeps_own_name(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Changing only the URL is not blocked by the entry's own name."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    entry = await add_entry(hass, "Test Feed", url)

    result = await start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Test Feed", CONF_FEED_URL: url},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_rejects_duplicate(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Reconfigure can't give a feed the name another sensor of that feed uses."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    await add_entry(hass, "Test Feed", url)
    other = await add_entry(hass, "Other Feed", url)

    result = await start_reconfigure(hass, other)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "test feed", CONF_FEED_URL: url},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "already_configured"}
    assert other.data[CONF_NAME] == "Other Feed"


@pytest.mark.parametrize(
    ("make_url", "field", "error"),
    [
        (lambda _p: "ftp://example.com/feed", CONF_FEED_URL, "invalid_url"),
        (lambda p: (p / "missing.xml").as_uri(), "base", "cannot_connect"),
        (lambda p: (p / "page.html").as_uri(), CONF_FEED_URL, "invalid_feed"),
    ],
    ids=["bad_scheme", "unreachable", "not_a_feed"],
)
async def test_reconfigure_errors(
    hass: HomeAssistant,
    tmp_path: Path,
    make_url: Any,  # noqa: ANN401
    field: str,
    error: str,
) -> None:
    """A bad new URL is reported on the form and the entry is left unchanged."""
    (tmp_path / "page.html").write_text("<html><body>hi</body></html>")
    url = write_feed(tmp_path / "feed.xml", ["one"])
    entry = await add_entry(hass, "Test Feed", url)

    result = await start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Test Feed", CONF_FEED_URL: make_url(tmp_path)},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: error}
    assert entry.data[CONF_FEED_URL] == url


async def setup_yaml(hass: HomeAssistant, *sensors: dict[str, Any]) -> None:
    """Set up the sensor domain with YAML feedparser platforms."""
    assert await async_setup_component(
        hass,
        "sensor",
        {"sensor": [{"platform": DOMAIN, **sensor} for sensor in sensors]},
    )
    await hass.async_block_till_done()


async def test_reconfigure_yaml_feed(hass: HomeAssistant, tmp_path: Path) -> None:
    """A YAML feed is changed in YAML; once moved to the UI it can be reconfigured."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    await setup_yaml(hass, {"name": "Yaml Feed", "feed_url": url})
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "managed_in_yaml"

    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_MANAGED_BY_YAML: False},
    )
    result = await start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Renamed Feed", CONF_FEED_URL: url},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.title == "Renamed Feed"
    assert entry.data[CONF_MANAGED_BY_YAML] is False
    assert get_state(hass, "sensor.yaml_feed").attributes["friendly_name"] == (
        "Renamed Feed"
    )


async def test_yaml_is_imported(hass: HomeAssistant, tmp_path: Path) -> None:
    """A YAML sensor becomes a config entry with the same entity ID."""
    url = write_feed(tmp_path / "feed.xml", ["one", "two", "three"])
    await setup_yaml(
        hass,
        {
            "name": "Yaml Feed",
            "feed_url": url,
            "inclusions": ["title"],
            "show_topn": TOP_N,
            "scan_interval": {"minutes": 30},
        },
    )

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.source == config_entries.SOURCE_IMPORT
    assert entry.title == "Yaml Feed"
    assert entry.options[CONF_INCLUSIONS] == ["title"]
    assert entry.options[CONF_SHOW_TOPN] == TOP_N
    assert entry.options[CONF_SCAN_INTERVAL] == {"hours": 0, "minutes": 30}
    # the YAML default agent is stored as "use the default"
    assert entry.options[CONF_USER_AGENT] == ""

    state = get_state(hass, "sensor.yaml_feed")
    assert state.state == "2"
    assert [e["title"] for e in state.attributes["entries"]] == ["one", "two"]

    # managed by YAML, shown in the UI, and no longer deprecated
    assert entry.data[CONF_MANAGED_BY_YAML] is True
    assert entry.unique_id == "yaml_yaml_feed"
    assert not [domain for domain, _ in ir.async_get(hass).issues if domain == DOMAIN]


async def test_yaml_import_is_idempotent(hass: HomeAssistant, tmp_path: Path) -> None:
    """Importing again on the next start does not duplicate the entry."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    config = {"platform": DOMAIN, "name": "Yaml Feed", "feed_url": url}
    await setup_yaml(hass, {"name": "Yaml Feed", "feed_url": url})

    await async_import_yaml_sensor(hass, PLATFORM_SCHEMA(config))
    await hass.async_block_till_done()

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_yaml_same_feed_twice(hass: HomeAssistant, tmp_path: Path) -> None:
    """Two YAML sensors on one feed with different names both get imported."""
    url = write_feed(tmp_path / "feed.xml", ["one", "two"])
    await setup_yaml(
        hass,
        {"name": "All Fields", "feed_url": url},
        {"name": "Titles Only", "feed_url": url, "inclusions": ["title"]},
    )

    titles = sorted(e.title for e in hass.config_entries.async_entries(DOMAIN))
    assert titles == ["All Fields", "Titles Only"]
    assert get_state(hass, "sensor.all_fields").state == "2"
    assert get_state(hass, "sensor.titles_only").state == "2"


async def import_yaml(hass: HomeAssistant, **sensor: Any) -> None:  # noqa: ANN401
    """Run the YAML import for one sensor, as happens on every start."""
    config = PLATFORM_SCHEMA({"platform": DOMAIN, **sensor})
    await async_import_yaml_sensor(hass, config)
    await hass.async_block_till_done()


def yaml_issues(hass: HomeAssistant, translation_key: str) -> list[ir.IssueEntry]:
    """Return this integration's Repairs issues with a translation key."""
    return [
        issue
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.translation_key == translation_key
    ]


async def test_yaml_changes_are_applied(hass: HomeAssistant, tmp_path: Path) -> None:
    """Changing a YAML sensor updates and reloads its entry on the next start."""
    url = write_feed(tmp_path / "feed.xml", ["one", "two", "three"])
    other_url = write_feed(tmp_path / "other.xml", ["four"])
    await setup_yaml(hass, {"name": "Yaml Feed", "feed_url": url})
    assert get_state(hass, "sensor.yaml_feed").state == "3"
    entry_id = hass.config_entries.async_entries(DOMAIN)[0].entry_id

    await import_yaml(hass, name="Yaml Feed", feed_url=url, show_topn=TOP_N)
    assert get_state(hass, "sensor.yaml_feed").state == "2"

    # the name identifies the sensor, so a new URL updates the same entry
    await import_yaml(hass, name="Yaml Feed", feed_url=other_url)
    entries = hass.config_entries.async_entries(DOMAIN)
    assert [e.entry_id for e in entries] == [entry_id]
    assert entries[0].data[CONF_FEED_URL] == other_url
    assert get_state(hass, "sensor.yaml_feed").state == "1"


async def test_yaml_removed_removes_entry(hass: HomeAssistant, tmp_path: Path) -> None:
    """A YAML sensor removed from configuration.yaml is removed from the UI too."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    await setup_yaml(
        hass,
        {"name": "Kept", "feed_url": url},
        {"name": "Removed", "feed_url": url},
    )
    ui_entry = await add_entry(hass, "Ui Feed", url)
    assert len(hass.config_entries.async_entries(DOMAIN)) == 3  # noqa: PLR2004

    # the next start, with only "Kept" left in the YAML
    await async_remove_stale_yaml_entries(
        hass,
        {"sensor": [{"platform": DOMAIN, "name": "Kept", "feed_url": url}]},
    )
    await hass.async_block_till_done()

    titles = sorted(e.title for e in hass.config_entries.async_entries(DOMAIN))
    assert titles == ["Kept", ui_entry.title]
    assert hass.states.get("sensor.removed") is None


async def test_yaml_entry_options_offer_moving_to_ui(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """A YAML feed can be moved to the UI; after that the YAML is ignored."""
    url = write_feed(tmp_path / "feed.xml", ["one", "two", "three"])
    await setup_yaml(hass, {"name": "Yaml Feed", "feed_url": url})
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "yaml"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"next_step_id": "move_to_ui"},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_MANAGED_BY_YAML] is False

    # now it opens the normal options form
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    hass.config_entries.options.async_abort(result["flow_id"])

    # YAML still present on the next start: ignored, with a Repairs notice
    await async_remove_stale_yaml_entries(hass, {})
    await import_yaml(hass, name="Yaml Feed", feed_url=url, show_topn=TOP_N)
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert entry.options[CONF_SHOW_TOPN] != TOP_N
    issues = yaml_issues(hass, "yaml_ignored")
    assert len(issues) == 1
    assert issues[0].translation_placeholders == {"name": "Yaml Feed"}


async def test_yaml_relinks_entries_imported_by_1_0_0(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Entries imported by 1.0.0 follow the YAML again after upgrading."""
    url = write_feed(tmp_path / "feed.xml", ["one", "two", "three"])
    old = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        source=config_entries.SOURCE_IMPORT,
        title="Yaml Feed",
        data={CONF_NAME: "Yaml Feed", CONF_FEED_URL: url},
        options={**options(), CONF_INCLUSIONS: [], CONF_EXCLUSIONS: []},
    )
    old.add_to_hass(hass)
    # a 1.0.0 entry is not removed just because it is not linked yet
    await async_remove_stale_yaml_entries(hass, {})
    assert hass.config_entries.async_entries(DOMAIN) == [old]

    await setup_yaml(hass, {"name": "Yaml Feed", "feed_url": url, "show_topn": TOP_N})

    assert hass.config_entries.async_entries(DOMAIN) == [old]
    assert old.unique_id == "yaml_yaml_feed"
    assert old.data[CONF_MANAGED_BY_YAML] is True
    assert old.options[CONF_SHOW_TOPN] == TOP_N


async def test_yaml_duplicate_of_ui_entry_is_ignored(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """YAML never takes over a feed that was added in the UI."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    ui_entry = await add_entry(hass, "Same Feed", url)

    await import_yaml(hass, name="Same Feed", feed_url=url, show_topn=TOP_N)

    assert hass.config_entries.async_entries(DOMAIN) == [ui_entry]
    assert CONF_MANAGED_BY_YAML not in ui_entry.data
    assert len(yaml_issues(hass, "yaml_ignored")) == 1


async def test_deprecation_issue_from_1_0_0_is_cleared(hass: HomeAssistant) -> None:
    """The Repairs notice raised by 1.0.0 goes away after upgrading."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        "deprecated_yaml",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
    )
    assert await async_setup_component(hass, DOMAIN, {})
    assert ir.async_get(hass).async_get_issue(DOMAIN, "deprecated_yaml") is None


async def test_yaml_import_failure_raises_issue(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """A failed import raises an error-level Repairs issue naming the sensor."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    config = PLATFORM_SCHEMA({"platform": DOMAIN, "name": "Broken", "feed_url": url})

    with patch.object(
        hass.config_entries.flow,
        "async_init",
        return_value={"type": FlowResultType.ABORT, "reason": "unknown"},
    ):
        await async_import_yaml_sensor(hass, config)

    issues = [
        issue
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.translation_key == "yaml_import_failed"
    ]
    assert len(issues) == 1
    assert issues[0].severity is ir.IssueSeverity.ERROR
    assert issues[0].translation_placeholders == {"name": "Broken", "reason": "unknown"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_feed_down_at_setup_retries(hass: HomeAssistant, tmp_path: Path) -> None:
    """If the first fetch fails, the entry is retried instead of failing setup."""
    url = (tmp_path / "missing.xml").as_uri()
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        title="Test Feed",
        data={CONF_NAME: "Test Feed", CONF_FEED_URL: url},
        options={**options(), CONF_INCLUSIONS: ["title"], CONF_EXCLUSIONS: []},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_fetch_failure_marks_unavailable_and_recovers(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """A failed poll makes the sensor unavailable; the next success restores it."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    entry = await add_entry(hass, "Test Feed", url)
    coordinator = entry.runtime_data

    with patch(
        "custom_components.feedparser.reader.fetch_feed",
        side_effect=requests.ConnectTimeout("boom"),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert get_state(hass).state == "unavailable"

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert get_state(hass).state == "1"


async def test_polls_on_configured_interval(
    hass: HomeAssistant,
    tmp_path: Path,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The coordinator uses the entry's interval and picks up feed changes."""
    path = tmp_path / "feed.xml"
    url = write_feed(path, ["one"])
    entry = await add_entry(hass, "Test Feed", url)
    interval = timedelta(hours=1)
    assert entry.runtime_data.update_interval == interval

    write_feed(path, ["new", "old"])
    freezer.tick(interval)
    async_fire_time_changed(hass)
    # scheduled refreshes run as background tasks
    await hass.async_block_till_done(wait_background_tasks=True)

    state = get_state(hass)
    assert state.state == "2"
    assert [e["title"] for e in state.attributes["entries"]] == ["new", "old"]


async def test_entries_not_recorded(hass: HomeAssistant, tmp_path: Path) -> None:
    """The entries attribute is excluded from the recorder."""
    url = write_feed(tmp_path / "feed.xml", ["one"])
    await add_entry(hass, "Test Feed", url)
    entity = hass.data["entity_components"]["sensor"].get_entity("sensor.test_feed")
    assert "entries" in entity._state_info["unrecorded_attributes"]  # noqa: SLF001
