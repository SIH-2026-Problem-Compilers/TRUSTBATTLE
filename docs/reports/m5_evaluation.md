# M5 Evaluation Report — Backend + Dashboard Performance

> **Owner:** M5 (backend/frontend) · **Date:** 2026-10-06
> **Scope:** REST/WS latency and backend/browser memory during live streaming.
> §6 originally asked for "1 h of streaming"; per team decision (2026-10-06) a **30-minute soak** was run instead — every 1-hour figure below is an **extrapolation, clearly labeled**, not a measurement.

## 1. Environment & method

| Item | Value |
|---|---|
| Machine | Windows 11, single dev machine (backend + Vite + headless Chrome on one host) |
| Backend | FastAPI/uvicorn (no `--reload`), `RealTrustService` → live M1→M2→M3 pipeline, SQLite |
| Frontend dev server | Vite :5173, proxies `/api` + `/ws` → :8000 (browser path measured **through the proxy**) |
| Browser | Headless Chrome 154 via CDP (`--remote-debugging-port=9222`), dashboard loaded at `localhost:5173` |
| Soak | **1800 s** (13:30:05–14:00:05, 2026-10-06), 2 concurrent WS consumers (soak client + browser) |
| REST probe | 10 warmup + **200 timed requests/endpoint**, run *during* the soak (loaded state) at t≈1200 s |
| Tooling | `member5_software/eval/{ws_soak.py, rest_latency.py, browser_heap.mjs}` (added by this eval) |

Raw artifacts: `member5_software/eval/ws_soak_log.csv` (30 RSS+frame samples + summary), `member5_software/eval/browser_heap_log.csv` (120 samples, 0 failures), `member5_software/eval/rest_latency_results.json`.
Note: a first soak attempt was interrupted at 850 s by a session teardown (`ws_soak_log_interrupted.csv`, 0 errors up to that point); the reported run is the full 1800 s rerun.

## 2. REST latency (during soak, n=200/endpoint, all HTTP 200)

| Endpoint | mean | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| `GET /health` | 10.4 | **6.1** | 26.9 | 29.3 | 45.0 |
| `GET /api/v1/trust/current` | 39.2 | **12.6** | 178.2 | 217.2 | 243.1 |
| `GET /api/v1/trust/history?limit=200` | 71.5 | **38.6** | 187.0 | 325.1 | 417.0 |
| `GET /api/v1/trajectory` | 24.9 | **11.4** | 103.7 | 160.0 | 250.8 |
| `GET /api/v1/alerts?limit=50` | 33.2 | **25.7** | 97.7 | 107.3 | 123.9 |

*(ms; browser-path via Vite proxy; a separate idle-state probe (n=20) gave p50s of 6–32 ms for the same endpoints, so the figures above include the concurrent-soak load effect)*

- **All endpoints p50 < 40 ms, p99 < 330 ms** under concurrent streaming load — well inside operator-dashboard budgets (subjective UI budget ≈ 100 ms p95 for data panels; `trust/history` p95 187 ms is the heaviest because it serializes up to 200 rows).
- Probe finding (probe bug, not backend): `?active_only=` (empty string → bool) returns **422**; omit the param (`?limit=50`) → 200. The dashboard does not send the empty bool.

## 3. WebSocket streaming (`/ws/live` via Vite proxy, 1800 s)

| Metric | Measured |
|---|---|
| Handshake → open | 2.20 s |
| Open → first §2 frame | **2.30 s** |
| Frames received | **8015** (0 errors, 0 reconnects) |
| Throughput | 4.45 frames/s · avg interval **224 ms** · p95 **316 ms** |
| Worst interval | 6305 ms (single stall; all other intervals < ~1 s) |
| Payload | 39.2 MB total · avg frame **4887 B** · ≈ 21.8 KB/s |

Tick cadence matches the backend's ~200 ms stream loop plus scoring time. The single 6.3 s stall coincides with scenario/pipeline work (documented, non-repeating); no disconnects resulted.

## 4. Backend memory (RSS, 60 s samples, n=30)

| Metric | Value |
|---|---|
| First / last | 232.8 MB / **199.8 MB** |
| Min / max | 75.5 MB / 288.8 MB |
| Pattern | sawtooth (rise → GC/working-set trim), **no monotonic growth** |

Working set ends **below** its starting value after 30 min / 8015 frames / 39 MB streamed → **no backend memory leak detected**. Peaks < 300 MB include the loaded M1+M2+M3 models.

## 5. Browser memory (headless Chrome, 15 s samples, n=120, 0 failures)

| Metric | Value |
|---|---|
| JS heap used | min 0.6 MB (initial load) · avg 44.2 MB · **max 75.7 MB** · last 27.8 MB |
| JS heap total | ≤ 115 MB |
| DOM nodes | **stable 634–657** (avg 633) after load — no DOM growth |
| GC pattern | sawtooth 28–76 MB — normal GC cycling, no runaway plateau |

Linear-regression trend over 30 min: **+5.7 MB/h** (noisy GC sawtooth; first-10 avg 34.8 MB vs last-10 avg 41.3 MB).

**⚠ Extrapolation (not measured):** at the observed slope a 1 h session would land ≈ 6 MB above the 30-min point — i.e. **heap stays bounded well under 150 MB**; DOM stable. **A true 1-hour soak was not run**; the 1 h figure is a linear projection of a 30 min measurement.

## 6. Findings

1. ✅ **No leaks in either process** over the 30-min soak (backend RSS flat/down; JS heap bounded sawtooth; DOM constant).
2. ✅ **Streaming is stable**: 8015 frames / 0 errors through the real Vite-proxy path at the designed ~200 ms cadence.
3. ⚠ **Latency tail**: p95 > 100 ms on the heavier endpoints under load (worst: `trust/history` p99 325 ms, max 417 ms). Acceptable for the dashboard's 1–2 s refresh cadence; if needed, index/paginate `trust/history` first.
4. ⚠ **Single 6.3 s WS stall** observed once — non-repeating, no disconnect; worth alerting on (`ws_interval` metric) in a future M5 pass.
5. ℹ Probe caveat: `active_only=` empty bool → 422 (FastAPI validation); documented in the probe, not a regression.

## 7. Reproduce

```bash
py -m uvicorn backend.app.main:app --port 8000     # repo root
cd frontend && npm run dev                          # :5173
py member5_software/eval/rest_latency.py 200 > member5_software/eval/rest_latency_results.json
py member5_software/eval/ws_soak.py 1800 member5_software/eval/ws_soak_log.csv
# browser heap (headless Chrome must be running with --remote-debugging-port=9222):
node member5_software/eval/browser_heap.mjs 1800 member5_software/eval/browser_heap_log.csv
```

## 8. Open follow-ups (not in scope)

- Full 1 h browser soak (spec's original duration — see §5 extrapolation caveat).
- Browser **process**-level memory (Private bytes) was not sampled — JS heap + DOM only.
- `trust/history` pagination/index for p99 < 100 ms.
