import React, { useEffect, useRef, useState } from 'react';
import AlertBanner from '../components/AlertBanner.jsx';
import TrustGauge from '../components/TrustGauge.jsx';
import SensorStatusCards from '../components/SensorStatusCards.jsx';
import EvidencePanel from '../components/EvidencePanel.jsx';
import TrustChart from '../components/TrustChart.jsx';
import SensorWeightsChart from '../components/SensorWeightsChart.jsx';
import MapView from '../components/MapView.jsx';
import ScenarioControl from '../components/ScenarioControl.jsx';
import { api, openLiveSocket } from '../services/api.js';

const REAL_GPS = 'real_gps';
const REAL_GEO = 'real_geolife';

function haversineM(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function bearingDeg(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const y = Math.sin(toRad(lon2 - lon1)) * Math.cos(toRad(lat2));
  const x =
    Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
    Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(toRad(lon2 - lon1));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function appendHistory(hist, msg) {
  return [
    ...hist,
    {
      timestamp: msg.timestamp,
      observation_trust: msg.trust?.observation_trust ?? 0,
      level: msg.alert?.level,
      sensor_weights: msg.trust?.sensor_weights || {},
    },
  ].slice(-500);
}

export default function DashboardPage() {
  const [current, setCurrent] = useState(null);
  const [history, setHistory] = useState([]);
  const [trajectory, setTrajectory] = useState(null);
  const [activeScenario, setActiveScenario] = useState('gnss_spoof');
  const [wsConnected, setWsConnected] = useState(false);
  const [realStatus, setRealStatus] = useState(null); // string message for real modes
  const historyRef = useRef([]);

  // mode: 'scenario' (synthetic WS playback) | 'real_gps' | 'real_geolife'
  const modeRef = useRef('scenario');
  const watchIdRef = useRef(null);
  const flushTimerRef = useRef(null);
  const pollTimerRef = useRef(null);
  const sessionIdRef = useRef(null);
  const batchRef = useRef([]);
  const lastFixRef = useRef(null);
  const motionRef = useRef(null);
  const seqRef = useRef(0);
  const reportedRef = useRef([]);
  const fusedRef = useRef([]);

  const applyMessage = (msg) => {
    setCurrent(msg);
    historyRef.current = appendHistory(historyRef.current, msg);
    setHistory([...historyRef.current]);
  };

  const rebuildTrajectory = (scenarioName) => {
    setTrajectory({
      true_trajectory: [...reportedRef.current],
      reported_trajectory: [...reportedRef.current],
      fused_trajectory: [...fusedRef.current],
      scenario: scenarioName,
    });
  };

  // --------------------------------------------------------------- initial fetch
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const [trust, hist, traj] = await Promise.all([
          api.getCurrentTrust(),
          api.getTrustHistory(undefined, 200),
          api.getTrajectory(),
        ]);
        if (!mounted) return;
        setCurrent(trust);
        setHistory(hist || []);
        historyRef.current = hist || [];
        setTrajectory(traj);
      } catch (e) {
        console.warn('initial fetch failed:', e);
      }
    })();
    return () => { mounted = false; };
  }, []);

  // --------------------------------------------------------------- WS (synthetic only)
  useEffect(() => {
    const sock = openLiveSocket(
      (msg) => {
        if (modeRef.current !== 'scenario') return; // real modes drive their own stream
        applyMessage(msg);
      },
      (open, err) => {
        setWsConnected(!!open);
        if (err) console.warn('ws:', err);
      }
    );
    return () => sock.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --------------------------------------------------------------- live GPS helpers
  const stopRealModes = () => {
    if (watchIdRef.current != null && navigator.geolocation) {
      try { navigator.geolocation.clearWatch(watchIdRef.current); } catch { /* noop */ }
      watchIdRef.current = null;
    }
    if (flushTimerRef.current) { clearInterval(flushTimerRef.current); flushTimerRef.current = null; }
    if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null; }
    sessionIdRef.current = null;
    lastFixRef.current = null;
    batchRef.current = [];
    if (motionRef.current?.listener && typeof window !== 'undefined') {
      window.removeEventListener('devicemotion', motionRef.current.listener);
    }
    motionRef.current = null;
  };

  const buildRow = (pos) => {
    const c = pos.coords;
    const t = pos.timestamp / 1000;
    const last = lastFixRef.current;
    let speed = Number.isFinite(c.speed) && c.speed != null ? c.speed : 0;
    let heading = Number.isFinite(c.heading) && c.heading != null ? c.heading : 0;
    let dt = 1;
    if (last) {
      dt = Math.max(t - last.t, 1e-3);
      const dist = haversineM(last.lat, last.lon, c.latitude, c.longitude);
      if (c.speed == null || !Number.isFinite(c.speed)) speed = dist / dt;
      if (c.heading == null || !Number.isFinite(c.heading)) {
        heading = dist > 0.5 ? bearingDeg(last.lat, last.lon, c.latitude, c.longitude) : last.heading;
      }
    }
    const m = motionRef.current?.value || null;
    const rad = (d) => (d * Math.PI) / 180;
    const acc = Math.max(0, Math.min(1, 1 - (c.accuracy || 10) / 50));
    const seq = seqRef.current++;
    const row = {
      timestamp: t,
      sensor_id: 'device_gnss',
      latitude: c.latitude,
      longitude: c.longitude,
      altitude: c.altitude || 0,
      velocity: speed,
      vx: speed * Math.sin(rad(heading)),
      vy: speed * Math.cos(rad(heading)),
      vz: 0,
      accel_x: m?.ax ?? 0,
      accel_y: m?.ay ?? 0,
      accel_z: m?.az ?? 0,
      gyro_x: m?.gx ?? 0,
      gyro_y: m?.gy ?? 0,
      gyro_z: m?.gz ?? 0,
      heading,
      gnss_quality: acc,
      packet_rate: 1 / dt,
      packet_delay_ms: dt * 1000,
      packet_loss: 0,
      sequence_number: seq,
      label: 0,
      attack_start: 0,
    };
    lastFixRef.current = { t, lat: c.latitude, lon: c.longitude, speed, heading };
    return row;
  };

  const flushBatch = async () => {
    if (!batchRef.current.length) return;
    const rows = batchRef.current.splice(0, batchRef.current.length);
    try {
      const res = await api.ingestReal(rows);
      setRealStatus(`Live GPS: ${res.total_rows} real rows scored`);
      const msg = res.trust;
      if (msg && modeRef.current === REAL_GPS) {
        applyMessage(msg);
        const est = msg.trust?.state_estimate;
        if (est && est.lat != null && est.lon != null) {
          fusedRef.current.push({
            timestamp: msg.timestamp,
            lat: Number(est.lat),
            lon: Number(est.lon),
            velocity: est.velocity ?? 0,
          });
        }
        rebuildTrajectory('real_device_gps');
      }
    } catch (e) {
      console.warn('real ingest failed:', e);
      setRealStatus(`Live GPS ingest error: ${e.message}`);
    }
  };

  const startRealGps = async () => {
    stopRealModes();
    modeRef.current = REAL_GPS;
    historyRef.current = [];
    setHistory([]);
    reportedRef.current = [];
    fusedRef.current = [];
    setTrajectory(null);
    setRealStatus('Live GPS: waiting for first fix...');

    if (!navigator.geolocation) {
      setRealStatus('Live GPS: geolocation not supported in this browser');
      return;
    }
    try { await api.startRealSession(); } catch (e) { console.warn('real session reset failed', e); }

    // iOS motion-sensor permission (must be called from a user gesture)
    try {
      if (typeof DeviceMotionEvent !== 'undefined' && typeof DeviceMotionEvent.requestPermission === 'function') {
        const p = await DeviceMotionEvent.requestPermission();
        if (p === 'granted') attachMotion();
      } else if (typeof DeviceMotionEvent !== 'undefined') {
        attachMotion();
      }
    } catch { /* motion optional */ }

    watchIdRef.current = navigator.geolocation.watchPosition(
      (pos) => {
        try {
          const row = buildRow(pos);
          batchRef.current.push(row);
          reportedRef.current.push({
            timestamp: row.timestamp,
            lat: row.latitude,
            lon: row.longitude,
            velocity: row.velocity,
          });
          if (modeRef.current === REAL_GPS) rebuildTrajectory('real_device_gps');
        } catch (e) {
          console.warn('fix handling failed', e);
        }
      },
      (err) => setRealStatus(`Live GPS: ${err.message} (allow location access)`),
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 }
    );
    flushTimerRef.current = setInterval(flushBatch, 2000);
  };

  const attachMotion = () => {
    const listener = (e) => {
      const a = e.acceleration || (e.accelerationIncludingGravity
        ? { x: e.accelerationIncludingGravity.x, y: e.accelerationIncludingGravity.y,
            z: (e.accelerationIncludingGravity.z ?? 9.81) - 9.81 }
        : null);
      const r = e.rotationRate || null;
      const toRad = (d) => (d != null && Number.isFinite(d) ? (d * Math.PI) / 180 : 0);
      motionRef.current = {
        listener,
        value: {
          ax: a?.x ?? 0, ay: a?.y ?? 0, az: a?.z ?? 0,
          gx: toRad(r?.alpha), gy: toRad(r?.beta), gz: toRad(r?.gamma),
        },
      };
    };
    window.addEventListener('devicemotion', listener);
    motionRef.current = { listener, value: null };
  };

  // --------------------------------------------------------------- real dataset replay
  const startRealReplay = async () => {
    stopRealModes();
    modeRef.current = REAL_GEO;
    historyRef.current = [];
    setHistory([]);
    setRealStatus('Real dataset: running M1 → M2 → M3 on real GPS windows (one-time ~90 s, cached after)...');
    try {
      const res = await api.startScenario(REAL_GEO);
      sessionIdRef.current = res.session_id;
      setRealStatus(`Real dataset: streaming ${res.n_messages} pipeline windows of real GPS`);
      const traj = await api.getTrajectory(REAL_GEO);
      setTrajectory(traj);
    } catch (e) {
      setRealStatus(`Real dataset unavailable: ${e.message}`);
      return;
    }
    pollTimerRef.current = setInterval(async () => {
      if (!sessionIdRef.current) return;
      try {
        const msg = await api.advanceScenario(sessionIdRef.current);
        if (modeRef.current === REAL_GEO) applyMessage(msg);
      } catch {
        // playback finished — restart the loop for continuous streaming
        try {
          const res = await api.startScenario(REAL_GEO);
          sessionIdRef.current = res.session_id;
        } catch { /* backend restarting; next tick retries */ }
      }
    }, 700);
  };

  // --------------------------------------------------------------- scenario selection
  const handleSelectScenario = async (key) => {
    const wasReal = modeRef.current !== 'scenario';
    if (wasReal) {
      stopRealModes();
      modeRef.current = 'scenario';
      setRealStatus(null);
      reportedRef.current = [];
      fusedRef.current = [];
    }
    setActiveScenario(key);

    if (key === REAL_GPS) {
      await startRealGps();
      return;
    }
    if (key === REAL_GEO) {
      await startRealReplay();
      return;
    }

    try {
      await api.startScenario(key);
      historyRef.current = [];
      setHistory([]);
      const traj = await api.getTrajectory(key);
      setTrajectory(traj);
    } catch (e) {
      console.warn('scenario start error:', e);
    }
  };

  useEffect(() => () => stopRealModes(), []);

  const isReal = modeRef.current !== 'scenario';

  return (
    <>
      <ScenarioControl
        active={activeScenario}
        onSelect={handleSelectScenario}
        wsConnected={wsConnected || isReal}
      />

      {realStatus && (
        <div
          style={{
            margin: '0 0 10px', padding: '8px 12px', borderRadius: 8,
            background: 'rgba(34,211,238,0.12)', border: '1px solid rgba(34,211,238,0.45)',
            color: '#22d3ee', fontSize: 13, fontWeight: 600,
          }}
        >
          {realStatus}
        </div>
      )}

      <AlertBanner alert={current?.alert} trust={current?.trust} />

      <div className="card">
        <div className="card-title">
          <span>Observation Trust</span>
          <span style={{ textTransform: 'none', fontWeight: 500, color: 'var(--text)' }}>
            {current?.timestamp != null ? `t = ${Number(current.timestamp).toFixed(1)}s` : '—'}
          </span>
        </div>
        <TrustGauge trust={current?.trust} scores={current?.scores} />
      </div>

      <div className="card">
        <div className="card-title">
          <span>Sensor Status</span>
        </div>
        <SensorStatusCards trust={current?.trust} />
      </div>

      <div className="card" style={{ gridColumn: 'span 1' }}>
        <div className="card-title">
          <span>Battlefield Position</span>
          <span style={{ textTransform: 'none', fontWeight: 500, color: 'var(--text-dim)' }}>
            {trajectory?.scenario || 'scenario'}
          </span>
        </div>
        <MapView trajectory={trajectory} currentState={current?.trust} />
      </div>

      <div className="card">
        <div className="card-title">
          <span>Evidence Checklist</span>
        </div>
        <EvidencePanel evidence={current?.evidence} alert={current?.alert} />
      </div>

      <div className="card">
        <div className="card-title">
          <span>Trust Over Time</span>
        </div>
        <TrustChart history={history} />
      </div>

      <div className="card">
        <div className="card-title">
          <span>Fusion Weights (stacked)</span>
        </div>
        <SensorWeightsChart history={history} />
      </div>
    </>
  );
}
