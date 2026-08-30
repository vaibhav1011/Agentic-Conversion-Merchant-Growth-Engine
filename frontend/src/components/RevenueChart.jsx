import {
  Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

/**
 * Revenue-recovered + lost chart. Aggregates sessions by outcome so the
 * merchant can see where value flows.
 */
export default function RevenueChart({ sessions }) {
  const buckets = { recovered: 0, link_sent: 0, abandoned: 0, escalated: 0, expired: 0 }
  for (const s of sessions || []) {
    if (buckets[s.outcome] !== undefined) buckets[s.outcome] += Number(s.cart_value || 0)
  }
  const data = [
    { outcome: 'recovered', label: 'Recovered', value: buckets.recovered },
    { outcome: 'link_sent', label: 'Pending', value: buckets.link_sent },
    { outcome: 'abandoned', label: 'Abandoned', value: buckets.abandoned },
    { outcome: 'escalated', label: 'Escalated', value: buckets.escalated },
    { outcome: 'expired', label: 'Expired', value: buckets.expired },
  ]
  const colours = {
    recovered: '#4ade80',
    link_sent: '#60a5fa',
    abandoned: '#f87171',
    escalated: '#fbbf24',
    expired: '#94a3b8',
  }

  return (
    <div className="card">
      <h3>Revenue by outcome</h3>
      <div style={{ width: '100%', height: 280 }}>
        <ResponsiveContainer>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#232a45" />
            <XAxis dataKey="label" stroke="#8b93b0" />
            <YAxis stroke="#8b93b0" />
            <Tooltip
              contentStyle={{ background: '#111831', border: '1px solid #232a45' }}
              formatter={(v) => `₹${v.toLocaleString()}`}
            />
            <Legend />
            <Bar dataKey="value" name="Cart value (₹)">
              {data.map((entry) => (
                <Cell key={entry.outcome} fill={colours[entry.outcome]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
