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
