import { fetchLatestDailyReport, fetchSevereLeaderboard, fetchTradeAudit } from '@/lib/api';
import DailyClient from './daily/DailyClient';

function selectVideoAsset(mediaAssets) {
  if (!Array.isArray(mediaAssets)) return null;
  return (
    mediaAssets.find((asset) => String(asset.asset_type || '').toLowerCase().includes('video') && asset.storage_url) ||
    mediaAssets.find((asset) => asset.storage_url && String(asset.storage_url).includes('.mp4')) ||
    null
  );
}

export default async function HomePage() {
  let dailyReport = null;
  let severeVideos = [];
  let error = null;

  try {
    const [dailyReportData, severeData] = await Promise.all([
      fetchLatestDailyReport().catch(() => null),
      fetchSevereLeaderboard(12).catch(() => null),
    ]);

    dailyReport = dailyReportData;
    const severeItems = severeData?.items || [];

    severeVideos = await Promise.all(
      severeItems.map(async (item) => {
        const audit = await fetchTradeAudit(item.trade_id).catch(() => null);
        const videoAsset = selectVideoAsset(audit?.media_assets || []);
        return {
          ...item,
          audit_headline: audit?.audit_report?.headline || null,
          video_url: videoAsset?.storage_url || null,
          video_duration: videoAsset?.duration_seconds || null,
        };
      })
    );
  } catch (err) {
    error = err instanceof Error ? err.message : 'Unknown error';
  }

  return (
    <main className="container">
      <header className="header">
        <h1>Daily Summary</h1>
        <p>Watch the daily narrative and review severe case videos.</p>
      </header>

      {error ? <section className="error">Backend unavailable: {error}</section> : null}

      <DailyClient dailyReport={dailyReport} severeVideos={severeVideos} />
    </main>
  );
}
