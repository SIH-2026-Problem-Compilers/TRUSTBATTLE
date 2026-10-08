import React from 'react';

const SCENARIOS = [
  { key: 'normal', label: 'Normal', color: '#10b981' },
  { key: 'gnss_spoof', label: 'GNSS Spoofing', color: '#ef4444' },
  { key: 'replay', label: 'Replay / Stale', color: '#f59e0b' },
  { key: 'telemetry_manip', label: 'Telemetry Manip', color: '#f97316' },
  { key: 'network_anomaly', label: 'Network Anomaly', color: '#8b5cf6' },
  { key: 'sensor_malfunction', label: 'Sensor Malfunction', color: '#ec4899' },
  { key: 'cross_sensor_conflict', label: 'Cross-Sensor Conflict', color: '#06b6d4' },
  { key: 'mixed_c20', label: 'Mixed 20%', color: '#6366f1' },
];

const REAL_SCENARIOS = [
  { key: 'real_geolife', label: 'Real Dataset (GPS traces)', color: '#a3e635' },
  { key: 'real_gps', label: 'Live Device GPS', color: '#22d3ee' },
];

export default function ScenarioControl({ active, onSelect, wsConnected }) {
  return (
    <div className="scenario-control">
      <div className="scenario-label">
        Demo mode — §22 story: normal → GNSS spoofing → recovery (real M1→M2→M3 pipeline)
      </div>
      <div className="scenario-buttons">
        <button
          className={`scenario-btn ${active === 'demo_story' ? 'active' : ''}`}
          style={active === 'demo_story' ? { background: '#eab308', borderColor: '#eab308' } : {}}
          onClick={() => onSelect('demo_story')}
        >
          ▶ Run §22 Demo
        </button>
      </div>
      <div className="scenario-label" style={{ marginTop: 8 }}>
        Scenario Playback — controlled simulation (not real battlefield data)
      </div>
      <div className="scenario-buttons">
        {SCENARIOS.map((s) => (
          <button
            key={s.key}
            className={`scenario-btn ${active === s.key ? 'active' : ''}`}
            style={active === s.key ? { background: s.color, borderColor: s.color } : {}}
            onClick={() => onSelect(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="scenario-label" style={{ marginTop: 8 }}>Real public GPS data — model predicts live</div>
      <div className="scenario-buttons">
        {REAL_SCENARIOS.map((s) => (
          <button
            key={s.key}
            className={`scenario-btn ${active === s.key ? 'active' : ''}`}
            style={active === s.key ? { background: s.color, borderColor: s.color } : {}}
            onClick={() => onSelect(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="ws-status">
        <span className={`ws-dot ${wsConnected ? '' : 'disconnected'}`} />
        <span>{wsConnected ? 'Live WebSocket' : 'Reconnecting...'}</span>
      </div>
    </div>
  );
}
