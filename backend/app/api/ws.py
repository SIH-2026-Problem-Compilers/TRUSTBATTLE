from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import settings  # noqa: E402
from backend.app.db import SessionLocal  # noqa: E402
from backend.app.db.repository import store_trust_message  # noqa: E402
from backend.app.services.trust_service import get_trust_service  # noqa: E402

ws_router = APIRouter()

_active_connections: Set[WebSocket] = set()
_session_tasks: Dict[str, asyncio.Task] = {}
_live_frames: Dict[WebSocket, int] = {}


@ws_router.websocket("/ws/live")
async def ws_live(websocket: WebSocket, session_id: str = "default") -> None:
    await websocket.accept()
    _active_connections.add(websocket)
    service = get_trust_service()

    speed = settings.ws_playback_speed
    sleep_s = settings.ws_sleep_s / max(speed, 0.01)

    try:
        # Play whatever scenario the dashboard selected (default: gnss_spoof).
        # The service bumps an epoch on every scenario selection; when it
        # changes we reopen the session so the stream follows the buttons
        # instead of a hard-coded scenario.
        sid: Optional[str] = None
        epoch: Optional[int] = None

        while True:
            state = getattr(service, "ws_stream_state", None)
            if callable(state):
                scenario, ep = state()
            else:  # pragma: no cover - services always implement it now
                scenario, ep = "gnss_spoof", 0

            if sid is None or ep != epoch:
                # TRUSTBATTLE LIVE: when the service signals live mode the
                # controller itself drives generation; session id "live"
                # routes advance_playback to the live controller.
                if scenario == "live":
                    sid = "live"
                    epoch = ep
                else:
                    started = service.start_ws_session(scenario)
                    sid = started["session_id"]
                    epoch = ep

            msg = service.advance_playback(sid)
            if msg is None:
                # End of scenario; pause briefly then reopen for continuous stream
                await asyncio.sleep(2.0)
                sid = None
                continue

            payload = msg.model_dump(mode="json", by_alias=True)
            # TRUSTBATTLE LIVE: piggyback status frames (pipeline panel +
            # event log) so the dashboard reflects real controller state.
            if scenario == "live":
                _live_frames[websocket] = _live_frames.get(websocket, 0) + 1
                if _live_frames[websocket] % 5 == 0:
                    try:
                        from backend.app.services.live_demo import get_live_controller
                        status = get_live_controller().status()
                        status["auto_running"] = getattr(
                            get_live_controller(), "auto_running", False)
                        await websocket.send_text(
                            json.dumps({"type": "live_status", "status": status}))
                    except Exception:
                        pass
            try:
                db = SessionLocal()
                try:
                    store_trust_message(db, msg)
                finally:
                    db.close()
            except Exception:
                pass

            await websocket.send_text(json.dumps(payload))
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.001)
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except (asyncio.TimeoutError, WebSocketDisconnect):
                pass
            await asyncio.sleep(sleep_s)
    except WebSocketDisconnect:
        pass
    finally:
        _active_connections.discard(websocket)
        _live_frames.pop(websocket, None)
