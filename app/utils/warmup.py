import asyncio
import logging
import httpx
from app.core.http import get_http_client

logger = logging.getLogger(__name__)

# Per-endpoint minimal params so each API returns a valid (tiny) response.
_ENDPOINTS = [
    (
        "https://export.arxiv.org/api/query",
        {"search_query": "all:test", "start": "0", "max_results": "1"},
    ),
    (
        "https://api.semanticscholar.org/graph/v1/paper/search",
        {"query": "test", "limit": "1"},
    ),
    (
        "https://api.openalex.org/works",
        {"search": "test", "per-page": "1"},
    ),
]

_WARMUP_TIMEOUT = 20.0  # seconds – arXiv export mirror can be slow
_MAX_RETRIES = 2
_RETRY_DELAY = 2.0  # seconds


async def warm_up_apis():
    """Make lightweight GET requests to warm up TCP connections."""
    client = get_http_client()

    logger.info("Warming up external API connections...")

    async def _ping(url: str, params: dict):
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.get(url, params=params, timeout=_WARMUP_TIMEOUT)
                if attempt > 0:
                    logger.info("Connection to %s established after %d retries (HTTP %s).", url, attempt, resp.status_code)
                else:
                    logger.info("Connection to %s established (HTTP %s).", url, resp.status_code)
                return
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt < _MAX_RETRIES:
                    logger.warning("Warm-up attempt %d failed for %s: %s. Retrying in %ss...", attempt + 1, url, type(e).__name__, _RETRY_DELAY)
                    await asyncio.sleep(_RETRY_DELAY)
                else:
                    logger.warning("Warm-up failed for %s after %d retries: [%s] %r", url, _MAX_RETRIES, type(e).__name__, e)
            except Exception as e:
                # Non-fatal: the connection will be established on first real request.
                logger.warning("Warm-up failed for %s with unexpected error: [%s] %r", url, type(e).__name__, e)
                break

    await asyncio.gather(
        *[_ping(url, params) for url, params in _ENDPOINTS],
        return_exceptions=True,
    )
    logger.info("API warm-up completed.")
