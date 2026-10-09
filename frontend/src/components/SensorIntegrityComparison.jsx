import React from 'react';
import {
  REAL_SOURCE_LABEL, SIM_SOURCE_LABEL, COMPARISON_CAVEAT,
  comparisonRows, freshness, hasComputedTrust, sensorTrustOf, weightsOf,
} from '../services/deviceState.js';

/**
 * LIVE SENSOR INTEGRITY COMPARISON (spec §4).
 *
 * Three panels + a timeline:
 *   A. Real Device        — whatever the browser ACTUALLY supplied (never invented)
 *   B. Controlled Sim     — the live simulation's real M1->M2->M3 output
 *   C. Side-by-side       — backend values only; missing metrics read
 *                           NOT AVAILABLE / INSUFFICIENT DATA
 *   D. Evidence timeline  — real backend events + real client-side observations
 *
 * All trust values, weights and evidence arrive as props computed by the
 * backend pipeline; this component only renders them.
 */

const STATE_BADGE = {
  live: '#10b981', connecting: '#f59e0b', waiting: '#f59e0b',
  denied: '#ef4444', unsupported: '#ef4444', unavailable: '#ef4444',
  timeout: '#f59e0b', error: '#ef4444', idle: '#64748b',
};

function PanelTitle({ label, color, right }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
      fontSize: 12, fontWeight: 800, letterSpacing: 0.6,
    }}>
      <span style={{
        padding: '3px 8px', borderRadius: 6, color, border: `1px solid ${color}88`,
        background: `${color}1a`,
      }}>
        {label}
      </span>
      {right && <span style={{ marginLeft: 'auto', fontWeight: 600, color: 'var(--text-dim)' }}>{right}</span>}
    </div>
  );
}

function Metric({ name, value, bad }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 12, padding: '2px 0' }}>
      <span style={{ minWidth: 172, color: 'var(--text-dim)' }}>{name}</span>
      <span style={{ color: bad ? '#ef4444' : 'var(--text)' }}>{value}</span>
    </div>
  );
}

