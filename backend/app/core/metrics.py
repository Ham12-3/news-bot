from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import asyncio
from collections import defaultdict


@dataclass
class MetricsCollector:
    """Simple in-memory metrics collector for MVP.

    In production, replace with Prometheus or similar.
    """

    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    gauges: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    timestamps: dict[str, datetime] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def increment(self, name: str, value: int = 1, labels: dict | None = None) -> None:
        """Increment a counter."""
        key = self._make_key(name, labels)
        async with self._lock:
            self.counters[key] += value
            self.timestamps[key] = datetime.utcnow()

    async def set_gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        """Set a gauge value."""
        key = self._make_key(name, labels)
        async with self._lock:
            self.gauges[key] = value
            self.timestamps[key] = datetime.utcnow()

    async def get_counter(self, name: str, labels: dict | None = None) -> int:
        """Get current counter value."""
        key = self._make_key(name, labels)
        return self.counters.get(key, 0)

    async def get_gauge(self, name: str, labels: dict | None = None) -> float:
        """Get current gauge value."""
        key = self._make_key(name, labels)
        return self.gauges.get(key, 0.0)

    async def get_all(self) -> dict:
        """Get all metrics."""
        async with self._lock:
            return {
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "last_updated": {k: v.isoformat() for k, v in self.timestamps.items()}
            }

    def _make_key(self, name: str, labels: dict | None = None) -> str:
        """Create a unique key for a metric with labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# Global metrics instance
metrics = MetricsCollector()


# Convenience functions for common metrics
async def track_items_ingested(source: str, count: int = 1):
    await metrics.increment("items_ingested", count, {"source": source})


async def track_duplicates_removed(count: int = 1):
    await metrics.increment("duplicates_removed", count)


async def track_model_call(model: str, tokens: int = 0, cost: float = 0.0):
    await metrics.increment("model_calls", 1, {"model": model})
    await metrics.increment("model_tokens", tokens, {"model": model})
    # Track estimated cost
    current = await metrics.get_gauge("estimated_cost_usd")
    await metrics.set_gauge("estimated_cost_usd", current + cost)


async def track_embeddings_generated(count: int = 1):
    await metrics.increment("embeddings_generated", count)
