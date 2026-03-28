const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

async function getJson(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${path}`);
  }

  return res.json();
}

export async function fetchSystemic() {
  return getJson('/api/v1/systemic');
}

export async function fetchLeaderboard() {
  return getJson('/api/v1/leaderboard?limit=25');
}

export async function fetchSevereLeaderboard(limit = 12) {
  return getJson(`/api/v1/leaderboard?quadrant=SEVERE&limit=${limit}`);
}

export async function fetchTradeAudit(tradeId) {
  return getJson(`/api/v1/audit/${tradeId}`);
}

export async function fetchLatestDailyReport() {
  return getJson('/api/v1/daily-report/latest');
}

export async function fetchPoliticians(search = '', limit = 25, offset = 0) {
  const query = new URLSearchParams();
  if (search) query.set('search', search);
  query.set('limit', String(limit));
  query.set('offset', String(offset));
  return getJson(`/api/v1/politicians?${query.toString()}`);
}

export async function fetchPoliticianDetail(politicianId, limit = 50) {
  return getJson(`/api/v1/politician/${politicianId}?limit=${limit}`);
}
