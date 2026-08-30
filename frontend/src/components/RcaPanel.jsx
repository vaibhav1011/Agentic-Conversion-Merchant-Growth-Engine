/**
 * Payment-failure root-cause panel. Aggregates Razorpay failure codes,
 * affected revenue, and which sessions were lost (abandoned) to each code.
 */
export default function RcaPanel({ rca }) {
  if (!rca || rca.length === 0) {
    return (
      <div className="card">
        <h3>Payment-failure RCA</h3>
        <p className="muted">No payment failures recorded yet.</p>
      </div>
    )
  }
  return (
    <div className="card">
      <h3>Payment-failure RCA</h3>
      <table>
        <thead>
          <tr>
            <th>Failure code</th>
            <th>Occurrences</th>
            <th>Affected revenue</th>
            <th>Lost sessions</th>
          </tr>
        </thead>
        <tbody>
          {rca.map((row) => (
            <tr key={row.failure_code}>
              <td><code>{row.failure_code}</code></td>
              <td>{row.occurrences}</td>
              <td>₹{Number(row.affected_revenue || 0).toLocaleString()}</td>
              <td>{(row.lost_sessions || []).length}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