export default function SensorIntegrityComparison({
  real,        // { state, detail, message, lastRow, sessionRows, motion }
  sim,        // { status, message, autoRunning, scenario }
  realEvents = [],   // client-observed real events (actual messages only)
  onRealConnect,
  onRealDisconnect,
  onScenario, // existing backend pathway (handleLiveScenario)
  wsConnected,
}) {
  const now = Date.now() / 1000;
  const r = real || {};
  const s = sim || {};
  const realMsg = hasComputedTrust(r.message) ? r.message : null;
  const simMsg = hasComputedTrust(s.message) ? s.message : null;
  const lastRowTs = r.lastRow?.timestamp ?? null;
  const fresh = freshness(lastRowTs, now);
  const realStateColor = STATE_BADGE[r.state] || '#64748b';

  const rows = comparisonRows(r, s, now);

  const simTrust = simMsg?.trust;
  const simST = sensorTrustOf(simMsg);
  const simW = weightsOf(simMsg);
  const simFails = simMsg ? (simMsg.evidence || []).filter((e) => e.pass === false) : [];

  // ---- D. evidence timeline: backend sim events + real client observations ----
  const timeline = [
    ...(s.events || []).map((e) => ({ time: e.time, text: `SIM · ${e.text}`, sim: true })),
    ...realEvents.map((e) => ({ time: e.time, text: `REAL · ${e.text}`, sim: false })),
  ]
    .sort((a, b) => (a.time < b.time ? 1 : a.time > b.time ? -1 : 0))
    .slice(0, 14);

  return (
    <div className="scenario-control" style={{ marginTop: 6 }}>
      <div className="scenario-label" style={{ fontSize: 13, fontWeight: 800, letterSpacing: 1 }}>
        LIVE SENSOR INTEGRITY COMPARISON
      </div>

      {/* ------------- A. REAL DEVICE PANEL ------------- */}
      <div style={{
        marginTop: 8, padding: '8px 10px', borderRadius: 8,
        border: '1px solid rgba(34,211,238,0.45)', background: 'rgba(34,211,238,0.07)',
      }}>
        <PanelTitle label={REAL_SOURCE_LABEL} color="#22d3ee"
          right={`state: ${(r.state || 'idle').toUpperCase()}`} />
        <Metric name="Connection / permission" value={r.detail || (r.state === 'live' ? 'Connected, receiving fixes' : 'Not connected')} bad={['denied', 'unsupported', 'error', 'timeout', 'unavailable'].includes(r.state)} />
        <Metric name="Latest observation" value={lastRowTs == null ? 'NOT AVAILABLE' : `${new Date(lastRowTs * 1000).toISOString()} — ${fresh.label}`} />
        <Metric
          name="GPS coordinates"
          value={r.lastRow && r.lastRow.latitude != null && r.lastRow.longitude != null
            ? `${Number(r.lastRow.latitude).toFixed(6)}, ${Number(r.lastRow.longitude).toFixed(6)}`
            : 'NOT AVAILABLE'}
        />
        <Metric name="Motion readings (DeviceMotion)"
          value={r.motion
            ? 'AVAILABLE (accelerometer supplied by this browser)'
            : 'UNAVAILABLE — no motion sensor/permission (optional; demo does not require it)'} />
        <Metric name="Integrity trust (computed)"
          value={realMsg
            ? `${Number(realMsg.trust.observation_trust).toFixed(1)} (${realMsg.alert?.level || '—'}) — ${realMsg.evidence?.length || 0} evidence items`
            : 'INSUFFICIENT DATA — the pipeline needs a full observation window (multiple readings) before it computes trust'}
          bad={!realMsg} />
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 6 }}>
          Source is what this browser actually reported. GPS position accuracy does not, by
          itself, prove authenticity — the pipeline's evidence is what assesses integrity.
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button className="scenario-btn" style={{ background: '#22d3ee', borderColor: '#22d3ee', color: '#05242c', fontWeight: 700 }}
            onClick={onRealConnect}>Connect live device</button>
          <button className="scenario-btn" onClick={onRealDisconnect}>Disconnect</button>
        </div>
      </div>

      {/* ------------- B. CONTROLLED SIMULATION PANEL ------------- */}
      <div style={{
        marginTop: 10, padding: '8px 10px', borderRadius: 8,
        border: '1px solid rgba(245,158,11,0.5)', background: 'rgba(245,158,11,0.07)',
      }}>
        <PanelTitle label={SIM_SOURCE_LABEL} color="#f59e0b"
          right={`scenario: ${(s.scenario || '—').replace(/_/g, ' ').toUpperCase()}${s.autoRunning ? ' · AUTO' : ''}`} />
        <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
          {[['normal', 'NORMAL'], ['gnss_spoof', 'GNSS SPOOF'], ['normal', 'RECOVER']].map(([k, label], i) => (
            <button key={i} className="scenario-btn"
              style={{ background: label === 'GNSS SPOOF' ? '#ef4444' : '#10b981', borderColor: label === 'GNSS SPOOF' ? '#ef4444' : '#10b981', color: '#04140c', fontWeight: 700 }}
              disabled={s.autoRunning}
              onClick={() => onScenario(k)}>
              {label}
            </button>
          ))}
        </div>
        <Metric name="Observation trust (M3)"
          value={simTrust
            ? `${Number(simTrust.observation_trust).toFixed(1)} (${simMsg.alert?.level || '—'})`
            : 'NOT AVAILABLE — start the simulation'}
          bad={!simTrust} />
        <Metric name="Per-sensor trust"
          value={simST ? Object.entries(simST).map(([k, v]) => `${k} ${Number(v).toFixed(1)}`).join(' · ') : 'NOT AVAILABLE'} />
        <Metric name="Fusion weights"
          value={simW ? Object.entries(simW).map(([k, v]) => `${k} ${Number(v).toFixed(3)}`).join(' · ') : 'NOT AVAILABLE'} />
        <Metric name="Evidence (this window)"
          value={simMsg ? `${(simMsg.evidence || []).length} items — ${simFails.length} failing` : 'NOT AVAILABLE'} />
        {simMsg?.alert?.recommended_action && (
          <Metric name="Recommended action" value={simMsg.alert.recommended_action} />
        )}
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 6 }}>
          Values above are computed by M1 → M2 → M3 from generated input observations — no
          score is scripted or hardcoded in the UI.
        </div>
      </div>

      {/* ------------- C. SIDE-BY-SIDE COMPARISON ------------- */}
      <div style={{ marginTop: 10 }}>
        <div className="scenario-label" style={{ fontSize: 12 }}>
          Side-by-side (backend values only)
        </div>
        <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--text-dim)' }}>
              <th style={{ padding: '4px 6px', width: '24%' }}>Metric</th>
              <th style={{ padding: '4px 6px', color: '#22d3ee' }}>REAL DEVICE DATA</th>
              <th style={{ padding: '4px 6px', color: '#f59e0b' }}>SIMULATED DATA</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metric} style={{ borderTop: '1px solid rgba(148,163,184,0.15)' }}>
                <td style={{ padding: '4px 6px', color: 'var(--text-dim)' }}>{row.metric}</td>
                <td style={{ padding: '4px 6px' }}>{row.real}</td>
                <td style={{ padding: '4px 6px' }}>{row.sim}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 6 }}>
          {COMPARISON_CAVEAT}
        </div>
      </div>

      {/* ------------- D. EVIDENCE TIMELINE ------------- */}
      <div style={{ marginTop: 10 }}>
        <div className="scenario-label" style={{ fontSize: 12 }}>
          Evidence timeline (computed events only){wsConnected === false ? ' — WS reconnecting' : ''}
        </div>
        {timeline.length === 0 ? (
          <div style={{ fontSize: 11.5, color: 'var(--text-dim)', padding: '4px 0' }}>
            No computed events yet — connect the device or start the simulation.
          </div>
        ) : (
          <div style={{
            maxHeight: 130, overflowY: 'auto', fontFamily: 'ui-monospace, monospace',
            fontSize: 11.5, background: 'rgba(2,6,23,0.55)', borderRadius: 8,
            border: '1px solid rgba(148,163,184,0.2)', padding: '6px 10px',
          }}>
            {timeline.map((e, i) => (
              <div key={i} style={{ display: 'flex', gap: 10, padding: '1px 0' }}>
                <span style={{ color: '#64748b' }}>{e.time}</span>
                <span style={{ color: e.sim ? '#f59e0b' : '#22d3ee' }}>{e.text}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
