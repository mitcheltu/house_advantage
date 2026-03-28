# House Advantage — Full MVP Blueprint
### A Civic News Platform for Congressional Trade Accountability
**Version:** 4.1 (V3 GenMedia Architecture — Revised)
**Target:** Google GenMedia Hackathon Submission
**Date:** March 2026

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [What Makes This "Not a Wrapper"](#2-what-makes-this-not-a-wrapper)
3. [The Dual-Model Architecture](#3-the-dual-model-architecture)
4. [System Architecture](#4-system-architecture)
5. [Database Schema](#5-database-schema)
6. [Data Ingestion Layer](#6-data-ingestion-layer)
7. [ML Scoring Engine](#7-ml-scoring-engine)
8. [API Strategy](#8-api-strategy)
9. [FastAPI Backend](#9-fastapi-backend)
10. [Gemini Contextualizer](#10-gemini-contextualizer)
11. [GenMedia Pipeline](#11-genmedia-pipeline)
12. [Next.js Frontend](#12-nextjs-frontend)
13. [Deployment & Scheduling](#13-deployment--scheduling)
14. [Legal & Ethical Safeguards](#14-legal--ethical-safeguards)
15. [MVP Scope & Roadmap](#15-mvp-scope--roadmap)
16. [Virality & Distribution Strategy](#16-virality--distribution-strategy)
17. [Environment Variables & API Keys](#17-environment-variables--api-keys)

---

## 1. Project Overview

**House Advantage** is a civic-tech news platform that automatically detects, explains, and *broadcasts* statistically anomalous congressional stock trades. It combines a dual machine learning model with a Gemini-powered contextualizer and Google's genMedia APIs (Veo 3.1, TTS) to produce daily video news reports, per-trade video briefings for severe cases, and a searchable politician trade explorer with interactive charts.

### The Core Problem

The STOCK Act requires members of Congress to publicly disclose stock trades. That data sits in raw government databases that most people will never read. Existing tools surface numbers — they don't explain them. A constituent seeing that their senator bought $250,000 of Lockheed Martin stock has no way of knowing whether that's suspicious without hours of cross-referencing voting records, committee assignments, and campaign finance disclosures themselves.

### The Two-Layer Insight

Most transparency tools treat every congressional trade in isolation. House Advantage makes two distinct accusations:

- **Individual accusation:** *"This specific trade is unusual even by congressional standards"*
- **Systemic accusation:** *"Congressional trading as a whole is unusual compared to normal investors — the average member of Congress trades in ways that would be flagged as anomalous in any other context"*

These require two separate ML models trained on fundamentally different baselines.

### Target Audience (Three Tiers)

| Tier | Who | What Draws Them | Primary Feature |
|---|---|---|---|
| **General Public** | TikTok/Reels/social civic audience | Daily ~30s video news reports on suspicious trades. Shareable, snackable. | **Daily Veo 3.1 Video** |
| **Journalists & Media** | Reporters, news outlets | Searchable trade database, contextualizer reports, embeddable trade cards with OG previews | **Contextualizer Reports** |
| **Watchdog Orgs & Activists** | Transparency advocates, researchers | Politician rankings, interactive trade timelines, filterable trade index by quadrant/party/state | **Politician Index + Charts** |

### The Core Loop

```
Public STOCK Act Disclosures
        ↓
Model 1 (Cohort Model): Is this unusual within Congress?
Model 2 (Baseline Model): Is this unusual vs. normal investors?
        ↓
Combined Dual Score → Severity Quadrant
        ↓
Gemini Contextualizer investigates SEVERE + SYSTEMIC trades
  → Function-calls DB tools, reads bill text, cross-references evidence
  → Stores sourced context analysis in audit_reports table
        ↓
Daily Video Scriptwriter (Gemini) reviews the day's flagged trades
  → Writes ~30s narration script + Veo video prompt
        ↓
TTS generates narration audio → Veo 3.1 generates video with scene extensions
  → ffmpeg muxes audio + video → Daily video report published
        ↓
Users browse news feed, explore politician index, view interactive trade timelines
```

---

## 2. What Makes This "Not a Wrapper"

Gemini and Google's genMedia models perform **five non-trivial roles** in a chained intelligence pipeline. Gemini is the brain that investigates and writes the scripts; TTS is the voice, and Veo is the camera.

| # | Role | Google Model | Why It's Non-Trivial |
|---|---|---|---|
| 1 | **Function-Calling Contextualizer** | Gemini 2.5 Pro (tool use) | Gemini autonomously decides which DB queries to run based on dual-model score context. It investigates each SEVERE + SYSTEMIC trade and writes a sourced analysis stored in the database. |
| 2 | **Bill Text Analyst** | Gemini 2.5 Pro (1M-token context) | Gemini reads raw congressional bill text (50,000–200,000+ tokens) and extracts sections relevant to the trade's industry sector. |
| 3 | **Daily Script + Prompt Writer** | Gemini 2.5 Pro (structured output) | Gemini reviews the day's flagged trades and their context, then writes a ~30s narration script for TTS and a visual prompt for Veo. For SEVERE trades, also writes per-trade scripts. |
| 4 | **Voice Narrator** | Google TTS | Converts Gemini's narration scripts into natural-sounding audio. Gemini tailors scripts for spoken delivery — shorter sentences, verbal emphasis cues, news-broadcast pacing. |
| 5 | **Video Director** | Veo 3.1 | Generates ~30s news report videos using scene extensions (7s segments chained for continuity). Gemini writes the visual direction — shot composition, mood, pacing — based on the severity quadrant and trade evidence. |

**The chained intelligence pattern:** Gemini doesn't just use genMedia as output channels — it writes their instructions. The `veo_prompt` for Veo and `narration_script` for TTS are authored by Gemini after it has investigated the trades, read the bill text, and cross-referenced the evidence. Each daily video report and per-trade briefing is the product of an autonomous AI investigation, not a template. The pipeline chains three Google AI models: Gemini 2.5 Pro → TTS → Veo 3.1, with ffmpeg for final audio/video assembly.

---

## 3. The Dual-Model Architecture

### Why Two Models Are Required

**Model 1 (Cohort Model)** trains on congressional trades. It learns what a "normal" congressional trade looks like. The problem: congressional trading may itself be systematically abnormal due to legislative information advantages. If most politicians are already trading on privileged information, a model trained on that population learns that behavior is normal and only flags the most extreme outliers within an already-suspicious cohort.

**Model 2 (Baseline Model)** trains on SEC 13-F institutional fund manager trades — investors with no access to non-public legislative information. It establishes a genuinely clean baseline of what normal market participation looks like.

Running both models on every congressional trade and comparing their outputs produces a two-dimensional signal that neither model alone can provide.

### The Four Severity Quadrants

Every trade is placed into one of four quadrants based on its two anomaly scores:

| Model 1 (Cohort) | Model 2 (Baseline) | Quadrant | Meaning |
|---|---|---|---|
| 🔴 High | 🔴 High | **SEVERE** | Unusual even by congressional standards AND unlike normal investors. The strongest individual flag. |
| 🟠 Low | 🔴 High | **SYSTEMIC** | Looks normal within Congress but highly abnormal vs. the public. Suggests a widespread pattern, not an individual outlier. |
| 🟡 High | 🟢 Low | **OUTLIER** | Statistical oddity within Congress but trades like a normal investor. Lower concern — possibly a clean but unusual trade. |
| 🟢 Low | 🟢 Low | **UNREMARKABLE** | Normal on both measures. No audit triggered. |

### The Systemic Dashboard

The **SYSTEMIC** quadrant is the product's most powerful civic insight. When many trades cluster there — low cohort score, high baseline score — the product surfaces a systemic finding:

> *"Congressional trading as a whole is statistically anomalous compared to institutional investors with no legislative access. The average member of Congress trades in ways that would be flagged by independent fund managers."*

This is displayed as a platform-level insight on the homepage, separate from individual politician profiles.

### Scoring Formula

Each trade receives:
- `cohort_index` (0–100): from Model 1
- `baseline_index` (0–100): from Model 2
- `combined_severity`: the quadrant label derived from both scores
- `audit_triggered`: boolean — true if either score ≥ 70

```python
def assign_quadrant(cohort_index: int, baseline_index: int) -> str:
    HIGH = 60  # threshold for "high" on each dimension
    if cohort_index >= HIGH and baseline_index >= HIGH:
        return "SEVERE"
    elif cohort_index < HIGH and baseline_index >= HIGH:
        return "SYSTEMIC"
    elif cohort_index >= HIGH and baseline_index < HIGH:
        return "OUTLIER"
    else:
        return "UNREMARKABLE"
```

---

## 4. System Architecture

### High-Level Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                              │
│  House Clerk PDFs │ Senate eFD     │ Congress.gov  │ OpenFEC     │
│  SEC 13-F Bulk    │ yfinance       │ OpenFIGI      │ GovInfo     │
└──────────┬───────────────────────────────────────────────────────┘
           │ Nightly Ingestion (APScheduler)
           ▼
┌──────────────────────────────────────────────────────────────────┐
│                       MySQL DATABASE                             │
│  politicians │ trades │ votes │ committees │ donors │ bills      │
│  stock_prices │ baseline_trades │ anomaly_scores                 │
│  audit_reports │ media_assets │ daily_reports                    │
└──────────┬───────────────────────────────────────────────────────┘
           │                              ▲
           │  Nightly Scoring Job          │ Function Calls
           ▼                              │
┌─────────────────────┐       ┌───────────────────────────────────┐
│  MODEL 1 (Cohort)   │──┐    │  Gemini 2.5 Pro Contextualizer    │
│  MODEL 2 (Baseline) │──┤    │  ─ get_candidate_data()           │
└─────────────────────┘  │    │  ─ get_trades_for_candidate()     │
                         │    │  ─ get_votes_near_trade()         │
                    scores│    │  ─ get_donors()                   │
                         ├──▶ │  ─ read_bill_text()               │
                         │    │  ─ get_systemic_stats()           │
                         │    └──────────────────┬────────────────┘
                         │                       │ JSON Report
                         │                       │ + video_prompt
                         │                       │ + narration_script
                         │                       ▼
                         │    ┌───────────────────────────────────┐
                         │    │  GenMedia Pipeline                 │
                         │    │  ┌─────────┐  ┌──────────┐        │
                         │    │  │ TTS API │  │ Veo 3.1  │        │
                         │    │  │ → MP3   │  │ → MP4    │        │
                         │    │  └────┬────┘  └────┬─────┘        │
                         │    │       └──────┬─────┘              │
                         │    │              ▼                    │
                         │    │         ffmpeg mux                │
                         │    │              ▼                    │
                         │    │    media_assets + daily_reports    │
                         │    │    + GCS / local storage           │
                         │    └──────────────────┬────────────────┘
                         │                       │
                         ▼                       ▼
                    ┌────────────────────────────────────────────┐
                    │   FastAPI Backend (Python)                  │
                    │   /api/v1/systemic        (dashboard)      │
                    │   /api/v1/leaderboard     (top trades)     │
                    │   /api/v1/politician/{id} (profile)        │
                    │   /api/v1/trade/{id}      (detail+media)   │
                    │   /api/v1/chart/trade/{id}   (timeline)    │
                    │   /api/v1/chart/politician/{id} (timeline) │
                    │   /api/v1/media/{id}      (stream asset)   │
                    │   /api/v1/share/{id}      (OG embed)       │
                    │   /api/v1/daily-report/{date} (daily video)│
                    │   /api/v1/politicians     (ranked index)   │
                    │   /api/v1/trades          (filterable)     │
                    └──────────────────┬─────────────────────────┘
                                       │ REST JSON
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│   Next.js Frontend                                               │
│   /                  → News Feed (daily video + latest trades)   │
│   /daily/[date]      → Daily video report page                   │
│   /politicians       → Politician index (ranked, filterable)     │
│   /politician/[id]   → Profile + trade timeline + media gallery  │
│   /trades            → All trades (filterable by quadrant)       │
│   /trade/[id]        → Chart + Report + Video + Audio + Share    │
│   /about             → Methodology + disclaimers                 │
└──────────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| Frontend | Next.js 15 (App Router) | SSR, API routes, OG meta generation |
| Charts | Lightweight Charts (TradingView) | Financial candlesticks, markers, annotations, ~40KB |
| Backend API | FastAPI (Python 3.12) | Async, auto-docs, ML integration |
| ML Engine | scikit-learn (Python) | Isolation Forest, two pipeline instances |
| AI Contextualizer | Gemini 2.5 Pro via `google-generativeai` SDK | Function calling, 1M token context, structured JSON |
| Voice Narration | Google TTS API | Natural-sounding MP3 audio from narration scripts |
| Video Generation | Veo 3.1 API | 9:16 portrait video with scene extensions from Gemini-written prompts |
| Audio/Video Assembly | ffmpeg | Mux TTS audio into Veo video for final output |
| Database | MySQL 8.0 | Relational joins across all entities |
| Task Scheduler | APScheduler | Nightly ingestion, scoring, and media generation |
| ORM | SQLAlchemy 2.0 | Async MySQL queries |
| Media Storage | GCS bucket (prod) / local volume (dev) | Video + audio file storage |
| Containerization | Docker + docker-compose | Reproducible environment |
| Reverse Proxy | Nginx | Routes `/api/*` to FastAPI |

---

## 5. Database Schema

> **Note:** Unchanged V2 tables (politicians, committees, committee_memberships, trades, trade_sectors, baseline_trades, votes, politician_votes, bills, donors, stock_prices, institutional_holdings, institutional_trades, cusip_ticker_map, anomaly_scores, systemic_stats, pac_contributions) are preserved as-is from Version 2. The `trade_sectors` junction table was added in V2 to normalise multi-sector trade mappings (see V2 schema). Only modified and new tables are shown below.

### Modified: `audit_reports` (V3 — added GenMedia fields)

```sql
CREATE TABLE IF NOT EXISTS audit_reports (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_id            BIGINT NOT NULL UNIQUE,
    generated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    headline            VARCHAR(500),
    risk_level          ENUM('low','medium','high','very_high') NOT NULL,
    severity_quadrant   ENUM('SEVERE','SYSTEMIC','OUTLIER','UNREMARKABLE'),
    narrative           TEXT NOT NULL,
    evidence_json       JSON,
    bill_excerpt        TEXT,
    disclaimer          TEXT NOT NULL,

    -- V3: GenMedia output fields (written by Gemini)
    video_prompt        TEXT,           -- Veo prompt authored by Gemini
    narration_script    TEXT,           -- TTS script authored by Gemini

    gemini_model        VARCHAR(80),
    prompt_tokens       INT,
    output_tokens       INT,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);
```

### New: `media_assets` (V3 — Veo videos + TTS audio)

```sql
CREATE TABLE IF NOT EXISTS media_assets (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_id            BIGINT NOT NULL,
    audit_report_id     BIGINT,
    asset_type          ENUM('audio','video','thumbnail') NOT NULL,
    storage_url         VARCHAR(500) NOT NULL,
    file_size_bytes     INT,
    duration_seconds    FLOAT,
    resolution          VARCHAR(20),          -- e.g. '1080x1920' for 9:16
    generation_status   ENUM('pending','generating','ready','failed') NOT NULL DEFAULT 'pending',
    error_message       TEXT,
    model_used          VARCHAR(100),         -- e.g. 'veo-2', 'tts-1'
    generated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE CASCADE,
    FOREIGN KEY (audit_report_id) REFERENCES audit_reports(id) ON DELETE SET NULL,
    INDEX idx_trade (trade_id),
    INDEX idx_type (asset_type),
    INDEX idx_status (generation_status)
) ENGINE=InnoDB;
```

### New: `daily_reports` (V3 — daily video news reports)

```sql
CREATE TABLE IF NOT EXISTS daily_reports (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date         DATE NOT NULL UNIQUE,
    trade_ids_covered   JSON,
    narration_script    TEXT,
    veo_prompt          TEXT,
    video_url           VARCHAR(500),
    audio_url           VARCHAR(500),
    duration_seconds    FLOAT,
    generation_status   ENUM('pending','generating','ready','failed') DEFAULT 'pending',
    generated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
```

---

## 6. Data Ingestion Layer

> **Unchanged from V2.** The 12-step orchestrator pipeline, data sources, congressional trade ingestion, and SEC 13-F baseline ingestion remain identical. See Version 2 Blueprint §6 for full details.

### Data Sources Summary

| Data Type | Source | Cost | Used For |
|---|---|---|---|
| Congressional trades (House) | House Clerk Financial Disclosure portal | Free | Training Model 1 + nightly scoring |
| Congressional trades (Senate) | Senate eFD (efdsearch.senate.gov) | Free | Training Model 1 + nightly scoring |
| Politicians, votes, bills | Congress.gov API | Free | Features + Gemini context |
| Committee memberships | Congress.gov API + congress-legislators GitHub | Free | committee_relevance feature |
| Bill text | GovInfo API | Free | Gemini bill analysis |
| Campaign finance / donors | OpenFEC API | Free | Gemini context |
| Institutional fund trades | SEC 13-F Bulk CSVs | Free | Training Model 2 |
| CUSIP → Ticker mapping | OpenFIGI API | Free | Processing 13-F data |
| Stock prices | yfinance | Free | cohort_alpha + chart data |

---

## 7. ML Scoring Engine

> **Unchanged from V2.** The 9-feature dual scoring pipeline, Isolation Forest models, nightly scoring job, and quadrant assignment remain identical. See Version 2 Blueprint §7 for full details.

### Feature Summary (V2, 9 features)

| Feature | Congressional Trades | Baseline (13-F) Trades |
|---|---|---|
| `cohort_alpha` | 30-day forward return vs SPY | Same computation |
| `pre_trade_alpha` | 5-day pre-trade return vs SPY | Computed (V2) |
| `proximity_days` | Days to nearest sector-relevant vote | Fixed at median |
| `bill_proximity` | Days to nearest sector-relevant bill | Fixed at median |
| `has_proximity_data` | 1 if real vote found within 90 days | Fixed at 0 |
| `committee_relevance` | 0.0–1.0 committee oversight score | Fixed at 0.0 |
| `amount_zscore` | Trade size z-score within politician | Fixed at 0.0 |
| `cluster_score` | Same-ticker ±7-day clustering count | Fixed at 0 |
| `disclosure_lag` | `log1p(days)` trade → filing | Fixed at 0 |

### Current Results (V2, 9,720 trades scored)

| Quadrant | Count | % |
|---|---|---|
| SEVERE | 14 | 0.1% |
| SYSTEMIC | 379 | 3.9% |
| OUTLIER | 78 | 0.8% |
| UNREMARKABLE | 9,249 | 95.2% |

---

## 8. API Strategy

### Principle: DB-First, All Content Pre-Generated

All user-facing requests are served from the database. External APIs (yfinance, Congress.gov, etc.) are called **only during the nightly ingest pipeline** — never on user request. All media content (daily videos, per-trade SEVERE videos, audio briefings, contextualizer reports) is pre-generated during the nightly pipeline. There are no user-triggered API calls to Gemini, Veo, or TTS.

**No authentication required.** The entire site is public. No Google Sign-In, no rate limiting, no user accounts. This maximizes reach, virality, and simplicity.

### What Gets Called at Ingest Time (nightly, no user involvement)

| API | When Called | What's Stored in DB |
|---|---|---|
| **yfinance** | Nightly ingest (Step 8) | `stock_prices` — daily OHLCV for every traded ticker + SPY (3-year window, incremental) |
| **Congress.gov** | Nightly ingest (Steps 1–3) | `politicians`, `committees`, `committee_memberships`, `bills`, `votes` |
| **House Clerk / Senate eFD** | Nightly ingest (Steps 4–6) | `trades` — new disclosures scraped and merged |
| **OpenFEC** | Nightly ingest (Step 7) | `fec_candidates`, `fec_candidate_totals`, `pac_contributions` |
| **GovInfo** | Nightly ingest (Step 11) | Bill full text |
| **Gemini 2.5 Pro** | Post-scoring batch | `audit_reports` — contextualizer analysis + `video_prompt` + `narration_script` |
| **Gemini 2.5 Pro** | Post-contextualizer | `daily_reports` — daily video narration script + Veo prompt |
| **TTS API** | Post-script generation | `media_assets` + `daily_reports` — MP3 audio |
| **Veo 3.1 API** | Post-TTS | `media_assets` + `daily_reports` — MP4 video with scene extensions |
| **ffmpeg** | Post-Veo generation | Final muxed video (TTS audio + Veo video) |

### What the User Sees (all served from DB, all public)

| User Action | Data Source | External API? |
|---|---|---|
| Watch daily video report | `daily_reports` (pre-generated MP4) | ❌ No |
| Watch per-trade video (SEVERE) | `media_assets` (pre-generated MP4) | ❌ No |
| View trade timeline/chart | `stock_prices` + `trades` + `anomaly_scores` | ❌ No |
| View politician profile | `politicians` + `trades` + `anomaly_scores` | ❌ No |
| Read contextualizer report | `audit_reports` (pre-generated) | ❌ No |
| Listen to audio briefing | `media_assets` (pre-generated MP3) | ❌ No |
| Browse politician index | `anomaly_scores` + `trades` + `politicians` | ❌ No |
| Browse all trades | `trades` + `anomaly_scores` | ❌ No |
| View systemic dashboard | `anomaly_scores` aggregate | ❌ No |







---

## 9. FastAPI Backend

### Key Endpoints

```python
# routers/systemic.py
router = APIRouter(prefix="/api/v1", tags=["systemic"])

@router.get("/systemic")
async def get_systemic_stats(session: AsyncSession = Depends(get_session)):
    """Platform-level systemic insight. Powers homepage dashboard."""
    result = await session.execute(
        "SELECT * FROM systemic_stats ORDER BY computed_at DESC LIMIT 1"
    )
    return dict(result.fetchone())

@router.get("/leaderboard")
async def get_leaderboard(
    quadrant: str = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session)
):
    """Top anomalous trades, optionally filtered by severity quadrant."""
    ...
```

### Chart Endpoints (V3 — Interactive Timeline)

```python
# routers/chart.py
router = APIRouter(prefix="/api/v1/chart", tags=["chart"])

@router.get("/trade/{trade_id}")
async def get_trade_chart(trade_id: int, session: AsyncSession = Depends(get_session)):
    """
    Returns ±90 days of OHLCV price data around a trade, plus trade markers,
    SPY benchmark, and nearby political context. All served from DB.
    """
    # Response schema:
    # {
    #   "ticker": "AAPL",
    #   "trade": { "trade_date", "trade_type", "amount_midpoint", "disclosure_date" },
    #   "scores": { "cohort_index", "baseline_index", "severity_quadrant" },
    #   "prices": [ { "date", "open", "high", "low", "close", "volume" }, ... ],
    #   "spy_prices": [ { "date", "close" }, ... ],
    #   "nearby_votes": [ { "vote_date", "bill_title" }, ... ],
    #   "nearby_bills": [ { "action_date", "bill_title", "sector" }, ... ]
    # }
    ...

@router.get("/politician/{politician_id}")
async def get_politician_chart(politician_id: str,
                                session: AsyncSession = Depends(get_session)):
    """
    Returns all trades by a politician with price series for each traded ticker.
    Powers the politician timeline overlay view.
    """
    # Response schema:
    # {
    #   "politician": { "name", "party", "state" },
    #   "trades": [
    #     { "ticker", "trade_date", "trade_type", "amount_midpoint",
    #       "severity_quadrant", "cohort_index", "baseline_index" }, ...
    #   ],
    #   "price_series": { "AAPL": [ { "date", "close" } ], "MSFT": [...] }
    # }
    ...
```

### Content & Discovery Endpoints (V3)

```python
# routers/media.py
router = APIRouter(prefix="/api/v1", tags=["media"])

@router.get("/media/{asset_id}")
async def stream_media(asset_id: int, session: AsyncSession = Depends(get_session)):
    """Stream a pre-generated video or audio file."""
    ...

@router.get("/share/{trade_id}")
async def get_share_meta(trade_id: int, session: AsyncSession = Depends(get_session)):
    """Returns OG meta tags + embed data for social link previews."""
    ...
```

```python
# routers/daily_reports.py
router = APIRouter(prefix="/api/v1", tags=["daily"])

@router.get("/daily-reports")
async def list_daily_reports(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session)
):
    """Paginated list of daily video reports, newest first."""
    ...

@router.get("/daily-report/{date}")
async def get_daily_report(date: str, session: AsyncSession = Depends(get_session)):
    """Single daily report with video URL, narration, and covered trade IDs."""
    ...
```

```python
# routers/trades.py
router = APIRouter(prefix="/api/v1", tags=["trades"])

@router.get("/trades")
async def list_trades(
    quadrant: str = None,
    party: str = None,
    state: str = None,
    ticker: str = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session)
):
    """All trades with optional filters. Includes anomaly scores and audit status."""
    ...
```

```python
# routers/politicians.py
router = APIRouter(prefix="/api/v1", tags=["politicians"])

@router.get("/politicians")
async def list_politicians(
    party: str = None,
    state: str = None,
    chamber: str = None,
    committee: str = None,
    sort_by: str = "aggregate_anomaly_score",
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session)
):
    """
    Politician index ranked by aggregate anomaly score.
    Filterable by party, state, chamber, and committee membership.
    """
    ...
```

### Full Endpoint Inventory

| Method | Route | Description |
|---|---|---|
| GET | `/api/v1/systemic` | Systemic dashboard stats |
| GET | `/api/v1/leaderboard` | Top flagged trades |
| GET | `/api/v1/politician/{id}` | Politician profile + trades |
| GET | `/api/v1/trade/{id}` | Trade detail + audit report |
| GET | `/api/v1/chart/trade/{id}` | OHLCV + trade markers |
| GET | `/api/v1/chart/politician/{id}` | All trades timeline |
| GET | `/api/v1/media/{asset_id}` | Stream pre-generated media |
| GET | `/api/v1/share/{trade_id}` | OG meta for link previews |
| GET | `/api/v1/daily-reports` | Paginated daily video reports |
| GET | `/api/v1/daily-report/{date}` | Single daily report by date |
| GET | `/api/v1/trades` | All trades (filterable by quadrant/party/state/ticker) |
| GET | `/api/v1/politicians` | Politician index (ranked, filterable) |

All endpoints are public — no authentication required.

---

## 10. Gemini Contextualizer

The Gemini contextualizer operates in two modes:

1. **Per-trade contextualizer**: Runs on each SEVERE + SYSTEMIC trade after scoring. Investigates the trade and writes a sourced analysis stored in `audit_reports`. For SEVERE trades, also generates per-trade video + narration scripts.
2. **Daily video scriptwriter**: Runs once after all per-trade contextualizations. Reviews the day's flagged trades and writes the daily video narration script + Veo prompt stored in `daily_reports`.

### Mode 1: Per-Trade Contextualizer

The contextualizer receives **both scores** as context and generates a structured JSON report. For SEVERE trades, it additionally writes creative direction for individual video generation.

#### System Prompt

```python
# gemini/contextualizer.py

SYSTEM_PROMPT = """
You are a non-partisan financial ethics investigator. You have access to TWO anomaly
scores for every trade:

1. COHORT INDEX (0–100): How anomalous this trade is compared to all other
   congressional trades. A high score means this trade is unusual even by
   congressional standards.

2. BASELINE INDEX (0–100): How anomalous this trade is compared to institutional
   fund managers with no legislative access (SEC 13-F filers). A high score here
   means the trade looks unusual to a normal investor with no political information.

The combination determines severity:
- SEVERE (both high): Individual AND systemic concern.
- SYSTEMIC (baseline high, cohort low): Normal within Congress but abnormal in
  the real world — systemic information advantage.
- OUTLIER (cohort high, baseline low): Unusual within Congress but normal investor
  behavior. Lower concern.
- UNREMARKABLE: Normal on both measures.

Use your tools to investigate, then write a structured JSON report. Do not
speculate without evidence. Always clearly state which score is driving your
finding and why.

Output raw JSON only — no markdown fences — in this schema:
{
  "headline": "<one sentence, max 120 chars>",
  "risk_level": "low" | "medium" | "high" | "very_high",
  "severity_quadrant": "<SEVERE|SYSTEMIC|OUTLIER|UNREMARKABLE>",
  "cohort_explanation": "<why the cohort score is what it is>",
  "baseline_explanation": "<why the baseline score is what it is>",
  "narrative": "<2-4 paragraphs, full investigative report>",
  "evidence": [{"type": "...", "description": "...", "source": "..."}],
  "bill_excerpt": "<direct quote or null>",
  "caveats": "<limitations of this analysis>",
  "narration_script": "<30-60 second spoken briefing script for SEVERE trades.
    Written for audio delivery: short sentences, verbal emphasis, no visual
    references. Opens with the politician name and trade. Ends with the severity
    assessment. null for non-SEVERE trades.>",
  "video_prompt": "<Veo 3.1 prompt for a ~15 second 9:16 portrait video for SEVERE
    trades. Describe visual mood, pacing, and composition. SEVERE = urgent/alarming
    visuals. Do NOT include real faces or names — use abstract representations,
    data visualizations, or symbolic imagery. Include 'AI-generated disclosure
    analysis' text overlay. null for non-SEVERE trades.>"
}
""".strip()
```

### Initial Message Builder

```python
def build_initial_message(trade) -> str:
    return f"""
Investigate the following congressional trade:

Politician: {trade.full_name} (ID: {trade.politician_id})
Ticker: {trade.ticker} | Sectors: {', '.join(trade.sectors) if trade.sectors else 'unknown'}
Trade: {trade.trade_type.upper()} on {trade.trade_date}
Disclosed: {trade.disclosure_date} ({trade.disclosure_lag_days} days after trade)
Amount Estimate: ${trade.amount_midpoint:,}

─── DUAL MODEL SCORES ──────────────────────────────
Cohort Index  (vs. Congress):          {trade.cohort_index}/100
Baseline Index (vs. fund managers):    {trade.baseline_index}/100
Severity Quadrant:                     {trade.severity_quadrant}

─── FEATURE BREAKDOWN ──────────────────────────────
30-day cohort alpha:         {trade.feat_cohort_alpha:.4f}
5-day pre-trade alpha:       {trade.feat_pre_trade_alpha:.4f}
Days to nearest vote:        {trade.feat_proximity_days}
Days to nearest bill:        {trade.feat_bill_proximity}
Has proximity vote data:     {'YES' if trade.feat_has_proximity_data else 'NO'}
Committee relevance score:   {trade.feat_committee_relevance:.2f}
Amount z-score:              {trade.feat_amount_zscore:.2f}
Cluster score (±7 days):     {trade.feat_cluster_score}
Disclosure lag (log1p days): {trade.feat_disclosure_lag}

Use your tools to investigate. Focus your explanation on which of the two scores
is more significant and why the severity quadrant is {trade.severity_quadrant}.
For SEVERE trades, also write the narration_script (for TTS audio) and video_prompt
(for Veo 3.1). For non-SEVERE trades, set narration_script and video_prompt to null.
""".strip()
```

### Mode 2: Daily Video Scriptwriter

After all per-trade contextualizations are complete, a second Gemini call reviews the day's flagged trades and writes the daily video report script.

```python
# gemini/daily_scriptwriter.py

DAILY_SCRIPT_PROMPT = """
You are the scriptwriter for House Advantage, a civic news platform that reports
on statistically anomalous congressional stock trades. You are writing the narration
script for today's daily video news report.

Below are today's flagged trades (SEVERE and SYSTEMIC) with their contextualizer
analyses. Write a ~30 second narration script (approximately 75 words) that:

1. Opens with "This is House Advantage for {date}."
2. Summarizes the most newsworthy findings from today's flagged trades.
3. Names specific politicians and their trades when severity warrants it.
4. Closes with a one-sentence systemic observation.
5. Uses news-broadcast tone: authoritative, factual, no hedging.

Also write a Veo video prompt that describes the visual atmosphere for the report:
- Use abstract/symbolic imagery (no real faces)
- Match the tone to the severity of the day's findings
- Include 'AI-Generated — House Advantage' text overlay
- The video should feel like a professional news broadcast opening

Output raw JSON only:
{
  "narration_script": "<~75 words, 30 seconds at broadcast pace>",
  "veo_prompt": "<Veo 3.1 prompt for ~30s 9:16 portrait video>"
}
""".strip()

async def generate_daily_script(flagged_trades: list, date: str) -> dict:
    """Generate daily video narration + Veo prompt from the day's flagged trades."""
    trade_summaries = []
    for t in flagged_trades:
        trade_summaries.append(
            f"- {t.full_name} ({t.party}-{t.state}): {t.trade_type} ${t.amount_midpoint:,} "
            f"of {t.ticker} | Quadrant: {t.severity_quadrant} | "
            f"Headline: {t.audit_headline}"
        )

    if not trade_summaries:
        # No new trades — pull random historical SEVERE/SYSTEMIC/OUTLIER
        trade_summaries = await get_random_historical_trades()

    message = DAILY_SCRIPT_PROMPT.replace("{date}", date) + "\n\n" + "\n".join(trade_summaries)
    # Call Gemini 2.5 Pro with structured output
    ...
```

---

## 11. GenMedia Pipeline

### Pipeline Overview

The genMedia pipeline produces two types of video content, both generated during the nightly batch — never on user request.

1. **Daily Video Report**: A single ~30s video covering the day's SEVERE + SYSTEMIC trades, published to the news feed.
2. **Per-SEVERE-Trade Video**: Individual ~15s videos for each SEVERE trade, shown on the trade detail page.

Both follow the same assembly pattern: Gemini writes the script → TTS generates audio (exact duration known) → Veo 3.1 generates video with scene extensions to match audio duration → ffmpeg muxes audio into video.

```
  Gemini (script + prompt)
           ↓
  ┌────────────────┐    ┌─────────────────────┐
  │  TTS API       │    │  Veo 3.1 API        │
  │  Script → MP3  │    │  Prompt → MP4       │
  │  (exact dur.)  │    │  (scene extensions) │
  └───────┬────────┘    └──────────┬──────────┘
          │                        │
          └────────┬───────────────┘
                   ▼
              ffmpeg mux
           (audio + video)
                   ▼
          Final MP4 → storage
```

### Step 1: TTS Audio Generation

```python
# gemini/tts_pipeline.py
from google.cloud import texttospeech

def generate_audio(narration_script: str, output_id: str) -> tuple[str, float]:
    """Convert narration script to MP3 audio. Returns (storage_url, duration_seconds)."""
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=narration_script)
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Neural2-J",  # authoritative news voice
        ssml_gender=texttospeech.SsmlVoiceGender.MALE,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.05,  # slightly faster for broadcast feel
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    url = store_media_file(response.audio_content, output_id, "audio", "mp3")
    duration = get_mp3_duration(response.audio_content)
    return url, duration
```

- **Input:** `narration_script` from Gemini (either per-trade or daily)
- **Output:** MP3 audio file + exact duration in seconds
- **Key principle:** TTS is generated first because its duration is deterministic. Veo then matches this duration via scene extensions.
- **Voice:** Google Cloud TTS Neural2 — authoritative news delivery

### Step 2: Veo 3.1 Video Generation (Scene Extensions)

```python
# gemini/veo_pipeline.py
import google.generativeai as genai
import time

def generate_video_with_extensions(
    veo_prompt: str,
    target_duration: float,
    output_id: str
) -> str:
    """
    Generate a Veo 3.1 video with scene extensions to match target duration.
    Initial clip ~8s, each extension adds ~7s. Returns storage URL.
    """
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    # Step 1: Generate initial ~8s clip
    operation = client.models.generate_videos(
        model="veo-3.1-generate-preview",
        prompt=veo_prompt,
        config=types.GenerateVideosConfig(
            person_generation="dont_allow",
            aspect_ratio="9:16",
            number_of_videos=1,
        ),
    )
    while not operation.done:
        time.sleep(20)
        operation = client.operations.get(operation)

    video = operation.result.generated_videos[0]
    current_duration = 8.0  # initial clip ~8s

    # Step 2: Extend with scene extensions until target duration reached
    extensions_needed = max(0, int((target_duration - current_duration) / 7))
    extensions_needed = min(extensions_needed, 20)  # Veo 3.1 max: 20 extensions

    for i in range(extensions_needed):
        operation = client.models.generate_videos(
            model="veo-3.1-generate-preview",
            image=video.video.thumbnails[-1],  # last frame as continuation seed
            config=types.GenerateVideosConfig(
                person_generation="dont_allow",
                aspect_ratio="9:16",
                extend_video=video.video,  # scene extension
            ),
        )
        while not operation.done:
            time.sleep(20)
            operation = client.operations.get(operation)

        video = operation.result.generated_videos[0]
        current_duration += 7.0

    url = store_media_file(video.video.video_bytes, output_id, "video", "mp4")
    return url
```

- **Initial clip:** ~8 seconds
- **Scene extensions:** Each adds ~7 seconds with visual continuity from previous clip
- **For daily video (~30s target):** initial clip + 3 extensions = ~29s (4 Veo API calls)
- **For per-trade video (~15s target):** initial clip + 1 extension = ~15s (2 Veo API calls)
- **Content policy:** `person_generation="dont_allow"` — no real faces. Gemini's prompt ensures abstract/symbolic visuals.

### Step 3: ffmpeg Assembly

```python
# gemini/ffmpeg_assembly.py
import subprocess

def mux_audio_video(video_path: str, audio_path: str, output_path: str) -> str:
    """Mux TTS audio into Veo video, trimming to shorter duration."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ], check=True)
    return output_path
```

### Daily Video Pipeline (Orchestrated)

```python
# gemini/daily_video_pipeline.py

async def generate_daily_video(date: str):
    """Full pipeline: scriptwriter → TTS → Veo 3.1 → ffmpeg → daily_reports."""
    # 1. Get today's SEVERE + SYSTEMIC trades with audit context
    flagged_trades = await get_flagged_trades_for_date(date)

    # 2. Gemini daily scriptwriter generates narration + Veo prompt
    script = await generate_daily_script(flagged_trades, date)

    # 3. TTS generates audio (exact duration known)
    audio_url, duration = generate_audio(script["narration_script"], f"daily_{date}")

    # 4. Veo 3.1 generates video with scene extensions to match audio
    video_url = generate_video_with_extensions(
        script["veo_prompt"], target_duration=duration, output_id=f"daily_{date}"
    )

    # 5. ffmpeg muxes audio into video
    final_url = mux_audio_video(video_url, audio_url, f"daily_{date}_final.mp4")

    # 6. Store in daily_reports table
    await store_daily_report(
        report_date=date,
        trade_ids_covered=[t.id for t in flagged_trades],
        narration_script=script["narration_script"],
        veo_prompt=script["veo_prompt"],
        video_url=final_url,
        audio_url=audio_url,
        duration_seconds=duration,
    )
```

### Veo API Call Budget

| Content Type | Frequency | Veo API Calls | Notes |
|---|---|---|---|
| Daily video (~30s) | Nightly | ~4 (1 initial + 3 extensions) | One video per day |
| Per-SEVERE video (~15s) | Per detection | ~2 (1 initial + 1 extension) | ~14 SEVERE trades total (to date) |
| **Steady state** | **Per week** | **~28 daily + ~4 per-SEVERE** | **~32 Veo calls/week** |

---

## 12. Next.js Frontend

### Pages

| Route | Description |
|---|---|
| `/` | **News Feed**: Latest daily video report at top, then SEVERE/SYSTEMIC trade cards with headlines and scores. Systemic dashboard insight sidebar. |
| `/daily/[date]` | **Daily Report**: Full video player (muxed daily video), narration transcript, list of covered trades with links |
| `/politicians` | **Politician Index**: All politicians ranked by aggregate anomaly score. Filterable by party, state, chamber, committee. Click to profile. |
| `/politician/[id]` | **Politician Profile**: Committees, donor sectors, **interactive trade timeline** with all trades overlaid on price charts, trade list with scores |
| `/trades` | **All Trades**: Filterable by severity quadrant, party, state, ticker. Sortable by score, date, amount. |
| `/trade/[id]` | **Trade Detail**: **Interactive price chart** (±90 days), dual score badge, contextualizer report, video player + audio player (if SEVERE), share buttons |
| `/about` | Methodology, dual-model explanation, disclaimers |

All pages are public — no authentication required.

### Interactive Trade Timeline

The timeline is the visual centerpiece. Two views powered by the chart API endpoints.

**Single Trade View (`/trade/[id]`):**
- ±90 days of stock price around the trade date (OHLCV candles or line chart)
- Trade marker (buy/sell) on `trade_date`, color-coded by severity quadrant (red=SEVERE, orange=SYSTEMIC, yellow=OUTLIER, gray=UNREMARKABLE)
- Vertical dashed line at `disclosure_date` showing the disclosure lag visually
- Dimmed SPY benchmark line for visual alpha comparison
- Hover tooltip: trade amount, cohort_index, baseline_index, disclosure_date
- Optional: nearby vote dates and bill dates as secondary markers

**Politician Timeline (`/politician/[id]`):**
- Full date range of all trades by this politician
- Multiple ticker price lines, each with trade markers
- Color-coded markers by severity quadrant
- Filter controls: ticker dropdown, quadrant filter, date range picker
- Reveals *when* they trade relative to price movements

**Chart library:** Lightweight Charts (by TradingView) — purpose-built for financial data. ~40KB, supports candlesticks, line charts, markers/annotations, zoom/pan, hover tooltips.

### Dual Score Component

```typescript
// components/DualScoreBadge.tsx
interface DualScoreBadgeProps {
  cohortIndex: number;
  baselineIndex: number;
  quadrant: "SEVERE" | "SYSTEMIC" | "OUTLIER" | "UNREMARKABLE";
}

const QUADRANT_STYLES = {
  SEVERE:       { bg: "bg-red-100",    border: "border-red-400",    text: "text-red-900"    },
  SYSTEMIC:     { bg: "bg-orange-100", border: "border-orange-400", text: "text-orange-900" },
  OUTLIER:      { bg: "bg-yellow-100", border: "border-yellow-400", text: "text-yellow-900" },
  UNREMARKABLE: { bg: "bg-gray-100",   border: "border-gray-300",   text: "text-gray-700"   },
};

export function DualScoreBadge({ cohortIndex, baselineIndex, quadrant }: DualScoreBadgeProps) {
  const style = QUADRANT_STYLES[quadrant];
  return (
    <div className={`rounded-xl border-2 p-4 ${style.bg} ${style.border}`}>
      <div className="flex justify-between mb-3">
        <div className="text-center">
          <div className={`text-4xl font-bold ${style.text}`}>{cohortIndex}</div>
          <div className="text-xs text-gray-500 mt-1">vs. Congress</div>
        </div>
        <div className="text-center">
          <div className={`text-4xl font-bold ${style.text}`}>{baselineIndex}</div>
          <div className="text-xs text-gray-500 mt-1">vs. Fund Managers</div>
        </div>
      </div>
      <div className={`text-center font-bold text-sm uppercase tracking-wide ${style.text}`}>
        {quadrant}
      </div>
    </div>
  );
}
```

### Trade Detail Page Layout (`/trade/[id]`)

```
┌──────────────────────────────────────────────┐
│  [SEVERE]  Rep. Jane Smith — $500K AAPL BUY  │  ← DualScoreBadge
│  Cohort: 87/100    Baseline: 92/100          │
├──────────────────────────────────────────────┤
│                                              │
│  ┌──── Interactive Price Chart ────────────┐ │  ← Lightweight Charts
│  │  AAPL │ ±90 days │ Trade ▲ │ SPY ···   │ │     OHLCV + markers
│  │  ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈ │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  ▶ Listen to Briefing (0:45)    [Audio bar]  │  ← TTS MP3 (if SEVERE)
│                                              │
│  📹 Watch Video Clip                         │  ← Veo MP4 (if SEVERE)
│  ┌──── 9:16 Video Player ─────────────────┐ │
│  │                                        │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  [Share to X]  [Copy Link]  [Download Video] │  ← Share buttons
│                                              │
│  ─── Contextualizer Report ─────────────────│
│  Headline: ...                               │  ← From audit_reports
│  Narrative: ...                              │
│  Evidence: ...                               │
│  Disclaimer: ...                             │
└──────────────────────────────────────────────┘
```

### Systemic Dashboard Component

```typescript
// components/SystemicInsight.tsx
export function SystemicInsight({ stats }: { stats: SystemicStats }) {
  return (
    <div className="bg-orange-50 border-2 border-orange-300 rounded-2xl p-6">
      <h2 className="text-2xl font-bold text-orange-900 mb-2">
        Systemic Finding
      </h2>
      <p className="text-4xl font-black text-orange-700 my-4">
        {(stats.pctFlaggedByBaseline * 100).toFixed(1)}%
      </p>
      <p className="text-orange-800 text-lg">
        of congressional trades over the past 3 years would be flagged as
        statistically anomalous if evaluated against institutional fund managers
        with no access to legislative information.
      </p>
    </div>
  );
}
```

---

## 13. Deployment & Scheduling

```yaml
# docker-compose.yml
version: "3.9"
services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: house_advantage
    volumes:
      - mysql_data:/var/lib/mysql
      - ./backend/db/schema.sql:/docker-entrypoint-initdb.d/schema.sql

  backend:
    build: ./backend
    environment:
      DATABASE_URL: mysql+aiomysql://root:${MYSQL_ROOT_PASSWORD}@mysql:3306/house_advantage
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      GOOGLE_CLOUD_API_KEY: ${GOOGLE_CLOUD_API_KEY}
      CONGRESS_GOV_API_KEY: ${CONGRESS_GOV_API_KEY}
      FEC_API_KEY: ${FEC_API_KEY}
      GOVINFO_API_KEY: ${GOVINFO_API_KEY}
      OPENFIGI_API_KEY: ${OPENFIGI_API_KEY}
      MEDIA_STORAGE_PATH: /media
      GCS_BUCKET: ${GCS_BUCKET:-}
    ports: ["8000:8000"]
    volumes:
      - media_data:/media
    command: uvicorn main:app --host 0.0.0.0 --port 8000

  scheduler:
    build: ./backend
    environment:
      DATABASE_URL: mysql+aiomysql://root:${MYSQL_ROOT_PASSWORD}@mysql:3306/house_advantage
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      GOOGLE_CLOUD_API_KEY: ${GOOGLE_CLOUD_API_KEY}
      MEDIA_STORAGE_PATH: /media
      GCS_BUCKET: ${GCS_BUCKET:-}
    volumes:
      - media_data:/media
    command: python scheduler.py

  frontend:
    build: ./frontend
    environment:
      NEXT_PUBLIC_API_URL: http://backend:8000
    ports: ["3000:3000"]

  nginx:
    image: nginx:alpine
    volumes: ["./nginx.conf:/etc/nginx/conf.d/default.conf"]
    ports: ["80:80"]

volumes:
  mysql_data:
  media_data:
```

### Nightly Job Schedule (APScheduler)

| Time | Job | Description |
|---|---|---|
| 02:00 UTC | Data ingestion | 12-step orchestrator (Steps 1–12) |
| 04:00 UTC | Dual scoring | Score new trades, assign quadrants |
| 04:30 UTC | Gemini contextualizer | Generate context reports for SEVERE + SYSTEMIC trades |
| 05:00 UTC | Daily video scriptwriter | Gemini writes daily narration script + Veo prompt |
| 05:10 UTC | TTS generation | Generate audio for daily report + per-SEVERE trades |
| 05:30 UTC | Veo 3.1 generation | Generate video for daily report + per-SEVERE trades |
| 05:50 UTC | ffmpeg assembly | Mux TTS audio into Veo video for all new media |
| 06:00 UTC | Systemic stats | Update platform-level aggregate stats |

---

## 14. Legal & Ethical Safeguards

- **Naming:** Output is called **"Trade Anomaly Index"** — never "corruption score"
- **Quadrant framing:** SYSTEMIC trades are explicitly framed as a possible *systemic* pattern, not individual wrongdoing
- **Mandatory disclaimer** on every trade card, report, video, and audio:

> *"The Trade Anomaly Index is generated by automated statistical models. A high score means a trade is a statistical outlier relative to its comparison population — it does NOT constitute evidence of illegal activity or wrongdoing. The Cohort Index compares against all congressional trades; the Baseline Index compares against institutional fund managers. All data sourced from public STOCK Act disclosures and SEC filings."*

- All source URLs link back to the original government filing

### GenMedia-Specific Safeguards

- **Video disclaimer watermark:** All Veo-generated videos carry a persistent "AI-Generated Disclosure Analysis" text overlay, authored by Gemini in the `video_prompt`
- **TTS preamble:** Every audio briefing opens with: "This is an AI-generated analysis from House Advantage."
- **No real faces:** Veo prompts use `person_generation="dont_allow"` and Gemini is instructed to use abstract/symbolic imagery only
- **Video metadata:** All generated MP4 files include "AI-Generated" in file metadata tags

---

## 15. MVP Scope & Roadmap

### ✅ V2 (Completed — July 2025)
- [x] 9-feature dual scoring (cohort + baseline Isolation Forest models)
- [x] SEC 13-F baseline ingestion + training
- [x] 9,720 trades scored — SEVERE 14 | SYSTEMIC 379 | OUTLIER 78 | UNREMARKABLE 9,249
- [x] V1→V2 validated, disclosure_lag dominance eliminated

### 🎯 V3 MVP (Current — GenMedia Hackathon)
- [ ] Gemini 2.5 Pro function-calling contextualizer with V3 JSON schema
- [ ] Daily video scriptwriter (Gemini → narration + Veo prompt)
- [ ] TTS audio pipeline (Google Cloud TTS — generates first, exact duration)
- [ ] Veo 3.1 video pipeline with scene extensions (~30s daily, ~15s per-SEVERE)
- [ ] ffmpeg audio/video muxing (TTS MP3 into Veo MP4)
- [ ] `media_assets`, `daily_reports` DB tables
- [ ] Daily video news report published to news feed
- [ ] Per-SEVERE-trade individual video + audio briefing
- [ ] Politician index (ranked by aggregate anomaly score, filterable)
- [ ] Interactive trade timeline (Lightweight Charts — single-trade + politician views)
- [ ] Chart API endpoints (`/chart/trade/{id}`, `/chart/politician/{id}`)
- [ ] FastAPI endpoints: systemic, leaderboard, politician, trade, media, share, daily-reports, trades, politicians
- [ ] Next.js frontend: News Feed, Daily Report, Politician Index, Politician Profile, All Trades, Trade Detail, About
- [ ] OG meta tags on `/trade/[id]` and `/daily/[date]` for social link previews
- [ ] All genMedia disclaimers (video watermark, TTS preamble)

### 🗓 V4 Roadmap
- Longitudinal tracking (politician score trends over time)
- Per-sector systemic breakdown
- Alert subscriptions (notify when your rep trades)
- Bill ghostwriter detection
- Network graph (donor → politician → vote → trade)
- Quarterly model retraining pipeline with MLflow
- Podcast RSS feed auto-generated from weekly TTS briefings

---

## 16. Virality & Distribution Strategy

### Primary Platform: TikTok / Instagram Reels

**Format:** 9:16 portrait video (1080×1920), ~30 seconds daily / ~15 seconds per-trade, auto-generated by Veo 3.1 with scene extensions from Gemini-written prompts.

**Content cadence:**
- **Daily (auto):** ~30s daily news report video covering that night's SEVERE + SYSTEMIC trades
- **Per-SEVERE (auto):** Individual ~15s video for each new SEVERE trade detected
- **Content drought:** If no new SEVERE/SYSTEMIC trades on a given day, daily video covers random historical flagged trades

### Social Hooks

- *"Did your representative trade stocks before a vote?"*
- *"14 congressional trades are unusual even by congressional standards"*
- *"Congress trades like no one else — literally. Here's the data."*

### Share Flow

```
User views /trade/[id]
    → Sees video + contextualizer report + chart
    → Clicks [Share to X] / [Copy Link] / [Download Video]
    → Link has OG meta tags → rich preview shows:
        ├── Politician name + photo_url
        ├── Severity quadrant badge (SEVERE/SYSTEMIC)
        ├── Dual score (e.g., "87/100 vs. Congress | 92/100 vs. Fund Managers")
        └── Headline from contextualizer report
    → Downloaded video is 9:16 ready for TikTok/Reels upload
```

### OG Meta Tags

```html
<!-- Generated server-side for every /trade/[id] -->
<meta property="og:title" content="SEVERE: Rep. Smith bought $500K AAPL before defense vote" />
<meta property="og:description" content="Cohort: 87/100 | Baseline: 92/100 — House Advantage" />
<meta property="og:image" content="/api/v1/share/4523/thumbnail.png" />
<meta property="og:video" content="/api/v1/media/4523" />
<meta property="og:type" content="video.other" />
```

### Accessibility

All dashboards, charts, reports, pre-generated videos, and audio are **public and unauthenticated**. No sign-in is required for any feature. Every piece of content is pre-generated during the nightly pipeline and served from the database.

This maximizes virality: anyone with a shared link sees the full content immediately, no login wall.

---

## 17. Environment Variables & API Keys

```bash
# .env
MYSQL_ROOT_PASSWORD=your_password

# ── Google AI & Cloud ─────────────────────────────────────────
GEMINI_API_KEY=                   # aistudio.google.com/app/apikey (Gemini 2.5 Pro + Veo 3.1)
GOOGLE_CLOUD_API_KEY=             # console.cloud.google.com      (TTS API)

# ── Government Data APIs ──────────────────────────────────────
CONGRESS_GOV_API_KEY=             # api.congress.gov              (free)
FEC_API_KEY=                      # api.open.fec.gov              (free)
GOVINFO_API_KEY=                  # api.govinfo.gov               (free)
OPENFIGI_API_KEY=                 # openfigi.com/api              (free, optional)

# ── Media Storage ─────────────────────────────────────────────
MEDIA_STORAGE_PATH=/media         # Local volume path for dev
GCS_BUCKET=                       # GCS bucket name for production (optional)

# ── No Key Required ───────────────────────────────────────────
# yfinance: no key
# SEC 13-F bulk CSVs: no key
# House Clerk disclosures: no key
# Senate eFD filings: no key
```

---

*House Advantage MVP Blueprint v4.1 · V3 GenMedia Architecture (Revised) · March 2026*
