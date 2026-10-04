from __future__ import annotations

import asyncio
import random
import sys
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.models.schemas import (  # noqa: E402
    AlertData,
    AlertItem,
    EvidenceItem,
    Scores,
    TrajectoryPoint,
    TrajectoryResponse,
    TrustData,
    TrustHistoryPoint,
    TrustMessage,
)
from backend.app.core.config import settings  # noqa: E402


class PlaybackSession(BaseModel):
    session_id: str
    scenario: str
    start_time: float
    speed: float = 1.0
    is_active: bool = True
    current_index: int = 0
    messages: List[Dict[str, Any]] = []


class TrustServiceABC(ABC):
    @abstractmethod
    def get_current_trust(self) -> TrustMessage: ...

    @abstractmethod
    def get_trust_history(self, sensor_id: Optional[str] = None, limit: int = 500) -> List[TrustHistoryPoint]: ...

    @abstractmethod
    def get_evidence(self, observation_id: str) -> List[EvidenceItem]: ...

    @abstractmethod
    def get_alerts(self, active_only: bool = True, limit: int = 100) -> List[AlertItem]: ...

    @abstractmethod
    def get_trajectory(self, scenario: Optional[str] = None) -> TrajectoryResponse: ...

    @abstractmethod
    def start_attack_scenario(self, scenario: str) -> Dict[str, Any]: ...

    @abstractmethod
    def stop_playback(self, session_id: str) -> None: ...

    @abstractmethod
    def get_playback(self, session_id: str) -> Optional[PlaybackSession]: ...

    @abstractmethod
    def advance_playback(self, session_id: str) -> Optional[TrustMessage]: ...


