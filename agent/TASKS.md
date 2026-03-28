# House Advantage — Task Tracker

> **Last updated:** 2025-07-14

---

## Current Status: V2 Scoring Complete — All Trades Scored

All 12 orchestrator steps run end-to-end. V2 feature expansion (5→9 features) implemented and validated. 9,720 trades scored with V2 dual models.

### DB Table Counts (as of 2025-07-14)

| Table                    | Rows      | Status | Change from V1 |
|--------------------------|-----------|--------|----------------|
| politicians              | 548       | ✅ OK   | — |
| committees               | 235       | ✅ OK   | — |
| committee_memberships    | 3,867     | ✅ OK   | — |
| trades                   | 10,845    | ✅ OK   | — |
| votes                    | 1,079     | ✅ OK   | — |
| politician_votes         | 228,948   | ✅ OK   | — |
| bills                    | 12,213    | ✅ OK   | — |
| fec_candidates           | 200       | ✅ OK   | — |
| fec_candidate_totals     | 201       | ✅ OK   | — |
| stock_prices             | 1,250,147 | ✅ OK   | — |
| institutional_holdings   | 252,789   | ✅ OK   | — |
| institutional_trades     | 66,226    | ✅ OK   | — |
| cusip_ticker_map         | 0         | ⚠️ No data (OpenFIGI API key not configured) |
| anomaly_scores           | 9,720     | ✅ V2 scored | +9,720 (all trades scored) |
| audit_reports            | 0         | ⏳ Pending (Gemini integration not yet built) |

### V2 Scoring Results (2025-07-14)

| Quadrant       | Count  | % of Total |
|---------------|--------|-----------|
| SEVERE        | 14     | 0.1%      |
| SYSTEMIC      | 379    | 3.9%      |
| OUTLIER       | 78     | 0.8%      |
| UNREMARKABLE  | 9,249  | 95.2%     |
| Audit triggered | 55   | 0.6%      |

**V1→V2 comparison:** 889 trades (9.1%) changed quadrant. Disclosure lag dominance eliminated (flagged/unflagged ratio: V1 ≈ 2.6x → V2 ≈ 0.98x). More selective: OUTLIER count dropped from 504 → 78.

---

## Completed Tasks

### Phase 1: Pipeline Discovery & Testing
- [x] Explored 12-step orchestrator pipeline structure
- [x] Created 48 tests across 9 test classes (`tests/test_pipeline_db.py`)
- [x] Identified step 1 crash (404 on vote collection endpoint)

### Phase 2: Step Fixes
- [x] **Step 1 fix:** Removed redundant `collect_votes()` from `collect_all()` in `collect_congress_gov.py`
- [x] **Step 3 fix:** Added retry + exponential backoff to `collect_senate_votes.py`
- [x] Verified step 2 (committee memberships from GitHub) works correctly
- [x] Verified step 3 (senate votes from senate.gov XML) works correctly

### Phase 3: DB Blocker Audit & Fixes
- [x] **Blocker 1 — 13-F CIK derivation:** Rewrote `_extract_infotable()` to derive CIK from ACCESSION_NUMBER instead of COVERPAGE.tsv join. Fixed column mapping (SSHPRNAMT/SSHPRNAMTTYPE were both mapping to "shares").
- [x] **Blocker 2 — Trades name resolution:** Built multi-format name mapping in `load_trades()` ("Last, First" + "First Last" + last-name fallback). Resolved 10,022 of 10,845 trades to politician FKs.
- [x] **Blocker 3 — Committee membership IDs:** Added `_normalize_committee_id()` to lowercase and append "00" suffix for main committee codes.

### Phase 4: Loader Fixes (setup_db.py)
- [x] **Trades NaN handling:** Drop rows with NaN `trade_date` (NOT NULL), replace remaining NaN with None for nullable columns.
- [x] **Votes date parsing:** `pd.to_datetime(format="mixed")` for "January 9, 2025, 02:54 PM" → DATE.
- [x] **Votes result truncation:** Truncate `result` to 100 chars for VARCHAR(100).
- [x] **Bills bill_number splitting:** Split "HR144" → `bill_type="HR"` + `bill_number=144` (INT).
- [x] **13-F trades column rename:** `shares_curr` → `shares_current` to match DB schema.
- [x] **Stock prices:** Loaded 602,331 price rows from ~1,696 ticker CSV files.

