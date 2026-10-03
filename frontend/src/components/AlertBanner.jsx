import React from 'react';
import { trustLevelColor } from '../services/api.js';

export default function AlertBanner({ alert, trust }) {
  const level = alert?.level || 'GREEN';
  const causes = alert?.possible_causes || [];
  const message = alert?.message || 'Observations within normal integrity bounds.';

  const icon = level === 'RED' ? '⚠' : level === 'AMBER' ? '⚑' : '✓';

  return (
    <div className={`alert-banner ${level}`}>
      <div className="alert-icon">{icon}</div>
      <div className="alert-message">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            padding: '2px 8px',
            borderRadius: 4,
            background: trustLevelColor(level) + '22',
            border: `1px solid ${trustLevelColor(level)}55`,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 0.5,
          }}>
            {level}
          </span>
          <span>{message}</span>
          {trust?.observation_trust != null && (
            <span style={{ marginLeft: 'auto', fontSize: 13, opacity: 0.9 }}>
              Observation Trust: <strong>{trust.observation_trust.toFixed(1)}%</strong>
            </span>
          )}
        </div>
        {causes.length > 0 && (
          <div className="alert-causes">
            Possible causes: {causes.join(' · ')}
          </div>
        )}
      </div>
    </div>
  );
}
