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

export default function DashboardPage() {
  const [current, setCurrent] = useState(null);
  const [history, setHistory] = useState([]);
  const [trajectory, setTrajectory] = useState(null);
  const [activeScenario, setActiveScenario] = useState('gnss_spoof');
  const [wsConnected, setWsConnected] = useState(false);
  const historyRef = useRef([]);

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

  useEffect(() => {
    const sock = openLiveSocket(
      (msg) => {
        setCurrent(msg);
        historyRef.current = [
          ...historyRef.current,
          {
            timestamp: msg.timestamp,
            observation_trust: msg.trust?.observation_trust ?? 0,
            level: msg.alert?.level,
            sensor_weights: msg.trust?.sensor_weights || {},
          },
        ].slice(-500);
        setHistory([...historyRef.current]);
      },
      (open, err) => {
        setWsConnected(!!open);
        if (err) console.warn('ws:', err);
      }
    );
    return () => sock.close();
  }, []);

  const handleSelectScenario = async (key) => {
    setActiveScenario(key);
    try {
      const res = await api.startScenario(key);
      historyRef.current = [];
      setHistory([]);
      const traj = await api.getTrajectory(key);
      setTrajectory(traj);
    } catch (e) {
      console.warn('scenario start error:', e);
    }
  };

  return (
    <>
      <ScenarioControl
        active={activeScenario}
        onSelect={handleSelectScenario}
        wsConnected={wsConnected}
      />

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
