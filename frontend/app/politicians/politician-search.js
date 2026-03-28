'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchPoliticianDetail, fetchPoliticians, fetchTickerPrices } from '@/lib/api';

function formatDate(value) {
  if (!value) return '—';
  return String(value).slice(0, 10);
}

function QuadrantPill({ value }) {
  if (!value) return null;
  return <span className={`pill ${String(value).toLowerCase()}`}>{value}</span>;
}

function addDays(value, days) {
  const date = new Date(value);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function isBuyTrade(tradeType) {
  const normalized = String(tradeType || '').toLowerCase();
  return normalized.includes('buy') || normalized.includes('purchase');
}

function Sparkline({ prices, markerDate }) {
  if (!prices?.length) return <div className="sparkline-empty">No price data</div>;

  const width = 180;
  const height = 48;
  const padding = 4;
  const values = prices.map((p) => p.close);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = prices
    .map((p, idx) => {
      const x = padding + (idx / (prices.length - 1 || 1)) * (width - padding * 2);
      const y = padding + ((max - p.close) / range) * (height - padding * 2);
      return `${x},${y}`;
    })
    .join(' ');

  let markerX = null;
  if (markerDate) {
    const target = prices.findIndex((p) => p.date === markerDate);
    const index = target >= 0 ? target : Math.max(0, prices.length - 1);
    markerX = padding + (index / (prices.length - 1 || 1)) * (width - padding * 2);
  }

  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} role="img">
      <polyline points={points} fill="none" stroke="#2563eb" strokeWidth="2" />
      {markerX !== null ? (
        <line x1={markerX} y1={padding} x2={markerX} y2={height - padding} stroke="#ef4444" strokeWidth="2" />
      ) : null}
    </svg>
  );
}

function safeParseEvidence(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(value);
  } catch (err) {
    return null;
  }
}

function formatScore(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(1);
}

function scoreWidth(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 0;
  const clamped = Math.max(0, Math.min(100, Number(value)));
  return clamped;
}

export default function PoliticianSearch() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [priceCache, setPriceCache] = useState({});
  const inflightRef = useRef(new Set());

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

  useEffect(() => {
    if (!selectedTrade.length) return;

    selectedTrade.forEach((trade) => {
      if (!isBuyTrade(trade.trade_type) || !trade.ticker || !trade.trade_date) return;
      const start = addDays(trade.trade_date, -30);
      const end = addDays(trade.trade_date, 30);
      const key = `${trade.ticker}-${start}-${end}`;
      if (priceCache[key] || inflightRef.current.has(key)) return;

      inflightRef.current.add(key);
      fetchTickerPrices(trade.ticker, start, end)
        .then((data) => {
          setPriceCache((prev) => ({ ...prev, [key]: data.prices || [] }));
        })
        .catch(() => {
          setPriceCache((prev) => ({ ...prev, [key]: [] }));
        })
        .finally(() => {
          inflightRef.current.delete(key);
        });
    });
  }, [selectedTrade, priceCache]);

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
                    <th>Market</th>
                    <th>Score</th>
                    <th>Quadrant</th>
                    <th>Contextualizer</th>
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
                        {isBuyTrade(trade.trade_type) && trade.ticker && trade.trade_date ? (
                          (() => {
                            const start = addDays(trade.trade_date, -30);
                            const end = addDays(trade.trade_date, 30);
                            const key = `${trade.ticker}-${start}-${end}`;
                            return (
                              <Sparkline prices={priceCache[key]} markerDate={trade.trade_date} />
                            );
                          })()
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>
                        <div className="score-cell">
                          <div className="score-value">{formatScore(trade.max_index)}</div>
                          <div className="score-track">
                            <div className="score-fill" style={{ width: `${scoreWidth(trade.max_index)}%` }} />
                          </div>
                          <div className="score-meta">
                            Cohort {formatScore(trade.cohort_index)} · Baseline {formatScore(trade.baseline_index)}
                          </div>
                        </div>
                      </td>
                      <td>
                        <QuadrantPill value={trade.severity_quadrant || 'UNREMARKABLE'} />
                      </td>
                      <td>
                        {trade.audit_report_id ? (
                          <div className="context-block">
                            <div className="audit-title">{trade.audit_headline || 'Audit Report'}</div>
                            <div className="audit-subtitle">Risk: {trade.risk_level || '—'}</div>
                            {trade.narrative ? (
                              <p className="context-body">{trade.narrative}</p>
                            ) : null}
                            {trade.bill_excerpt ? (
                              <p className="context-caption">Bill excerpt: {trade.bill_excerpt}</p>
                            ) : null}
                            {trade.disclaimer ? (
                              <p className="context-caption">{trade.disclaimer}</p>
                            ) : null}
                            {(() => {
                              const evidence = safeParseEvidence(trade.evidence_json);
                              if (!evidence) return null;
                              const keys = Array.isArray(evidence)
                                ? evidence.slice(0, 3)
                                : Object.keys(evidence).slice(0, 3);
                              if (!keys.length) return null;
                              return (
                                <div className="context-evidence">
                                  Evidence: {keys.join(', ')}
                                </div>
                              );
                            })()}
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
