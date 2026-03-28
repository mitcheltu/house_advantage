# House Advantage — Frontend UI/UX Implementation Prompt

**Stack:** Next.js 15 (App Router), React 18, Lightweight Charts (TradingView), CSS dark theme  
**Backend:** FastAPI at `http://localhost:8000` — all endpoints public, no auth  
**Design language:** Dark civic-tech newsroom. Background `#090d14`, text `#e5ebf5`, accent cards `#111a28` with `#1f2f46` borders. Severity quadrant colors: SEVERE `red-500`, SYSTEMIC `orange-500`, OUTLIER `yellow-500`, UNREMARKABLE `gray-500`.

---

## Existing State

The frontend currently has a single home page (`/`) displaying systemic stat cards and a leaderboard table (top 25 trades). There is a `lib/api.js` with `fetchSystemic()` and `fetchLeaderboard()`. No other pages, components, or routes exist.

---

## API Endpoints Available

| # | Method | Route | Returns |
|---|--------|-------|---------|
| A1 | GET | `/api/v1/systemic` | `{ total_scored, quadrants: { SEVERE: {count,pct}, ... }, audit_triggered: {count,pct}, averages: {cohort_index, baseline_index} }` |
| A2 | GET | `/api/v1/leaderboard?quadrant=&limit=&offset=` | `{ items: [{ trade_id, trade_date, ticker, trade_type, amount_midpoint, industry_sector, politician_id, bioguide_id, full_name, party, state, cohort_index, baseline_index, severity_quadrant, audit_triggered, max_index }], total }` |
| A3 | GET | `/api/v1/politician/{id}` | `{ politician: {id, bioguide_id, full_name, party, state, chamber, ...}, aggregate: {total_trades, quadrants, avg_cohort_index, avg_baseline_index}, trades: [{trade_id, trade_date, ticker, company_name, trade_type, amount_midpoint, disclosure_date, disclosure_lag_days, industry_sector, cohort_index, baseline_index, severity_quadrant, audit_triggered, audit_report_id, audit_headline, risk_level}] }` |
| A4 | GET | `/api/v1/audit/{trade_id}` | `{ trade: {trade_id, trade_date, disclosure_date, ticker, company_name, trade_type, amount_midpoint, industry_sector, politician_id, bioguide_id, full_name, party, state, cohort_index, baseline_index, severity_quadrant, audit_triggered}, audit_report: {headline, risk_level, severity_quadrant, narrative, evidence_json, bill_excerpt, disclaimer, video_prompt, narration_script, ...} or null, media_assets: [{asset_type, storage_url, duration_seconds, generation_status, ...}] }` |
| A5 | GET | `/api/v1/trades?quadrant=&party=&state=&ticker=&limit=&offset=` | **(needs backend)** Paginated filterable trade list |
| A6 | GET | `/api/v1/politicians?party=&state=&chamber=&sort_by=&limit=&offset=` | **(needs backend)** Paginated politician index ranked by aggregate anomaly |
| A7 | GET | `/api/v1/chart/trade/{trade_id}` | **(needs backend)** `{ ticker, trade, scores, prices: [OHLCV], spy_prices, nearby_votes, nearby_bills }` |
| A8 | GET | `/api/v1/chart/politician/{politician_id}` | **(needs backend)** `{ politician, trades, price_series: { TICKER: [{date, close}] } }` |
| A9 | GET | `/api/v1/daily-reports?limit=&offset=` | **(needs backend)** Paginated daily video reports |
| A10 | GET | `/api/v1/daily-report/{date}` | **(needs backend)** `{ report_date, narration_script, video_url, audio_url, duration_seconds, trade_ids_covered }` |
| A11 | GET | `/api/v1/media/{asset_id}` | **(needs backend)** Streams pre-generated video/audio file |
| A12 | GET | `/api/v1/share/{trade_id}` | **(needs backend)** OG meta tags for social link previews |