### Phase 5: Model Training Readiness Fixes (2026-03-20)
- [x] **SPY benchmark prices:** SPY was in CSV on disk but missing from `stock_prices` table. Loaded 752 rows of SPY prices directly into DB, then full reload brought total stock_prices to 1.25M.
- [x] **House vote collection:** `collect_votes()` exists in `collect_congress_gov.py` but was removed from `collect_all()` (step 1) due to earlier crash. Ran vote collection standalone → 458 House votes + 198,152 positions via Congress.gov `/house-vote/{congress}` endpoint.
- [x] **Senate vote merge:** Re-ran step 3 to collect 717 Senate votes from senate.gov XML. Merged into single `votes_raw.csv` (1,079 total). Manually merged `politician_votes_raw.csv` with `senate_politician_votes_raw.csv` (228,957 combined positions).
- [x] **Sector mapping expansion:** Expanded `TICKER_SECTOR_MAP` in `merge_trades.py` from ~50 to ~170 tickers using yfinance `.info['sector']` lookups. Sector coverage improved from 25% → 45.7% of trades. Full yfinance results saved in `backend/data/raw/ticker_sector_lookup.json`.
- [x] **Timezone handling fix:** Added `utc=True` to `pd.to_datetime()` in vote loader (`setup_db.py`) to handle mixed timezone-aware (House) and timezone-naive (Senate) vote dates.
- [x] **PAC per-sector data:** Accepted as degraded for v1 — FEC PAC contributions are not broken out by sector. Feature 4 (donor_overlap) will be 0 for all trades. Can enhance in v2 with sector-tagged PAC data.
- [x] **Bad trade dates:** 7 rows with clearly invalid dates (e.g., `2099`) — trivial, will be cleaned during feature engineering.

---

## Active Tasks

### ~~Task A: Run Regression Tests~~ ✅ DONE
- **Result:** 48/48 passed (was 44 pass / 2 fail / 2 skip before fixes)
- **Command:** `python -m pytest tests/test_pipeline_db.py -v`

### Task B: CUSIP→Ticker Map (OpenFIGI)
- **Priority:** Low (deferred)
- **Description:** The `cusip_ticker_map` table is empty because OpenFIGI requires an API key. Model 2 baseline training works without it (uses price-file matching instead).
- **Blocked by:** User needs to provide OpenFIGI API key
- **Subtasks:**
  - [ ] B.1: Get API key from user
  - [ ] B.2: Configure and run step 10 (OpenFIGI collector)
  - [ ] B.3: Verify cusip_ticker_map table loads

### ~~Task C: Scoring Pipeline~~ ✅ COMPLETE (V2)
- **Status:** Complete — V1 trained March 2025, V2 trained + scored July 2025
- **V1:** 5 features, `cohort_model.pkl` / `baseline_model.pkl`
- **V2:** 9 features (added pre_trade_alpha, bill_proximity, amount_zscore, cluster_score; disclosure_lag → log1p), `cohort_model_v2.pkl` / `baseline_model_v2.pkl`
- **Result:** 9,720 trades scored with V2 models. V1 preserved for comparison.
- **Key files:**
  - `backend/scoring/dual_scorer.py` — V2 production scorer
  - `backend/scoring/dual_scorer_v1.py` — V1 backup scorer
  - `training/model1/build_features_model1_v2.py` + `train_cohort_model_v2.py`
  - `training/model2/build_features_model2_v2.py` + `train_baseline_model_v2.py`
  - `scripts/compare_v1_v2.py` — V1↔V2 comparison script

