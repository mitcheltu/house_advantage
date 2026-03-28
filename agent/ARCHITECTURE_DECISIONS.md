# House Advantage — Architecture Decisions

## Key Decisions Log

### 1. ProPublica Replacement (March 2026)

**Decision:** Replace ProPublica Congress API with Congress.gov API  
**Reason:** ProPublica Congress API discontinued February 2025  
**Impact:** All politician, committee, and vote collection scripts rewritten against Congress.gov v3 endpoints  

### 2. MySQL via Docker

**Decision:** Run MySQL 8.0 in Docker via docker-compose  
**Reason:** Reproducible, isolated, doesn't require local MySQL installation  
**Alternative considered:** Local MySQL install  

### 3. SEC 13-F via EDGAR API

**Decision:** Use SEC EDGAR submissions API (`data.sec.gov`) to locate 13-F filings, with bulk ZIP fallback  
**Reason:** More reliable than hardcoded ZIP URL patterns which SEC changes periodically  

### 4. Collection-First Architecture

**Decision:** All collectors save to CSV first, then a separate loader pushes to MySQL  
**Reason:** 
- Decouples API failures from DB operations
- Raw CSVs serve as audit trail
- Enables re-loading without re-fetching
- Easier debugging

### 5. Sector Mapping Strategy

**Decision:** Use a static ticker→sector lookup table, expanded via yfinance batch lookups  
**Reason:** MVP scope — covers ~170 most-traded congressional tickers (45.7% of trades). Initially was ~50 tickers (25% coverage). Expanded in March 2026 using `yfinance.Ticker(symbol).info['sector']` to auto-classify GICS sectors into 7 model categories.  
**Mapping:** GICS sectors → {defense, finance, healthcare, energy, tech, telecom, agriculture}  
**Cache:** Full yfinance results in `backend/data/raw/ticker_sector_lookup.json`  
**V2:** Can add dynamic classification via SIC codes, GICS database, or OpenFIGI.

### 6. Vote Collection Split (March 2026)

**Decision:** Collect House and Senate votes separately, then merge  
**Reason:**
- Congress.gov only has a House vote endpoint (`/v3/house-vote/{congress}`), no Senate equivalent
- Senate votes come from senate.gov XML, a completely different source
- House vote collection is slow (~40 min for ~460 votes), prone to API timeouts
- Removed `collect_votes()` from Step 1's `collect_all()` to prevent pipeline crashes
- House votes run as a standalone operation; Senate votes run via Step 3
- Both merge into `votes_raw.csv`; politician positions require manual merge

### 7. Timezone Handling for Merged Data (March 2026)

**Decision:** Use `utc=True` in `pd.to_datetime()` when loading vote dates  
**Reason:** House vote dates from Congress.gov are timezone-aware (e.g., `2025-09-08T18:56:00-04:00`), while Senate vote dates from senate.gov XML are timezone-naive. Merging them causes pandas `Mixed timezones` error. Converting all to UTC then extracting `.dt.date` normalizes both formats.

### 8. PAC Sector Data — Deferred (March 2026)

**Decision:** Accept `donor_overlap` feature as degraded (always 0) for v1  
**Reason:** FEC PAC contribution data (`fec_pac_contributions_raw.csv`) is not broken out by sector. Adding per-sector PAC mapping would require cross-referencing PAC names with sector databases, which is out of scope for MVP. Feature 4 in the Isolation Forest model will have zero variance—acceptable since the other 4 features carry the signal.

### 9. V2 Feature Expansion — 5→9 Features (July 2025)

**Decision:** Expand from 5 to 9 features and transform disclosure_lag with log1p  
**Reason:** V1 model validation revealed disclosure_lag dominated ~61% of flagged detections. The raw-day scale (0–365) overwhelmed IsolationForest splits, causing trades to be flagged primarily for late disclosure rather than suspicious trading patterns.  
**Changes:**
- **4 new features:** `pre_trade_alpha` (30-day pre-trade return vs SPY), `bill_proximity` (days to sector-matched bill), `amount_zscore` (trade size z-score within politician), `cluster_score` (same-ticker temporal clustering)
- **Transform:** `disclosure_lag` changed from raw days to `log1p(days)`, compressing the right tail
- **Model 2 upgrade:** `pre_trade_alpha` now computed for institutional trades (was fixed at 0). Model 2 goes from 1→2 effective features.
- **V1 preserved:** Original models kept as `cohort_model.pkl` / `baseline_model.pkl` for comparison. V2 models: `cohort_model_v2.pkl` / `baseline_model_v2.pkl`.  
**Result:** Disclosure lag dominance eliminated (flagged/unflagged ratio: 2.6x → 0.98x). 889 trades (9.1%) changed quadrant. More selective overall: OUTLIER count dropped from 504 → 78 while SYSTEMIC grew from 240 → 379. Corrected over-flagging (e.g., Britt: 16→3 flags) and under-flagging (e.g., Greene: 7→16 flags).