Endpoints marked **(needs backend)** are specified in the V3 blueprint but not yet implemented in FastAPI. Build frontend pages against all endpoints; stub missing ones in `lib/api.js` so they degrade gracefully (show "Coming soon" or empty state).

---

## Pages & Indexed Flows

### Page 1: News Feed — `/`

The homepage. Entry point for all three audience tiers.

**Layout (top to bottom):**

| # | Section | Description |
|---|---------|-------------|
| 1.1 | **Header** | "House Advantage" title + tagline "Daily anomaly intelligence for congressional stock trades." |
| 1.2 | **Daily Video Hero** | Latest daily report video player (9:16 aspect, max 400px wide centered). Video date, narration transcript expandable below. Links to `/daily/{date}`. If no video available, show placeholder card: "Daily video report coming soon." |
| 1.3 | **Systemic Insight Banner** | Orange-tinted banner. "X% of congressional trades would be flagged as anomalous if held to the same standard as institutional fund managers." Pull from A1 SYSTEMIC pct. |
| 1.4 | **Stat Cards Row** | 4 cards in a grid: Total Scored, SEVERE count, SYSTEMIC count, Audit Triggered — each with percentage subtext. **(Already exists — keep as-is.)** |
| 1.5 | **Latest Flagged Trades** | Top 10 SEVERE + SYSTEMIC trades as cards (not a table). Each card: politician name, party badge, ticker, trade type, amount, dual score badge (cohort/baseline), quadrant pill. Click → `/trade/{id}`. |
| 1.6 | **Leaderboard Table** | Full sortable table (existing). Add: click row → `/trade/{id}`, click politician name → `/politician/{id}`. Add quadrant filter tabs above table. |
| 1.7 | **Navigation Footer** | Links to /politicians, /trades, /about. |

**Flows:**

| Flow | Trigger | Action |
|------|---------|--------|
| F1.1 | Page load | Fetch A1 (systemic), A2 (leaderboard limit=50), A9 (daily-reports limit=1) in parallel. SSR. |
| F1.2 | Click trade card (1.5) | Navigate to `/trade/{trade_id}` |
| F1.3 | Click politician name in leaderboard (1.6) | Navigate to `/politician/{politician_id}` |
| F1.4 | Click trade row in leaderboard (1.6) | Navigate to `/trade/{trade_id}` |
| F1.5 | Click quadrant filter tab (1.6) | Re-fetch A2 with `?quadrant=SEVERE` etc. Client-side filter or re-fetch. |
| F1.6 | Click daily video (1.2) | Navigate to `/daily/{date}` |
| F1.7 | Scroll to bottom | Load more leaderboard rows (offset pagination via A2) |

---

### Page 2: Daily Report — `/daily/[date]`

Single daily video report page.

**Layout:**

| # | Section | Description |
|---|---------|-------------|
| 2.1 | **Back link** | "← Back to News Feed" → `/` |
| 2.2 | **Date header** | "House Advantage — March 25, 2026" |
| 2.3 | **Video player** | 9:16 video, centered, max-width 480px. Stream from A11 or direct URL from A10. |
| 2.4 | **Narration transcript** | Collapsible section showing the full narration_script text. Default collapsed on mobile, expanded on desktop. |
| 2.5 | **Trades Covered** | List of trade cards that were featured in this daily report (from `trade_ids_covered`). Each links to `/trade/{id}`. |
| 2.6 | **Share bar** | "Share to X", "Copy Link" buttons. |
| 2.7 | **Previous/Next navigation** | Links to adjacent daily reports by date. |

**Flows:**

| Flow | Trigger | Action |
|------|---------|--------|
| F2.1 | Page load | Fetch A10 with `date` param. If 404/unavailable, show "No report for this date." |
| F2.2 | Click a covered trade card (2.5) | Navigate to `/trade/{trade_id}` |
| F2.3 | Click "Share to X" (2.6) | Open Twitter/X intent URL with prefilled text + page URL |
| F2.4 | Click "Copy Link" (2.6) | Copy current page URL to clipboard, show toast "Link copied" |
| F2.5 | Click Previous/Next (2.7) | Navigate to `/daily/{adjacent_date}` |