### Task D: Gemini Contextualizer (V3 — Per-Trade + Daily Scriptwriter)
- **Priority:** High
- **Description:** Build the Gemini function-calling contextualizer. Runs on SEVERE + SYSTEMIC trades to produce sourced analyses stored in `audit_reports`. For SEVERE trades, also writes `video_prompt` and `narration_script`. A second Gemini call (daily scriptwriter) reviews the day's flagged trades and writes the daily video narration + Veo prompt. Directory `backend/gemini/` exists but is empty.
- **Subtasks:**
  - [ ] D.1: Implement `gemini/contextualizer.py` (system prompt + function-calling tools)
  - [ ] D.2: Implement function tools: `get_candidate_data`, `get_trades_for_candidate`, `get_votes_near_trade`, `get_donors`, `read_bill_text`, `get_systemic_stats`
  - [ ] D.3: Implement `build_initial_message()` with dual score context
  - [ ] D.4: Implement `gemini/daily_scriptwriter.py` (aggregates day's trades, writes ~30s narration + Veo prompt)
  - [ ] D.5: Add batch contextualizer + daily scriptwriter to nightly scheduler (post-scoring)
  - [ ] D.6: Test report quality + JSON schema validation

### Task E: Frontend (Next.js 15)
- **Priority:** High
- **Description:** Build the frontend UI as a news site. The `frontend/` directory exists but is empty. See HOUSE_ADVANTAGE_MVP_Version3.md §12 for full page specs.
- **Subtasks:**
  - [ ] E.1: Initialize Next.js 15 (App Router) project in `frontend/`
  - [ ] E.2: Build `/` News Feed page (daily video report + SEVERE/SYSTEMIC trade cards + systemic insight sidebar)
  - [ ] E.3: Build `/daily/[date]` Daily Report page (video player + narration transcript + covered trades)
  - [ ] E.4: Build `/politicians` Politician Index page (ranked by aggregate anomaly score, filterable by party/state/chamber/committee)
  - [ ] E.5: Build `/politician/[id]` page (profile + interactive timeline)
  - [ ] E.6: Build `/trades` All Trades page (filterable by quadrant/party/state/ticker)
  - [ ] E.7: Build `/trade/[id]` page (chart + report + video + audio + share)
  - [ ] E.8: Build `/about` page (methodology + disclaimers)
  - [ ] E.9: Implement DualScoreBadge, trade timeline, video/audio player components

### Task F: GenMedia Pipeline
- **Priority:** High
- **Description:** Build the TTS, Veo 3.1, and ffmpeg pipelines for daily video reports and per-SEVERE trade videos. See HOUSE_ADVANTAGE_MVP_Version3.md §11 for full specs.
- **Subtasks:**
  - [ ] F.1: Implement `gemini/tts_pipeline.py` (narration_script → MP3 via Google Cloud TTS, return exact duration)
  - [ ] F.2: Implement `gemini/veo_pipeline.py` (video_prompt → MP4 via Veo 3.1 with scene extensions, match TTS duration)
  - [ ] F.3: Implement `gemini/ffmpeg_assembly.py` (mux TTS audio into Veo video)
  - [ ] F.4: Implement `gemini/daily_video_pipeline.py` (orchestrate: scriptwriter → TTS → Veo 3.1 → ffmpeg → daily_reports table)
  - [ ] F.5: Implement per-SEVERE-trade video pipeline (audit_reports → TTS → Veo 3.1 → ffmpeg → media_assets table)
  - [ ] F.6: Implement media storage layer (GCS for prod, local volume for dev)

### Task G: Interactive Trade Timeline (Charts)
- **Priority:** Medium
- **Description:** Build chart API endpoints and frontend chart components using Lightweight Charts (TradingView). See HOUSE_ADVANTAGE_MVP_Version3.md §9 and §12.
- **Subtasks:**
  - [ ] G.1: Implement `/api/v1/chart/trade/{id}` endpoint (±90 days OHLCV + markers)
  - [ ] G.2: Implement `/api/v1/chart/politician/{id}` endpoint (all trades timeline)
  - [ ] G.3: Build single-trade chart component (candles + trade marker + SPY + vote markers)
  - [ ] G.4: Build politician timeline component (multi-ticker + filter controls)

---

## Known Issues / Warnings

| Issue | Severity | Notes |
|-------|----------|-------|
| 537 trades dropped (missing trade_date) | Low | These rows had no trade_date in source data — expected |
| 41 committee memberships dropped (unresolved FKs) | Low | Politicians not in congress-legislators dataset |
| 9 politician votes dropped (unresolved FKs) | Low | Bioguide IDs not in politicians table |
| 823 trades not linked to politicians | Low | Name format mismatches not caught by fallbacks |
| QuiverQuant replaced by House Clerk + Senate eFD scrapers | Resolved | No paid API needed |
| OpenFEC/GovInfo API key may be missing | Medium | Steps 7/11 need `api.data.gov` key |

---

## Files Modified This Session (2026-03-20)

| File | Changes |
|------|---------|
| `backend/ingest/collectors/merge_trades.py` | Expanded `TICKER_SECTOR_MAP` from ~50 to ~170 tickers (yfinance-derived sectors) |
| `backend/db/setup_db.py` | Added `utc=True` to vote date parsing for mixed timezone handling |
| `backend/data/raw/votes_raw.csv` | Now contains merged House (362) + Senate (717) = 1,079 votes |
| `backend/data/raw/politician_votes_raw.csv` | Now contains merged House (198K) + Senate (72K) = 229K positions |
| `backend/data/raw/ticker_sector_lookup.json` | New file — full yfinance sector lookup results for ~150 tickers |

### Files Modified in Previous Session (2026-03-17)

| File | Changes |
|------|---------|
| `backend/ingest/collectors/collect_sec_13f.py` | Rewrote `_extract_infotable()`, fixed column mapping, added `_find_in_zip()` |
| `backend/ingest/collectors/collect_congress_gov.py` | Removed `collect_votes()` from `collect_all()` |
| `backend/ingest/collectors/collect_senate_votes.py` | Added retry + exponential backoff |
| `backend/db/setup_db.py` | Fixed `load_trades()`, `load_votes()`, `load_bills()`, `load_committee_memberships()`, `load_13f_holdings()` |

---

## Architecture Reference

- **Pipeline:** 12-step orchestrator at `backend/ingest/orchestrator.py`
- **CLI:** `python -m backend.ingest.orchestrator --step N` (or `--from-step`, `--to-step`)
- **DB:** MySQL 8.0 via Docker (port 3307, user `root`, db `house_advantage`)
- **Schema:** `backend/db/schema.sql`
- **Loader:** `backend/db/setup_db.py` (step 12)
- **Tests:** `tests/test_pipeline_db.py` (48 tests)
