export default function MetricsCards({ metrics }) {
  if (!metrics) return null
  const cards = [
    { label: 'Recovered revenue', value: `₹${metrics.recovered_revenue.toLocaleString()}`, accent: 'ok' },
    { label: 'Conversion rate', value: `${(metrics.conversion_rate * 100).toFixed(1)}%`, accent: 'ok' },
    { label: 'Escalation rate', value: `${(metrics.escalation_rate * 100).toFixed(1)}%`, accent: metrics.escalation_rate > 0.2 ? 'warn' : 'ok' },
    { label: 'Total sessions', value: metrics.total_sessions, accent: 'neutral' },
    { label: 'Pending (link sent)', value: metrics.link_sent_sessions, accent: 'neutral' },
    { label: 'Expired (silent)', value: metrics.expired_sessions, accent: 'bad' },
  ]
  return (
    <div className="metrics-grid">
      {cards.map((c) => (
        <div key={c.label} className="card metric">
          <div className="metric-label">{c.label}</div>
          <div className={`metric-value ${c.accent}`}>{c.value}</div>
        </div>
      ))}
    </div>
  )
}
