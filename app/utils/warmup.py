import asyncio
import logging
from app.core.http import get_http_client

logger = logging.getLogger(__name__)

async def warm_up_apis():
    """Make lightweight HEAD or empty GET requests to warm up TCP connections."""
    client = get_http_client()
    
    endpoints = [
        "https://export.arxiv.org/api/query",
        "https://api.semanticscholar.org/graph/v1/paper/search",
        "https://api.openalex.org/works"
    ]
    
    logger.info("Warming up external API connections...")
    
    async def _ping(url):
        try:
            # Most APIs allow a simple search query or just a HEAD request
            # We'll use a very small limit/page size to minimize data transfer
            await client.get(url, params={"max_results": 1, "limit": 1, "per-page": 1}, timeout=5.0)
            logger.info(f"Connection to {url} established.")
        except Exception as e:
            logger.warning(f"Warm-up failed for {url}: {e}")

    # Run in parallel
    await asyncio.gather(*[_ping(url) for url in endpoints], return_exceptions=True)
    logger.info("API warm-up completed.")
