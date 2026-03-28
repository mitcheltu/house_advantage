import { fetchLeaderboard, fetchSystemic } from '@/lib/api';

function StatCard({ label, value, subtext }) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
      {subtext ? <div className="card-subtext">{subtext}</div> : null}
    </div>
  );
}

export default async function HomePage() {
  let systemic = null;
  let leaderboard = null;
  let error = null;

  try {
    [systemic, leaderboard] = await Promise.all([fetchSystemic(), fetchLeaderboard()]);
  } catch (err) {
    error = err instanceof Error ? err.message : 'Unknown error';
  }

  return (
    <main className="container">
      <header className="header">
        <h1>House Advantage</h1>
        <p>Daily anomaly intelligence for congressional stock trades.</p>
      </header>

      {error ? (
        <section className="error">Backend unavailable: {error}</section>
      ) : null}

      {systemic ? (
        <section>
          <h2>Systemic Snapshot</h2>
          <div className="stats-grid">
            <StatCard label="Total Scored" value={systemic.total_scored} />
            <StatCard
              label="SEVERE"
              value={systemic.quadrants.SEVERE.count}
              subtext={`${systemic.quadrants.SEVERE.pct}%`}
            />
            <StatCard
              label="SYSTEMIC"
              value={systemic.quadrants.SYSTEMIC.count}
              subtext={`${systemic.quadrants.SYSTEMIC.pct}%`}
            />
            <StatCard
              label="Audit Triggered"
              value={systemic.audit_triggered.count}
              subtext={`${systemic.audit_triggered.pct}%`}
            />
          </div>
        </section>
      ) : null}

      <section>
        <h2>Leaderboard</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Politician</th>
                <th>Ticker</th>
                <th>Type</th>
                <th>Cohort</th>
                <th>Baseline</th>
                <th>Quadrant</th>
              </tr>
            </thead>
            <tbody>
              {(leaderboard?.items || []).map((row) => (
                <tr key={row.trade_id}>
                  <td>{String(row.trade_date).slice(0, 10)}</td>
                  <td>{row.full_name || 'Unknown'}</td>
                  <td>{row.ticker}</td>
                  <td>{row.trade_type}</td>
                  <td>{row.cohort_index}</td>
                  <td>{row.baseline_index}</td>
                  <td>
                    <span className={`pill ${String(row.severity_quadrant).toLowerCase()}`}>
                      {row.severity_quadrant}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
