import React, { useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, CircleMarker } from 'react-leaflet';
import L from 'leaflet';

const CARTO_KEY = import.meta.env.VITE_CARTO_KEY || '';
const CARTO_QS = CARTO_KEY ? `?key=${CARTO_KEY}` : '';

const PALETTE = {
  true: '#10b981',
  reported: '#ef4444',
  fused: '#3b82f6',
};

function pathOf(arr) {
  return (arr || []).map((p) => [Number(p.lat), Number(p.lon)]).filter(([a, b]) => isFinite(a) && isFinite(b));
}

function centerOf(arrs) {
  const all = arrs.flat().filter((p) => isFinite(Number(p?.lat)) && isFinite(Number(p?.lon)));
  if (!all.length) return [28.61, 77.21];  // Delhi-region reference airfield (India), matches pipeline data
  const lats = all.map((p) => Number(p.lat));
  const lons = all.map((p) => Number(p.lon));
  return [lats.reduce((a, b) => a + b, 0) / lats.length,
          lons.reduce((a, b) => a + b, 0) / lons.length];
}

function boundsFor(arrs) {
  const pts = arrs.flat().filter((p) => isFinite(Number(p?.lat)) && isFinite(Number(p?.lon)));
  if (!pts.length) return null;
  const lats = pts.map((p) => Number(p.lat));
  const lons = pts.map((p) => Number(p.lon));
  return [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]];
}

const startIcon = L.divIcon({
  className: '',
  html: `<div style="
    width: 14px; height: 14px; border-radius: 50%;
    background: #10b981; border: 2px solid #fff;
    box-shadow: 0 0 0 2px #10b98155;"></div>`,
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

export default function MapView({ trajectory, currentState }) {
  const trueTraj = trajectory?.true_trajectory || [];
  const repTraj = trajectory?.reported_trajectory || [];
  const fusTraj = trajectory?.fused_trajectory || [];
  const mapRef = useRef(null);

  const center = useMemo(() => centerOf([trueTraj, repTraj, fusTraj]), [trueTraj, repTraj, fusTraj]);
  const bounds = useMemo(() => boundsFor([trueTraj, repTraj, fusTraj]), [trueTraj, repTraj, fusTraj]);

  useEffect(() => {
    if (bounds && mapRef.current) {
      try {
        const map = mapRef.current;
        if (map && typeof map.fitBounds === 'function') {
          map.fitBounds(bounds, { padding: [40, 40] });
        }
      } catch { /* noop */ }
    }
  }, [bounds]);

  const last = fusTraj[fusTraj.length - 1] || repTraj[repTraj.length - 1] || trueTraj[trueTraj.length - 1];
  const current = currentState?.state_estimate || last || {};

  return (
    <div className="map-wrapper">
      <MapContainer
        ref={mapRef}
        center={center}
        zoom={13}
        scrollWheelZoom={true}
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url={`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png${CARTO_QS}`}
          maxZoom={19}
        />

        <Polyline positions={pathOf(trueTraj)} color={PALETTE.true} weight={3} opacity={0.9} />
        <Polyline positions={pathOf(repTraj)} color={PALETTE.reported} weight={2} opacity={0.8} dashArray="4 4" />
        <Polyline positions={pathOf(fusTraj)} color={PALETTE.fused} weight={3} opacity={0.9} />

        {trueTraj[0] && (
          <Marker position={[Number(trueTraj[0].lat), Number(trueTraj[0].lon)]} icon={startIcon}>
            <Popup>Start — true position</Popup>
          </Marker>
        )}

        {current?.lat != null && current?.lon != null && (
          <CircleMarker
            center={[Number(current.lat), Number(current.lon)]}
            radius={8}
            pathOptions={{ color: PALETTE.fused, fillColor: PALETTE.fused, fillOpacity: 1, weight: 2 }}
          >
            <Popup>
              <strong>Live fused estimate</strong><br />
              Trust: {currentState?.observation_trust?.toFixed?.(1) ?? '—'}%<br />
              Lat: {Number(current.lat).toFixed(6)}<br />
              Lon: {Number(current.lon).toFixed(6)}
            </Popup>
          </CircleMarker>
        )}
      </MapContainer>

      <div className="map-legend">
        <div className="legend-item">
          <span className="legend-swatch" style={{ background: PALETTE.true }} />
          <span>True trajectory</span>
        </div>
        <div className="legend-item">
          <span className="legend-swatch" style={{ background: PALETTE.reported }} />
          <span>Reported (GNSS)</span>
        </div>
        <div className="legend-item">
          <span className="legend-swatch" style={{ background: PALETTE.fused }} />
          <span>Trust-aware fusion</span>
        </div>
      </div>
    </div>
  );
}
