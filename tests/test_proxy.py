"""Tests for fetching feeds through an HTTP or SOCKS proxy (issue #27)."""

from __future__ import annotations

import socket
import socketserver
import struct
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
import requests
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.feedparser import fetch
from custom_components.feedparser.const import (
    CONF_DATE_FORMAT,
    CONF_EXCLUSIONS,
    CONF_FEED_URL,
    CONF_INCLUSIONS,
    CONF_LOCAL_TIME,
    CONF_PROXY,
    CONF_REMOVE_SUMMARY_IMAGE,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_TOPN,
    CONF_USER_AGENT,
    DOMAIN,
    ENTRY_VERSION,
)
from custom_components.feedparser.reader import FeedReader

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

FEED = (
    b'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
    b"<title>T</title><link>https://e.x</link><description>T</description>"
    b"<item><title>through the proxy</title><link>https://e.x/1</link></item>"
    b"</channel></rss>"
)
# .invalid never resolves (RFC 6761), so these feeds are only reachable when the
# proxy, not this machine, handles the host name.
BLOCKED_URL = "http://blocked.invalid/rss"


# --- tiny local proxies -------------------------------------------------------


class _Server(socketserver.ThreadingTCPServer):
    # handler threads are joined on close so none outlive the test
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = True
    seen: list[str]


def _serve_feed(conn: socket.socket) -> None:
    """Answer one HTTP request on `conn` with the test feed."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            return
        data += chunk
    conn.sendall(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/rss+xml\r\n"
        b"Content-Length: " + str(len(FEED)).encode() + b"\r\n"
        b"Connection: close\r\n\r\n" + FEED,
    )


class _HttpProxyHandler(socketserver.BaseRequestHandler):
    """Forward-proxy stand-in: records the request line and serves the feed."""

    def handle(self) -> None:
        conn: socket.socket = self.request
        first = conn.recv(4096, socket.MSG_PEEK).split(b"\r\n", 1)[0]
        self.server.seen.append(first.decode())  # type: ignore[attr-defined]
        _serve_feed(conn)


class _Socks5Handler(socketserver.BaseRequestHandler):
    """Minimal SOCKS5 server (no auth, CONNECT only) that serves the feed itself.

    It records the requested destination instead of connecting to it.
    """

    def handle(self) -> None:
        conn: socket.socket = self.request
        _, n_methods = conn.recv(2)
        conn.recv(n_methods)
        conn.sendall(b"\x05\x00")  # no authentication
        _, cmd, _, atyp = conn.recv(4)
        if atyp == 3:  # domain name: resolved by the proxy (socks5h)  # noqa: PLR2004
            host = conn.recv(conn.recv(1)[0]).decode()
        else:  # IPv4: already resolved by the client (socks5)
            host = socket.inet_ntoa(conn.recv(4))
        (port,) = struct.unpack(">H", conn.recv(2))
        self.server.seen.append(f"{cmd} {host}:{port}")  # type: ignore[attr-defined]
        conn.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("127.0.0.1") + b"\0\0")
        _serve_feed(conn)


def _start(handler: type[socketserver.BaseRequestHandler]) -> Iterator[_Server]:
    server = _Server(("127.0.0.1", 0), handler)
    server.seen = []
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


# The Home Assistant test plugin blocks sockets; these fixtures need real ones on
# 127.0.0.1 to act as the proxy.
@pytest.fixture
def http_proxy(socket_enabled: None) -> Iterator[_Server]:  # noqa: ARG001
    """Run a local HTTP forward proxy."""
    yield from _start(_HttpProxyHandler)


@pytest.fixture
def socks_proxy(socket_enabled: None) -> Iterator[_Server]:  # noqa: ARG001
    """Run a local SOCKS5 proxy."""
    yield from _start(_Socks5Handler)


def _url(scheme: str, server: _Server) -> str:
    host, port = server.server_address[:2]
    return f"{scheme}://{host}:{port}"


# --- proxy URL helpers --------------------------------------------------------


@pytest.mark.parametrize(
    "proxy",
    [
        "http://proxy.local:3128",
        "https://proxy.local:443",
        "socks4://10.0.0.1:1080",
        "socks4a://10.0.0.1:1080",
        "socks5://10.0.0.1:1080",
        "SOCKS5H://10.0.0.1:1080/",
        "http://user:p%40ss@proxy.local:3128",
        "socks5h://[::1]:1080",
    ],
)
def test_valid_proxies(proxy: str) -> None:
    """Supported schemes with a host and port are accepted."""
    assert fetch.is_valid_proxy(proxy)


@pytest.mark.parametrize(
    "proxy",
    [
        "proxy.local:3128",  # no scheme
        "ftp://proxy.local:21",
        "socks5://10.0.0.1",  # no port
        "http://:3128",  # no host
        "http://proxy.local:99999",
        "http://proxy.local:3128/path",
        "http://proxy.local:3128?x=1",
        "http://[::1:3128",
    ],
)
def test_invalid_proxies(proxy: str) -> None:
    """Anything requests could not use as a proxy is rejected."""
    assert not fetch.is_valid_proxy(proxy)


def test_redact_proxy_hides_password() -> None:
    """Passwords are masked; URLs without one are unchanged."""
    assert (
        fetch.redact_proxy("http://bob:s3cret@proxy.local:3128")
        == "http://bob:***@proxy.local:3128"
    )
    assert fetch.redact_proxy("socks5h://h:1080") == "socks5h://h:1080"
    assert fetch.redact_text(
        "failed via http://bob:s3cret@p:1 ok",
        "http://bob:s3cret@p:1",
    ) == ("failed via http://bob:***@p:1 ok")
    assert fetch.redact_text("unchanged", "") == "unchanged"


def test_reader_repr_hides_proxy_password() -> None:
    """The reader's repr (used in debug logs) does not show the password."""
    reader = FeedReader(
        feed="https://e.x/rss",
        name="n",
        date_format="%Y",
        show_topn=1,
        remove_summary_image=False,
        inclusions=[],
        exclusions=[],
        local_time=False,
        proxy="http://bob:s3cret@proxy.local:3128",
    )
    assert "s3cret" not in repr(reader)
    assert "http://bob:***@proxy.local:3128" in repr(reader)


