import httpx
import logging

logger = logging.getLogger(__name__)

# Global shared client with connection pooling
# This avoids the overhead of opening/closing connections for every request
_client: httpx.AsyncClient | None = None

def get_http_client() -> httpx.AsyncClient:
    """Return the global shared HTTP client. Initialize if needed."""
    global _client
    if _client is None:
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
            keepalive_expiry=30.0
        )
        timeouts = httpx.Timeout(
            connect=5.0,
            read=30.0,
            write=10.0,
            pool=10.0
        )
        _client = httpx.AsyncClient(
            limits=limits,
            timeout=timeouts,
            follow_redirects=True
        )
        logger.info("Initialized shared httpx.AsyncClient with connection pooling.")
    return _client

async def close_http_client():
    """Close the global shared HTTP client."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("Shared httpx.AsyncClient closed.")