---

### Page 3: Politician Index — `/politicians`

Ranked list of all politicians by aggregate anomaly score.

**Layout:**

| # | Section | Description |
|---|---------|-------------|
| 3.1 | **Page header** | "Politician Index" + subtext "Ranked by aggregate trade anomaly score." |
| 3.2 | **Filter bar** | Dropdowns/pills: Party (All, Democrat, Republican, Independent), State (all 50), Chamber (All, House, Senate). Applied as query params. |
| 3.3 | **Sort control** | Sort by: Aggregate Score (default), Total Trades, SEVERE Count, SYSTEMIC Count. |
| 3.4 | **Politician cards/rows** | Each row: Rank #, Name, Party badge (D=blue, R=red, I=purple), State, Chamber, Total Trades, SEVERE count pill, SYSTEMIC count pill, avg cohort/baseline scores. Click → `/politician/{id}`. |
| 3.5 | **Pagination** | "Load more" button or infinite scroll. 50 per page via offset. |

**Flows:**

| Flow | Trigger | Action |
|------|---------|--------|
| F3.1 | Page load | Fetch A6 with default params (sort=aggregate_anomaly_score, limit=50). SSR first page. |
| F3.2 | Change filter (3.2) | Re-fetch A6 with updated `party`, `state`, `chamber` params. Reset offset to 0. |
| F3.3 | Change sort (3.3) | Re-fetch A6 with updated `sort_by`. Reset offset to 0. |
| F3.4 | Click politician row (3.4) | Navigate to `/politician/{politician_id}` |
| F3.5 | Click "Load More" (3.5) | Fetch A6 with offset += 50, append results. |

---

### Page 4: Politician Profile — `/politician/[id]`

Deep-dive into one politician's trading history.

**Layout:**

| # | Section | Description |
|---|---------|-------------|
| 4.1 | **Back link** | "← Politician Index" → `/politicians` |
| 4.2 | **Profile header** | Full name, Party badge, State, Chamber, District (if House). Official photo placeholder (silhouette if unavailable). |
| 4.3 | **Aggregate stats** | 4 stat cards: Total Trades, SEVERE, SYSTEMIC, OUTLIER. Plus avg cohort/baseline scores. |
| 4.4 | **Interactive Trade Timeline** | Lightweight Charts component. X-axis = date range of all their trades. Multiple ticker price lines overlaid. Trade markers (▲ buy / ▼ sell) color-coded by severity quadrant. Hover tooltip: ticker, date, amount, cohort, baseline, quadrant. Filter controls above chart: ticker dropdown (multi-select), quadrant filter pills, date range. Uses A8. |
| 4.5 | **Trade list** | Full table of all trades for this politician. Columns: Date, Ticker, Company, Type, Amount, Disclosure Lag, Cohort, Baseline, Quadrant, Audit Report (link icon if exists). Click row → `/trade/{id}`. Sortable by column headers. |
| 4.6 | **Quadrant breakdown** | Small donut/pie chart or horizontal stacked bar showing % of trades in each quadrant. |

**Flows:**

| Flow | Trigger | Action |
|------|---------|--------|
| F4.1 | Page load | Fetch A3 (politician profile + trades) and A8 (chart data) in parallel. SSR profile, client-side chart hydration. |
| F4.2 | Change chart ticker filter (4.4) | Client-side: show/hide price series and markers for selected tickers. No re-fetch. |
| F4.3 | Change chart quadrant filter (4.4) | Client-side: show/hide trade markers by quadrant. |
| F4.4 | Hover trade marker on chart (4.4) | Show tooltip with trade details. |
| F4.5 | Click trade marker on chart (4.4) | Navigate to `/trade/{trade_id}` |
| F4.6 | Click trade row in table (4.5) | Navigate to `/trade/{trade_id}` |
| F4.7 | Click audit report icon (4.5) | Navigate to `/trade/{trade_id}#report` (scroll to report section) |
| F4.8 | Sort table column (4.5) | Client-side sort (all trades already loaded). |

