/**
 * Tests for the pure device-state / comparison helpers used by the
 * LIVE SENSOR INTEGRITY COMPARISON view.
 *
 * Run with:  node --test frontend/src/services/deviceState.test.mjs
 * (Node's built-in test runner — no extra dependencies, no browser needed.)
 *
 * What is mocked here: browser permission/hardware outcomes (GeolocationPositionError
 * codes) and clocks. What is NOT mocked: any trust value — those are produced by the
 * backend pipeline and are only asserted for pass-through/formatting behaviour.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  describeGeoError, geolocationUnsupported, freshness, hasComputedTrust,
  comparisonRows, formatMap, weightsOf, recommendedAction, sensorTrustOf,
  NOT_AVAILABLE, INSUFFICIENT_DATA, REAL_SOURCE_LABEL, SIM_SOURCE_LABEL,
} from './deviceState.js';

const NOW = 1_735_600_000;   // fixed clock for deterministic freshness

test('denied permission (code 1) maps to a denied state', () => {
  const s = describeGeoError({ code: 1, message: 'User denied Geolocation' });
  assert.equal(s.state, 'denied');
  assert.match(s.detail, /Permission denied/);
});

test('unavailable (code 2) and timeout (code 3) map to their own states', () => {
  assert.equal(describeGeoError({ code: 2, message: 'no fix' }).state, 'unavailable');
  assert.equal(describeGeoError({ code: 3, message: 'slow' }).state, 'timeout');
});

test('unknown geolocation error still yields a displayable state', () => {
  assert.equal(describeGeoError({}).state, 'error');
  assert.equal(describeGeoError(undefined).state, 'error');
});

test('browsers without the Geolocation API report unsupported', () => {
  assert.equal(geolocationUnsupported().state, 'unsupported');
});

test('freshness: fresh / aging / stale / unavailable', () => {
  assert.equal(freshness(NOW - 3, NOW).age, 'fresh');
  assert.equal(freshness(NOW - 30, NOW).age, 'aging');
  assert.equal(freshness(NOW - 600, NOW).age, 'stale');
  const none = freshness(null, NOW);
  assert.equal(none.label, NOT_AVAILABLE);
  assert.equal(none.stale, true);
  // a device clock slightly ahead must not produce a negative age
  assert.equal(freshness(NOW + 5, NOW).seconds, 0);
});

test('a message without pipeline output is not treated as computed trust', () => {
  assert.equal(hasComputedTrust(null), false);
  assert.equal(hasComputedTrust({}), false);
  assert.equal(hasComputedTrust({ trust: {} }), false);
  assert.equal(hasComputedTrust({ trust: { observation_trust: 0 } }), true);
});

test('empty weights / sensor trust are reported as unavailable, not zero', () => {
  assert.equal(weightsOf({ trust: { sensor_weights: {} } }), null);
  assert.equal(weightsOf({ trust: { sensor_weights: { gnss: 0.25 } } }).gnss, 0.25);
  assert.equal(formatMap(null), NOT_AVAILABLE);
  assert.equal(sensorTrustOf(null), null);
  assert.equal(recommendedAction({ alert: {} }), null);
});

test('real device with no computable window shows INSUFFICIENT DATA, never a score', () => {
  const rows = comparisonRows({ state: 'live', sessionRows: 3, lastRow: { timestamp: NOW - 2 } },
                              { scenario: 'normal', message: null }, NOW);
  const trust = rows.find((r) => r.metric === 'Observation trust');
  assert.equal(trust.real, INSUFFICIENT_DATA);
  assert.equal(rows.find((r) => r.metric === 'Integrity evidence').real, INSUFFICIENT_DATA);
  assert.equal(rows.find((r) => r.metric === 'Sensor contributions / fusion weights').real, NOT_AVAILABLE);
  // the real reading the device DID provide is still reported
  assert.match(rows.find((r) => r.metric === 'Freshness').real, /LIVE/);
});

test('comparison labels sources so real and simulated can never be confused', () => {
  const rows = comparisonRows({}, {}, NOW);
  const src = rows.find((r) => r.metric === 'Data source');
  assert.equal(src.real, REAL_SOURCE_LABEL);
  assert.equal(src.sim, SIM_SOURCE_LABEL);
  assert.match(src.real, /REAL/);
  assert.match(src.sim, /SIMULATED/);
});

test('comparison reports backend values verbatim when the pipeline produced them', () => {
  const msg = {
    timestamp: NOW - 1,
    trust: { observation_trust: 42.5, sensor_weights: { gnss: 0.125, imu: 0.4 } },
    alert: { level: 'AMBER', recommended_action: 'Reduce GNSS influence.' },
    evidence: [{ check: 'Cross-sensor agreement evidence', pass: false, detail: 'x' },
               { check: 'Historical reliability evidence', pass: true, detail: 'y' }],
  };
  const rows = comparisonRows({ state: 'live', message: msg }, { scenario: 'gnss_spoof', message: msg }, NOW);
  assert.equal(rows.find((r) => r.metric === 'Observation trust').real, '42.5 (AMBER)');
  assert.equal(rows.find((r) => r.metric === 'Integrity evidence').real, '2 items (1 failing)');
  assert.equal(rows.find((r) => r.metric === 'Recommended action').real, 'Reduce GNSS influence.');
  assert.equal(rows.find((r) => r.metric === 'Device / scenario state').sim, 'GNSS SPOOF');
});

test('disconnected real device reports NOT CONNECTED and unavailable metrics', () => {
  const rows = comparisonRows({ state: 'denied', detail: 'Permission denied' }, {}, NOW);
  assert.equal(rows.find((r) => r.metric === 'Device / scenario state').real, 'DENIED — Permission denied');
  assert.equal(rows.find((r) => r.metric === 'Latest observation time').real, NOT_AVAILABLE);
  assert.equal(rows.find((r) => r.metric === 'Freshness').real, NOT_AVAILABLE);
});