---

## Open Questions

- [x] ~~QuiverQuant API key~~ — replaced with free House Clerk + Senate eFD scraping
- [x] ~~OpenFEC/GovInfo API key~~ — configured (api.data.gov)
- [ ] OpenFIGI API key — awaiting from user (optional)
- [ ] MySQL password preference — awaiting from user
- [ ] Sector coverage improvement — 45.7% is acceptable for v1, but v2 should target >70%

---

## V3 GenMedia Decisions

### 10. GenMedia Strategy — Chained Intelligence (March 2026)

**Decision:** Integrate Veo 3.1 (video) and TTS (audio) as a chained intelligence pipeline, where Gemini 2.5 Pro writes the creative direction for all downstream genMedia models.  
**Reason:** Hackathon requires Google genMedia models. Rather than bolting on a wrapper, Gemini acts as the "brain" that writes Veo prompts and TTS narration scripts after investigating each trade. This makes every genMedia output the product of an autonomous AI investigation.  
**Pattern:** Gemini contextualizer investigates → writes `video_prompt` + `narration_script` in JSON → TTS and Veo 3.1 consume Gemini's authored instructions. A second Gemini call (daily scriptwriter) aggregates the day's flagged trades into a daily video report script.

### 11. Media Storage — GCS + Local Volume (March 2026)

**Decision:** Store generated MP4/MP3 files in a GCS bucket (production) or Docker volume (dev).  
**Reason:** Media files are too large for MySQL BLOBs. GCS provides CDN-like serving for production. Local volume for dev avoids GCS credential setup during development.  
**Schema:** `media_assets` table tracks metadata (storage_url, file_size, duration, status). Actual bytes stored externally.

### 12. Virality Design — 9:16 Portrait for TikTok/Reels (March 2026)

**Decision:** All Veo-generated videos use 9:16 portrait orientation (1080×1920).  
**Reason:** Primary distribution target is TikTok and Instagram Reels. 9:16 is the native format for both platforms. Landscape video gets cropped/letterboxed on short-form feeds.  
**Content:** ~30 second daily video reports, ~15 second per-trade SEVERE videos, abstract/symbolic visuals (no real faces), "AI-Generated" watermark.

### 13. DB-First API Strategy (March 2026)

**Decision:** All user-facing requests served from MySQL. External APIs called only during nightly ingest. All media content (daily videos, per-trade videos, audio, contextualizer reports) is pre-generated. No user-triggered API calls to Gemini, Veo, or TTS.  
**Reason:** Prevents rate limit issues, ensures fast page loads, app stays functional if upstream APIs go down. No authentication needed since nothing is on-demand.  
**Impact:** `stock_prices` table serves chart data (no live yfinance calls). `audit_reports` + `media_assets` + `daily_reports` serve pre-generated content.

### 14. Chart Library — Lightweight Charts (March 2026)

**Decision:** Use Lightweight Charts (by TradingView) for interactive trade timelines.  
**Reason:** Purpose-built for financial data (candlesticks, line charts, markers/annotations). ~40KB bundle size. Supports zoom/pan, hover tooltips, and multiple overlays.  
**Alternative considered:** Chart.js (not optimized for financial), D3.js (too low-level), Recharts (no candlestick support).

### 15. Veo 3.1 Generation Strategy — Daily + Per-SEVERE (March 2026)

**Decision:** Generate Veo videos in two modes: (1) daily ~30s news report video covering the day's SEVERE + SYSTEMIC trades, (2) individual ~15s videos for each SEVERE trade. All pre-generated during the nightly pipeline.  
**Reason:** Daily video provides regular content for the news feed and social sharing. Per-SEVERE videos serve as detailed individual trade briefings. Veo 3.1 scene extensions (7s segments) enable ~30s videos by chaining an initial clip with 3 extensions.  
**Cost:** ~4 Veo API calls per daily video + ~2 per SEVERE trade. Steady state: ~32 calls/week.

### 16. ffmpeg Audio/Video Assembly (March 2026)

**Decision:** Use ffmpeg to mux TTS-generated audio into Veo-generated video as a post-processing step.  
**Reason:** TTS is generated first (deterministic duration), then Veo matches that duration via scene extensions. ffmpeg combines them into a single MP4 with audio. This avoids relying on Veo's built-in audio (which can't carry factual narration) and ensures the narration track is the informational carrier while Veo provides atmospheric visuals.

### 17. No Authentication — Fully Public Site (March 2026)

**Decision:** No Google Sign-In, no rate limiting, no user accounts. The entire site is public and unauthenticated.  
**Reason:** All content is pre-generated during the nightly pipeline. There are no user-triggered API calls that need cost protection. Removing auth maximizes reach, virality, and simplicity — anyone with a link sees full content immediately.
