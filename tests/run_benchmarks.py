"""Small local benchmark for archive inserts and rendered search responses."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from statistics import mean, median
from time import perf_counter

from src.app import create_app
from src.database import create_entry


def run_benchmarks(entry_count: int = 1_000, request_count: int = 100) -> dict[str, float | int]:
    if entry_count < 1 or request_count < 1:
        raise ValueError("Benchmark counts must be positive.")

    with tempfile.TemporaryDirectory(prefix="miskatonic-benchmark-") as directory:
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "benchmark-only-secret",
                "DATABASE": str(Path(directory) / "benchmark.sqlite3"),
            }
        )
        with app.app_context():
            insert_started = perf_counter()
            for index in range(entry_count):
                create_entry(
                    title=f"Evidence record {index:04d}",
                    category="Investigation",
                    content=f"Benchmark note {index}.",
                    sanity=index % 101,
                )
            insert_seconds = perf_counter() - insert_started

        client = app.test_client()
        timings = []
        for _ in range(request_count):
            started = perf_counter()
            response = client.get("/?q=Evidence")
            timings.append(perf_counter() - started)
            if response.status_code != 200:
                raise RuntimeError(f"Search benchmark returned HTTP {response.status_code}.")

        return {
            "entries": entry_count,
            "search_requests": request_count,
            "insert_seconds": insert_seconds,
            "search_mean_ms": mean(timings) * 1_000,
            "search_median_ms": median(timings) * 1_000,
            "search_p95_ms": _percentile(timings, 0.95) * 1_000,
            "search_min_ms": min(timings) * 1_000,
            "search_max_ms": max(timings) * 1_000,
        }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


if __name__ == "__main__":
    print(json.dumps(run_benchmarks(), indent=2))
