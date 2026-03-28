import {
  fetchLatestDailyReport,
  fetchLeaderboard,
  fetchSystemic,
  fetchTradeAudit,
} from '@/lib/api';

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
  let dailyReport = null;
  let auditPreview = null;
  let error = null;

  try {
    [systemic, leaderboard, dailyReport] = await Promise.all([
      fetchSystemic(),
      fetchLeaderboard(),
      fetchLatestDailyReport().catch(() => null),
    ]);

    const topTradeId = leaderboard?.items?.[0]?.trade_id;
    if (topTradeId) {
      auditPreview = await fetchTradeAudit(topTradeId).catch(() => null);
    }
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

      {dailyReport ? (
        <section>
          <h2>Daily GenMedia Snapshot</h2>
          <div className="stats-grid">
            <StatCard label="Report Date" value={String(dailyReport.report_date).slice(0, 10)} />
            <StatCard label="Generation Status" value={dailyReport.generation_status || 'unknown'} />
            <StatCard label="Has Veo Prompt" value={dailyReport.veo_prompt ? 'Yes' : 'No'} />
            <StatCard label="Has Narration" value={dailyReport.narration_script ? 'Yes' : 'No'} />
          </div>
          {dailyReport.video_url ? (
            <p className="muted-line">Video URL: {dailyReport.video_url}</p>
          ) : null}
        </section>
      ) : null}

      {auditPreview?.audit_report ? (
        <section>
          <h2>Auditor Preview (Top Flagged Trade)</h2>
          <div className="card">
            <div className="card-label">{auditPreview.audit_report.headline}</div>
            <div className="card-subtext">
              Risk: {auditPreview.audit_report.risk_level} · Quadrant: {auditPreview.audit_report.severity_quadrant}
            </div>
            <p>{auditPreview.audit_report.narrative}</p>
            <div className="card-subtext">
              Media assets: {(auditPreview.media_assets || []).length}
            </div>
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
