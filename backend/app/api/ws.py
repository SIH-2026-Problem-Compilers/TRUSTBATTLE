from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Set

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


@ws_router.websocket("/ws/live")
async def ws_live(websocket: WebSocket, session_id: str = "default") -> None:
    await websocket.accept()
    _active_connections.add(websocket)
    service = get_trust_service()

    speed = settings.ws_playback_speed
    sleep_s = settings.ws_sleep_s / max(speed, 0.01)

    try:
        started = service.start_attack_scenario("gnss_spoof")
        sid = started["session_id"]

        while True:
            msg = service.advance_playback(sid)
            if msg is None:
                # End of scenario; pause briefly then restart loop for continuous stream
                await asyncio.sleep(2.0)
                started = service.start_attack_scenario("gnss_spoof")
                sid = started["session_id"]
                continue

            payload = msg.model_dump(mode="json", by_alias=True)
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
