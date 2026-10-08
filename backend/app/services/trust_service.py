from __future__ import annotations

import random
import sys
import threading
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# One observation window in rows (10 Hz -> 5 s), shared by the pipeline
# playback sessions and the integration/demo code.
WINDOW = 50

# Scenario key -> dataset file (schema §5 pairs under data/). Keys match the
# dashboard ScenarioControl buttons and POST /api/v1/demo/attack/{scenario}.
SCENARIO_DATASETS = {
    "normal": "synthetic/uav_normal_v1.parquet",
    "gnss_spoof": "attacks/scenario_gnss_spoof.parquet",
    "replay": "attacks/scenario_replay.parquet",
    "telemetry_manip": "attacks/scenario_telemetry_manipulation.parquet",
    "network_anomaly": "attacks/scenario_network_anomaly.parquet",
    "sensor_malfunction": "attacks/scenario_sensor_malfunction.parquet",
    "cross_sensor_conflict": "attacks/scenario_cross_sensor_conflict.parquet",
    "mixed_c05": "attacks/scenario_mixed_c05.parquet",
    "mixed_c10": "attacks/scenario_mixed_c10.parquet",
    "mixed_c20": "attacks/scenario_mixed_c20.parquet",
    "mixed_c30": "attacks/scenario_mixed_c30.parquet",
}

_warned: set = set()


