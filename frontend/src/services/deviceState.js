/**
 * Pure, dependency-free helpers for the LIVE SENSOR INTEGRITY COMPARISON view.
 *
 * Kept out of the React component so the permission / freshness / comparison
 * logic can be unit-tested with `node --test` (no browser, no extra deps).
 *
 * Nothing here computes or invents a trust score: trust and evidence always
 * come from the backend pipeline. These helpers only describe source state and
 * decide when a metric is NOT AVAILABLE / INSUFFICIENT DATA.
 */

/** Label shown for the real-device source (spec §4A). */
export const REAL_SOURCE_LABEL = 'REAL DEVICE DATA';
/** Label shown for the controlled-simulation source (spec §4B). */
export const SIM_SOURCE_LABEL = 'SIMULATED DATA — CONTROLLED SCENARIO';

export const NOT_AVAILABLE = 'NOT AVAILABLE';
export const INSUFFICIENT_DATA = 'INSUFFICIENT DATA';

/** Freshness thresholds (seconds) for a live device fix. */
export const FRESH_S = 15;      // <= fresh
export const STALE_S = 60;      // > stale (nothing in between is "aging")

/**
 * Map a browser GeolocationPositionError to a displayable connection state.
 * Handles the mockable/permission cases the spec asks about:
 * denied, unavailable, timeout, unsupported (no API at all).
 */
export function describeGeoError(err) {
  const code = err && typeof err.code === 'number' ? err.code : null;
  const message = (err && err.message) || '';
  if (code === 1) {
    return { state: 'denied', detail: `Permission denied${message ? ` — ${message}` : ''}` };
  }
  if (code === 2) {
    return { state: 'unavailable', detail: `Position unavailable — ${message || 'no fix from this device'}` };
  }
  if (code === 3) {
    return { state: 'timeout', detail: `Timed out waiting for a fix — ${message || 'device did not respond'}` };
  }
  return { state: 'error', detail: message || 'Geolocation error' };
}

/** State when the browser exposes no Geolocation API at all. */
export function geolocationUnsupported() {
  return { state: 'unsupported', detail: 'Geolocation is not supported in this browser' };
}

/**
 * Describe how old a real observation is, from its timestamp.
 * `nowS` is injectable so the behaviour is deterministic in tests.
 */
export function freshness(timestampS, nowS = Date.now() / 1000) {
  if (timestampS == null || !Number.isFinite(Number(timestampS))) {
    return { seconds: null, label: NOT_AVAILABLE, stale: true, age: 'unavailable' };
  }
  const seconds = Math.max(0, Number(nowS) - Number(timestampS));
  if (seconds <= FRESH_S) {
    return { seconds, label: `LIVE (${seconds.toFixed(1)}s ago)`, stale: false, age: 'fresh' };
  }
  if (seconds <= STALE_S) {
    return { seconds, label: `AGING (${seconds.toFixed(0)}s ago)`, stale: false, age: 'aging' };
  }
  return { seconds, label: `STALE (${seconds.toFixed(0)}s ago)`, stale: true, age: 'stale' };
}

/** True when a TrustMessage carries computed pipeline output for this window. */
export function hasComputedTrust(msg) {
  return !!(msg && msg.trust && typeof msg.trust.observation_trust === 'number');
}

/** Sensor weights, or null when the pipeline has not produced them. */
export function weightsOf(msg) {
  const w = msg && msg.trust && msg.trust.sensor_weights;
  return w && Object.keys(w).length ? w : null;
}

/** Per-sensor trust, or null when unavailable. */
export function sensorTrustOf(msg) {
  const st = msg && msg.trust && msg.trust.sensor_trust;
  return st && Object.keys(st).length ? st : null;
}

/** Recommended action, or null when the pipeline did not compute one. */
export function recommendedAction(msg) {
  const a = msg && msg.alert && msg.alert.recommended_action;
  return a || null;
}

