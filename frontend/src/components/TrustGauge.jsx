import React from 'react';
import { trustLevelFromValue, trustValueColor } from '../services/api.js';

export default function TrustGauge({ trust, scores }) {
  const value = trust?.observation_trust ?? 0;
  const clamped = Math.max(0, Math.min(100, value));
  const radius = 76;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - clamped / 100);
  const color = trustValueColor(clamped);
  const level = trustLevelFromValue(clamped);

  const reliability = trust?.sensor_reliability ?? 94;
  const consensus = trust?.consensus_trust ?? value + 2;

  return (
    <div className="trust-gauge-wrap">
      <div className="gauge-container">
        <svg className="gauge-ring" viewBox="0 0 180 180">
          <circle className="gauge-circle-bg" cx="90" cy="90" r={radius} />
          <circle
            className="gauge-circle-fg"
            cx="90" cy="90" r={radius}
            stroke={color}
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
          />
        </svg>
        <div className="gauge-text">
          <div className="gauge-value" style={{ color }}>
            {clamped.toFixed(0)}
          </div>
          <div className="gauge-label">
            {level === 'RED' ? 'INTEGRITY ALERT' :
             level === 'AMBER' ? 'ELEVATED RISK' : 'TRUSTED'}
          </div>
        </div>
      </div>
      <div className="gauge-meta">
        <div className="meta-row">
          <span className="meta-label">Historical reliability</span>
          <span className="meta-value" style={{ color: trustValueColor(reliability) }}>
            {reliability.toFixed(1)}%
          </span>
        </div>
        <div className="meta-row">
          <span className="meta-label">Consensus trust</span>
          <span className="meta-value" style={{ color: trustValueColor(consensus) }}>
            {consensus.toFixed(1)}%
          </span>
        </div>
        <div className="meta-row">
          <span className="meta-label">Physical consistency</span>
          <span className="meta-value">{((scores?.physical_consistency ?? 0) * 100).toFixed(0)}%</span>
        </div>
        <div className="meta-row">
          <span className="meta-label">Temporal consistency</span>
          <span className="meta-value">{((scores?.temporal_consistency ?? 0) * 100).toFixed(0)}%</span>
        </div>
        <div className="meta-row">
          <span className="meta-label">Network integrity</span>
          <span className="meta-value">{((scores?.network_integrity ?? 0) * 100).toFixed(0)}%</span>
        </div>
        <div className="meta-row">
          <span className="meta-label">Cross-sensor agreement</span>
          <span className="meta-value">{((scores?.cross_sensor_agreement ?? 0) * 100).toFixed(0)}%</span>
        </div>
      </div>
    </div>
  );
}