def _warn_once(key: str, text: str) -> None:
    """Log a pipeline warning once instead of swallowing exceptions silently."""
    if key in _warned:
        return
    _warned.add(key)
    print(f"[trust_service] {text}", file=sys.stderr)

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
        # scenario the /ws/live stream should play + epoch (bumped on every
        # scenario selection so a connected client can pick the change up)
        self._ws_scenario: str = "gnss_spoof"
        self._ws_epoch: int = 0
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
        # Scenario selection changes what /ws/live streams (the mock story
        # itself is scenario-independent).
        self._ws_scenario = scenario
        self._ws_epoch += 1
        return self._open_session(scenario)

    def _open_session(self, scenario: str) -> Dict[str, Any]:
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
                "n_messages": len(session.messages), "source": "mock_story"}

    def ws_stream_state(self):
        """(scenario, epoch) the /ws/live stream should play."""
        return self._ws_scenario, self._ws_epoch

    def start_ws_session(self, scenario: str) -> Dict[str, Any]:
        """Open a playback session for /ws/live without bumping the epoch."""
        return self._open_session(scenario)

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
        # pipeline-backed playback: scenario datasets streamed window-by-window
        # through M1+M2 -> M3 -> fusion (no fabricated values on this path)
        self._pipeline_sessions: Dict[str, Dict[str, Any]] = {}
        self._sessions_by_scenario: Dict[str, str] = {}   # scenario -> open session_id
        self._scenario_dfs: Dict[str, Any] = {}   # df refs kept alive (stable id() for M3 IMU state)
        self._traj_cache: Dict[str, TrajectoryResponse] = {}
        self._ws_scenario: str = "gnss_spoof"
        self._ws_epoch: int = 0
        self._default_sid: Optional[str] = None
        self._lock = threading.Lock()

    def _try_init_pipeline(self) -> bool:
        try:
            from integration.pipeline import register_available_implementations
            from integration import interfaces  # noqa: F401
            register_available_implementations()
        except Exception as exc:
            _warn_once("pipeline_init", f"integration pipeline unavailable: {exc}")
            return False
        # Member imports fail SILENTLY inside register_available_implementations
        # (ImportError is swallowed per module), so a half-installed interpreter
        # (e.g. uvicorn running where pandas/scikit-learn are missing) would
        # otherwise look "ready" and crash mid-request. Real mode only when
        # every stage actually registered.
        from integration import interfaces
        missing = sorted(interfaces.MISSING)
        if missing:
            _warn_once(
                "pipeline_missing",
                "pipeline stages not registered: " + ", ".join(missing)
                + f" — install requirements.txt into this interpreter "
                  f"({sys.executable}); serving the labelled mock fallback instead",
            )
            return False
        return True

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
    # pipeline-backed scenario sessions (real M1+M2 -> M3 computation)
    # ------------------------------------------------------------------
    def _scenario_df(self, scenario: str) -> Optional[Any]:
        """Dataset for *scenario* (cached); None when the file is missing."""
        if scenario == "demo_story":
            # Demo mode (Step 11): the §22 story generator (clean -> GNSS
            # spoofing -> recovery) streamed through the REAL M1 -> M2 -> M3
            # pipeline — the same dataset `py -m member3_trust.src.demo`
            # asserts (7/7), on the dashboard.
            df = self._scenario_dfs.get(scenario)
            if df is None:
                try:
                    from member3_trust.src import eval_scenarios
                    df, _ = eval_scenarios.make_spoof_scenario(
                        n=3200, attack_start=1000, attack_end=1800)
                except Exception as exc:
                    _warn_once("demo_story", f"§22 demo generator unavailable: {exc}")
                    return None
                self._scenario_dfs[scenario] = df
            return df
        if scenario not in SCENARIO_DATASETS:
            return None
        df = self._scenario_dfs.get(scenario)
        if df is None:
            path = settings.data_dir / SCENARIO_DATASETS[scenario]
            if not path.exists():
                return None
            try:
                import pandas as pd
                df = pd.read_parquet(path)
            except Exception as exc:
                _warn_once(f"load:{scenario}", f"could not read {path}: {exc}")
                return None
            self._scenario_dfs[scenario] = df
        return df

    @staticmethod
    def _reset_imu() -> None:
        """Restart M3's IMU dead-reckoning when a new playback pass begins."""
        try:
            from member3_trust.src.eval_scenarios import _reset_imu_state
            _reset_imu_state()
        except Exception as exc:  # pragma: no cover
            _warn_once("imu_reset", f"IMU state reset failed: {exc}")

    def _open_pipeline_session(self, scenario: str, loop: bool = True,
                               allow_demo_fallback: bool = False) -> Optional[Dict[str, Any]]:
        """Open (or reuse) a session streaming *scenario*'s dataset through the pipeline.

        One session per scenario: the REST endpoint and /ws/live share it, so
        the M3 IMU dead-reckoning state (keyed by df identity) is never driven
        by two cursors at once. Nothing is precomputed — windows are scored on
        advance, so scenario switches are instant. Returns None when the
        pipeline or dataset is unavailable (caller falls back to the
        clearly-labelled mock story).
        """
        if not self._ready:
            return None
        df = self._scenario_df(scenario)
        name = scenario
        source = "pipeline"
        if df is None:
            if not (loop and allow_demo_fallback):
                return None
            # default stream: M4 spoof dataset when present, else the M3 §22
            # demo generator (clean -> spoof -> recovery)
            name = "fallback_spoof_demo"
            df = self._scenario_dfs.get(name)
            if df is None:
                try:
                    from member3_trust.src import eval_scenarios
                    df, _ = eval_scenarios.make_spoof_scenario(n=3200, attack_start=1000, attack_end=1800)
                except Exception as exc:
                    _warn_once("demo_df", f"scenario dataset unavailable: {exc}")
                    return None
                self._scenario_dfs[name] = df
            source = "demo_generator"
        existing = self._sessions_by_scenario.get(name)
        if existing is not None and existing in self._pipeline_sessions:
            st = self._pipeline_sessions[existing]
            return {"session_id": existing, "scenario": name,
                    "n_messages": max(1, len(st["df"]) // WINDOW), "source": source}
        self._reset_imu()
        sid = uuid.uuid4().hex[:10]
        self._pipeline_sessions[sid] = {
            "df": df, "scenario": name, "cursor": 0,
            "trust_history": [], "loop": loop,
        }
        self._sessions_by_scenario[name] = sid
        return {"session_id": sid, "scenario": name,
                "n_messages": max(1, len(df) // WINDOW), "source": source}

    def _advance_pipeline(self, session_id: str) -> Optional[TrustMessage]:
        """Score the session's next window through M1+M2 -> M3 -> fusion."""
        st = self._pipeline_sessions.get(session_id)
        if st is None:
            return None
        df = st["df"]
        cursor = st["cursor"]
        if cursor + WINDOW > len(df):
            if not st["loop"]:
                self._pipeline_sessions.pop(session_id, None)
                return None
            # wrap: restart the pass and M3's IMU dead-reckoning from row 0
            cursor = 0
            self._reset_imu()
        st["cursor"] = cursor + WINDOW
        window = df.iloc[cursor:cursor + WINDOW].reset_index(drop=True)

        from integration.pipeline import run_observation, temporal_context_rows
        from integration import interfaces
        from member3_trust.src import eval_scenarios

        # preceding rows -> M2 history (replay/stale seen-before, CR #5)
        ctx = temporal_context_rows()
        prior = df.iloc[max(0, cursor - ctx):cursor].reset_index(drop=True)
        result = run_observation(window, prior_rows=prior)
        obs = eval_scenarios.sensor_observations(
            df, slice(cursor, cursor + WINDOW), rng_seed=1000 + cursor,
            scores=result.get("scores", {}))
        trust_out = interfaces.compute_trust(result.get("scores", {}),
                                             st["trust_history"], observations=obs)
        # merge (a) M3's derived scores (e.g. cross_sensor_agreement) and
        # (b) M3's evidence AFTER M1/M2's — nothing upstream is overwritten
        result["scores"] = {**result.get("scores", {}), **trust_out.get("scores", {})}
        result["evidence"] = list(result.get("evidence", [])) + list(trust_out.get("evidence", []))
        result["trust"] = trust_out.get("trust", {})
        result["alert"] = trust_out.get("alert", {})
        try:
            state = interfaces.fuse(obs, result["trust"])
            result["trust"].setdefault("state_estimate", {}).update(state)
        except Exception as exc:
            _warn_once("fuse", f"fusion failed: {exc}")
        st["trust_history"].append(trust_out)
        if len(st["trust_history"]) > 200:
            st["trust_history"] = st["trust_history"][-200:]

        sensor_id = (str(window["sensor_id"].iloc[0])
                     if "sensor_id" in window.columns else "uav1_gnss")
        msg = TrustMessage(
            schema_version="1.0",
            observation_id=f"obs_{cursor:06d}",
            sensor_id=sensor_id,
            timestamp=float(window["timestamp"].iloc[0]),
            scores=Scores(**result.get("scores", {})),
            evidence=[EvidenceItem(**e) for e in result.get("evidence", [])],
            trust=TrustData(**result.get("trust", {})),
            alert=AlertData(**result.get("alert", {})),
        )
        return self._push_message(msg)

    def _run_pipeline(self) -> Optional[TrustMessage]:
        """Latest real pipeline message; seeds the default stream once."""
        if not self._ready:
            return None
        if self._history:
            return self._history[-1]
        try:
            opened = self._open_pipeline_session("gnss_spoof", loop=True,
                                                 allow_demo_fallback=True)
        except Exception as exc:
            _warn_once("seed_open", f"default session open failed: {exc}")
            return None
        if opened is None:
            return None
        self._default_sid = opened["session_id"]
        try:
            with self._lock:
                return self._advance_pipeline(self._default_sid)
        except Exception as exc:
            _warn_once("seed_advance", f"pipeline advance failed: {exc}")
            return None

    # ------------------------------------------------------------------
    def get_current_trust(self) -> TrustMessage:
        """Latest real pipeline message (never mixes mock values in once the
        pipeline has produced a real message)."""
        msg = self._run_pipeline()
        if msg is not None:
            return msg
        if self._history:
            return self._history[-1]
        return self._mock.get_current_trust()

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
        if self._ready:
            return []  # never serve mock evidence for a real-mode observation id
        return self._mock.get_evidence(observation_id)

    def get_alerts(self, active_only: bool = True, limit: int = 100) -> List[AlertItem]:
        if self._history:
            alerts = list(reversed(self._alerts))
            if active_only and alerts:
                last_ts = alerts[0].timestamp
                alerts = [a for a in alerts if a.timestamp >= last_ts - 30.0]
            return alerts[:limit]
        if self._ready:
            return []
        return self._mock.get_alerts(active_only, limit)

    def get_trajectory(self, scenario: Optional[str] = None) -> TrajectoryResponse:
        if scenario and scenario.startswith("real_"):
            from backend.app.services.real_data import replay_trajectory
            name = scenario[len("real_"):] or "geolife"
            try:
                return replay_trajectory(name)
            except Exception:
                pass
        if not self._ready:
            return self._mock.get_trajectory(scenario)

        key = scenario or "gnss_spoof"
        cached = self._traj_cache.get(key)
        if cached is not None:
            return cached
        try:
            resp = self._build_trajectory(key)
            if resp is not None:
                self._traj_cache[key] = resp
                return resp
        except Exception as exc:
            _warn_once(f"traj:{key}", f"trajectory build failed for {key}: {exc}")
        return self._mock.get_trajectory(scenario)

    def _build_trajectory(self, key: str) -> Optional[TrajectoryResponse]:
        """True/reported/fused trajectories for *key*, computed through M1+M2 -> M3.

        True positions come from M4's clean base track (the scenarios are
        row-aligned with ``data/synthetic/uav_normal_v1.parquet`` — parquet
        drops the truth attrs, so they are re-attached from the clean track).
        Returns None when the dataset is unavailable (caller falls back).
        """
        df = self._scenario_df(key)
        if df is None:
            return None
        import numpy as np
        from integration import interfaces
        from member3_trust.src import eval_scenarios
        from member3_trust.src.fusion import fuse
        from member3_trust.src.trust_engine import compute_trust

        # Truth position: parquet drops DataFrame.attrs, so regenerate the
        # seed-42 clean track M4 built every scenario from (row-aligned; the
        # attack functions only modify reported fields — build_datasets.py).
        truth_lat = truth_lon = None
        try:
            from member4_cyber.src.generate_data import make_clean_dataset
            base = make_clean_dataset()
            if len(base) >= len(df):
                truth_lat = base.attrs.get("truth_latitude")
                truth_lon = base.attrs.get("truth_longitude")
        except Exception as exc:
            _warn_once("truth", f"truth reconstruction unavailable: {exc}")

        trust_hist: List[Dict[str, Any]] = []
        true_t, rep_t, fus_t = [], [], []
        for w0 in range(0, len(df) - WINDOW + 1, WINDOW):
            window = df.iloc[w0:w0 + WINDOW].reset_index(drop=True)
            # preceding rows -> M2 history (replay/stale seen-before, CR #5)
            from integration.pipeline import score_window, temporal_context_rows
            prior = df.iloc[max(0, w0 - temporal_context_rows()):w0].reset_index(drop=True)
            try:
                scores: Dict[str, float] = score_window(window, prior_rows=prior).get("scores", {})
            except Exception:
                scores = {}
            obs = eval_scenarios.sensor_observations(
                df, slice(w0, w0 + WINDOW), rng_seed=2000 + w0, scores=scores)
            tres = compute_trust(scores, trust_hist, observations=obs)
            trust_hist.append(tres)
            est = fuse(obs, tres["trust"])
            ts = float(window["timestamp"].iloc[0])
            rlat = float(window["latitude"].mean())
            rlon = float(window["longitude"].mean())
            if truth_lat is not None and truth_lon is not None:
                tlat = float(np.mean(truth_lat[w0:w0 + WINDOW]))
                tlon = float(np.mean(truth_lon[w0:w0 + WINDOW]))
                true_t.append(TrajectoryPoint(timestamp=ts, lat=tlat, lon=tlon))
            rep_t.append(TrajectoryPoint(timestamp=ts, lat=rlat, lon=rlon))
            fus_t.append(TrajectoryPoint(timestamp=ts, lat=float(est["lat"]), lon=float(est["lon"]),
                                         velocity=float(est.get("velocity", 0))))
        return TrajectoryResponse(
            true_trajectory=true_t,
            reported_trajectory=rep_t,
            fused_trajectory=fus_t,
            scenario=key,
        )

    def start_attack_scenario(self, scenario: str) -> Dict[str, Any]:
        if scenario.startswith("real_"):
            # Replay REAL data (data/real/) precomputed through the M1->M2->M3 pipeline
            from backend.app.services.real_data import build_replay_messages
            name = scenario[len("real_"):] or "geolife"
            try:
                msgs = build_replay_messages(name)
            except Exception:
                msgs = []
            if msgs:
                sid = uuid.uuid4().hex[:10]
                session = PlaybackSession(
                    session_id=sid,
                    scenario=scenario,
                    start_time=time.time(),
                    speed=settings.ws_playback_speed,
                    is_active=True,
                    current_index=0,
                    messages=msgs,
                )
                self._playbacks[sid] = session
                return {"session_id": sid, "scenario": scenario,
                        "n_messages": len(msgs), "source": "real_data"}
            # real data not available — fall through to the scenario path below
        # Remember what /ws/live should stream; the epoch bump tells a
        # connected client to reopen its session for the new scenario.
        self._ws_scenario = scenario
        self._ws_epoch += 1
        try:
            opened = self._open_pipeline_session(scenario)
        except Exception as exc:
            _warn_once(f"open:{scenario}", f"pipeline session open failed: {exc}")
            opened = None
        if opened is not None:
            return opened
        # Pipeline/dataset unavailable: labelled mock-story fallback only.
        return self._mock.start_attack_scenario(scenario)

    def ws_stream_state(self):
        """(scenario, epoch) the /ws/live stream should play."""
        return self._ws_scenario, self._ws_epoch

    def start_ws_session(self, scenario: str) -> Dict[str, Any]:
        """Open a playback session for /ws/live without bumping the epoch."""
        try:
            opened = self._open_pipeline_session(scenario)
        except Exception as exc:
            _warn_once(f"open:{scenario}", f"pipeline session open failed: {exc}")
            opened = None
        if opened is not None:
            return opened
        return self._mock.start_ws_session(scenario)

    def stop_playback(self, session_id: str) -> None:
        if session_id == self._default_sid:
            return  # keep the seeded default stream alive
        st = self._pipeline_sessions.pop(session_id, None)
        if st is not None and self._sessions_by_scenario.get(st["scenario"]) == session_id:
            self._sessions_by_scenario.pop(st["scenario"], None)
        s = self._playbacks.get(session_id)
        if s:
            s.is_active = False
        self._mock.stop_playback(session_id)

    def get_playback(self, session_id: str) -> Optional[PlaybackSession]:
        return self._playbacks.get(session_id) or self._mock.get_playback(session_id)

    def advance_playback(self, session_id: str) -> Optional[TrustMessage]:
        if session_id in self._pipeline_sessions:
            try:
                with self._lock:
                    return self._advance_pipeline(session_id)
            except Exception as exc:
                _warn_once("advance", f"pipeline advance failed: {exc}")
                self._pipeline_sessions.pop(session_id, None)
                return None
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
