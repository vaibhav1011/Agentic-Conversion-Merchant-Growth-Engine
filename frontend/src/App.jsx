import { useCallback, useEffect, useState } from 'react'
import MetricsCards from './components/MetricsCards.jsx'
import RevenueChart from './components/RevenueChart.jsx'
import SessionsTable from './components/SessionsTable.jsx'
import RcaPanel from './components/RcaPanel.jsx'

const REFRESH_MS = 5000

export default function App() {
  const [health, setHealth] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [sessions, setSessions] = useState([])
  const [rca, setRca] = useState([])
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const [h, m, s, r] = await Promise.all([
        fetch('/health').then((r) => r.json()),
        fetch('/dashboard/metrics').then((r) => r.json()),
        fetch('/dashboard/sessions').then((r) => r.json()),
        fetch('/dashboard/rca').then((r) => r.json()),
      ])
      setHealth(h)
      setMetrics(m)
      setSessions(s)
      setRca(r)
      setError(null)
    } catch (err) {
      setHealth({ status: 'unreachable' })
      setError(String(err))
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, REFRESH_MS)
    return () => clearInterval(id)
  }, [refresh])

  return (
    <div className="app">
      <header className="app-header">
        <h1>Agentic Conversion &amp; Merchant Growth Engine</h1>
        <div className="header-right">
          <button className="ghost" onClick={refresh}>Refresh</button>
          <span className={`badge ${health?.status === 'ok' ? 'ok' : 'bad'}`}>
            backend: {health ? health.status : 'checking…'}
          </span>
        </div>
      </header>

      {error && <div className="card bad">{error}</div>}

      <MetricsCards metrics={metrics} />

      <div className="grid-2">
        <RevenueChart sessions={sessions} />
        <RcaPanel rca={rca} />
      </div>

      <SessionsTable sessions={sessions} />
    </div>
  )
}
