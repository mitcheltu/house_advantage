# House Advantage — API Migration Notes

## ProPublica Congress API → Congress.gov API

### Why

ProPublica's Congress API was **archived on February 4, 2025**. The GitHub repo (propublica/congress-api-docs) is read-only. The API no longer returns data.

### Replacement

The **Congress.gov API** (Library of Congress) is the official government replacement. It covers all the same data with slightly different endpoint structures.

**Sign-up:** https://api.congress.gov/sign-up/  
**Docs:** https://api.congress.gov/  

### Endpoint Mapping

| Data | ProPublica (dead) | Congress.gov (active) |
|------|-------------------|----------------------|
| All members | `GET /congress/v1/{congress}/{chamber}/members.json` | `GET /v3/member/congress/{congress}?api_key=...` |
| Member detail | `GET /congress/v1/members/{id}.json` | `GET /v3/member/{bioguideId}?api_key=...` |
| Committees | `GET /congress/v1/{congress}/{chamber}/committees.json` | `GET /v3/committee/{congress}?api_key=...` |
| Committee members | `GET /congress/v1/{congress}/{chamber}/committees/{id}.json` | `GET /v3/committee/{committeeCode}?api_key=...` |
| Member votes | `GET /congress/v1/members/{id}/votes.json` | `GET /v3/member/{bioguideId}?api_key=...` (includes votes) |
| Bill details | `GET /congress/v1/bills/{congress}/{bill-id}.json` | `GET /v3/bill/{congress}/{billType}/{billNumber}?api_key=...` |
| Vote details | N/A | `GET /v3/vote/{congress}/{chamber}?api_key=...` |

### Key Differences

1. **Auth:** ProPublica used `X-API-Key` header. Congress.gov uses `?api_key=` query parameter.
2. **IDs:** ProPublica used internal member IDs. Congress.gov uses **bioguide IDs** (e.g., `P000197` for Nancy Pelosi).
3. **Pagination:** Congress.gov returns paginated results with `pagination.next` URL in response.
4. **Rate Limit:** Congress.gov allows 5,000 requests/hour (ProPublica was also ~5,000/day).
5. **Response format:** Congress.gov returns nested JSON with a top-level key matching the resource type.

### Impact on MVP Blueprint

The MVP blueprint references ProPublica in several places. The data schema (tables, columns) is unchanged — only the ingestion scripts differ. The `politician_id` field uses bioguide IDs, which Congress.gov natively supports.

---

## Congress.gov Vote Endpoints — Limitations (March 2026)

### House Votes
Congress.gov provides a **House vote endpoint**: `GET /v3/house-vote/{congress}?api_key=...`

- Returns paginated roll-call votes with bill references, dates, and results
- Individual member positions available via sub-endpoint per vote
- Rate limit: ~1.5s delay between calls recommended. Collection of ~460 votes takes ~40 minutes.
- **Note:** `collect_votes()` in `collect_congress_gov.py` is NOT called by `collect_all()` (Step 1) because early testing revealed timeout/crash issues with the member positions sub-endpoint. It must be invoked separately or as a dedicated script.

### Senate Votes
Congress.gov does **NOT** have a Senate vote endpoint. Senate votes are collected from **senate.gov XML** instead:
- URL pattern: `https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress}{session}/vote_{congress}_{session}_{number:05d}.xml`
- This is handled by `collect_senate_votes.py` (Step 3)
- Senate votes use LIS member IDs (e.g., `S001` for the presiding officer) which are mapped to bioguide IDs using `senators_cfm.xml`

### Merged Output
Both House and Senate votes merge into a single `votes_raw.csv`:
- Step 3 (Senate) reads the existing House `votes_raw.csv` and concatenates Senate votes
- `politician_votes_raw.csv` must be manually merged with `senate_politician_votes_raw.csv` (Senate collector does not auto-merge positions)

---

## yfinance for Sector Lookups (March 2026)

For the `industry_sector` field in congressional trades, we use **yfinance** to look up sector information:

- API: `yfinance.Ticker(symbol).info['sector']` → maps to one of 7 model sectors
- Mapping: GICS sectors → model sectors (defense, finance, healthcare, energy, tech, telecom, agriculture)
- Coverage: ~170 tickers mapped, covering 45.7% of congressional trades
- Full lookup results cached in `backend/data/raw/ticker_sector_lookup.json`
- Static mapping lives in `TICKER_SECTOR_MAP` dict in `merge_trades.py`

---

## SEC 13-F URL Pattern Change

The original blueprint used `https://www.sec.gov/files/13f-{year}q{quarter}.zip`. The SEC has reorganized its data hosting. The current pattern may be:

`https://www.sec.gov/files/structureddata/data/form-13f-data-sets/{year}q{quarter}_13f.zip`

The collector attempts both patterns with fallback.

---

## OpenFIGI v2 → v3

OpenFIGI v2 is sunsetting on **July 1, 2026**. All calls should use `/v3/mapping`. The request/response format is identical; only the URL path changed.
