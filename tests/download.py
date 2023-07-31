"""Download RSS feeds for testing."""
import asyncio
import json
from datetime import datetime

import aiohttp
from constants import TEST_FEEDS
from feedsource import FeedSource

base_date = datetime.now()


async def run_feed(feed: FeedSource) -> None:
    """Download feed and store its metadata and content."""
    async with aiohttp.ClientSession() as session:
        async with session.get(feed.url) as response:
            text = await response.text()
    metadata = feed.raw
    metadata["download_date"] = base_date.isoformat()
    feed.metadata_path.write_text(json.dumps(metadata, indent=4) + "\n")
    feed.path.write_text(text)


async def run_all(feeds: list[FeedSource]) -> None:
    """Gather all feeds."""
    await asyncio.gather(*[run_feed(feed) for feed in feeds])


if __name__ == "__main__":
    asyncio.run(run_all([FeedSource(f) for f in TEST_FEEDS]))
