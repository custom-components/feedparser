"""HTTP helpers shared by the Feedparser sensor and config flow."""

from __future__ import annotations

from typing import NamedTuple
from urllib.parse import urlsplit

import requests
from requests_file import FileAdapter

from .const import VERSION

USER_AGENT = f"Home Assistant Feed-parser Integration {VERSION}"

# (connect, read) timeouts in seconds. Without a timeout a server that accepts the
# connection but never answers blocks an executor thread indefinitely.
REQUEST_TIMEOUT = (10, 30)

# Proxy URL schemes requests understands. The socks* schemes need PySocks;
# socks5h / socks4a also resolve the feed's host name through the proxy.
PROXY_SCHEMES = ("http", "https", "socks4", "socks4a", "socks5", "socks5h")


class FetchedFeed(NamedTuple):
    """A downloaded feed and the URL it was finally served from."""

    content: bytes
    # after redirects; feedparser resolves the feed's relative links against it
    url: str


def is_valid_proxy(proxy: str) -> bool:
    """Return True if `proxy` looks like scheme://[user:pass@]host:port."""
    try:
        parts = urlsplit(proxy)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme.lower() in PROXY_SCHEMES
        and bool(parts.hostname)
        and port is not None
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
    )


def redact_proxy(proxy: str) -> str:
    """Return `proxy` with any password replaced, safe to log."""
    try:
        parts = urlsplit(proxy)
        password = parts.password
    except ValueError:
        return "<invalid proxy>"
    if password is None:
        return proxy
    netloc = parts.netloc.replace(f":{password}@", ":***@", 1)
    return parts._replace(netloc=netloc).geturl()


def redact_text(text: str, proxy: str) -> str:
    """Remove the proxy password from `text` (e.g. an exception message)."""
    if not proxy:
        return text
    return text.replace(proxy, redact_proxy(proxy))


def fetch_feed(
    url: str,
    user_agent: str = USER_AGENT,
    proxy: str = "",
) -> FetchedFeed:
    """Download a feed and return its raw bytes and final URL.

    Raw bytes (not ``Response.text``) are returned so that feedparser can detect the
    document encoding from the XML prolog instead of relying on requests' guess.

    When `proxy` is set, http(s) requests go through it instead of any proxy set
    in the environment. ``file://`` feeds never use a proxy.

    Raises ``requests.RequestException`` on network or HTTP errors.
    """
    with requests.Session() as session:
        session.mount("file://", FileAdapter())
        session.headers.update({"User-Agent": user_agent})
        proxies = {"http": proxy, "https": proxy} if proxy else None
        # closing the response also closes the file a file:// URL opened
        with session.get(url, timeout=REQUEST_TIMEOUT, proxies=proxies) as response:
            response.raise_for_status()
            return FetchedFeed(response.content, response.url or url)
