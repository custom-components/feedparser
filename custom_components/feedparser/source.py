"""Where a feed's URL comes from: typed in, or the state of another entity.

Taking the URL from an entity (an ``input_text``, ``text`` or template ``sensor``
helper) lets users build it dynamically, e.g. with today's date, without this
integration rendering templates itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from yarl import URL

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

URL_SCHEMES = ("http", "https", "file")

# Entity domains whose state can hold a URL. Entity states are capped at 255
# characters by Home Assistant, so longer URLs can't be passed this way.
URL_ENTITY_DOMAINS = ["input_text", "text", "sensor"]


class FeedUrlError(Exception):
    """The URL entity can't provide a feed URL right now."""


class NoFeedUrlError(FeedUrlError):
    """The URL entity does not exist or has no value."""


class InvalidFeedUrlError(FeedUrlError):
    """The URL entity's value is not a supported feed URL."""


def is_supported_url(feed_url: str) -> bool:
    """Return whether the URL is well-formed with a supported scheme."""
    try:
        return URL(feed_url).scheme in URL_SCHEMES
    except ValueError:
        return False


def feed_url_from_entity(hass: HomeAssistant, entity_id: str) -> str:
    """Return the feed URL currently held in `entity_id`'s state.

    Must run in the event loop. Raises ``NoFeedUrlError`` if the entity is
    missing, unknown, unavailable or empty, and ``InvalidFeedUrlError`` if its
    value is not an http(s) or file URL.
    """
    state = hass.states.get(entity_id)
    if state is None:
        msg = f"{entity_id} does not exist"
        raise NoFeedUrlError(msg)
    url = state.state.strip()
    if not url or url in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        msg = f"{entity_id} has no URL (state: {state.state!r})"
        raise NoFeedUrlError(msg)
    if not is_supported_url(url):
        msg = f"{entity_id} does not hold a valid feed URL: {url!r}"
        raise InvalidFeedUrlError(msg)
    return url
