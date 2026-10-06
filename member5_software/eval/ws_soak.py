"""M5 evaluation — WS streaming soak.

Connects to ws://localhost:5173/ws/live (through the Vite proxy — the same
path the browser uses), receives §2 frames for SOAK_SECONDS, and samples the
backend process RSS every 60 s. Writes one CSV row per sample plus a final
summary line to stdout / the given log file.

Usage:
    py member5_software/eval/ws_soak.py [duration_s] [log_path]
"""
from __future__ import annotations

import asyncio
import json
import statistics
import subprocess
import sys
import time

import websockets

WS_URL = "ws://localhost:5173/ws/live"
HEALTH_URL = "http://127.0.0.1:8000/health"

CSV_HEADER = "kind,elapsed_s,frames,bytes,interval_avg_ms,interval_max_ms,rss_mb"


def backend_rss_mb() -> float | None:
    """Working set of the process listening on :8000 (PowerShell one-liner)."""
    ps = (
        "$p=(Get-NetTCPConnection -LocalPort 8000 -State Listen "
        "-ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1; "
        "if($p){[math]::Round((Get-Process -Id $p).WorkingSet64/1MB,1)}"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        return float(out) if out else None
    except Exception:
        return None


async def run(duration_s: int, log_path: str) -> dict:
    stats = {
        "frames": 0, "bytes": 0, "intervals_ms": [], "errors": 0,
        "connect_s": None, "first_frame_s": None, "rss_samples": [],
    }
    start = time.monotonic()
    next_rss_at = 0.0
    lines: list[str] = []

    def elapsed() -> float:
        return time.monotonic() - start

    async def rss_loop():
        nonlocal next_rss_at
        while elapsed() < duration_s:
            wait = next_rss_at - elapsed()
            if wait > 0:
                await asyncio.sleep(wait)
            rss = backend_rss_mb()
            if rss is not None:
                stats["rss_samples"].append(rss)
                lines.append(f"rss,{elapsed():.0f},{stats['frames']},"
                             f"{stats['bytes']},,,{rss}")
            next_rss_at = elapsed() + 60

    rss_task = asyncio.create_task(rss_loop())
    last_frame = None
    try:
        t_conn = time.monotonic()
        async with websockets.connect(WS_URL, open_timeout=15) as ws:
            stats["connect_s"] = time.monotonic() - t_conn
            while elapsed() < duration_s:
                timeout = max(0.1, duration_s - elapsed())
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                now = time.monotonic()
                if stats["first_frame_s"] is None:
                    stats["first_frame_s"] = now - t_conn
                if last_frame is not None:
                    stats["intervals_ms"].append((now - last_frame) * 1000)
                last_frame = now
                stats["frames"] += 1
                stats["bytes"] += len(msg)
    except Exception as exc:  # connection drop counts as an error
        stats["errors"] += 1
        lines.append(f"error,{elapsed():.0f},0,0,0,0,{exc}")
    finally:
        rss_task.cancel()

    iv = stats["intervals_ms"] or [0.0]
    result = {
        "duration_s": duration_s,
        "connect_s": round(stats["connect_s"] or -1, 4),
        "first_frame_s": round(stats["first_frame_s"] or -1, 4),
        "frames": stats["frames"],
        "bytes": stats["bytes"],
        "avg_frame_bytes": round(stats["bytes"] / stats["frames"], 1) if stats["frames"] else 0,
        "interval_avg_ms": round(statistics.mean(iv), 1),
        "interval_p95_ms": round(sorted(iv)[int(len(iv) * 0.95)] if len(iv) > 1 else iv[0], 1),
        "interval_max_ms": round(max(iv), 1),
        "fps": round(stats["frames"] / duration_s, 3),
        "errors": stats["errors"],
        "rss_first_mb": stats["rss_samples"][0] if stats["rss_samples"] else None,
        "rss_last_mb": stats["rss_samples"][-1] if stats["rss_samples"] else None,
        "rss_max_mb": max(stats["rss_samples"]) if stats["rss_samples"] else None,
    }
    with open(log_path, "w") as fh:
        fh.write(CSV_HEADER + "\n")
        fh.write("\n".join(lines) + "\n")
        fh.write("summary," + json.dumps(result) + "\n")
    return result


if __name__ == "__main__":
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
    log = sys.argv[2] if len(sys.argv) > 2 else "member5_software/eval/ws_soak_log.csv"
    out = asyncio.run(run(dur, log))
    print(json.dumps(out, indent=2))
