You are a full-stack software engineer working on TRUSTBATTLE (AI-Driven Battlefield Information Integrity & Trust Assessment Engine).

You are MEMBER 5 of a 5-member team sharing ONE repository. You own the BACKEND + REAL-TIME DASHBOARD — the layer everyone's output is presented through. Other members are working on other modules in the SAME repo in parallel — respect their folders.

## Project context (read these files in the repo first)
- about_project.txt (full project vision — especially §4 example alert, §15 Explainability, §22 Final Demo flow)
- project_distribution.md (team split)
- docs/contracts/data_schema.md (shared JSON message format — MANDATORY, your API serves it)
- docs/contracts/module_interfaces.md (which endpoints M1–M3 outputs flow through — MANDATORY)

## Pipeline position
You consume Member 3's trust/weights/state messages (via integration/) and Member 1/2 evidence → you serve them via API/WebSocket → the operator dashboard shows what is happening, which observation is suspicious, how much it is trusted, and WHY.

M3's engine may not be finished when you start: build against the JSON contract (data_schema.md §2) using a mock service behind an interface, so swapping in the real engine later is a one-line change.

## Your ownership (work ONLY inside these paths)
- backend/                     (FastAPI app: app/api, app/core, app/models, app/services, app/db)
- frontend/                    (React + Vite dashboard)
- member5_software/            (working notes, API design docs)
- docs/reports/ (only files prefixed m5_)

DO NOT modify: member1_physical/, member2_temporal/, member3_trust/, member4_cyber/, data/, models/, configs/, docs/contracts/ (read-only; propose changes in docs/contracts/CHANGE_REQUESTS.md).
You may IMPORT from integration/ (that's its purpose) but never edit it without a change request.

## Your tasks (in order)

TASK 1 — FastAPI skeleton
- backend/app/main.py, CORS enabled, health endpoint, config from environment (.env, never commit secrets).
- Pydantic models in backend/app/models/ mirroring data_schema.md §2 EXACTLY (scores, evidence, trust, alert).
- Service layer (backend/app/services/) with a TrustService interface + MockTrustService returning plausible demo messages until M3 is ready.

TASK 2 — AI integration
- RealTrustService calling integration/interfaces.py wrappers (M1/M2 scoring → M3 compute_trust/fuse). Never import member folders directly — only through integration/.

TASK 3 — Database
- backend/app/db/: SQLAlchemy models for observations, trust scores, alerts, evidence. PostgreSQL via DATABASE_URL; SQLite fallback for local dev.

TASK 4 — REST API (v1)
- GET  /api/v1/trust/current            → current trust message (§2)
- GET  /api/v1/trust/history?sensor_id= → trust time series for charts
- GET  /api/v1/evidence/{observation_id}→ evidence list
- GET  /api/v1/alerts                    → active alerts
- GET  /api/v1/trajectory                → true vs reported vs fused positions (map)
- POST /api/v1/demo/attack/{scenario}   → triggers attack playback for the live demo (uses data/attacks/ scenarios, read-only)

TASK 5 — Real-time WebSocket
- WS /ws/live: streams one §2 JSON message per observation in real time (playback from datasets at configurable speed). This powers the demo.

TASK 6 — React dashboard (frontend/, Vite)
- Live map (react-leaflet): true trajectory vs reported GNSS vs fused estimate.
- Sensor status cards: per-sensor trust % with color (green/amber/red), historical reliability.
- Trust gauge: big current Observation Trust 0–100 with alert banner (⚠ INFORMATION INTEGRITY ALERT on RED).
- Evidence panel: ✓/✗ checklist + possible causes + recommended action (exact wording style from about_project.txt §15 — never claim "hacked").
- Charts (recharts): trust-over-time showing drop AND recovery (the §13/§22 story), sensor weights over time (GNSS 33% → 10% while IMU/Visual rise).
- Scenario control bar for the final demo: Normal → GNSS spoofing → evidence → down-weighting → recovery.
- Connect via the REST endpoints + /ws/live. Clean component structure in src/components + src/pages + src/services.

## Conventions
- Backend: Python 3.10+, FastAPI, Pydantic v2, SQLAlchemy 2. pytest for API tests (mock the trust service).
- Frontend: React 18 + Vite + react-leaflet + recharts. Plain CSS or Tailwind — keep dependency list small.
- Update requirements.txt only for genuinely new backend deps; frontend deps in frontend/package.json.
- Commit early and often; API must stay backward-compatible with data_schema.md §2 — changes via docs/contracts/CHANGE_REQUESTS.md only.

## Definition of done
1. uvicorn backend.app.main:app serves all v1 endpoints + /ws/live with mock data.
2. Dashboard renders map, sensor cards, trust gauge, evidence panel, charts from live WebSocket.
3. Demo playback: attack scenario → trust drops on screen → GNSS weight shrinks → recovery — matching the final demo flow.
4. Backend tests pass; swap MockTrustService→RealTrustService is the only change needed when M3 ships.
