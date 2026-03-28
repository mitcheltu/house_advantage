# House Advantage — Data Collection Plan

## Overview

This document describes the full data collection pipeline, all API sources, their current status, and the collection order required.

---

## API Status (Verified March 2026)

| API | Status | Auth Method | Cost |
|-----|--------|-------------|------|
| House Clerk Disclosures | ✅ Active | No auth | Free |
| Senate eFD | ✅ Active | No auth (cloudscraper for CDN) | Free |
| Congress.gov (replaces ProPublica) | ✅ Active | `api_key` query parameter | Free |
| OpenFEC | ✅ Active | `api_key` query parameter | Free |
| GovInfo | ✅ Active | `api_key` query parameter | Free |
| SEC EDGAR / 13-F | ✅ Active | No auth (User-Agent header required) | Free |
| OpenFIGI | ✅ Active | `X-OPENFIGI-APIKEY` header (optional) | Free |
| yfinance | ✅ Active | No auth | Free |

### ⚠️ ProPublica Congress API — DISCONTINUED

The ProPublica Congress API was **archived on February 4, 2025** and is no longer available. All politician, committee, and vote data is now sourced from the **Congress.gov API** (Library of Congress).

---

## Collection Order (Dependencies)

```
Phase 1 — Reference Data (no dependencies):
  ├── Congress.gov → politicians, committees, committee_memberships
  ├── Congress.gov → votes, politician_votes, bills
  └── OpenFEC     → donors

Phase 2 — Trade Data (requires Phase 1 for politician IDs):
  ├── House Clerk PDFs → trades (House congressional)
  ├── Senate eFD       → trades (Senate congressional)
  └── SEC 13-F    → baseline_trades (fund manager holdings)
      └── OpenFIGI → CUSIP-to-ticker resolution

Phase 3 — Feature Engineering (requires Phase 1 + 2):
  └── yfinance → stock prices for cohort_alpha computation

Phase 4 — Model Training (requires Phase 3):
  └── Build feature matrices → Train cohort_model.pkl + baseline_model.pkl
```

---

## Data Source Details

### 1. Congress.gov API (Replaces ProPublica)

**Base URL:** `https://api.congress.gov/v3`
**Auth:** `?api_key={CONGRESS_GOV_API_KEY}` query parameter
**Rate Limit:** 5,000 requests/hour
**Docs:** https://api.congress.gov/

**Endpoints Used:**

| Endpoint | Data | DB Table |
|----------|------|----------|
| `GET /member/congress/{congress}` | All members of a specific Congress | `politicians` |
| `GET /member/{bioguideId}` | Individual member details | `politicians` |
| `GET /committee/{congress}` | All committees | `committees` |
| `GET /committee/{congress}/{chamber}/{committeeCode}` | Committee members | `committee_memberships` |
| `GET /bill/{congress}` | Bills list | `bills` |
| `GET /bill/{congress}/{billType}/{billNumber}` | Bill details | `bills` |
| `GET /vote/{congress}/{chamber}` | Floor votes | `votes`, `politician_votes` |

**Current Congress:** 119th (2025–2027)

---

### 2. House Clerk + Senate eFD (Congressional Trade Disclosures)

**House source:** `https://disclosures-clerk.house.gov/`  
**Senate source:** `https://efdsearch.senate.gov/`  
**Auth:** None (Senate uses cloudscraper to bypass Akamai CDN)  
**Cost:** Free

House trades are extracted from annual ZIP files containing XML indexes and PTR PDFs.  
Senate trades are scraped from the eFD DataTables AJAX API.

| Collector | Data | DB Table |
|----------|------|----------|
| `collect_house_disclosures.py` | House STOCK Act PTR disclosures | `trades` |
| `collect_senate_disclosures.py` | Senate STOCK Act PTR disclosures | `trades` |
| `merge_trades.py` | Combines House + Senate into unified format | `trades` |

---

### 3. OpenFEC API