class MockTrustService(TrustServiceABC):
    """Plausible demo data until M1/M2/M3 + real datasets are wired in.

    Produces the §22 demo story: high trust → GNSS spoof kicks in → trust
    drops to RED, GNSS weight shrinks, alert fires → recovery after window.
    """

    def __init__(self) -> None:
        self._history: List[TrustMessage] = []
        self._alerts: List[AlertItem] = []
        self._playbacks: Dict[str, PlaybackSession] = {}
        self._demo_story: List[Dict[str, Any]] = self._build_demo_story()
        self._seed_initial_history()

    # ------------------------------------------------------------------
    # demo story generator
    # ------------------------------------------------------------------
    @staticmethod
    def _build_demo_story(n_points: int = 300) -> List[Dict[str, Any]]:
        """Approximate §22 demo numbers as 10-Hz sample sequence (30 s)."""
        story: List[Dict[str, Any]] = []
        base_lat, base_lon = 28.61, 77.21  # Delhi-region reference airfield (India), same as M1/M2/M4 data
        attack_start, attack_end = 60, 200  # indices: 6 s to 20 s into playback

        for i in range(n_points):
            t = i * 0.1
            lat = base_lat + (i * 0.00002)
            lon = base_lon + (i * 0.00003)
            reported_lat = lat
            reported_lon = lon
            true_lat = lat
            true_lon = lon

            if attack_start <= i <= attack_end:
                spoof_offset = min((i - attack_start) * 0.00010, 0.006)
                reported_lat += spoof_offset
                reported_lon += spoof_offset * 0.8
                phys_cons = max(0.02, 0.92 - (i - attack_start) * 0.008)
                anom_phys = min(0.98, 0.05 + (i - attack_start) * 0.009)
                temp_cons = max(0.08, 0.90 - (i - attack_start) * 0.005)
                anom_temp = min(0.85, 0.03 + (i - attack_start) * 0.005)
                net_int = 0.85
                cross_ag = max(0.05, 0.90 - (i - attack_start) * 0.008)
                obs_trust = max(18.0, 92.0 - (i - attack_start) * 0.65)
            elif i > attack_end:
                recovery_i = i - attack_end
                phys_cons = min(0.95, 0.05 + recovery_i * 0.012)
                anom_phys = max(0.02, 0.92 - recovery_i * 0.012)
                temp_cons = min(0.95, 0.12 + recovery_i * 0.012)
                anom_temp = max(0.03, 0.82 - recovery_i * 0.012)
                net_int = 0.92
                cross_ag = min(0.95, 0.05 + recovery_i * 0.015)
                obs_trust = min(93.0, 20.0 + recovery_i * 0.75)
            else:
                phys_cons = 0.94
                anom_phys = 0.04
                temp_cons = 0.93
                anom_temp = 0.03
                net_int = 0.95
                cross_ag = 0.94
                obs_trust = 92.0 + random.uniform(-1.5, 1.5)

            w_gnss_raw = 0.33 if obs_trust > 70 else (0.33 - (93 - obs_trust) * 0.0035)
            w_gnss = max(0.05, w_gnss_raw)
            w_rem = 1.0 - w_gnss
            w_imu = round(w_rem * 0.5, 3)
            w_vis = round(w_rem * 0.5, 3)

            if obs_trust >= 70:
                level = "GREEN"
                msg = "Observations within normal integrity bounds."
                causes: List[str] = []
                recommended = "None — continue routine monitoring."
            elif obs_trust >= 40:
                level = "AMBER"
                msg = "ELEVATED INTEGRITY RISK — observation shows degraded consistency."
                causes = ["Potential GNSS spoofing", "Sensor wear or drift"]
                recommended = "Increase scrutiny of this observation and cross-check it against independent sources."
            else:
                level = "RED"
                msg = "INFORMATION INTEGRITY ALERT — observation is potentially unreliable."
                causes = ["GNSS spoofing", "sensor malfunction", "communication manipulation"]
                recommended = "Reduce this observation's influence in fusion and request independent verification."

            evidence: List[Dict[str, Any]] = []
            checks = [
                ("Historical sensor reliability", obs_trust > 20, "GNSS reliability = 94% (last 30 days)"),
                ("Physical consistency (IMU vs position)", phys_cons > 0.6,
                 f"velocity residual {int((1-phys_cons)*80)} m/s vs limit 22 m/s"),
                ("Temporal consistency", temp_cons > 0.6,
                 f"rolling change score {(1-temp_cons):.2f}"),
                ("Network/telemetry integrity", net_int > 0.7,
                 f"packet loss {(1-net_int)*5:.1f}%"),
                ("Cross-sensor agreement", cross_ag > 0.6,
                 f"GNSS/IMU/visual spread {int((1-cross_ag)*600)} m"),
            ]
            for name, ok, detail in checks:
                evidence.append({"check": name, "pass": ok, "detail": detail})

            fused_w = w_gnss
            fused_lat = reported_lat * fused_w + true_lat * (1 - fused_w)
            fused_lon = reported_lon * fused_w + true_lon * (1 - fused_w)

            story.append({
                "timestamp": t,
                "observation_id": f"obs_{i:06d}",
                "sensor_id": "uav1_gnss",
                "scores": {
                    "physical_consistency": round(phys_cons, 4),
                    "anomaly_physical": round(anom_phys, 4),
                    "temporal_consistency": round(temp_cons, 4),
                    "anomaly_temporal": round(anom_temp, 4),
                    "network_integrity": round(net_int, 4),
                    "cross_sensor_agreement": round(cross_ag, 4),
                },
                "evidence": evidence,
                "trust": {
                    "observation_trust": round(obs_trust, 1),
                    "sensor_reliability": 94.0,
                    "sensor_weights": {"gnss": round(w_gnss, 3), "imu": w_imu, "visual": w_vis},
                    "sensor_trust": {
                        "gnss": round(max(5.0, obs_trust - (93 - obs_trust) * 0.3), 1),
                        "imu": round(min(95.0, obs_trust + 3.0), 1),
                        "visual": round(min(95.0, obs_trust + 2.5), 1),
                    },
                    "consensus_trust": round(obs_trust + 2.0, 1),
                    "state_estimate": {"lat": round(fused_lat, 7),
                                       "lon": round(fused_lon, 7),
                                       "velocity": 18.5},
                },
                "alert": {
                    "level": level,
                    "message": msg,
                    "possible_causes": causes,
                    "recommended_action": recommended,
                },
                "true_pos": {"lat": true_lat, "lon": true_lon, "velocity": 18.5},
                "reported_pos": {"lat": reported_lat, "lon": reported_lon, "velocity": 18.5},
                "fused_pos": {"lat": fused_lat, "lon": fused_lon, "velocity": 18.5},
            })
        return story

    def _seed_initial_history(self) -> None:
        # Seed with tail of story so there's history immediately
        tail = self._demo_story[:30]
        for d in tail:
            self._push_message(d)

    def _push_message(self, data: Dict[str, Any]) -> TrustMessage:
        msg = TrustMessage(
            schema_version="1.0",
            observation_id=data["observation_id"],
            sensor_id=data["sensor_id"],
            timestamp=data["timestamp"],
            scores=Scores(**data["scores"]),
            evidence=[EvidenceItem(**e) for e in data["evidence"]],
            trust=TrustData(**data["trust"]),
            alert=AlertData(**data["alert"]),
        )
        self._history.append(msg)
        if len(self._history) > 5000:
            self._history = self._history[-5000:]
        if msg.alert.level in ("AMBER", "RED"):
            self._alerts.append(AlertItem(
                id=f"alert_{uuid.uuid4().hex[:8]}",
                timestamp=msg.timestamp or 0.0,
                level=msg.alert.level,
                message=msg.alert.message,
                possible_causes=list(msg.alert.possible_causes),
                observation_id=msg.observation_id,
                sensor_id=msg.sensor_id,
                observation_trust=msg.trust.observation_trust,
            ))
            if len(self._alerts) > 500:
                self._alerts = self._alerts[-500:]
        return msg

    # ------------------------------------------------------------------
    # interface implementation
    # ------------------------------------------------------------------
    def get_current_trust(self) -> TrustMessage:
        if self._history:
            return self._history[-1]
        data = self._demo_story[0]
        return self._push_message(data)

    def get_trust_history(self, sensor_id: Optional[str] = None, limit: int = 500) -> List[TrustHistoryPoint]:
        points: List[TrustHistoryPoint] = []
        for msg in reversed(self._history[-limit:]):
            if sensor_id and msg.sensor_id != sensor_id:
                continue
            points.append(TrustHistoryPoint(
                timestamp=msg.timestamp or 0.0,
                observation_trust=msg.trust.observation_trust,
                sensor_id=msg.sensor_id,
                level=msg.alert.level,
                sensor_weights=dict(msg.trust.sensor_weights),
            ))
        return list(reversed(points))

    def get_evidence(self, observation_id: str) -> List[EvidenceItem]:
        for msg in reversed(self._history):
            if msg.observation_id == observation_id:
                return list(msg.evidence)
        for data in self._demo_story:
            if data["observation_id"] == observation_id:
                return [EvidenceItem(**e) for e in data["evidence"]]
        return []

    def get_alerts(self, active_only: bool = True, limit: int = 100) -> List[AlertItem]:
        alerts = list(reversed(self._alerts))
        if active_only and alerts:
            last_ts = alerts[0].timestamp
            alerts = [a for a in alerts if a.timestamp >= last_ts - 30.0]
        return alerts[:limit]

    def get_trajectory(self, scenario: Optional[str] = None) -> TrajectoryResponse:
        src = self._demo_story
        true_t, rep_t, fus_t = [], [], []
        for d in src:
            tp = d["true_pos"]
            rp = d["reported_pos"]
            fp = d["fused_pos"]
            true_t.append(TrajectoryPoint(timestamp=d["timestamp"], **tp))
            rep_t.append(TrajectoryPoint(timestamp=d["timestamp"], **rp))
            fus_t.append(TrajectoryPoint(timestamp=d["timestamp"], **fp))
        return TrajectoryResponse(
            true_trajectory=true_t,
            reported_trajectory=rep_t,
            fused_trajectory=fus_t,
            scenario=scenario or "demo_spoof_story",
        )

    def start_attack_scenario(self, scenario: str) -> Dict[str, Any]:
        # For mock service: always play back the demo story regardless of scenario name
        sid = uuid.uuid4().hex[:10]
        session = PlaybackSession(
            session_id=sid,
            scenario=scenario,
            start_time=time.time(),
            speed=settings.ws_playback_speed,
            is_active=True,
            current_index=0,
            messages=self._demo_story,
        )
        self._playbacks[sid] = session
        return {"session_id": sid, "scenario": scenario,
                "n_messages": len(session.messages)}

    def stop_playback(self, session_id: str) -> None:
        s = self._playbacks.get(session_id)
        if s:
            s.is_active = False

    def get_playback(self, session_id: str) -> Optional[PlaybackSession]:
        return self._playbacks.get(session_id)

    def advance_playback(self, session_id: str) -> Optional[TrustMessage]:
        s = self._playbacks.get(session_id)
        if not s or not s.is_active:
            return None
        if s.current_index >= len(s.messages):
            s.is_active = False
            return None
        data = s.messages[s.current_index]
        s.current_index += 1
        return self._push_message(data)