---

### Page 5: All Trades — `/trades`

Filterable index of every scored trade.

**Layout:**

| # | Section | Description |
|---|---------|-------------|
| 5.1 | **Page header** | "Trade Index" + trade count |
| 5.2 | **Filter bar** | Quadrant pills (All, SEVERE, SYSTEMIC, OUTLIER, UNREMARKABLE), Party dropdown, State dropdown, Ticker search (autocomplete). All applied as query params. |
| 5.3 | **Active filters** | Row of dismissible chips showing current filters. "Clear all" button. |
| 5.4 | **Trade table** | Columns: Date, Politician (link), Party, Ticker, Type, Amount, Disclosure Lag, Cohort, Baseline, Quadrant pill, Audit (icon). Sortable column headers. |
| 5.5 | **Pagination** | Page numbers or "Load more". 50 per page. |

**Flows:**

| Flow | Trigger | Action |
|------|---------|--------|
| F5.1 | Page load | Fetch A5 with defaults (limit=50, offset=0). SSR. URL query params hydrate filters on load. |
| F5.2 | Click quadrant pill (5.2) | Update URL `?quadrant=SEVERE`, re-fetch A5. |
| F5.3 | Change party/state dropdown (5.2) | Update URL params, re-fetch A5. |
| F5.4 | Type in ticker search (5.2) | Debounce 300ms, update `?ticker=AAPL`, re-fetch A5. |
| F5.5 | Dismiss filter chip (5.3) | Remove that query param, re-fetch A5. |
| F5.6 | Click "Clear all" (5.3) | Remove all query params, re-fetch A5. |
| F5.7 | Click trade row (5.4) | Navigate to `/trade/{trade_id}` |
| F5.8 | Click politician name (5.4) | Navigate to `/politician/{politician_id}` |
| F5.9 | Sort column header (5.4) | Re-fetch A5 with `sort_by` param, or client-side sort if all loaded. |
| F5.10 | Pagination (5.5) | Fetch A5 with updated offset. |

---

### Page 6: Trade Detail — `/trade/[id]`

The most content-rich page. Chart + scores + report + media + share.

**Layout:**

| # | Section | Description |
|---|---------|-------------|
| 6.1 | **Back link** | "← All Trades" → `/trades` |
| 6.2 | **Trade header** | Politician name (link to profile), party badge, ticker, company name, trade type (BUY/SELL), trade date, amount, disclosure date, disclosure lag in days. |
| 6.3 | **Dual Score Badge** | Large component: two score columns (Cohort Index X/100, Baseline Index X/100) with quadrant label. Background color matches quadrant. Styled per the DualScoreBadge component in the blueprint. |
| 6.4 | **Interactive Price Chart** | Lightweight Charts: ±90 days of OHLCV candles for the ticker. Trade marker (▲/▼) on trade_date, color-coded by quadrant. Vertical dashed line at disclosure_date. Dimmed SPY benchmark line overlay. Nearby vote dates and bill action dates as secondary markers (small diamonds). Hover tooltip on markers. Uses A7. |
| 6.5 | **Media section** (if SEVERE) | Subsections: (a) Audio briefing — HTML5 audio player with waveform or simple progress bar, duration display. (b) Video clip — 9:16 video player, max 400px wide. Only shown if `media_assets` contains ready assets. |
| 6.6 | **Share bar** | "Share to X", "Copy Link", "Download Video" (if video exists). |
| 6.7 | **Contextualizer Report** (id="report") | From `audit_report`: Headline (large), Risk Level badge, Narrative (rendered markdown or paragraphs), Evidence list (type, description, source — each source linked if URL), Bill Excerpt (blockquote), Caveats. If no audit report exists: "Contextualizer report pending." |
| 6.8 | **Disclaimer** | Fixed disclaimer text at bottom of report section: "The Trade Anomaly Index is generated by automated statistical models..." (full legal text from blueprint). |
| 6.9 | **Related trades** | Other trades by the same politician, showing the 5 most recent. Each links to its own `/trade/{id}`. |

