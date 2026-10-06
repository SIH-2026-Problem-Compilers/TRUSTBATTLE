"""M5 evaluation — REST endpoint latency.

Probes each v1 endpoint through the Vite proxy (browser path) with a warmup
then N timed requests; reports mean/p50/p95/p99/max in ms as JSON.

Usage:
    py member5_software/eval/rest_latency.py [n_requests] [base_url]
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request

ENDPOINTS = [
    ("GET", "/health"),
    ("GET", "/api/v1/trust/current"),
    ("GET", "/api/v1/trust/history?sensor_id=&limit=200"),
    ("GET", "/api/v1/trajectory"),
    ("GET", "/api/v1/alerts?limit=50"),  # NOTE: active_only= (empty bool) → 422; omit it
]


def pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[k]


def measure(method: str, url: str, n: int) -> dict:
    # warmup
    for _ in range(10):
        urllib.request.urlopen(url, timeout=10).read()
    times = []
    status = None
    for _ in range(n):
        t0 = time.perf_counter()
        with urllib.request.urlopen(url, timeout=10) as resp:
            resp.read()
            status = resp.status
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return {
        "status": status,
        "n": n,
        "mean_ms": round(statistics.mean(times), 2),
        "p50_ms": round(pct(times, 50), 2),
        "p95_ms": round(pct(times, 95), 2),
        "p99_ms": round(pct(times, 99), 2),
        "max_ms": round(times[-1], 2),
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:5173"
    results = {}
    for method, path in ENDPOINTS:
        results[path] = measure(method, base + path, n)
    print(json.dumps(results, indent=2))
