import time
import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class AsyncTTLCache:
    """A simple in-memory TTL cache for async operations."""
    
    def __init__(self, ttl_seconds: int = 3600, max_size: int = 1000):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self._cache:
                return None
            
            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None
            
            return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        async with self._lock:
            # Simple eviction if max size reached
            if len(self._cache) >= self.max_size:
                # Remove the first item (oldest inserted)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            
            expiration = time.time() + (ttl or self.ttl)
            self._cache[key] = (value, expiration)

    async def clear(self):
        async with self._lock:
            self._cache.clear()

# Global instances for different retrieval sources
arxiv_cache = AsyncTTLCache(ttl_seconds=3600)  # 1 hour
openalex_cache = AsyncTTLCache(ttl_seconds=3600)
semantic_scholar_cache = AsyncTTLCache(ttl_seconds=3600)
tavily_cache = AsyncTTLCache(ttl_seconds=3600)