**Flows:**

| Flow | Trigger | Action |
|------|---------|--------|
| F6.1 | Page load | Fetch A4 (trade + audit + media) and A7 (chart data) in parallel. SSR trade data, client-side chart hydration. |
| F6.2 | Chart hover on trade marker (6.4) | Tooltip: amount, cohort, baseline, quadrant. |
| F6.3 | Chart hover on vote/bill marker (6.4) | Tooltip: vote/bill title, date. |
| F6.4 | Click audio play (6.5a) | Play MP3 via HTML5 `<audio>`, streaming from A11 or direct URL. |
| F6.5 | Click video play (6.5b) | Play MP4 via HTML5 `<video>`, streaming from A11 or direct URL. |
| F6.6 | Click "Share to X" (6.6) | Open X intent: "🚨 {quadrant}: {politician} {trade_type} ${amount} of {ticker} — Cohort: {cohort}/100, Baseline: {baseline}/100 {page_url}" |
| F6.7 | Click "Copy Link" (6.6) | Copy page URL to clipboard, toast confirmation. |
| F6.8 | Click "Download Video" (6.6) | Trigger browser download of the MP4 file. |
| F6.9 | Click politician name (6.2) | Navigate to `/politician/{politician_id}` |
| F6.10 | Click related trade (6.9) | Navigate to `/trade/{trade_id}` |
| F6.11 | URL has `#report` hash | Scroll to contextualizer report section on load. |

**OG Meta (for social previews):**
- `og:title`: "{Quadrant}: {Politician} — {TradeType} ${Amount} of {Ticker}"
- `og:description`: "{Headline from audit_report}" or "Cohort: {X}/100 | Baseline: {Y}/100"
- `og:image`: Thumbnail from media_assets or auto-generated card image
- `og:type`: "article"

---

### Page 7: About — `/about`

Static methodology and disclaimers page.

**Layout:**

| # | Section | Description |
|---|---------|-------------|
| 7.1 | **Header** | "How It Works" |
| 7.2 | **Dual Model Explanation** | Two-column or stacked sections: "Model 1: Cohort Model" (trains on congressional trades, detects outliers within Congress) and "Model 2: Baseline Model" (trains on SEC 13-F fund manager trades, detects deviation from normal investors). Include the 2x2 quadrant grid diagram with color-coded cells. |
| 7.3 | **Scoring explanation** | "Every trade receives two scores (0–100). The combination places it in one of four severity quadrants." Show the quadrant matrix. |
| 7.4 | **Contextualizer explanation** | "Gemini 2.5 Pro investigates SEVERE and SYSTEMIC trades by cross-referencing votes, bills, committee assignments, and campaign finance data." |
| 7.5 | **Data sources** | Table: Source → What it provides → Update frequency. (House Clerk, Senate eFD, Congress.gov, OpenFEC, SEC 13-F, yfinance, GovInfo) |
| 7.6 | **GenMedia explanation** | "Daily video reports are generated using Google's TTS and Veo 3.1 models. Gemini writes the narration scripts and visual prompts. All videos carry an 'AI-Generated' watermark." |
| 7.7 | **Full disclaimer** | The complete legal disclaimer text. |
| 7.8 | **Open source / contact** | Links to GitHub repo, methodology notes. |

**Flows:**

| Flow | Trigger | Action |
|------|---------|--------|
| F7.1 | Page load | Static render, no API calls. SSG or static. |

---

## Shared Components to Build

