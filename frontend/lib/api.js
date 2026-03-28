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