# --- fetching -----------------------------------------------------------------


def test_fetch_without_proxy_passes_none() -> None:
    """No proxy configured keeps requests' default (environment) behavior."""
    with patch.object(requests.Session, "get") as get:
        get.return_value.content = FEED
        fetch.fetch_feed("https://example.com/feed")
    assert get.call_args.kwargs["proxies"] is None


def test_fetch_passes_proxy_for_both_schemes() -> None:
    """The proxy is used for http and https feeds."""
    with patch.object(requests.Session, "get") as get:
        get.return_value.content = FEED
        fetch.fetch_feed("https://example.com/feed", proxy="socks5h://h:1080")
    assert get.call_args.kwargs["proxies"] == {
        "http": "socks5h://h:1080",
        "https": "socks5h://h:1080",
    }


def test_fetch_through_http_proxy(http_proxy: _Server) -> None:
    """A feed this machine cannot resolve is fetched through an HTTP proxy."""
    content = fetch.fetch_feed(BLOCKED_URL, proxy=_url("http", http_proxy))
    assert content == FEED
    assert http_proxy.seen == [f"GET {BLOCKED_URL} HTTP/1.1"]


def test_fetch_through_socks5h_proxy(socks_proxy: _Server) -> None:
    """socks5h hands the host name to the proxy, so blocked DNS does not matter."""
    content = fetch.fetch_feed(BLOCKED_URL, proxy=_url("socks5h", socks_proxy))
    assert content == FEED
    assert socks_proxy.seen == ["1 blocked.invalid:80"]


def test_file_feed_ignores_proxy(tmp_path: Path) -> None:
    """Local file:// feeds never go through the proxy."""
    feed = tmp_path / "feed.xml"
    feed.write_bytes(FEED)
    # an unusable proxy: the fetch would fail if it were used
    content = fetch.fetch_feed(feed.as_uri(), proxy="http://127.0.0.1:9")
    assert content == FEED


# --- Home Assistant flows -----------------------------------------------------

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _options(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        CONF_DATE_FORMAT: "%Y-%m-%d",
        CONF_LOCAL_TIME: False,
        CONF_SCAN_INTERVAL: {"hours": 1, "minutes": 0},
        CONF_SHOW_TOPN: 10,
        CONF_REMOVE_SUMMARY_IMAGE: False,
        CONF_INCLUSIONS: "title",
        CONF_EXCLUSIONS: "",
        CONF_USER_AGENT: "",
    } | overrides


