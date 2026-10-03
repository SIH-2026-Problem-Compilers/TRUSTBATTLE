import React from 'react';

export default function EvidencePanel({ evidence, alert }) {
  const items = evidence || [];
  const recommended = alert?.recommended_action;

  return (
    <div>
      <div className="evidence-list">
        {items.length === 0 && (
          <div style={{ fontSize: 12, color: 'var(--text-dim)', padding: 10 }}>
            Awaiting first observation...
          </div>
        )}
        {items.map((e, i) => {
          const pass = e.pass === true || e.pass === 1;
          return (
            <div key={i} className={`evidence-item ${pass ? '' : 'fail'}`}>
              <div className={`evidence-status ${pass ? 'pass' : 'fail'}`}>
                {pass ? '✓' : '✗'}
              </div>
              <div style={{ flex: 1 }}>
                <div className="evidence-check">{e.check}</div>
                {e.detail && <div className="evidence-detail">{e.detail}</div>}
              </div>
            </div>
          );
        })}
      </div>
      {recommended && (
        <div className="recommendation-box">
          <strong>Recommended action: </strong>
          {recommended}
        </div>
      )}
    </div>
  );
}
