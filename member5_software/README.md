# member5_software — Backend & Real-Time Dashboard

**Role:** Member 5 — Software Engineer (full-stack)

**Output:** FastAPI backend + React dashboard serving every other module's output to the operator.

## Status (2026-10-03)

✅ **Backend — complete:**
- `backend/app/main.py` FastAPI app with CORS, health endpoints, SQLAlchemy init.
- Pydantic models in `backend/app/models/schemas.py` mirror `data_schema.md §2` EXACTLY (scores, evidence, trust, alert, trajectory, history).
- Service layer: `backend/app/services/trust_service.py` →
  - `TrustServiceABC` interface (swappable)
  - `MockTrustService` (plausible §22 demo-story data: 92% → ~18% RED → 93% recovery)
  - `RealTrustService` that calls M1/M2 via `integration/pipeline.py::run_observation()` and M3 `compute_trust(..., observations=)` + `fuse(...)`.
- SQLAlchemy DB: 4 tables (`observations`, `trust_scores`, `evidences`, `alerts`) — SQLite fallback via `DATABASE_URL`, PostgreSQL supported.
- REST v1 (all return correct status codes, schema-validated):
  - `GET  /health`, `GET  /api/v1/health`
  - `GET  /api/v1/trust/current`
  - `GET  /api/v1/trust/history?sensor_id=&limit=`
  - `GET  /api/v1/evidence/{observation_id}`
  - `GET  /api/v1/alerts?active_only=&limit=`
  - `GET  /api/v1/trajectory?scenario=`
  - `POST /api/v1/demo/attack/{scenario}` → starts playback
  - `POST /api/v1/demo/stop/{session_id}`
- `WS /ws/live` streams one `§2 JSON` frame per tick; auto-restarts; auto-reconnect on client.
- **17/17 pytest passing** (backend/tests — schema compliance, endpoint contracts, scenario validation).

✅ **Dashboard — complete:**
- Vite + React 18, proxy `/api` + `/ws` → `localhost:8000`.
- Components: `MapView` (react-leaflet, dark CartoDB tiles, 3-line legend true / reported GNSS / fused), `TrustGauge` (180 px SVG ring with color by level), `SensorStatusCards` (4 cards, weight %, level bar), `EvidencePanel` (✓/✗ + detail + recommended action in §15 wording), `TrustChart` + `SensorWeightsChart` (Recharts, GREEN/AMBER threshold refs), `AlertBanner` (RED pulses), `ScenarioControl` (8 attack-scenario buttons + WS live indicator).
- Initial REST fetch → WebSocket keeps everything live (trust rolling history, weights stacked area, evidence, alert, map current marker).

## Swapping mock → real M1+M2+M3

The only change needed is one line in `backend/app/services/trust_service.py::get_trust_service()` — but **it already auto-prefers `RealTrustService`** (falls back to `MockTrustService` if modules raise on import). The backend TestClient run already exercises the real pipeline (M1 physical + M2 temporal scores → M3 trust → fused trajectory).

## How to run

From repo root:

```bash
# Backend (:8000)
py -m uvicorn backend.app.main:app --reload

# Frontend (:5173)
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173` — the 30-second §22 spoof → alert → recovery plays on a loop over `/ws/live`.

## Ownership (read-only for everything else)

Write paths: `backend/`, `frontend/`, `member5_software/`, `docs/reports/m5_*`.
Read + call into: `integration/interfaces.py`, `integration/pipeline.py` (never edit without CR).

## Remaining work (low priority)

- M5-specific evaluation report `docs/reports/m5_evaluation.md` (latency, memory, browser perf on 1 h playback).
- Auth / RBAC for deployment (not MVP scope).
