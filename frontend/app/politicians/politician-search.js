'use client';

import { useEffect, useMemo, useState } from 'react';
import { fetchPoliticianDetail, fetchPoliticians } from '@/lib/api';

function formatDate(value) {
  if (!value) return '—';
  return String(value).slice(0, 10);
}

function QuadrantPill({ value }) {
  if (!value) return null;
  return <span className={`pill ${String(value).toLowerCase()}`}>{value}</span>;
}

export default function PoliticianSearch() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const selectedTrade = useMemo(() => detail?.trades || [], [detail]);

  useEffect(() => {
    if (!query) {
      setResults([]);
      return;
    }

    const handle = setTimeout(() => {
      fetchPoliticians(query, 25, 0)
        .then((data) => setResults(data.items || []))
        .catch(() => setResults([]));
    }, 300);

    return () => clearTimeout(handle);
  }, [query]);

  async function handleSelect(politician) {
    setSelectedId(politician.id);
    setLoading(true);
    setError('');
    try {
      const data = await fetchPoliticianDetail(politician.id, 100);
      setDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load politician');
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="politician-layout">
      <div className="search-panel">
        <label className="search-label" htmlFor="politician-search">Search member</label>
        <div className="search-input">
          <input
            id="politician-search"
            type="search"
            placeholder="Search by name or state (e.g., Nancy Pelosi, CA)"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="results-list">
          {query && !results.length ? <div className="empty-state">No matches yet.</div> : null}
          {results.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`result-card ${selectedId === item.id ? 'active' : ''}`}
              onClick={() => handleSelect(item)}
            >
              <div>
                <div className="result-name">{item.full_name}</div>
                <div className="result-subtitle">
                  {item.party || '—'} · {item.state || '—'} · {item.chamber || '—'}
                </div>
              </div>
              <div className="result-meta">ID {item.id}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="detail-panel">
        {loading ? <div className="card">Loading…</div> : null}
        {error ? <div className="error">{error}</div> : null}
        {!loading && !detail && !error ? (
          <div className="card">Select a member to view trades and audit reports.</div>
        ) : null}

        {detail ? (
          <div className="detail-content">
            <div className="card">
              <div className="detail-header">
                <div>
                  <h2>{detail.politician.full_name}</h2>
                  <p className="muted-line">
                    {detail.politician.party || '—'} · {detail.politician.state || '—'} ·{' '}
                    {detail.politician.chamber || '—'} · District {detail.politician.district || '—'}
                  </p>
                </div>
                <div className="detail-meta">
                  <div>Bioguide: {detail.politician.bioguide_id || '—'}</div>
                  <div>Active: {detail.politician.end_date ? 'No' : 'Yes'}</div>
                </div>
              </div>
            </div>

            <div className="stats-row">
              <div className="stat-chip">
                <span>Total Trades</span>
                <strong>{detail.aggregate.total_trades}</strong>
              </div>
              <div className="stat-chip">
                <span>Severe</span>
                <strong>{detail.aggregate.quadrants.SEVERE}</strong>
              </div>
              <div className="stat-chip">
                <span>Systemic</span>
                <strong>{detail.aggregate.quadrants.SYSTEMIC}</strong>
              </div>
              <div className="stat-chip">
                <span>Avg Cohort</span>
                <strong>{detail.aggregate.avg_cohort_index}</strong>
              </div>
              <div className="stat-chip">
                <span>Avg Baseline</span>
                <strong>{detail.aggregate.avg_baseline_index}</strong>
              </div>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Ticker</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Quadrant</th>
                    <th>Audit</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedTrade.map((trade) => (
                    <tr key={trade.trade_id}>
                      <td>{formatDate(trade.trade_date)}</td>
                      <td>{trade.ticker || '—'}</td>
                      <td>{trade.trade_type || '—'}</td>
                      <td>{trade.amount_midpoint || '—'}</td>
                      <td>
                        <QuadrantPill value={trade.severity_quadrant || 'UNREMARKABLE'} />
                      </td>
                      <td>
                        {trade.audit_report_id ? (
                          <div>
                            <div className="audit-title">{trade.audit_headline || 'Audit Report'}</div>
                            <div className="audit-subtitle">Risk: {trade.risk_level || '—'}</div>
                          </div>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
