"""Config flow for Feedparser."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, cast

import requests
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    FlowResult,
    OptionsFlow,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from requests_file import FileAdapter
from yarl import URL

from .const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_REMOVE_SUMMARY_IMAGE,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_TOPN,
    DEFAULT_DATE_FORMAT,
    DEFAULT_LOCAL_TIME,
    DEFAULT_NAME,
    DEFAULT_REMOVE_SUMMARY_IMAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOPN,
    DOMAIN,
    ENTRY_VERSION,
)


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
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            feed_url = str(user_input[CONF_FEED_URL]).strip()
            scan_interval: dict[str, int] | None = None

            try:
                scan_interval = _scan_interval_from_input(user_input)
            except vol.Invalid:
                errors[CONF_SCAN_INTERVAL] = "scan_interval_too_short"

            try:
                parsed_url = URL(feed_url)
            except ValueError:
                errors[CONF_FEED_URL] = "invalid_url"
            else:
                if parsed_url.scheme not in ("http", "https", "file"):
                    errors[CONF_FEED_URL] = "invalid_url"

            if not errors:
                await self.async_set_unique_id(feed_url)
                self._abort_if_unique_id_configured(error="already_configured")

                try:
                    await self.hass.async_add_executor_job(
                        self._validate_feed_url,
                        feed_url,
                    )
                except requests.RequestException:
                    errors["base"] = "cannot_connect"
                else:
                    assert scan_interval is not None
                    data = {
                        CONF_NAME: str(user_input[CONF_NAME]).strip(),
                        CONF_FEED_URL: feed_url,
                    }
                    options = {
                        CONF_DATE_FORMAT: str(user_input[CONF_DATE_FORMAT]).strip(),
                        CONF_LOCAL_TIME: bool(user_input[CONF_LOCAL_TIME]),
                        CONF_SCAN_INTERVAL: scan_interval,
                        CONF_SHOW_TOPN: _to_int(
                            user_input[CONF_SHOW_TOPN],
                            DEFAULT_TOPN,
                        ),
                        CONF_REMOVE_SUMMARY_IMAGE: bool(
                            user_input[CONF_REMOVE_SUMMARY_IMAGE],
                        ),
                        CONF_INCLUSIONS: _split_csv(
                            str(user_input[CONF_INCLUSIONS]).strip(),
                        ),
                        CONF_EXCLUSIONS: _split_csv(
                            str(user_input[CONF_EXCLUSIONS]).strip(),
                        ),
                    }
                    return cast(
                        "FlowResult",
                        self.async_create_entry(
                            title=data[CONF_NAME],
                            data=data,
                            options=options,
                        ),
                    )

        data_schema = _schema_with_defaults(
            include_feed_identity=True,
        )

        return cast(
            "FlowResult",
            self.async_show_form(
                step_id="user",
                data_schema=data_schema,
                errors=errors,
            ),
        )

    @staticmethod
    def _validate_feed_url(feed_url: str) -> None:
        """Validate that the URL can be fetched."""
        session = requests.Session()
        session.mount("file://", FileAdapter())
        response = session.get(feed_url, timeout=20)
        response.raise_for_status()


class FeedparserOptionsFlow(OptionsFlowWithReload):
    """Handle options for Feedparser."""

    async def async_step_init(
        self,
        user_input: Mapping[str, object] | None = None,
    ) -> FlowResult:
        """Manage Feedparser options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                scan_interval = _scan_interval_from_input(user_input)
            except vol.Invalid:
                errors[CONF_SCAN_INTERVAL] = "scan_interval_too_short"
            else:
                options = {
                    CONF_DATE_FORMAT: str(user_input[CONF_DATE_FORMAT]).strip(),
                    CONF_LOCAL_TIME: bool(user_input[CONF_LOCAL_TIME]),
                    CONF_SCAN_INTERVAL: scan_interval,
                    CONF_SHOW_TOPN: _to_int(user_input[CONF_SHOW_TOPN], DEFAULT_TOPN),
                    CONF_REMOVE_SUMMARY_IMAGE: bool(
                        user_input[CONF_REMOVE_SUMMARY_IMAGE],
                    ),
                    CONF_INCLUSIONS: _split_csv(
                        str(user_input[CONF_INCLUSIONS]).strip(),
                    ),
                    CONF_EXCLUSIONS: _split_csv(
                        str(user_input[CONF_EXCLUSIONS]).strip(),
                    ),
                }
                return cast(
                    "FlowResult",
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
        )
        return cast(
            "FlowResult",
            self.async_show_form(
                step_id="init",
                data_schema=data_schema,
                errors=errors,
            ),
        )