**Base URL:** `https://api.open.fec.gov/v1`
**Auth:** `?api_key={FEC_API_KEY}` query parameter
**Rate Limit:** 1,000 requests/hour (standard key)
**Docs:** https://api.open.fec.gov/swagger/

**Endpoints Used:**

| Endpoint | Data | DB Table |
|----------|------|----------|
| `GET /schedules/schedule_a/` | Itemized receipts (donations) | `donors` |

**Key Parameters:** `committee_id`, `two_year_transaction_period`, `per_page`, `sort`

---

### 4. GovInfo API

**Base URL:** `https://api.govinfo.gov`
**Auth:** `?api_key={GOVINFO_API_KEY}` query parameter
**Rate Limit:** 1,000 requests/hour
**Docs:** https://api.govinfo.gov/docs

**Endpoints Used:**

| Endpoint | Data | DB Table |
|----------|------|----------|
| `GET /packages/{packageId}/summary` | Bill metadata | `bills` |
| `GET /packages/{packageId}/granules` | Bill sections | `bills` (full text) |
| `POST /search` | Search for bill packages | `bills` |

**Package ID Format:** `BILLS-{congress}{billType}{billNumber}{version}` (e.g., `BILLS-119hr1234ih`)

---

### 5. SEC 13-F Bulk Data

**Base URL:** `https://www.sec.gov/files/structureddata/data/form-13f-data-sets/`  
**Alternative:** `https://efts.sec.gov/LATEST/search-index?q=%2213F-HR%22`  
**Auth:** No key; must include `User-Agent` header with contact info (SEC policy).  
**Rate Limit:** 10 requests/second max.

**URL Pattern:** `https://www.sec.gov/files/structureddata/data/form-13f-data-sets/{year}q{quarter}_13f.zip`

**Files in ZIP:** `INFOTABLE.tsv` — contains all institutional holdings for that quarter.

**Curated Fund CIKs (Model 2 baseline):**
- `0001166559` — Vanguard Group
- `0001364742` — BlackRock Inc
- `0000093715` — Fidelity (FMR)
- `0001109357` — State Street Corp
- `0001045810` — T. Rowe Price

---

### 6. OpenFIGI API

**Base URL:** `https://api.openfigi.com/v3`
**Auth:** `X-OPENFIGI-APIKEY: {key}` header (optional, higher limits with key)
**Rate Limit:** 25 req/min (no key), 25 req/6sec (with key)
**Max batch:** 10 jobs/request (no key), 100 jobs/request (with key)

**Endpoint:** `POST /v3/mapping`

**Request Body:**
```json
[{"idType": "ID_CUSIP", "idValue": "594918104"}]
```

---

### 7. yfinance

**Python Package:** `yfinance` (pip installable)
**Auth:** None
**Rate Limit:** Unofficial; respect ~2,000 requests/hour

**Usage:** Download historical OHLCV data for any ticker + SPY for alpha computation.

---

## Sector Mapping

Tickers are mapped to sectors using a static lookup table (`data/raw/_combined_sector_map.json`, ~963 tickers). Sectors align with congressional committee jurisdictions:

| Sector | Example Tickers | Relevant Committees |
|--------|----------------|---------------------|
| defense | LMT, RTX, BA, NOC | Armed Services, Defense Appropriations |
| finance | JPM, GS, BAC, WFC | Banking, Financial Services |
| healthcare | UNH, CVS, PFE, JNJ | Health, Ways & Means |
| energy | XOM, CVX, COP | Energy & Commerce, Natural Resources |
| tech | AAPL, MSFT, GOOGL, NVDA | Science & Technology, Commerce |
| telecom | T, VZ | Commerce, Communications |
| agriculture | ADM, DE, MOS | Agriculture |

**Multi-sector support:** 33 tickers carry multi-sector lists (e.g. MSFT → ["tech", "defense"], GE → ["defense", "energy", "healthcare"]). Multi-sector data is normalised in the `trade_sectors` junction table `(trade_id, sector)` — ~9,931 rows, 1,248 trades have multiple sectors. The `_parse_sector()` helper in `dual_scorer.py` handles all DB string formats at read time.
