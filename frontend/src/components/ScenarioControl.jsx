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

export default function ScenarioControl({ active, onSelect, wsConnected }) {
  return (
    <div className="scenario-control">
      <div className="scenario-label">Scenario Playback</div>
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
      <div className="ws-status">
        <span className={`ws-dot ${wsConnected ? '' : 'disconnected'}`} />
        <span>{wsConnected ? 'Live WebSocket' : 'Reconnecting...'}</span>
      </div>
    </div>
  );
}
