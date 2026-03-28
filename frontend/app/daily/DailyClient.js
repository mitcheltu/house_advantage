'use client';

import { useMemo, useState } from 'react';

function formatDate(value) {
  if (!value) return '—';
  return String(value).slice(0, 10);
}

function formatDuration(seconds) {
  if (!seconds) return null;
  const total = Math.round(Number(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function safeParseEvidence(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  try { return JSON.parse(value); } catch { return null; }
}

function extractBillLinks(text) {
  if (!text) return [];
  const pattern = /\b(H\.?\s*R\.?\s*\d+|S\.?\s*\d+|H\.?\s*Res\.?\s*\d+|S\.?\s*Res\.?\s*\d+|H\.?\s*Con\.?\s*Res\.?\s*\d+|S\.?\s*Con\.?\s*Res\.?\s*\d+)\b/gi;
  const matches = [...new Set(text.match(pattern) || [])];
  return matches.map((m) => {
    const slug = m.replace(/\.\s*/g, '').replace(/\s+/g, '').toLowerCase();
    return { label: m, url: `https://www.congress.gov/bill/119th-congress/${slug.startsWith('s') ? 'senate' : 'house'}-bill/${slug.replace(/\D/g, '')}` };
  });
}

export default function DailyClient({ dailyReport, severeVideos }) {
  const defaultMain = useMemo(() => {
    if (dailyReport?.video_url) {
      return {
        type: 'daily',
        title: 'Daily Summary',
        subtitle: formatDate(dailyReport.report_date),
        videoUrl: dailyReport.video_url,
      };
    }
    const firstSevere = severeVideos.find((item) => item.video_url) || severeVideos[0];
    if (firstSevere?.video_url) {
      return {
        type: 'severe',
        title: firstSevere.audit_headline || 'Severe Case',
        subtitle: `${firstSevere.full_name || 'Unknown'} · ${firstSevere.ticker || '—'}`,
        videoUrl: firstSevere.video_url,
        tradeId: firstSevere.trade_id,
        narrative: firstSevere.audit_narrative,
        evidenceJson: firstSevere.audit_evidence_json,
        billExcerpt: firstSevere.audit_bill_excerpt,
        disclaimer: firstSevere.audit_disclaimer,
        riskLevel: firstSevere.audit_risk_level,
        bioguideId: firstSevere.bioguide_id,
        ticker: firstSevere.ticker,
        fullName: firstSevere.full_name,
      };
    }
    return {
      type: 'empty',
      title: 'No video available',
      subtitle: 'Run the daily job to generate media.',
      videoUrl: null,
    };
  }, [dailyReport, severeVideos]);

  const [mainVideo, setMainVideo] = useState(defaultMain);
  const [severePage, setSeverePage] = useState(0);
  const severePageSize = 6;

  const severePageCount = Math.max(1, Math.ceil(severeVideos.length / severePageSize));
  const pagedSevereVideos = severeVideos.slice(
    severePage * severePageSize,
    severePage * severePageSize + severePageSize,
  );

  const dailyStats = dailyReport
    ? [
        { label: 'Report Date', value: formatDate(dailyReport.report_date) },
        { label: 'Status', value: dailyReport.generation_status || 'unknown' },
        { label: 'Narration', value: dailyReport.narration_script ? 'Ready' : 'Missing' },
        { label: 'Video', value: dailyReport.video_url ? 'Ready' : 'Missing' },
      ]
    : [];

  return (
    <section className="daily-layout">
      <div className="daily-main">
        <div className="main-video-card">
          <div className="main-video-header">
            <div>
              <div className="eyebrow">Now Playing</div>
              <h2>{mainVideo.title}</h2>
              <p className="muted-line">{mainVideo.subtitle}</p>
            </div>
            {dailyReport?.video_url ? (
              <button
                type="button"
                className="ghost-button"
                onClick={() =>
                  setMainVideo({
                    type: 'daily',
                    title: 'Daily Summary',
                    subtitle: formatDate(dailyReport.report_date),
                    videoUrl: dailyReport.video_url,
                  })
                }
              >
                Reset to Daily
              </button>
            ) : null}
          </div>
          {mainVideo.videoUrl ? (
            <video className="hero-video" controls playsInline src={mainVideo.videoUrl} />
          ) : (
            <div className="video-placeholder">No video available yet.</div>
          )}

          {mainVideo.type === 'severe' && (mainVideo.narrative || mainVideo.evidenceJson || mainVideo.billExcerpt) ? (
            <div className="video-sources">
              <h4 className="video-sources-title">Sources &amp; Context</h4>
              {mainVideo.narrative ? (
                <p className="video-sources-narrative">{mainVideo.narrative}</p>
              ) : null}
              {(() => {
                const evidence = safeParseEvidence(mainVideo.evidenceJson);
                const factors = Array.isArray(evidence)
                  ? evidence
                  : Array.isArray(evidence?.key_factors)
                    ? evidence.key_factors
                    : [];
                if (!factors.length) return null;
                return (
                  <div className="video-sources-factors">
                    <span className="video-sources-label">Key Factors:</span>
                    {factors.map((f, i) => (
                      <span key={i} className="source-tag">{typeof f === 'string' ? f : JSON.stringify(f)}</span>
                    ))}
                  </div>
                );
              })()}
              {mainVideo.billExcerpt ? (
                <div className="video-sources-bills">
                  <span className="video-sources-label">Bill Reference:</span>
                  {(() => {
                    const links = extractBillLinks(mainVideo.billExcerpt);
                    if (links.length) {
                      return (
                        <>
                          <span className="video-sources-text">{mainVideo.billExcerpt}</span>
                          <div className="video-sources-links">
                            {links.map((link, i) => (
                              <a key={i} href={link.url} target="_blank" rel="noopener noreferrer" className="source-link">
                                {link.label} — Congress.gov ↗
                              </a>
                            ))}
                          </div>
                        </>
                      );
                    }
                    return <span className="video-sources-text">{mainVideo.billExcerpt}</span>;
                  })()}
                </div>
              ) : null}
              <div className="video-sources-links">
                {mainVideo.bioguideId ? (
                  <a href={`https://www.congress.gov/member/${(mainVideo.fullName || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}/${mainVideo.bioguideId}`} target="_blank" rel="noopener noreferrer" className="source-link">
                    {mainVideo.fullName || 'Politician'} — Congress.gov Profile ↗
                  </a>
                ) : null}
                {mainVideo.ticker ? (
                  <a href={`https://www.google.com/finance/quote/${mainVideo.ticker}:NASDAQ`} target="_blank" rel="noopener noreferrer" className="source-link">
                    {mainVideo.ticker} — Stock Data ↗
                  </a>
                ) : null}
              </div>
              {mainVideo.disclaimer ? (
                <p className="video-sources-disclaimer">{mainVideo.disclaimer}</p>
              ) : null}
            </div>
          ) : null}
        </div>

        {dailyStats.length ? (
          <div className="stats-row">
            {dailyStats.map((stat) => (
              <div className="stat-chip" key={stat.label}>
                <span>{stat.label}</span>
                <strong>{stat.value}</strong>
              </div>
            ))}
          </div>
        ) : null}

        <div className="severe-panel">
          <div className="panel-header">
            <div>
              <h3>Severe Case Focus</h3>
              <p>Click a clip to make it the main player.</p>
            </div>
            <button
              type="button"
              className="ghost-button"
              onClick={() =>
                dailyReport?.video_url
                  ? setMainVideo({
                      type: 'daily',
                      title: 'Daily Summary',
                      subtitle: formatDate(dailyReport.report_date),
                      videoUrl: dailyReport.video_url,
                    })
                  : null
              }
              disabled={!dailyReport?.video_url}
            >
              Focus Daily Summary
            </button>
          </div>
          <div className="video-grid">
            {dailyReport ? (
              <button
                type="button"
                className={`video-tile ${mainVideo.type === 'daily' ? 'active' : ''}`}
                onClick={() =>
                  dailyReport.video_url
                    ? setMainVideo({
                        type: 'daily',
                        title: 'Daily Summary',
                        subtitle: formatDate(dailyReport.report_date),
                        videoUrl: dailyReport.video_url,
                      })
                    : null
                }
                disabled={!dailyReport.video_url}
              >
                {dailyReport.video_url ? (
                  <video className="tile-video" muted playsInline preload="metadata" src={dailyReport.video_url} />
                ) : (
                  <div className="video-placeholder">Daily video pending</div>
                )}
                <div className="tile-meta">
                  <div className="tile-title">Daily Summary</div>
                  <div className="tile-subtitle">{formatDate(dailyReport.report_date)}</div>
                </div>
              </button>
            ) : null}
            {pagedSevereVideos.length ? (
              pagedSevereVideos.map((item) => {
                const isActive = mainVideo.tradeId && mainVideo.tradeId === item.trade_id;
                return (
                  <button
                    key={item.trade_id}
                    type="button"
                    className={`video-tile ${isActive ? 'active' : ''}`}
                    onClick={() =>
                      setMainVideo({
                        type: 'severe',
                        title: item.audit_headline || 'Severe Case',
                        subtitle: `${item.full_name || 'Unknown'} · ${item.ticker || '—'}`,
                        videoUrl: item.video_url,
                        tradeId: item.trade_id,
                        narrative: item.audit_narrative,
                        evidenceJson: item.audit_evidence_json,
                        billExcerpt: item.audit_bill_excerpt,
                        disclaimer: item.audit_disclaimer,
                        riskLevel: item.audit_risk_level,
                        bioguideId: item.bioguide_id,
                        ticker: item.ticker,
                        fullName: item.full_name,
                      })
                    }
                  >
                    {item.video_url ? (
                      <video className="tile-video" muted playsInline preload="metadata" src={item.video_url} />
                    ) : (
                      <div className="video-placeholder">Video pending</div>
                    )}
                    <div className="tile-meta">
                      <div className="tile-title">{item.audit_headline || 'Severe Case'}</div>
                      <div className="tile-subtitle">
                        {item.full_name || 'Unknown'} · {item.ticker || '—'} · {formatDate(item.trade_date)}
                      </div>
                      <div className="tile-subtitle">
                        Severity: {item.severity_quadrant || 'SEVERE'}
                        {item.video_duration ? ` · ${formatDuration(item.video_duration)}` : ''}
                      </div>
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="empty-state">No severe cases yet.</div>
            )}
          </div>
          {severeVideos.length > severePageSize ? (
            <div className="results-pagination">
              <button
                type="button"
                className="page-button"
                onClick={() => setSeverePage((prev) => Math.max(0, prev - 1))}
                disabled={severePage === 0}
                aria-label="Previous page"
              >
                ←
              </button>
              <span className="page-indicator">Page {severePage + 1} of {severePageCount}</span>
              <button
                type="button"
                className="page-button"
                onClick={() => setSeverePage((prev) => Math.min(severePageCount - 1, prev + 1))}
                disabled={severePage >= severePageCount - 1}
                aria-label="Next page"
              >
                →
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