class RealTrustService(TrustServiceABC):
    """Integrates M1 + M2 scoring → M3 compute_trust/fuse via integration/ adapters.

    Falls back gracefully to MockTrustService semantics when modules/datasets
    are not yet available.
    """

    def __init__(self) -> None:
        self._mock = MockTrustService()
        self._history: List[TrustMessage] = []
        self._alerts: List[AlertItem] = []
        self._playbacks: Dict[str, PlaybackSession] = {}
        self._ready: bool = self._try_init_pipeline()

    def _try_init_pipeline(self) -> bool:
        try:
            from integration.pipeline import register_available_implementations
            from integration import interfaces  # noqa: F401
            register_available_implementations()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    def _push_message(self, msg: TrustMessage) -> TrustMessage:
        self._history.append(msg)
        if len(self._history) > 5000:
            self._history = self._history[-5000:]
        if msg.alert.level in ("AMBER", "RED"):
            self._alerts.append(AlertItem(
                id=f"alert_{uuid.uuid4().hex[:8]}",
                timestamp=msg.timestamp or 0.0,
                level=msg.alert.level,
                message=msg.alert.message,
                possible_causes=list(msg.alert.possible_causes),
                observation_id=msg.observation_id,
                sensor_id=msg.sensor_id,
                observation_trust=msg.trust.observation_trust,
            ))
        return msg

    # ------------------------------------------------------------------
    def _run_pipeline(self) -> Optional[TrustMessage]:
        if not self._ready:
            return None
        try:
            from integration.pipeline import run_observation
            from member3_trust.src import eval_scenarios
            import pandas as pd

            WINDOW = 50
            if not hasattr(self, "_df"):
                self._df, _ = eval_scenarios.make_spoof_scenario(n=3200, attack_start=1000, attack_end=1800)
                self._cursor = 0
                self._trust_history: List[Dict[str, Any]] = []

            if self._cursor + WINDOW > len(self._df):
                return None

            window = self._df.iloc[self._cursor:self._cursor + WINDOW].reset_index(drop=True)
            self._cursor += WINDOW

            result = run_observation(window)
            obs = eval_scenarios.sensor_observations(self._df,
                                                     slice(self._cursor - WINDOW, self._cursor),
                                                     rng_seed=1000 + self._cursor)
            try:
                from integration import interfaces
                scores = result.get("scores", {})
                trust_out = interfaces.compute_trust(scores, self._trust_history, observations=obs)
                result.update(trust_out)
                state = interfaces.fuse(obs, result.get("trust", {}))
                result.setdefault("trust", {}).setdefault("state_estimate", {}).update(state)
                self._trust_history.append(result)
                if len(self._trust_history) > 200:
                    self._trust_history = self._trust_history[-200:]
            except Exception:
                pass

            msg = TrustMessage(
                schema_version="1.0",
                observation_id=f"obs_{self._cursor:06d}",
                sensor_id=result.get("sensor_id") or "uav1_gnss",
                timestamp=float(window["timestamp"].iloc[0]),
                scores=Scores(**result.get("scores", {})),
                evidence=[EvidenceItem(**e) for e in result.get("evidence", [])],
                trust=TrustData(**result.get("trust", {})),
                alert=AlertData(**result.get("alert", {})),
            )
            return self._push_message(msg)
        except Exception:
            return None

    # ------------------------------------------------------------------
    def get_current_trust(self) -> TrustMessage:
        msg = self._run_pipeline()
        if msg is None:
            return self._mock.get_current_trust()
        return msg

    def get_trust_history(self, sensor_id: Optional[str] = None, limit: int = 500) -> List[TrustHistoryPoint]:
        src = self._history if self._ready else self._mock.get_trust_history(sensor_id, limit)
        if self._ready:
            points: List[TrustHistoryPoint] = []
            for m in self._history[-limit:]:
                if sensor_id and m.sensor_id != sensor_id:
                    continue
                points.append(TrustHistoryPoint(
                    timestamp=m.timestamp or 0.0,
                    observation_trust=m.trust.observation_trust,
                    sensor_id=m.sensor_id,
                    level=m.alert.level,
                    sensor_weights=dict(m.trust.sensor_weights),
                ))
            return points
        return src

    def get_evidence(self, observation_id: str) -> List[EvidenceItem]:
        for m in reversed(self._history):
            if m.observation_id == observation_id:
                return list(m.evidence)
        return self._mock.get_evidence(observation_id)

    def get_alerts(self, active_only: bool = True, limit: int = 100) -> List[AlertItem]:
        if self._history:
            alerts = list(reversed(self._alerts))
            if active_only and alerts:
                last_ts = alerts[0].timestamp
                alerts = [a for a in alerts if a.timestamp >= last_ts - 30.0]
            return alerts[:limit]
        return self._mock.get_alerts(active_only, limit)

    def get_trajectory(self, scenario: Optional[str] = None) -> TrajectoryResponse:
        if not self._ready:
            return self._mock.get_trajectory(scenario)
        try:
            from member3_trust.src import eval_scenarios
            from member3_trust.src.fusion import fuse, fuse_normal
            from member3_trust.src.trust_engine import compute_trust
            from integration import interfaces

            WINDOW = 50
            df, _ = eval_scenarios.make_spoof_scenario(n=1600, attack_start=500, attack_end=900)
            trust_hist: List[Dict[str, Any]] = []
            true_t, rep_t, fus_t = [], [], []
            for w0 in range(0, len(df) - WINDOW + 1, WINDOW):
                window = df.iloc[w0:w0 + WINDOW].reset_index(drop=True)
                scores = {}
                for scorer in (interfaces.score_physical, interfaces.score_temporal):
                    try:
                        scores.update(scorer(window)["scores"])
                    except Exception:
                        pass
                obs = eval_scenarios.sensor_observations(df, slice(w0, w0 + WINDOW), rng_seed=2000 + w0)
                tres = compute_trust(scores, trust_hist, observations=obs)
                trust_hist.append(tres)
                est = fuse(obs, tres["trust"])
                tlat = float(window["latitude"].mean())
                tlon = float(window["longitude"].mean())
                rlat = tlat
                rlon = tlon
                try:
                    tlat = float(df.attrs["truth_latitude"][w0:w0 + WINDOW].mean())
                    tlon = float(df.attrs["truth_longitude"][w0:w0 + WINDOW].mean())
                except Exception:
                    pass
                ts = float(window["timestamp"].iloc[0])
                true_t.append(TrajectoryPoint(timestamp=ts, lat=tlat, lon=tlon))
                rep_t.append(TrajectoryPoint(timestamp=ts, lat=rlat, lon=rlon))
                fus_t.append(TrajectoryPoint(timestamp=ts, lat=float(est["lat"]), lon=float(est["lon"]),
                                             velocity=float(est.get("velocity", 0))))
            return TrajectoryResponse(
                true_trajectory=true_t,
                reported_trajectory=rep_t,
                fused_trajectory=fus_t,
                scenario=scenario or "m4_mixed_spoof",
            )
        except Exception:
            return self._mock.get_trajectory(scenario)

    def start_attack_scenario(self, scenario: str) -> Dict[str, Any]:
        if not self._ready:
            return self._mock.start_attack_scenario(scenario)
        sid = uuid.uuid4().hex[:10]
        # Use the mock story structure for now (WS playback from pipeline run one at a time is heavy)
        session = PlaybackSession(
            session_id=sid,
            scenario=scenario,
            start_time=time.time(),
            speed=settings.ws_playback_speed,
            is_active=True,
            current_index=0,
            messages=self._mock._demo_story,
        )
        self._playbacks[sid] = session
        return {"session_id": sid, "scenario": scenario,
                "n_messages": len(session.messages)}

    def stop_playback(self, session_id: str) -> None:
        s = self._playbacks.get(session_id)
        if s:
            s.is_active = False
        self._mock.stop_playback(session_id)

    def get_playback(self, session_id: str) -> Optional[PlaybackSession]:
        return self._playbacks.get(session_id) or self._mock.get_playback(session_id)

    def advance_playback(self, session_id: str) -> Optional[TrustMessage]:
        s = self._playbacks.get(session_id)
        if s and s.is_active:
            if s.current_index >= len(s.messages):
                s.is_active = False
                return None
            data = s.messages[s.current_index]
            s.current_index += 1
            msg = TrustMessage(
                schema_version="1.0",
                observation_id=data["observation_id"],
                sensor_id=data["sensor_id"],
                timestamp=data["timestamp"],
                scores=Scores(**data["scores"]),
                evidence=[EvidenceItem(**e) for e in data["evidence"]],
                trust=TrustData(**data["trust"]),
                alert=AlertData(**data["alert"]),
            )
            return self._push_message(msg)
        return self._mock.advance_playback(session_id)


_service: Optional[TrustServiceABC] = None


def get_trust_service() -> TrustServiceABC:
    """Default dependency — returns RealTrustService, falls back to mock."""
    global _service
    if _service is None:
        try:
            _service = RealTrustService()
        except Exception:
            _service = MockTrustService()
    return _service
