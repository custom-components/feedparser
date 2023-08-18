"""Feed source class to be used in tests."""
import json
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from constants import (
    DATA_PATH,
    DATE_FORMAT,
    DEFAULT_EXCLUSIONS,
    DEFAULT_INCLUSIONS,
    TEST_HASS_PATH,
)

yaml.Dumper.ignore_aliases = lambda *args: True  # type: ignore[method-assign] # noqa: ARG005, E501


class FeedSource:
    """Feed source."""

    feed_storage = DATA_PATH

    def __init__(self: "FeedSource", data: dict) -> None:
        """Initialize."""
        self.raw = data

    def __repr__(self: "FeedSource") -> str:
        """Return representation."""
        return f"<FeedSource {self.name}>"

    @property
    def sensor_config(self: "FeedSource") -> "FeedConfig":
        """Return sensor_config."""
        return FeedConfig(self.raw["sensor_config"])

    @property
    def name(self: "FeedSource") -> str:
        """Return name."""
        return self.sensor_config.name

    @property
    def url(self: "FeedSource") -> str:
        """Return url."""
        return self.sensor_config.url

    @property
    def path(self: "FeedSource") -> Path:
        """Return path of the RSS feed file in a XML format."""
        return self.feed_storage / f"{self.name}.xml"

    @property
    def metadata_path(self: "FeedSource") -> Path:
        """Return metadata path."""
        return self.feed_storage / f"{self.name}.json"

    @cached_property
    def metadata(self: "FeedSource") -> dict:
        """Return metadata."""
        return json.loads(self.metadata_path.read_text())

    @property
    def text(self: "FeedSource") -> str:
        """Return text."""
        return self.path.read_text()

    @property
    def download_date(self: "FeedSource") -> datetime:
        """Return download date."""
        try:
            return datetime.fromisoformat(self.metadata["download_date"])
        except KeyError as ke:
            msg = (
                f"download_date not found in {self.metadata_path}. "
                "Is feed metadata downloaded?"
            )
            raise KeyError(
                msg,
            ) from ke

    @property
    def has_images(self: "FeedSource") -> bool:
        """Return has_images."""
        return self.metadata.get("has_images", False)

    @property
    def all_entries_have_images(self: "FeedSource") -> bool:
        """Return all_entries_have_images."""
        return self.metadata.get("all_entries_have_images", True)

    @property
    def has_unique_links(self: "FeedSource") -> bool:
        """Return has_unique_links."""
        return self.metadata.get("has_unique_links", True)

    @property
    def has_unique_titles(self: "FeedSource") -> bool:
        """Return has_unique_titles."""
        return self.metadata.get("has_unique_titles", True)

    @property
    def has_unique_images(self: "FeedSource") -> bool:
        """Return has_unique_images."""
        return self.metadata.get("has_unique_images", True)

    @property
    def _common_config(self: "FeedSource") -> dict[str, str | int | bool | list[str]]:
        """Return common config."""
        return {
            "name": self.name,
            "date_format": self.sensor_config.date_format,
            "show_topn": self.sensor_config.show_topn,
            "inclusions": self.sensor_config.inclusions,
            "exclusions": self.sensor_config.exclusions,
            "local_time": self.sensor_config.local_time,
        }

    @property
    def feed_parser_sensor_config(
        self: "FeedSource",
    ) -> dict[str, str | int | bool | list[str]]:
        """Generate sensor config for the FeedParserSensor constructor."""
        return self._common_config | {
            "feed": self.url,
            "scan_interval": self.sensor_config.scan_interval,
        }

    @property
    def sensor_config_local_feed(
        self: "FeedSource",
    ) -> dict[str, str | int | bool | list[str]]:
        """Gen. sensor config for the FeedParserSensor constructor with local feed."""
        return self.feed_parser_sensor_config | {"feed": self.path.absolute().as_uri()}

    @property
    def ha_config_entry(self: "FeedSource") -> dict[str, Any]:
        """Generate HA config entry."""
        return self._common_config | {
            "platform": "feedparser",
            "feed_url": self.url,
            "scan_interval": {"seconds": self.sensor_config.scan_interval},
        }

    @classmethod
    def gen_ha_sensors_yml_config(
        cls: type["FeedSource"],
        sensors: list["FeedSource"],
    ) -> str:
        """Generate HA "sensors" config."""
        return yaml.dump([s.ha_config_entry for s in sensors])

    @classmethod
    def create_ha_sensors_config_file(
        cls: type["FeedSource"],
        sensors: list["FeedSource"],
    ) -> None:
        """Create HA "sensors" config file."""
        sensors_yml = TEST_HASS_PATH / "sensors.yaml"
        sensors_yml.write_text(cls.gen_ha_sensors_yml_config(sensors))


class FeedConfig:
    """Feed config class to be used in tests."""

    def __init__(self: "FeedConfig", data: dict) -> None:
        """Initialize."""
        self.raw = data

    def __repr__(self: "FeedConfig") -> str:
        """Return representation."""
        return f"<FeedConfig {self.name}>"

    @property
    def name(self: "FeedConfig") -> str:
        """Return name."""
        return self.raw["name"]

    @property
    def url(self: "FeedConfig") -> str:
        """Return url."""
        return self.raw["feed_url"]

    @property
    def date_format(self: "FeedConfig") -> str:
        """Return date_format."""
        return self.raw.get("date_format", DATE_FORMAT)

    @property
    def show_topn(self: "FeedConfig") -> int:
        """Return show_topn."""
        return self.raw.get("show_topn", 9999)

    @property
    def scan_interval(self: "FeedConfig") -> int:
        """Return scan_interval in seconds."""
        return int(self.scan_interval_timedelta.total_seconds())

    @property
    def scan_interval_timedelta(self: "FeedConfig") -> timedelta:
        """Return scan_interval as timedelta."""
        if scan_interval := self.raw.get("scan_interval"):
            td = timedelta(**scan_interval)
        else:
            td = timedelta(hours=1)
        return td

    @property
    def inclusions(self: "FeedConfig") -> list:
        """Return inclusions."""
        return self.raw.get("inclusions", DEFAULT_INCLUSIONS)

    @property
    def exclusions(self: "FeedConfig") -> list:
        """Return exclusions."""
        return self.raw.get("exclusions", DEFAULT_EXCLUSIONS)

    @property
    def local_time(self: "FeedConfig") -> bool:
        """Return local_time."""
        return self.raw.get("local_time", False)