async def _start_user_flow(hass: HomeAssistant, **overrides: Any) -> Any:  # noqa: ANN401
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Blocked Feed", CONF_FEED_URL: BLOCKED_URL} | _options(**overrides),
    )


async def test_user_flow_through_proxy(
    hass: HomeAssistant,
    http_proxy: _Server,
) -> None:
    """Setup validates through the proxy, and the sensor then polls through it."""
    proxy = _url("http", http_proxy)
    result = await _start_user_flow(hass, **{CONF_PROXY: f"  {proxy} "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_PROXY] == proxy
    await hass.async_block_till_done()

    state = hass.states.get("sensor.blocked_feed")
    assert state is not None
    assert state.state == "1"
    assert state.attributes["entries"][0]["title"] == "through the proxy"
    # one request to validate, one for the first refresh
    assert len(http_proxy.seen) == 2  # noqa: PLR2004


async def test_user_flow_rejects_invalid_proxy(hass: HomeAssistant) -> None:
    """A malformed proxy is reported on its field before anything is fetched."""
    with patch(
        "custom_components.feedparser.config_flow.fetch_feed",
    ) as fetch_feed:
        result = await _start_user_flow(hass, **{CONF_PROXY: "proxy.local:3128"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PROXY: "invalid_proxy"}
    fetch_feed.assert_not_called()


async def test_user_flow_unreachable_proxy(hass: HomeAssistant) -> None:
    """A proxy that cannot be reached shows the usual cannot_connect error."""
    proxy = "http://127.0.0.1:9"
    with patch(
        "custom_components.feedparser.config_flow.fetch_feed",
        side_effect=requests.exceptions.ProxyError("unreachable"),
    ) as fetch_feed:
        result = await _start_user_flow(hass, **{CONF_PROXY: proxy})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    fetch_feed.assert_called_once_with(BLOCKED_URL, fetch.USER_AGENT, proxy)


async def test_options_set_and_validate_proxy(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    """Options reject a malformed proxy and store a valid one."""
    feed = tmp_path / "feed.xml"
    feed.write_bytes(FEED)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        title="Test Feed",
        data={CONF_NAME: "Test Feed", CONF_FEED_URL: feed.as_uri()},
        options={**_options(), CONF_INCLUSIONS: ["title"], CONF_EXCLUSIONS: []},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _options(**{CONF_PROXY: "socks5://no-port"}),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PROXY: "invalid_proxy"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _options(**{CONF_PROXY: "socks5h://10.0.0.1:1080"}),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_PROXY] == "socks5h://10.0.0.1:1080"


async def test_yaml_proxy_is_imported(
    hass: HomeAssistant,
    socks_proxy: _Server,
) -> None:
    """`proxy` from YAML is stored and used by the sensor."""
    proxy = _url("socks5h", socks_proxy)
    assert await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": [
                {
                    "platform": DOMAIN,
                    "name": "Yaml Feed",
                    "feed_url": BLOCKED_URL,
                    "proxy": proxy,
                },
            ],
        },
    )
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.options[CONF_PROXY] == proxy
    state = hass.states.get("sensor.yaml_feed")
    assert state is not None
    assert state.state == "1"
    assert socks_proxy.seen == ["1 blocked.invalid:80"]


async def test_fetch_error_does_not_log_proxy_password(
    hass: HomeAssistant,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing poll's message has the proxy password masked."""
    proxy = "http://bob:s3cret@127.0.0.1:9"
    feed = tmp_path / "feed.xml"
    feed.write_bytes(FEED)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=ENTRY_VERSION,
        title="Test Feed",
        data={CONF_NAME: "Test Feed", CONF_FEED_URL: feed.as_uri()},
        options={
            **_options(),
            CONF_INCLUSIONS: ["title"],
            CONF_EXCLUSIONS: [],
            CONF_PROXY: proxy,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch(
        "custom_components.feedparser.reader.fetch_feed",
        side_effect=requests.exceptions.ProxyError(f"Cannot connect to {proxy}"),
    ):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    assert entry.runtime_data.last_update_success is False
    # the failure Home Assistant reports (log and entity) has the password masked
    reported = [
        r.getMessage() for r in caplog.records if "Unable to fetch" in r.getMessage()
    ]
    assert reported
    assert all("s3cret" not in m for m in reported)
    assert "http://bob:***@127.0.0.1:9" in reported[-1]
    error = entry.runtime_data.last_exception
    assert error is not None
    assert "s3cret" not in str(error)
