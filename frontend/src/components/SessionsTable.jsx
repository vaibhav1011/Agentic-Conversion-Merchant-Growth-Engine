const outcomeStyles = {
  recovered: 'ok',
  link_sent: 'info',
  abandoned: 'bad',
  escalated: 'warn',
  expired: 'bad',
  pending: 'neutral',
}

function formatTs(ts) {
  if (!ts) return '—'
  try { return new Date(ts).toLocaleString() } catch { return ts }
}

export default function SessionsTable({ sessions }) {
  if (!sessions || sessions.length === 0) {
    return (
      <div className="card">
        <h3>Recovery sessions</h3>
        <p className="muted">No sessions yet. Fire a `cart.abandoned` webhook to populate.</p>
      </div>
    )
  }
  return (
    <div className="card">
      <h3>Recovery sessions</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Session</th>
              <th>Cart value</th>
              <th>Intent</th>
              <th>Offer</th>
              <th>Turns</th>
              <th>Outcome</th>
              <th>Created</th>
              <th>Resolved</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => {
              const offer = s.offer || {}
              return (
                <tr key={s.session_id}>
                  <td><code>{s.session_id.slice(0, 12)}</code></td>
                  <td>₹{Number(s.cart_value).toLocaleString()}</td>
                  <td>{s.intent || '—'}</td>
                  <td>
                    {offer.kind === 'percent_discount'
                      ? `${offer.discount_pct}% off`
                      : offer.kind === 'flat_discount'
                        ? `₹${offer.flat_amount} off`
                        : (offer.kind || '—').replace(/_/g, ' ')}
                  </td>
                  <td>{s.negotiation_turns}</td>
                  <td><span className={`badge ${outcomeStyles[s.outcome] || 'neutral'}`}>{s.outcome}</span></td>
                  <td>{formatTs(s.created_at)}</td>
                  <td>{formatTs(s.resolved_at)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
