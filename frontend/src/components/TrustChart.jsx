import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from 'recharts';

export default function TrustChart({ history }) {
  const data = (history || [])
    .map((p, idx) => ({
      idx,
      t: p.timestamp != null ? Number(p.timestamp).toFixed(1) : idx,
      trust: Number(p.observation_trust ?? 0),
      label: p.level,
    }))
    .slice(-200);

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="t"
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
            ticks={[0, 20, 40, 60, 80, 100]}
          />
          <Tooltip
            contentStyle={{
              background: '#111827',
              border: '1px solid #334155',
              borderRadius: 6,
              fontSize: 12,
              color: '#e5e7eb',
            }}
            labelStyle={{ color: '#94a3b8' }}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
          <ReferenceLine y={70} stroke="#10b981" strokeDasharray="3 3" label={{ value: 'GREEN ≥70', position: 'right', fontSize: 10, fill: '#10b981' }} />
          <ReferenceLine y={40} stroke="#f59e0b" strokeDasharray="3 3" label={{ value: 'AMBER ≥40', position: 'right', fontSize: 10, fill: '#f59e0b' }} />
          <Line
            type="monotone"
            dataKey="trust"
            name="Observation Trust"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#3b82f6' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
