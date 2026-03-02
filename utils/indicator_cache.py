"""
Indicator caching system for backtest performance optimization.

Avoids redundant calculations of technical indicators (KDJ, BBI, MA, etc.)
when multiple selectors need the same indicators for the same stock/date.

Expected performance improvement: 5-10x for backtests with multiple selectors.
"""

from typing import Dict, Tuple, Callable, Any, Optional
from datetime import datetime
import pandas as pd
import hashlib


class IndicatorCache:
    """
    LRU-style cache for technical indicators.

    Caches indicator values by (stock_code, date, indicator_name, params).
    Automatically evicts old entries to limit memory usage.
    """

    def __init__(self, max_entries: int = 100000):
        """
        Initialize indicator cache.

        Args:
            max_entries: Maximum number of cached entries before eviction starts
        """
        self.max_entries = max_entries
        self.cache: Dict[str, Any] = {}
        self.access_count: Dict[str, int] = {}  # Track access for LRU

    def _make_key(
        self,
        code: str,
        date: datetime,
        indicator_name: str,
        params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create cache key from stock code, date, indicator name, and params.

        Args:
            code: Stock code (e.g., "000001")
            date: Trading date
            indicator_name: Name of indicator (e.g., "KDJ", "BBI", "MA60")
            params: Additional parameters (e.g., {"n": 9} for KDJ-9)

        Returns:
            Cache key string
        """
        # Normalize date to string
        date_str = date.strftime("%Y-%m-%d") if isinstance(date, datetime) else str(date)

        # Include params in key if provided
        if params:
            # Sort params for consistent hashing
            params_str = str(sorted(params.items()))
            params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
            return f"{code}_{date_str}_{indicator_name}_{params_hash}"
        else:
            return f"{code}_{date_str}_{indicator_name}"

    def get_or_compute(
        self,
        code: str,
        date: datetime,
        indicator_name: str,
        compute_fn: Callable[[], Any],
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Get cached indicator value or compute and cache it.

        Args:
            code: Stock code
            date: Trading date (last date in historical window)
            indicator_name: Indicator name (e.g., "KDJ", "BBI")
            compute_fn: Function to compute indicator if not cached
                       Should return indicator value (scalar, Series, or DataFrame)
            params: Optional parameters for indicator computation

        Returns:
            Cached or computed indicator value

        Example:
            >>> cache = IndicatorCache()
            >>> def compute_kdj():
            ...     return Selector.compute_kdj(df)
            >>> kdj = cache.get_or_compute("000001", date, "KDJ", compute_kdj, {"n": 9})
        """
        key = self._make_key(code, date, indicator_name, params)

        # Cache hit
        if key in self.cache:
            self.access_count[key] = self.access_count.get(key, 0) + 1
            return self.cache[key]

        # Cache miss - compute value
        value = compute_fn()

        # Store in cache
        self.cache[key] = value
        self.access_count[key] = 1

        # Evict old entries if cache is too large
        if len(self.cache) > self.max_entries:
            self._evict_lru()

        return value

    def _evict_lru(self):
        """Evict least recently used entries (10% of cache)."""
        num_to_evict = max(1, len(self.cache) // 10)

        # Sort by access count (ascending)
        sorted_keys = sorted(self.access_count.items(), key=lambda x: x[1])

        # Remove least accessed
        for key, _ in sorted_keys[:num_to_evict]:
            if key in self.cache:
                del self.cache[key]
            if key in self.access_count:
                del self.access_count[key]

    def clear(self):
        """Clear all cached entries."""
        self.cache.clear()
        self.access_count.clear()

    def get_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache size, total accesses, etc.
        """
        total_accesses = sum(self.access_count.values())
        return {
            "size": len(self.cache),
            "total_accesses": total_accesses,
            "max_entries": self.max_entries,
        }


# Global cache instance (can be accessed across modules)
_global_cache: Optional[IndicatorCache] = None


def get_global_cache() -> IndicatorCache:
    """Get or create global indicator cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = IndicatorCache()
    return _global_cache


def clear_global_cache():
    """Clear global indicator cache."""
    global _global_cache
    if _global_cache:
        _global_cache.clear()
