import React from 'react';
import { trustLevelFromValue, trustValueColor } from '../services/api.js';

const SENSOR_LABELS = {
  gnss: { name: 'GNSS', desc: 'GPS / Global Nav', icon: '🛰' },
  imu: { name: 'IMU', desc: 'Inertial Measurement', icon: '📐' },
  visual: { name: 'Visual', desc: 'Camera / Vision', icon: '👁' },
  net: { name: 'Network', desc: 'Telemetry Link', icon: '📡' },
};

export default function SensorStatusCards({ trust }) {
  // Per-sensor values shown here are CURRENT observation trust (dynamic),
  // not historical sensor reliability — see TrustGauge for the reliability
  // baseline. Fallback only fires when the backend omits the field.
  const st = trust?.sensor_trust || {};
  const sw = trust?.sensor_weights || {};
  const reliability = trust?.sensor_reliability ?? 94;

  const sensors = Object.keys({ ...SENSOR_LABELS, ...st, ...sw });

  return (
    <div className="sensor-cards">
      {sensors.map((key) => {
        const meta = SENSOR_LABELS[key] || { name: key, desc: key, icon: '◉' };
        const t = st[key] != null ? st[key] : reliability;
        const w = sw[key] != null ? sw[key] : (1 / sensors.length);
        const level = trustLevelFromValue(t);
        const color = trustValueColor(t);
        return (
          <div key={key} className={`sensor-card ${level}`}>
            <div className="sensor-name">
              <span>
                <span style={{ marginRight: 6 }}>{meta.icon}</span>
                {meta.name}
              </span>
              <strong style={{ color, fontSize: 16 }}>{t.toFixed(0)}%</strong>
            </div>
            <div className="sensor-trust-bar">
              <div
                className="sensor-trust-fill"
                style={{ width: `${Math.max(0, Math.min(100, t))}%`, background: color }}
              />
            </div>
            <div className="sensor-info">
              <span>{meta.desc}</span>
              <span>Weight {(w * 100).toFixed(0)}%</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
