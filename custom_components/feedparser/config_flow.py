"""Config flow for Feedparser."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast

import feedparser  # type: ignore[import]
import requests
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from yarl import URL

from .compat import vol
from .const import (
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
    DEFAULT_DATE_FORMAT,
    DEFAULT_LOCAL_TIME,
    DEFAULT_NAME,
    DEFAULT_REMOVE_SUMMARY_IMAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOPN,
    DOMAIN,
    ENTRY_VERSION,
)
from .fetch import USER_AGENT, fetch_feed
from .reader import compile_filter
from .yaml_import import (
    REASON_MANAGED_IN_UI,
    REASON_SYNCED,
    is_yaml_managed,
    yaml_unique_id,
)


class InvalidFeedError(Exception):
    """Raised when a URL downloads fine but is not an RSS/Atom feed."""


def _split_csv(value: str) -> list[str]:
    """Split a comma-separated string into a normalized list."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _join_csv(value: object) -> str:
    """Convert list value to comma-separated text."""
    if not isinstance(value, list):
        return ""
    return ", ".join(item for item in value if isinstance(item, str))


def _to_int(value: object, default: int) -> int:
    """Convert arbitrary value to int with default fallback."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _scan_interval_to_dict(value: object) -> dict[str, int]:
    """Normalize scan interval to {'hours': int, 'minutes': int}."""
    if isinstance(value, timedelta):
        total_minutes = max(1, int(value.total_seconds() // 60))
        return {
            "hours": total_minutes // 60,
            "minutes": total_minutes % 60,
        }

    if isinstance(value, Mapping):
        days = _to_int(value.get("days"), 0)
        hours = _to_int(value.get("hours"), 0)
        minutes = _to_int(value.get("minutes"), 0)
        seconds = _to_int(value.get("seconds"), 0)
        total_minutes = max(
            1,
            (days * 24 * 60) + (hours * 60) + minutes + (seconds // 60),
        )
        return {
            "hours": total_minutes // 60,
            "minutes": total_minutes % 60,
        }

    default_minutes = int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)
    return {
        "hours": default_minutes // 60,
        "minutes": default_minutes % 60,
    }


def _scan_interval_from_input(user_input: Mapping[str, object]) -> dict[str, int]:
    """Build normalized scan interval dict from flow input."""
    value = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    if isinstance(value, timedelta):
        total_minutes = int(value.total_seconds() // 60)
    elif isinstance(value, Mapping):
        days = _to_int(value.get("days"), 0)
        hours = _to_int(value.get("hours"), 0)
        minutes = _to_int(value.get("minutes"), 0)
        seconds = _to_int(value.get("seconds"), 0)
        total_minutes = (days * 24 * 60) + (hours * 60) + minutes + (seconds // 60)
    else:
        total_minutes = int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)

    if total_minutes < 1:
        msg = "Refresh interval must be at least 1 minute"
        raise vol.Invalid(msg)

    return {
        "hours": total_minutes // 60,
        "minutes": total_minutes % 60,
    }


def _as_str_list(value: object) -> list[str]:
    """Return a list of non-empty strings from a YAML list or a CSV string."""
    if isinstance(value, str):
        return _split_csv(value)
    if isinstance(value, list):
        return [
            item.strip() for item in value if isinstance(item, str) and item.strip()
        ]
    return []


def _is_supported_url(feed_url: str) -> bool:
    """Return whether the URL is well-formed with a supported scheme."""
    try:
        return URL(feed_url).scheme in ("http", "https", "file")
    except ValueError:
        return False


def _options_from_input(user_input: Mapping[str, object]) -> dict[str, object]:
    """Build stored options from a setup/options form submission.

    Raises ``vol.Invalid`` if the refresh interval is shorter than a minute.
    """
    return {
        CONF_DATE_FORMAT: str(user_input[CONF_DATE_FORMAT]).strip(),
        CONF_LOCAL_TIME: bool(user_input[CONF_LOCAL_TIME]),
        CONF_SCAN_INTERVAL: _scan_interval_from_input(user_input),
        CONF_SHOW_TOPN: _to_int(user_input[CONF_SHOW_TOPN], DEFAULT_TOPN),
        CONF_REMOVE_SUMMARY_IMAGE: bool(user_input[CONF_REMOVE_SUMMARY_IMAGE]),
        CONF_INCLUSIONS: _split_csv(str(user_input.get(CONF_INCLUSIONS) or "")),
        CONF_EXCLUSIONS: _split_csv(str(user_input.get(CONF_EXCLUSIONS) or "")),
        CONF_USER_AGENT: _user_agent_from_input(user_input),
        CONF_MATCH: _pattern(user_input.get(CONF_MATCH)),
        CONF_EXCLUDE_MATCH: _pattern(user_input.get(CONF_EXCLUDE_MATCH)),
    }


def _pattern(value: object) -> str:
    """Return a filter pattern as typed, or "" if it is missing or blank.

    Inner and surrounding spaces can be part of a pattern, so they are kept.
    """
    return value if isinstance(value, str) and value.strip() else ""


def _pattern_errors(options: Mapping[str, object]) -> dict[str, str]:
    """Return form errors for filter patterns that are not valid regexes."""
    errors: dict[str, str] = {}
    for key in (CONF_MATCH, CONF_EXCLUDE_MATCH):
        try:
            compile_filter(str(options.get(key) or ""))
        except re.error:
            errors[key] = "invalid_pattern"
    return errors


def _options_from_import(import_data: Mapping[str, Any]) -> dict[str, object]:
    """Build stored options from a validated YAML sensor configuration."""
    user_agent = str(import_data.get(CONF_USER_AGENT) or "").strip()
    return {
        CONF_DATE_FORMAT: str(import_data.get(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT)),
        CONF_LOCAL_TIME: bool(import_data.get(CONF_LOCAL_TIME, DEFAULT_LOCAL_TIME)),
        CONF_SCAN_INTERVAL: _scan_interval_to_dict(
            import_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ),
        CONF_SHOW_TOPN: _to_int(import_data.get(CONF_SHOW_TOPN), DEFAULT_TOPN),
        CONF_REMOVE_SUMMARY_IMAGE: bool(
            import_data.get(CONF_REMOVE_SUMMARY_IMAGE, DEFAULT_REMOVE_SUMMARY_IMAGE),
        ),
        CONF_INCLUSIONS: _as_str_list(import_data.get(CONF_INCLUSIONS)),
        CONF_EXCLUSIONS: _as_str_list(import_data.get(CONF_EXCLUSIONS)),
        # the YAML schema fills in the default agent; store "" for "default"
        CONF_USER_AGENT: "" if user_agent == USER_AGENT else user_agent,
        CONF_MATCH: _pattern(import_data.get(CONF_MATCH)),
        CONF_EXCLUDE_MATCH: _pattern(import_data.get(CONF_EXCLUDE_MATCH)),
    }


def _user_agent_from_input(user_input: Mapping[str, object]) -> str:
    """Return the configured User-Agent, or "" to use the integration default."""
    return str(user_input.get(CONF_USER_AGENT) or "").strip()


def _schema_with_defaults(  # noqa: PLR0913 - one keyword per form field
    *,
    name: str = DEFAULT_NAME,
    feed_url: str = "",
    date_format: str = DEFAULT_DATE_FORMAT,
    local_time: bool = DEFAULT_LOCAL_TIME,
    show_topn: int = DEFAULT_TOPN,
    scan_interval: dict[str, int] | None = None,
    remove_summary_image: bool = DEFAULT_REMOVE_SUMMARY_IMAGE,
    inclusions: str = "",
    exclusions: str = "",
    user_agent: str = "",
    match: str = "",
    exclude_match: str = "",
    include_feed_identity: bool,
) -> vol.Schema:
    """Build schema for user/options forms."""
    normalized_scan_interval = scan_interval or _scan_interval_to_dict(
        DEFAULT_SCAN_INTERVAL,
    )
    schema: dict[Any, Any] = {
        vol.Required(CONF_DATE_FORMAT, default=date_format): str,
        vol.Required(CONF_LOCAL_TIME, default=local_time): bool,
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=normalized_scan_interval,
        ): selector.DurationSelector(
            selector.DurationSelectorConfig(
                allow_negative=False,
                enable_day=False,
                enable_second=False,
            ),
        ),
        vol.Required(CONF_SHOW_TOPN, default=show_topn): vol.All(
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                ),
            ),
            vol.Coerce(int),
        ),
        vol.Required(
            CONF_REMOVE_SUMMARY_IMAGE,
            default=remove_summary_image,
        ): bool,
        vol.Optional(CONF_INCLUSIONS, default=inclusions): str,
        vol.Optional(CONF_MATCH, default=match): str,
        vol.Optional(CONF_EXCLUDE_MATCH, default=exclude_match): str,
        vol.Optional(CONF_EXCLUSIONS, default=exclusions): str,
        vol.Optional(CONF_USER_AGENT, default=user_agent): str,
    }

    if include_feed_identity:
        schema = {
            vol.Required(CONF_NAME, default=name): str,
            vol.Required(CONF_FEED_URL, default=feed_url): str,
            **schema,
        }

    return vol.Schema(schema)


class FeedparserConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Feedparser."""

    VERSION = ENTRY_VERSION

    @staticmethod
    def async_get_options_flow(_config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return FeedparserOptionsFlow()

    async def async_step_user(
        self,
        user_input: Mapping[str, object] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            feed_url = str(user_input[CONF_FEED_URL]).strip()
            name = str(user_input[CONF_NAME]).strip()
            options: dict[str, object] = {}

            try:
                options = _options_from_input(user_input)
            except vol.Invalid:
                errors[CONF_SCAN_INTERVAL] = "scan_interval_too_short"
            else:
                errors.update(_pattern_errors(options))
            if not _is_supported_url(feed_url):
                errors[CONF_FEED_URL] = "invalid_url"
            elif self._is_configured(feed_url, name):
                # The same feed may be added more than once (e.g. with different
                # filters) as long as each sensor has its own name.
                errors[CONF_NAME] = "already_configured"

            if not errors:
                errors = await self._async_validate_feed(
                    feed_url,
                    str(options[CONF_USER_AGENT]) or USER_AGENT,
                )
            if not errors:
                return cast(
                    "ConfigFlowResult",
                    self.async_create_entry(
                        title=name,
                        data={CONF_NAME: name, CONF_FEED_URL: feed_url},
                        options=options,
                    ),
                )

        data_schema = _schema_with_defaults(
            include_feed_identity=True,
        )
        if user_input is not None:
            # keep what the user typed when showing errors
            data_schema = self.add_suggested_values_to_schema(data_schema, user_input)

        return cast(
            "ConfigFlowResult",
            self.async_show_form(
                step_id="user",
                data_schema=data_schema,
                errors=errors,
            ),
        )

    async def async_step_import(
        self,
        import_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Create or update the entry for a `sensor: - platform: feedparser` sensor.

        Runs on every start, so configuration.yaml stays the source of truth for
        YAML feeds. The feed is not fetched here: a feed that is down at startup
        must not stop the import, and the entry setup retries on its own.
        """
        name = str(import_data[CONF_NAME]).strip()
        feed_url = str(import_data[CONF_FEED_URL]).strip()
        unique_id = yaml_unique_id(name)
        data = {CONF_NAME: name, CONF_FEED_URL: feed_url, CONF_MANAGED_BY_YAML: True}
        options = _options_from_import(import_data)

        entry = self._yaml_entry(unique_id, feed_url, name)
        if entry is not None:
            if entry.data.get(CONF_MANAGED_BY_YAML) is False:
                # moved to the UI by the user: the YAML no longer applies
                return cast(
                    "ConfigFlowResult",
                    self.async_abort(reason=REASON_MANAGED_IN_UI),
                )
            return cast(
                "ConfigFlowResult",
                self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=name,
                    data=data,
                    options=options,
                    reason=REASON_SYNCED,
                    reload_even_if_entry_is_unchanged=False,
                ),
            )

        if self._is_configured(feed_url, name):
            # the same feed and name were added in the UI
            return cast(
                "ConfigFlowResult",
                self.async_abort(reason=REASON_MANAGED_IN_UI),
            )

        await self.async_set_unique_id(unique_id)
        return cast(
            "ConfigFlowResult",
            self.async_create_entry(title=name, data=data, options=options),
        )

    async def async_step_reconfigure(
        self,
        user_input: Mapping[str, object] | None = None,
    ) -> ConfigFlowResult:
        """Change the name and feed URL of an existing feed."""
        entry = self._get_reconfigure_entry()
        if is_yaml_managed(entry):
            # configuration.yaml would overwrite the change on the next start
            return cast(
                "ConfigFlowResult",
                self.async_abort(
                    reason="managed_in_yaml",
                    description_placeholders={"name": entry.title},
                ),
            )
        errors: dict[str, str] = {}

        if user_input is not None:
            feed_url = str(user_input[CONF_FEED_URL]).strip()
            name = str(user_input[CONF_NAME]).strip()

            if not _is_supported_url(feed_url):
                errors[CONF_FEED_URL] = "invalid_url"
            elif self._is_configured(feed_url, name, exclude_entry_id=entry.entry_id):
                errors[CONF_NAME] = "already_configured"

            if not errors:
                errors = await self._async_validate_feed(
                    feed_url,
                    str(entry.options.get(CONF_USER_AGENT) or "") or USER_AGENT,
                )
            if not errors:
                # The sensor's unique ID is the entry ID, so the entity ID and
                # history are kept; only its name and source change.
                return cast(
                    "ConfigFlowResult",
                    self.async_update_reload_and_abort(
                        entry,
                        title=name,
                        data_updates={CONF_NAME: name, CONF_FEED_URL: feed_url},
                    ),
                )

        data_schema = self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_FEED_URL): str,
                },
            ),
            user_input or entry.data,
        )
        return cast(
            "ConfigFlowResult",
            self.async_show_form(
                step_id="reconfigure",
                data_schema=data_schema,
                errors=errors,
            ),
        )

    def _yaml_entry(
        self,
        unique_id: str,
        feed_url: str,
        name: str,
    ) -> ConfigEntry | None:
        """Return the entry that belongs to a YAML sensor, if there is one.

        Entries imported by 1.0.0 have no unique ID; they are matched by feed URL
        and name, then linked to the YAML again.
        """
        for entry in self._async_current_entries(include_ignore=False):
            if entry.unique_id == unique_id:
                return entry
        for entry in self._async_current_entries(include_ignore=False):
            if (
                entry.source == SOURCE_IMPORT
                and entry.unique_id is None
                and CONF_MANAGED_BY_YAML not in entry.data
                and entry.data.get(CONF_FEED_URL) == feed_url
                and str(entry.data.get(CONF_NAME, "")).casefold() == name.casefold()
            ):
                return entry
        return None

    def _is_configured(
        self,
        feed_url: str,
        name: str,
        *,
        exclude_entry_id: str | None = None,
    ) -> bool:
        """Return whether another entry with this feed URL and name exists."""
        return any(
            entry.entry_id != exclude_entry_id
            and entry.data.get(CONF_FEED_URL) == feed_url
            and str(entry.data.get(CONF_NAME, "")).casefold() == name.casefold()
            for entry in self._async_current_entries(include_ignore=False)
        )

    async def _async_validate_feed(
        self,
        feed_url: str,
        user_agent: str,
    ) -> dict[str, str]:
        """Fetch the feed and return form errors (empty if it is usable)."""
        try:
            await self.hass.async_add_executor_job(
                self._validate_feed_url,
                feed_url,
                user_agent,
            )
        except requests.RequestException:
            return {"base": "cannot_connect"}
        except InvalidFeedError:
            return {CONF_FEED_URL: "invalid_feed"}
        return {}

    @staticmethod
    def _validate_feed_url(feed_url: str, user_agent: str = USER_AGENT) -> None:
        """Validate that the URL can be fetched and parses as a feed.

        Uses the same request (User-Agent, timeouts) as the sensor so a feed that
        passes here also works at runtime.
        """
        parsed = feedparser.parse(fetch_feed(feed_url, user_agent))
        # A real feed exposes a version (rss20, atom10, ...) even when it currently
        # has no entries; an HTML page or random document does not.
        if not parsed.get("version") and not parsed.get("entries"):
            raise InvalidFeedError


class FeedparserOptionsFlow(OptionsFlowWithReload):
    """Handle options for Feedparser."""

    async def async_step_init(
        self,
        user_input: Mapping[str, object] | None = None,
    ) -> ConfigFlowResult:
        """Manage Feedparser options."""
        if is_yaml_managed(self.config_entry):
            return await self.async_step_yaml()

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                options = _options_from_input(user_input)
            except vol.Invalid:
                errors[CONF_SCAN_INTERVAL] = "scan_interval_too_short"
            else:
                errors = _pattern_errors(options)
            if not errors:
                return cast(
                    "ConfigFlowResult",
                    self.async_create_entry(title="", data=options),
                )

        merged = {**self.config_entry.data, **self.config_entry.options}
        data_schema = _schema_with_defaults(
            include_feed_identity=False,
            date_format=str(merged.get(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT)),
            local_time=bool(merged.get(CONF_LOCAL_TIME, DEFAULT_LOCAL_TIME)),
            scan_interval=_scan_interval_to_dict(
                merged.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
            show_topn=int(merged.get(CONF_SHOW_TOPN, DEFAULT_TOPN)),
            remove_summary_image=bool(
                merged.get(
                    CONF_REMOVE_SUMMARY_IMAGE,
                    DEFAULT_REMOVE_SUMMARY_IMAGE,
                ),
            ),
            inclusions=_join_csv(merged.get(CONF_INCLUSIONS, [])),
            exclusions=_join_csv(merged.get(CONF_EXCLUSIONS, [])),
            user_agent=str(merged.get(CONF_USER_AGENT) or ""),
            match=str(merged.get(CONF_MATCH) or ""),
            exclude_match=str(merged.get(CONF_EXCLUDE_MATCH) or ""),
        )
        if user_input is not None:
            # keep what the user typed when showing errors
            data_schema = self.add_suggested_values_to_schema(data_schema, user_input)
        return cast(
            "ConfigFlowResult",
            self.async_show_form(
                step_id="init",
                data_schema=data_schema,
                errors=errors,
            ),
        )

    async def async_step_yaml(
        self,
        _user_input: Mapping[str, object] | None = None,
    ) -> ConfigFlowResult:
        """Explain that the feed is managed in YAML and offer to move it to the UI."""
        return cast(
            "ConfigFlowResult",
            self.async_show_menu(
                step_id="yaml",
                menu_options=["move_to_ui"],
                description_placeholders={"name": self.config_entry.title},
            ),
        )

    async def async_step_move_to_ui(
        self,
        user_input: Mapping[str, object] | None = None,
    ) -> ConfigFlowResult:
        """Stop following configuration.yaml for this feed."""
        if user_input is None:
            return cast(
                "ConfigFlowResult",
                self.async_show_form(
                    step_id="move_to_ui",
                    data_schema=vol.Schema({}),
                    description_placeholders={"name": self.config_entry.title},
                ),
            )

        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_MANAGED_BY_YAML: False},
        )
        return cast(
            "ConfigFlowResult",
            self.async_create_entry(title="", data=dict(self.config_entry.options)),
        )