/** Short human string for a weights/trust map, or NOT AVAILABLE. */
export function formatMap(map) {
  if (!map || !Object.keys(map).length) return NOT_AVAILABLE;
  return Object.entries(map)
    .map(([k, v]) => `${k} ${Number(v).toFixed(3)}`)
    .join(' · ');
}

/**
 * Build the side-by-side comparison rows (spec §4C).
 *
 * Every value comes from the backend; a metric that a source cannot produce
 * reports NOT AVAILABLE / INSUFFICIENT DATA instead of being invented.
 *
 * @param {object} real { message, lastRow, sessionRows, state, detail }
 * @param {object} sim  { message, scenario, autoRunning, events }
 * @param {number} nowS current epoch seconds (injectable for tests)
 */
export function comparisonRows(real = {}, sim = {}, nowS = Date.now() / 1000) {
  const realMsg = hasComputedTrust(real.message) ? real.message : null;
  const simMsg = hasComputedTrust(sim.message) ? sim.message : null;

  const realTs = real.lastRow?.timestamp ?? realMsg?.timestamp ?? null;
  const simTs = simMsg?.timestamp ?? null;

  const realEvidence = realMsg ? (realMsg.evidence || []) : null;
  const simEvidence = simMsg ? (simMsg.evidence || []) : null;

  const realState = real.state && real.state !== 'live'
    ? `${String(real.state).toUpperCase()} — ${real.detail || ''}`.trim()
    : null;

  return [
    {
      metric: 'Data source',
      real: REAL_SOURCE_LABEL,
      sim: SIM_SOURCE_LABEL,
    },
    {
      metric: 'Device / scenario state',
      real: realState || (real.sessionRows ? `${real.sessionRows} rows received` : 'NOT CONNECTED'),
      sim: sim.scenario ? String(sim.scenario).replace(/_/g, ' ').toUpperCase()
                        : NOT_AVAILABLE,
    },
    {
      metric: 'Latest observation time',
      real: realTs == null ? NOT_AVAILABLE : new Date(Number(realTs) * 1000).toISOString(),
      sim: simTs == null ? NOT_AVAILABLE : new Date(Number(simTs) * 1000).toISOString(),
    },
    {
      metric: 'Freshness',
      real: realTs == null ? NOT_AVAILABLE : freshness(realTs, nowS).label,
      sim: simTs == null ? NOT_AVAILABLE : freshness(simTs, nowS).label,
    },
    {
      metric: 'Integrity evidence',
      real: realEvidence == null ? INSUFFICIENT_DATA
        : `${realEvidence.length} items (${realEvidence.filter((e) => e.pass === false).length} failing)`,
      sim: simEvidence == null ? INSUFFICIENT_DATA
        : `${simEvidence.length} items (${simEvidence.filter((e) => e.pass === false).length} failing)`,
    },
    {
      metric: 'Observation trust',
      real: realMsg ? `${Number(realMsg.trust.observation_trust).toFixed(1)} (${realMsg.alert?.level || '—'})`
        : INSUFFICIENT_DATA,
      sim: simMsg ? `${Number(simMsg.trust.observation_trust).toFixed(1)} (${simMsg.alert?.level || '—'})`
        : NOT_AVAILABLE,
    },
    {
      metric: 'Sensor contributions / fusion weights',
      real: formatMap(weightsOf(realMsg)),
      sim: formatMap(weightsOf(simMsg)),
    },
    {
      metric: 'Recommended action',
      // A single device stream rarely gives the pipeline a full window, so the
      // honest answer is often that no action was computed for real data yet.
      real: recommendedAction(realMsg) || INSUFFICIENT_DATA,
      sim: recommendedAction(simMsg) || NOT_AVAILABLE,
    },
  ];
}

/** Short note explaining why the two columns are not always comparable. */
export const COMPARISON_CAVEAT =
  'Real device input and controlled simulated input are different data sources: '
  + 'the device provides whatever the browser exposes (often GNSS only), while the '
  + 'simulation provides a full multi-sensor track with cross-sensor evidence. '
  + 'Trust needs a full observation window, so single real readings show '
  + 'INSUFFICIENT DATA rather than an invented score.';
