const API_BASE = '/api/v1';

async function _get(url) {
  const res = await fetch(`${API_BASE}${url}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${url}`);
  return res.json();
}

async function _post(url, body) {
  const res = await fetch(`${API_BASE}${url}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${url}`);
  return res.json();
}

export const api = {
  health: () => _get('/health'),
  getCurrentTrust: () => _get('/trust/current'),
  getTrustHistory: (sensorId, limit = 300) =>
    _get(`/trust/history?sensor_id=${sensorId ?? ''}&limit=${limit}`),
  getEvidence: (observationId) => _get(`/evidence/${encodeURIComponent(observationId)}`),
  getAlerts: (activeOnly = true, limit = 100) =>
    _get(`/alerts?active_only=${activeOnly}&limit=${limit}`),
  getTrajectory: (scenario) =>
    _get(`/trajectory${scenario ? `?scenario=${encodeURIComponent(scenario)}` : ''}`),
  startScenario: (scenario) => _post(`/demo/attack/${encodeURIComponent(scenario)}`),
  stopScenario: (sessionId) => _post(`/demo/stop/${encodeURIComponent(sessionId)}`),
  advanceScenario: (sessionId) => _post(`/demo/advance/${encodeURIComponent(sessionId)}`),

  // ---- real-data endpoints ----
  startRealSession: () => _post('/real/session'),
  ingestReal: (rows) => _post('/real/ingest', { rows }),
  getRealTrajectory: () => _get('/real/trajectory'),
  listRealDatasets: () => _get('/real/datasets'),

  // ---- TRUSTBATTLE LIVE (controlled live simulation) ----
  liveStatus: () => _get('/live/status'),
  liveScenario: (scenario) => _post(`/live/scenario/${encodeURIComponent(scenario)}`),
  liveAuto: () => _post('/live/auto'),
  liveStep: () => _post('/live/step'),
  liveEvents: (limit = 100) => _get(`/live/events?limit=${limit}`),
  liveTrajectory: () => _get('/live/trajectory'),
};

/**
 * Open a persistent WebSocket to /ws/live.
 * onMessage callback receives parsed JSON TrustMessage objects.
 * Returns control object with close() / isOpen().
 */
export function openLiveSocket(onMessage, onStatus) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/ws/live`;
  let ws;
  let closed = false;

  function connect() {
    try {
      ws = new WebSocket(url);
    } catch (e) {
      onStatus?.(false, e.message);
      return;
    }

    ws.onopen = () => onStatus?.(true);
    ws.onclose = () => {
      onStatus?.(false);
      if (!closed) setTimeout(connect, 2000);
    };
    ws.onerror = (e) => onStatus?.(false, e.message);
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data && typeof data === 'object' && data.type !== 'pong') {
          onMessage?.(data);
        }
      } catch {
        /* ignore non-JSON frames */
      }
    };
  }

  connect();

  return {
    close() {
      closed = true;
      try { ws?.close(); } catch { /* noop */ }
    },
    isOpen() {
      return ws?.readyState === WebSocket.OPEN;
    },
    send(text) {
      if (ws?.readyState === WebSocket.OPEN) ws.send(text);
    },
  };
}

export function trustLevelColor(level) {
  switch ((level || 'GREEN').toUpperCase()) {
    case 'RED': return '#ef4444';
    case 'AMBER': return '#f59e0b';
    default: return '#10b981';
  }
}

export function trustValueColor(v) {
  if (v == null) return '#94a3b8';
  if (v < 40) return '#ef4444';
  if (v < 70) return '#f59e0b';
  return '#10b981';
}

export function trustLevelFromValue(v) {
  if (v == null) return 'GREEN';
  if (v < 40) return 'RED';
  if (v < 70) return 'AMBER';
  return 'GREEN';
}
