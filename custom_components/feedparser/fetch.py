"""HTTP helpers shared by the Feedparser sensor and config flow."""

from __future__ import annotations

import requests
from requests_file import FileAdapter

from .const import VERSION

USER_AGENT = f"Home Assistant Feed-parser Integration {VERSION}"

# (connect, read) timeouts in seconds. Without a timeout a server that accepts the
# connection but never answers blocks an executor thread indefinitely.
REQUEST_TIMEOUT = (10, 30)


def fetch_feed(url: str, user_agent: str = USER_AGENT) -> bytes:
    """Download a feed and return its raw bytes.

    Raw bytes (not ``Response.text``) are returned so that feedparser can detect the
    document encoding from the XML prolog instead of relying on requests' guess.

    Raises ``requests.RequestException`` on network or HTTP errors.
    """
    with requests.Session() as session:
        session.mount("file://", FileAdapter())
        session.headers.update({"User-Agent": user_agent})
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.content