| # | Component | Used On | Description |
|---|-----------|---------|-------------|
| C1 | `NavBar` | All pages | Top nav: logo "House Advantage", links to /, /politicians, /trades, /about. Current page highlighted. Mobile hamburger menu. |
| C2 | `DualScoreBadge` | Pages 1, 4, 5, 6 | Two-score display with quadrant label and color. Small variant (inline in tables/cards) and large variant (trade detail hero). |
| C3 | `QuadrantPill` | Pages 1, 3, 4, 5, 6 | Small colored badge: SEVERE (red), SYSTEMIC (orange), OUTLIER (yellow), UNREMARKABLE (gray). |
| C4 | `PartyBadge` | Pages 1, 3, 4, 5, 6 | "(D)" blue, "(R)" red, "(I)" purple. |
| C5 | `TradeCard` | Pages 1, 2, 4, 6 | Compact card: politician name, ticker, type, amount, dual scores, quadrant pill. Clickable. |
| C6 | `StatCard` | Pages 1, 4 | Label, large value, optional subtext. **(Already exists.)** |
| C7 | `TradeChart` | Pages 4, 6 | Lightweight Charts wrapper. Props: prices (OHLCV), trade markers, spy data, vote/bill markers. Handles zoom/pan/tooltips. |
| C8 | `PoliticianTimeline` | Page 4 | Multi-ticker Lightweight Charts with trade overlay. Props: price_series object, trades array. Filter controls. |
| C9 | `FilterBar` | Pages 3, 5 | Reusable filter component: quadrant pills, party/state/chamber dropdowns. Syncs with URL query params. |
| C10 | `Pagination` | Pages 3, 5 | "Load more" button or page numbers. Props: offset, limit, total, onLoadMore. |
| C11 | `ShareBar` | Pages 2, 6 | "Share to X", "Copy Link", optional "Download Video". |
| C12 | `VideoPlayer` | Pages 1, 2, 6 | Responsive 9:16 video player with custom controls. |
| C13 | `AudioPlayer` | Page 6 | HTML5 audio player with progress bar and duration. |
| C14 | `SystemicBanner` | Page 1 | Orange insight banner with the systemic percentage callout. |

---

## Navigation Map

```
/  (News Feed)
├── /daily/[date]             ← from daily video hero (F1.6)
│   └── /trade/[id]           ← from covered trades list (F2.2)
├── /trade/[id]               ← from flagged cards (F1.2) or leaderboard (F1.4)
│   └── /politician/[id]      ← from trade header (F6.9)
├── /politicians              ← from nav (C1) or footer (1.7)
│   └── /politician/[id]      ← from index row (F3.4)
│       └── /trade/[id]       ← from timeline (F4.5) or table (F4.6)
├── /trades                   ← from nav (C1) or footer (1.7)
│   ├── /trade/[id]           ← from row click (F5.7)
│   └── /politician/[id]      ← from name click (F5.8)
└── /about                    ← from nav (C1) or footer (1.7)
```

---

## Implementation Priority

| Phase | Pages | Dependencies |
|-------|-------|--------------|
| **Phase 1** | Refactor `/` (add NavBar, TradeCards, SystemicBanner, clickable rows) | Endpoints A1, A2 (exist) |
| **Phase 2** | `/politician/[id]` profile + trade table | Endpoint A3 (exists) |
| **Phase 3** | `/trade/[id]` detail with audit report | Endpoint A4 (exists) |
| **Phase 4** | `/politicians` index + `/trades` filterable index | Endpoints A5, A6 (need backend) |
| **Phase 5** | `/trade/[id]` chart (Lightweight Charts integration) | Endpoint A7 (needs backend) |
| **Phase 6** | `/politician/[id]` timeline chart | Endpoint A8 (needs backend) |
| **Phase 7** | `/daily/[date]` + video/audio players | Endpoints A9, A10, A11 (need backend) |
| **Phase 8** | `/about` static page, OG meta, share functionality | Endpoint A12 (needs backend for OG) |
