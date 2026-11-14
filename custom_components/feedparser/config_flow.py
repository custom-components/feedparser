"""Config flow for Feedparser."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast

import feedparser  # type: ignore[import]
import requests
from homeassistant.config_entries import (
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
    DEFAULT_NAME,
    DEFAULT_REMOVE_SUMMARY_IMAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOPN,
    DOMAIN,
    ENTRY_VERSION,
)
from .fetch import USER_AGENT, fetch_feed


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
    }


def _user_agent_from_input(user_input: Mapping[str, object]) -> str:
    """Return the configured User-Agent, or "" to use the integration default."""
    return str(user_input.get(CONF_USER_AGENT) or "").strip()


def _schema_with_defaults(
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
        """Import a legacy YAML `sensor: - platform: feedparser` configuration.

        The feed is not fetched here: a feed that is down at startup must not stop
        the migration, and the entry setup retries on its own.
        """
        name = str(import_data[CONF_NAME]).strip()
        feed_url = str(import_data[CONF_FEED_URL]).strip()
        if self._is_configured(feed_url, name):
            # already imported on a previous start
            return cast(
                "ConfigFlowResult",
                self.async_abort(reason="already_configured"),
            )

        user_agent = str(import_data.get(CONF_USER_AGENT) or "").strip()
        options = {
            CONF_DATE_FORMAT: str(
                import_data.get(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT),
            ),
            CONF_LOCAL_TIME: bool(import_data.get(CONF_LOCAL_TIME, DEFAULT_LOCAL_TIME)),
            CONF_SCAN_INTERVAL: _scan_interval_to_dict(
                import_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
            CONF_SHOW_TOPN: _to_int(import_data.get(CONF_SHOW_TOPN), DEFAULT_TOPN),
            CONF_REMOVE_SUMMARY_IMAGE: bool(
                import_data.get(
                    CONF_REMOVE_SUMMARY_IMAGE,
                    DEFAULT_REMOVE_SUMMARY_IMAGE,
                ),
            ),
            CONF_INCLUSIONS: _as_str_list(import_data.get(CONF_INCLUSIONS)),
            CONF_EXCLUSIONS: _as_str_list(import_data.get(CONF_EXCLUSIONS)),
            # the YAML schema fills in the default agent; store "" for "default"
            CONF_USER_AGENT: "" if user_agent == USER_AGENT else user_agent,
        }
        return cast(
            "ConfigFlowResult",
            self.async_create_entry(
                title=name,
                data={CONF_NAME: name, CONF_FEED_URL: feed_url},
                options=options,
            ),
        )

    def _is_configured(self, feed_url: str, name: str) -> bool:
        """Return whether an entry with this feed URL and name already exists."""
        return any(
            entry.data.get(CONF_FEED_URL) == feed_url
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
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                options = _options_from_input(user_input)
            except vol.Invalid:
                errors[CONF_SCAN_INTERVAL] = "scan_interval_too_short"
            else:
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
        )
        return cast(
            "ConfigFlowResult",
            self.async_show_form(
                step_id="init",
                data_schema=data_schema,
                errors=errors,
            ),
        )
