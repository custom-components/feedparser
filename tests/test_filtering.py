"""Tests for the `match` / `exclude_match` entry filters."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from reader_harness import ReaderHarness

from custom_components.feedparser.compat import vol
from custom_components.feedparser.reader import FeedReader, compile_filter
from custom_components.feedparser.sensor import PLATFORM_SCHEMA

if TYPE_CHECKING:
    from pathlib import Path

# Shaped like the Met Office warnings feed from issue #61.
WARNINGS = [
    (
        "Yellow warning of thunderstorm affecting East Midlands",
        "Yellow warning of thunderstorm affecting East Midlands: Derby, Leicester, "
        "Leicestershire, Nottingham valid from 0800 Wed 02 Aug to 1900 Wed 02 Aug",
    ),
    (
        "Yellow warning of rain affecting East Midlands",
        "Yellow warning of rain affecting East Midlands: Lincolnshire, "
        "Nottinghamshire valid from 1000 Wed 02 Aug to 1900 Wed 02 Aug",
    ),
    (
        "Amber warning of snow affecting East Midlands",
        "Amber warning of snow affecting East Midlands: Rutland valid from 0600 "
        "Thu 03 Aug to 1200 Thu 03 Aug",
    ),
]


def _write_feed(path: Path) -> str:
    items = "".join(
        f"<item><title>{title}</title><description>{desc}</description>"
        f"<link>https://e.x/{i}</link></item>"
        for i, (title, desc) in enumerate(WARNINGS)
    )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>T</title><link>https://e.x</link><description>T</description>{items}"
        "</channel></rss>",
        encoding="utf-8",
    )
    return path.absolute().as_uri()


def _titles(
    tmp_path: Path,
    *,
    match: str = "",
    exclude_match: str = "",
    show_topn: int = 10,
    inclusions: list[str] | None = None,
) -> list[object]:
    sensor = ReaderHarness(
        feed=_write_feed(tmp_path / "feed.xml"),
        name="test",
        date_format="%Y-%m-%d",
        local_time=False,
        show_topn=show_topn,
        remove_summary_image=False,
        inclusions=inclusions or ["title"],
        exclusions=[],
        match=match,
        exclude_match=exclude_match,
    )
    sensor.update()
    return [entry["title"] for entry in sensor.feed_entries]


def test_no_filter_keeps_everything(tmp_path: Path) -> None:
    """Without patterns every entry is kept."""
    assert len(_titles(tmp_path)) == len(WARNINGS)


def test_match_searches_summary_ignoring_case(tmp_path: Path) -> None:
    """A pattern found only in the description keeps that entry (issue #61)."""
    assert _titles(tmp_path, match="leicester") == [WARNINGS[0][0]]


def test_match_searches_title(tmp_path: Path) -> None:
    """A pattern found in the title keeps that entry."""
    assert _titles(tmp_path, match="rain|snow") == [WARNINGS[1][0], WARNINGS[2][0]]


def test_match_works_when_summary_not_included(tmp_path: Path) -> None:
    """Filtering uses the feed's summary even if it is not kept on the entry."""
    assert _titles(tmp_path, match="Rutland", inclusions=["title"]) == [
        WARNINGS[2][0],
    ]


def test_exclude_match(tmp_path: Path) -> None:
    """Entries matching the exclude pattern are removed."""
    assert _titles(tmp_path, exclude_match="^yellow") == [WARNINGS[2][0]]


def test_match_and_exclude_match_combine(tmp_path: Path) -> None:
    """An entry must match `match` and not match `exclude_match`."""
    assert _titles(tmp_path, match="Nottingham", exclude_match="rain") == [
        WARNINGS[0][0],
    ]


def test_filter_runs_before_show_topn(tmp_path: Path) -> None:
    """`show_topn` counts matching entries, not the feed's first entries."""
    assert _titles(tmp_path, match="snow", show_topn=1) == [WARNINGS[2][0]]


def test_no_match_gives_no_entries(tmp_path: Path) -> None:
    """When nothing matches the sensor has no entries."""
    assert _titles(tmp_path, match="Cornwall") == []


@pytest.mark.parametrize("pattern", ["", "   "])
def test_blank_pattern_is_no_filter(pattern: str) -> None:
    """A blank pattern means "no filter"."""
    assert compile_filter(pattern) is None


def test_reader_rejects_invalid_pattern() -> None:
    """An invalid pattern raises instead of silently keeping everything."""
    with pytest.raises(re.error):
        FeedReader(
            feed="file:///x",
            name="x",
            date_format="%Y",
            show_topn=1,
            remove_summary_image=False,
            inclusions=[],
            exclusions=[],
            local_time=False,
            match="(unclosed",
        )


def test_yaml_schema_accepts_patterns() -> None:
    """YAML takes `match` and `exclude_match`, defaulting to no filter."""
    base = {"platform": "feedparser", "name": "x", "feed_url": "https://e.x/rss"}
    assert PLATFORM_SCHEMA(base)["match"] == ""
    assert PLATFORM_SCHEMA(base)["exclude_match"] == ""
    config = PLATFORM_SCHEMA({**base, "match": "Leicester", "exclude_match": "rain"})
    assert config["match"] == "Leicester"
    assert config["exclude_match"] == "rain"


@pytest.mark.parametrize("key", ["match", "exclude_match"])
def test_yaml_schema_rejects_invalid_pattern(key: str) -> None:
    """An invalid YAML pattern fails config validation."""
    base = {"platform": "feedparser", "name": "x", "feed_url": "https://e.x/rss"}
    with pytest.raises(vol.Invalid, match="invalid regular expression"):
        PLATFORM_SCHEMA({**base, key: "(unclosed"})
