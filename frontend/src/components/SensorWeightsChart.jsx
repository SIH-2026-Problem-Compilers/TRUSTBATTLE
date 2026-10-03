import React from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

const SENSOR_COLORS = {
  gnss: '#ef4444',
  imu: '#10b981',
  visual: '#8b5cf6',
  net: '#06b6d4',
};

export default function SensorWeightsChart({ history }) {
  const h = history || [];
  const data = h.slice(-120).map((p, idx) => {
    const w = p.sensor_weights || {};
    const row = { idx };
    Object.entries(w).forEach(([k, v]) => { row[k] = Number(v) * 100; });
    return row;
  });

  const keys = data.length
    ? Object.keys(data[data.length - 1]).filter((k) => k !== 'idx')
    : ['gnss', 'imu', 'visual', 'net'];

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="idx"
            stroke="#64748b"
            tick={{ fontSize: 10 }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            stroke="#64748b"
            tick={{ fontSize: 10 }}
            tickLine={false}
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip
            contentStyle={{
              background: '#111827',
              border: '1px solid #334155',
              borderRadius: 6,
              fontSize: 12,
              color: '#e5e7eb',
            }}
            formatter={(v) => [`${Number(v).toFixed(0)}%`, '']}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
          {keys.map((k) => (
            <Area
              key={k}
              type="monotone"
              dataKey={k}
              stackId="1"
              name={k.toUpperCase()}
              stroke={SENSOR_COLORS[k] || '#64748b'}
              fill={SENSOR_COLORS[k] || '#64748b'}
              fillOpacity={0.55}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
