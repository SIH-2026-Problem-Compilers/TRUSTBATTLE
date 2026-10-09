import React from 'react';

/**
 * TRUSTBATTLE LIVE — presentation control panel (spec §6A, §7, §8, §12, §14).
 *
 * Buttons drive the backend live controller (POST /api/v1/live/...), which
 * changes the controlled INPUT data only. Every trust value, weight and
 * evidence item shown on the dashboard is computed by the real
 * M1 -> M2 -> M3 pipeline — this panel never fabricates or hardcodes scores.
 */

const ACTIONS = [
  { key: 'normal', label: 'NORMAL', color: '#10b981' },
  { key: 'gnss_spoof', label: 'GNSS SPOOF', color: '#ef4444' },
  { key: 'replay', label: 'REPLAY', color: '#f59e0b' },
  { key: 'telemetry_manip', label: 'TELEMETRY MANIP', color: '#f97316' },
  { key: 'sensor_malfunction', label: 'SENSOR MALFUNCTION', color: '#ec4899' },
  { key: 'reset', label: 'RESET', color: '#64748b' },
];

const SCENARIO_LABEL = {
  normal: 'NORMAL',
  gnss_spoof: 'GNSS SPOOFING',
  replay: 'REPLAY / STALE DATA',
  telemetry_manip: 'TELEMETRY MANIPULATION',
  sensor_malfunction: 'SENSOR MALFUNCTION',
};

const PIPELINE_STEPS = [
  { key: 'data', label: 'DATA', always: true },
  { key: 'm1_physical', label: 'M1 Physical' },
  { key: 'm2_temporal', label: 'M2 Temporal' },
  { key: 'm3_trust', label: 'M3 Trust' },
  { key: 'fusion', label: 'Fusion' },
];

export default function LiveControl({ status, autoRunning, onScenario, onAuto }) {
  const s = status || {};
  const pipeline = s.pipeline || {};
  const events = s.events || [];
  const level = (s.alert_level || 'GREEN');

  return (
    <div className="scenario-control live-control">
      {/* ---- A. SYSTEM STATUS (§6A) ---- */}
      <div className="scenario-label" style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
        <span style={{ fontSize: 15, fontWeight: 800, letterSpacing: 1 }}>
          TRUSTBATTLE LIVE
        </span>
        <span style={{ fontSize: 12, opacity: 0.85 }}>
          LIVE INFORMATION INTEGRITY MONITOR
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
          <span
            className="live-dot"
            style={{
              width: 9, height: 9, borderRadius: '50%', display: 'inline-block',
              background: autoRunning ? '#ef4444' : '#22c55e',
              boxShadow: `0 0 8px ${autoRunning ? '#ef4444' : '#22c55e'}`,
              animation: 'livePulse 1.4s ease-in-out infinite',
            }}
          />
          <strong style={{ color: autoRunning ? '#ef4444' : '#22c55e' }}>● LIVE</strong>
        </span>
      </div>
      <div className="scenario-label" style={{ fontSize: 12 }}>
        Data Source: <strong>Controlled Live Simulation</strong>
        {' '}— synthetic observations scored by the real M1→M2→M3 pipeline.
        {' '}Current Scenario: <strong>{SCENARIO_LABEL[s.scenario] || s.scenario || '—'}</strong>
      </div>

      {/* ---- 7. CONTROL BUTTONS ---- */}
      <div className="scenario-buttons" style={{ marginTop: 8 }}>
        {ACTIONS.map((a) => (
          <button
            key={a.key}
            className={`scenario-btn ${s.scenario === a.key || (a.key === 'reset' && false) ? 'active' : ''}`}
            style={s.scenario === a.key ? { background: a.color, borderColor: a.color } : {}}
            onClick={() => onScenario(a.key)}
            disabled={autoRunning}
            title={a.key === 'reset'
              ? 'Reset the simulation track (same seed — replayable)'
              : `Switch controlled input scenario to ${a.label}`}
          >
            {a.label}
          </button>
        ))}
        <button
          className="scenario-btn"
          style={{
            background: autoRunning ? '#b91c1c' : '#eab308',
            borderColor: '#eab308', fontWeight: 800,
          }}
          onClick={onAuto}
          disabled={autoRunning}
        >
          {autoRunning ? '● DEMO RUNNING…' : '▶ RUN LIVE DEMO'}
        </button>
      </div>

      <div className="scenario-label" style={{ marginTop: 6, fontSize: 11, opacity: 0.8 }}>
        Live Demonstration — Controlled Data. Trust, weights and evidence are
        computed by M1/M2/M3 from the generated observations (never scripted).
      </div>

      {/* ---- 12. PIPELINE STATUS ---- */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, opacity: 0.7, marginRight: 4 }}>Pipeline:</span>
        {PIPELINE_STEPS.map((st, i) => {
          const ok = st.always ? s.observation_trust != null : !!pipeline[st.key];
          return (
            <React.Fragment key={st.key}>
              {i > 0 && <span style={{ opacity: 0.5, fontSize: 11 }}>↓</span>}
              <span
                style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 6,
                  border: `1px solid ${ok ? '#10b98166' : '#64748b44'}`,
                  background: ok ? '#10b98118' : 'transparent',
                  color: ok ? '#10b981' : 'var(--text-dim)',
                  fontWeight: 700,
                }}
                title={ok ? `${st.label} produced output for the current window` : `${st.label} has no output yet`}
              >
                {st.label} {ok ? '✓' : '…'}
              </span>
            </React.Fragment>
          );
        })}
        <span
          style={{
            fontSize: 11, padding: '3px 8px', borderRadius: 6,
            border: '1px solid #ef444466', background: '#ef444418',
            color: '#ef4444', fontWeight: 800,
          }}
        >
          Dashboard ● LIVE
        </span>
      </div>

      {/* ---- 14. EVENT LOG ---- */}
      {events.length > 0 && (
        <div style={{
          marginTop: 10, maxHeight: 120, overflowY: 'auto',
          fontFamily: 'ui-monospace, monospace', fontSize: 11.5,
          background: 'rgba(2,6,23,0.55)', borderRadius: 8,
          border: '1px solid rgba(148,163,184,0.2)', padding: '6px 10px',
        }}>
          {events.slice().reverse().map((e, i) => (
            <div key={i} style={{ display: 'flex', gap: 10, padding: '1px 0' }}>
              <span style={{ color: '#64748b' }}>{e.time}</span>
              <span style={{
                color: /SPOOF|REPLAY|TELEMETRY|MALFUNCTION|DROPPING|REDUCED/.test(e.text) ? '#f59e0b'
                  : /RECOVERING|RESET|ONLINE|COMPLETE/.test(e.text) ? '#10b981' : '#94a3b8',
              }}>
                {e.text}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
