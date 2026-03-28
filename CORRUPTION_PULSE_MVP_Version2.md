# House Advantage — Full MVP Blueprint
### A Gemini-Powered Congressional Trade Anomaly Detection Platform
**Version:** 3.1 (V2 Feature Architecture)
**Target:** Gemini Hackathon Submission
**Date:** July 2025

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [What Makes This "Not a Wrapper"](#2-what-makes-this-not-a-wrapper)
3. [The Dual-Model Architecture](#3-the-dual-model-architecture)
4. [System Architecture](#4-system-architecture)
5. [Database Schema](#5-database-schema)
6. [Data Ingestion Layer](#6-data-ingestion-layer)
7. [ML Scoring Engine](#7-ml-scoring-engine)
8. [FastAPI Backend](#8-fastapi-backend)
9. [Gemini Agentic Auditor](#9-gemini-agentic-auditor)
10. [Next.js Frontend](#10-nextjs-frontend)
11. [Deployment & Scheduling](#11-deployment--scheduling)
12. [Legal & Ethical Safeguards](#12-legal--ethical-safeguards)
13. [MVP Scope vs. V2 Roadmap](#13-mvp-scope-vs-v2-roadmap)
14. [Environment Variables & API Keys](#14-environment-variables--api-keys)

---

## 1. Project Overview

**House Advantage** is a civic-tech platform that automatically detects and explains statistically anomalous congressional stock trades using a dual machine learning model and a Gemini-powered agentic auditor.

### The Core Problem

The STOCK Act requires members of Congress to publicly disclose stock trades. That data sits in raw government databases that most people will never read. Existing tools surface numbers — they don't explain them. A constituent seeing that their senator bought $250,000 of Lockheed Martin stock has no way of knowing whether that's suspicious without hours of cross-referencing voting records, committee assignments, and campaign finance disclosures themselves.

### The Two-Layer Insight

Most transparency tools treat every congressional trade in isolation. House Advantage makes two distinct accusations:

- **Individual accusation:** *"This specific trade is unusual even by congressional standards"*
- **Systemic accusation:** *"Congressional trading as a whole is unusual compared to normal investors — the average member of Congress trades in ways that would be flagged as anomalous in any other context"*

These require two separate ML models trained on fundamentally different baselines.

### The Core Loop

```
Public STOCK Act Disclosures
        ↓
Model 1 (Cohort Model): Is this unusual within Congress?
Model 2 (Baseline Model): Is this unusual vs. normal investors?
        ↓
Combined Dual Score → Severity Quadrant
        ↓
Gemini receives scores + context, calls DB tools, reads bill text
        ↓
Gemini synthesizes a sourced, natural-language "Trade Audit Report"
        ↓
User reads the report on a Next.js dashboard
```

---

## 2. What Makes This "Not a Wrapper"

Gemini performs three non-trivial roles that are impossible to replicate with a simple prompt:

| Role | Gemini Feature Used | Why It's Non-Trivial |
|---|---|---|
| **Function-Calling Auditor** | Function Calling (tool use) | Gemini autonomously decides which DB queries to run based on dual-model score context. It is not told what to fetch. |
| **Bill Text Analyst** | Long-Context Window (1M tokens) | Gemini reads raw congressional bill text (50,000–200,000+ tokens) and extracts sections relevant to the trade's industry sector. |
| **Report Synthesizer** | Structured output + grounded reasoning | Gemini generates a cited, structured JSON report — not freeform chat — that the frontend renders deterministically. |

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
│  House Clerk PDFs │ Senate eFD     │ Congress.gov  │ OpenFEC API   │
│  SEC 13-F Bulk    │ yfinance       │ OpenFIGI      │ GovInfo API   │
└──────────┬───────────────────────────────────────────────────────┘
           │ Nightly Ingestion (APScheduler)
           ▼
┌──────────────────────────────────────────────────────────────────┐
│                       MySQL DATABASE                             │
│  politicians │ trades │ votes │ committees │ donors              │
│  bills │ baseline_trades │ anomaly_scores │ audit_reports        │
└──────────┬───────────────────────────────────────────────────────┘
           │                              ▲
           │  Nightly Scoring Job          │ Function Calls
           ▼                              │
┌─────────────────────┐       ┌───────────────────────────────────┐
│  MODEL 1            │       │  Gemini 2.5 Pro Agent             │
│  Cohort Model       │──┐    │  - get_candidate_data()           │
│  (trained on        │  │    │  - get_trades_for_candidate()     │
│   congressional     │  │    │  - get_votes_near_trade()         │
│   trades)           │  │ scores │  - get_donors()               │
└─────────────────────┘  │    │  - read_bill_text()               │
                         ├──▶ │  - get_systemic_stats()           │
┌─────────────────────┐  │    └──────────────────┬────────────────┘
│  MODEL 2            │──┘                       │ Audit Report (JSON)
│  Baseline Model     │                          ▼
│  (trained on        │         ┌────────────────────────────────┐
│   SEC 13-F funds)   │         │   FastAPI Backend (Python)      │
└─────────────────────┘         │   /api/v1/politician/{id}       │
                                │   /api/v1/audit/{trade_id}      │
                                │   /api/v1/leaderboard           │
                                │   /api/v1/systemic              │
                                └──────────────┬─────────────────┘
                                               │ REST JSON
                                               ▼
                                ┌──────────────────────────────────┐
                                │   Next.js Frontend               │
                                │   - Systemic Dashboard           │
                                │   - Politician Profile           │
                                │   - Trade Anomaly Feed           │
                                │   - Dual Score Trade Detail      │
                                └──────────────────────────────────┘
```

### Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| Frontend | Next.js 15 (App Router) | SSR, easy API routes, great DX |
| Backend API | FastAPI (Python 3.12) | Async, auto-docs, ML integration |
| ML Engine | scikit-learn (Python) | Isolation Forest, two pipeline instances |
| AI Auditor | Gemini 2.5 Pro via `google-generativeai` SDK | Function calling, 1M token context |
| Database | MySQL 8.0 | Relational joins across all entities |
| Task Scheduler | APScheduler | Nightly ingestion and scoring |
| ORM | SQLAlchemy 2.0 | Async MySQL queries |
| Containerization | Docker + docker-compose | Reproducible environment |
| Reverse Proxy | Nginx | Routes `/api/*` to FastAPI |

---

## 5. Database Schema

```sql
-- ============================================================
-- house_advantage_schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS house_advantage;
USE house_advantage;

-- ── Politicians ──────────────────────────────────────────────
CREATE TABLE politicians (
    id              VARCHAR(20) PRIMARY KEY,
    full_name       VARCHAR(120) NOT NULL,
    party           ENUM('D','R','I') NOT NULL,
    chamber         ENUM('house','senate') NOT NULL,
    state           CHAR(2) NOT NULL,
    district        VARCHAR(10),
    photo_url       VARCHAR(255),
    in_office       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ── Committees ───────────────────────────────────────────────
CREATE TABLE committees (
    id              VARCHAR(10) PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    chamber         ENUM('house','senate','joint') NOT NULL,
    industry_sector VARCHAR(100)
);

-- ── Committee Memberships ────────────────────────────────────
CREATE TABLE committee_memberships (
    politician_id   VARCHAR(20) NOT NULL,
    committee_id    VARCHAR(10) NOT NULL,
    role            ENUM('member','chair','ranking_member') DEFAULT 'member',
    congress        SMALLINT NOT NULL,
    PRIMARY KEY (politician_id, committee_id, congress),
    FOREIGN KEY (politician_id) REFERENCES politicians(id),
    FOREIGN KEY (committee_id) REFERENCES committees(id)
);

-- ── Congressional Stock Trades ───────────────────────────────
CREATE TABLE trades (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    politician_id       VARCHAR(20) NOT NULL,
    ticker              VARCHAR(10) NOT NULL,
    company_name        VARCHAR(200),
    trade_type          ENUM('buy','sell','exchange') NOT NULL,
    trade_date          DATE NOT NULL,
    disclosure_date     DATE NOT NULL,
    disclosure_lag_days SMALLINT GENERATED ALWAYS AS
                            (DATEDIFF(disclosure_date, trade_date)) STORED,
    amount_lower        INT NOT NULL,
    amount_upper        INT NOT NULL,
    amount_midpoint     INT GENERATED ALWAYS AS
                            ((amount_lower + amount_upper) / 2) STORED,
    asset_type          VARCHAR(50),
    industry_sector     VARCHAR(100),
    source_url          VARCHAR(255),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (politician_id) REFERENCES politicians(id),
    INDEX idx_politician_date (politician_id, trade_date),
    INDEX idx_ticker (ticker),
    INDEX idx_sector (industry_sector)
);

-- ── Baseline Trades (SEC 13-F Derived) ──────────────────────
-- These are NOT real individual trades — they are inferred quarterly
-- position changes from 13-F filings, used exclusively for training
-- Model 2. They are never displayed to users.
CREATE TABLE baseline_trades (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    fund_cik        VARCHAR(20) NOT NULL,       -- SEC CIK of the fund
    fund_name       VARCHAR(200),
    ticker          VARCHAR(10) NOT NULL,
    trade_type      ENUM('buy','sell') NOT NULL, -- inferred from quarter-over-quarter change
    inferred_date   DATE NOT NULL,              -- last day of the quarter (approximate)
    shares_delta    INT NOT NULL,               -- positive = buy, negative = sell
    value_usd       BIGINT NOT NULL,            -- USD value of position change
    industry_sector VARCHAR(100),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fund (fund_cik),
    INDEX idx_sector (industry_sector)
);

-- ── Votes ────────────────────────────────────────────────────
CREATE TABLE votes (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    bill_id         VARCHAR(50) NOT NULL,
    vote_date       DATE NOT NULL,
    chamber         ENUM('house','senate') NOT NULL,
    vote_question   VARCHAR(500),
    description     TEXT,
    related_sector  VARCHAR(100)
);

-- ── Politician Votes ─────────────────────────────────────────
CREATE TABLE politician_votes (
    politician_id   VARCHAR(20) NOT NULL,
    vote_id         BIGINT NOT NULL,
    position        ENUM('yes','no','abstain','not_voting') NOT NULL,
    PRIMARY KEY (politician_id, vote_id),
    FOREIGN KEY (politician_id) REFERENCES politicians(id),
    FOREIGN KEY (vote_id) REFERENCES votes(id)
);

-- ── Bills ────────────────────────────────────────────────────
CREATE TABLE bills (
    id                  VARCHAR(50) PRIMARY KEY,
    congress            SMALLINT NOT NULL,
    bill_number         VARCHAR(20) NOT NULL,
    title               TEXT NOT NULL,
    introduced_date     DATE,
    related_sector      VARCHAR(100),
    govinfo_package_id  VARCHAR(80),
    summary             TEXT,
    full_text_url       VARCHAR(255)
);

-- ── Donors ───────────────────────────────────────────────────
CREATE TABLE donors (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    politician_id   VARCHAR(20) NOT NULL,
    donor_name      VARCHAR(255) NOT NULL,
    donor_type      ENUM('individual','pac','super_pac','corporation','other') NOT NULL,
    industry_sector VARCHAR(100),
    amount          INT NOT NULL,
    election_cycle  SMALLINT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (politician_id) REFERENCES politicians(id),
    INDEX idx_politician_sector (politician_id, industry_sector)
);

-- ── Dual Anomaly Scores ──────────────────────────────────────
-- Stores output from BOTH models for every trade
CREATE TABLE anomaly_scores (
    id                      BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_id                BIGINT NOT NULL UNIQUE,
    scored_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Model 1: Cohort Model (trained on congressional trades)
    cohort_raw_score        FLOAT NOT NULL,
    cohort_label            TINYINT NOT NULL,        -- -1 = outlier, 1 = normal
    cohort_index            TINYINT UNSIGNED NOT NULL, -- 0–100
    cohort_confidence_low   TINYINT UNSIGNED,
    cohort_confidence_high  TINYINT UNSIGNED,

    -- Model 2: Baseline Model (trained on 13-F institutional trades)
    baseline_raw_score      FLOAT NOT NULL,
    baseline_label          TINYINT NOT NULL,
    baseline_index          TINYINT UNSIGNED NOT NULL,
    baseline_confidence_low TINYINT UNSIGNED,
    baseline_confidence_high TINYINT UNSIGNED,

    -- Combined output
    severity_quadrant       ENUM('SEVERE','SYSTEMIC','OUTLIER','UNREMARKABLE') NOT NULL,
    audit_triggered         BOOLEAN DEFAULT FALSE,

    -- Feature values (stored for auditability and Gemini context)
    feat_cohort_alpha       FLOAT,
    feat_pre_trade_alpha    FLOAT,
    feat_proximity_days     SMALLINT,
    feat_bill_proximity     SMALLINT,
    feat_has_proximity_data TINYINT,
    feat_committee_relevance FLOAT,
    feat_amount_zscore      FLOAT,
    feat_cluster_score      TINYINT,
    feat_disclosure_lag     SMALLINT,          -- log1p(days) in V2

    FOREIGN KEY (trade_id) REFERENCES trades(id),
    INDEX idx_quadrant (severity_quadrant),
    INDEX idx_cohort_index (cohort_index),
    INDEX idx_baseline_index (baseline_index)
);

-- ── Gemini Audit Reports ──────────────────────────────────────
CREATE TABLE audit_reports (
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
    gemini_model        VARCHAR(80),
    prompt_tokens       INT,
    output_tokens       INT,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

-- ── Systemic Stats (platform-level aggregate) ────────────────
-- Updated nightly. Powers the Systemic Dashboard.
CREATE TABLE systemic_stats (
    id                          BIGINT AUTO_INCREMENT PRIMARY KEY,
    computed_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_trades_scored         INT,
    severe_count                INT,         -- both models high
    systemic_count              INT,         -- baseline high, cohort low
    outlier_count               INT,
    unremarkable_count          INT,
    avg_cohort_index            FLOAT,
    avg_baseline_index          FLOAT,
    -- The key systemic metric: what % of congressional trades would be
    -- flagged if evaluated against the institutional investor baseline alone?
    pct_flagged_by_baseline     FLOAT,
    top_systemic_sector         VARCHAR(100) -- sector with most SYSTEMIC trades
);
```

---

## 6. Data Ingestion Layer

### 6.1 Data Sources

| Data Type | Source | Cost | Used For |
|---|---|---|---|
| Congressional trades (House) | House Clerk Financial Disclosure portal | Free | Training Model 1 + nightly scoring |
| Congressional trades (Senate) | Senate eFD (efdsearch.senate.gov) | Free | Training Model 1 + nightly scoring |
| Politicians, votes, bills | Congress.gov API | Free | Features 2, 3 + Gemini context |
| Committee memberships | Congress.gov API + congress-legislators GitHub | Free | Feature 4 (committee_relevance) |
| Bill text | GovInfo API | Free | Gemini bill analysis |
| Campaign finance / donors | OpenFEC API | Free | Gemini context |
| Institutional fund trades | SEC 13-F Bulk CSVs | Free | Training Model 2 |
| CUSIP → Ticker mapping | OpenFIGI API | Free | Processing 13-F data |
| Stock prices | yfinance | Free | Feature 1 (both models) |

### 6.2 Congressional Trade Ingestion

Congressional trades are scraped directly from official government disclosure portals:

- **House:** Annual ZIP files from the House Clerk's Financial Disclosure site (`disclosures-clerk.house.gov`), containing XML indexes and PTR PDFs parsed with `pdfplumber`.
- **Senate:** The Senate eFD system (`efdsearch.senate.gov`) DataTables AJAX API, scraped with `cloudscraper`.

The ingestion orchestrator runs both collectors and merges results:

```python
# backend/ingest/orchestrator.py runs all collectors
# House: backend/ingest/collectors/collect_house_disclosures.py
# Senate: backend/ingest/collectors/collect_senate_disclosures.py
# Both produce data/raw/{house,senate}_trades_raw.csv
# which are combined into congressional_trades_raw.csv
```

### 6.3 SEC 13-F Baseline Ingestion

This is the new data pipeline that feeds Model 2. SEC 13-F filings are free quarterly bulk downloads from SEC.gov.

```python
# ingest/ingest_13f.py
"""
Downloads SEC 13-F quarterly bulk CSVs and converts them into
inferred trades (quarter-over-quarter position changes).
These populate the baseline_trades table for Model 2 training.

Data source: https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets
Free, no API key required.
"""
import io, requests, zipfile
import pandas as pd
import numpy as np

SEC_13F_BASE = "https://www.sec.gov/files"

# Limit to a curated set of large, diversified, non-activist funds
# that are unlikely to have any legislative information advantages.
# These are passive/index-tracking or broad market active managers.
CLEAN_FUND_CIKS = [
    "0001166559",  # Vanguard Group
    "0001364742",  # BlackRock
    "0000093715",  # Fidelity (FMR)
    "0001109357",  # State Street
    "0001045810",  # T. Rowe Price
    # Add more diversified institutional managers as needed
]

def download_13f_quarter(year: int, quarter: int) -> pd.DataFrame:
    """Download and parse a single quarter of 13-F bulk data."""
    url = f"{SEC_13F_BASE}/13f-{year}q{quarter}.zip"
    print(f"[13f] Downloading {url}...")
    
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        # The ZIP contains infotable.tsv — the holdings table
        with z.open("infotable.tsv") as f:
            df = pd.read_csv(f, sep="\t", dtype=str)
    
    # Normalize column names (SEC changes them occasionally)
    df.columns = [c.lower().strip() for c in df.columns]
    
    # Filter to clean funds only
    df = df[df["cik"].isin(CLEAN_FUND_CIKS)]
    
    # Keep only equity holdings (sshprnamt_type == 'SH')
    df = df[df.get("sshprnamttype", df.get("sshprnamt_type", pd.Series(dtype=str))) == "SH"]
    
    df["year"] = year
    df["quarter"] = quarter
    return df

def infer_trades_from_holdings(holdings_q1: pd.DataFrame,
                                holdings_q2: pd.DataFrame,
                                quarter_end_date: str) -> pd.DataFrame:
    """
    Compare two consecutive quarters of holdings to infer buys and sells.
    A position that increased = buy. Decreased or disappeared = sell.
    This is the standard academic methodology for 13-F derived trade analysis.
    """
    q1 = holdings_q1.set_index(["cik", "cusip"])[["sshprnamt"]].astype(float)
    q2 = holdings_q2.set_index(["cik", "cusip"])[["sshprnamt"]].astype(float)
    
    combined = q1.join(q2, lsuffix="_q1", rsuffix="_q2", how="outer").fillna(0)
    combined["delta"] = combined["sshprnamt_q2"] - combined["sshprnamt_q1"]
    
    # Only keep meaningful changes (> 100 shares to filter noise)
    combined = combined[combined["delta"].abs() > 100].reset_index()
    combined["trade_type"] = combined["delta"].apply(lambda x: "buy" if x > 0 else "sell")
    combined["shares_delta"] = combined["delta"].abs().astype(int)
    combined["inferred_date"] = quarter_end_date
    
    return combined[["cik", "cusip", "trade_type", "shares_delta", "inferred_date"]]

def cusip_to_ticker(cusips: list[str]) -> dict[str, str]:
    """
    Map CUSIPs to ticker symbols using the free OpenFIGI API.
    Batches requests to respect rate limits.
    """
    OPENFIGI_KEY = os.getenv("OPENFIGI_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if OPENFIGI_KEY:
        headers["X-OPENFIGI-APIKEY"] = OPENFIGI_KEY
    
    mapping = {}
    batch_size = 100  # OpenFIGI max batch size
    
    for i in range(0, len(cusips), batch_size):
        batch = cusips[i:i + batch_size]
        payload = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
        resp = requests.post(
            "https://api.openfigi.com/v3/mapping",
            headers=headers,
            json=payload,
            timeout=30,
        )
        for cusip, result in zip(batch, resp.json()):
            data = result.get("data", [])
            if data:
                mapping[cusip] = data[0].get("ticker", "")
    
    return mapping

def build_baseline_dataset(years: list[int] = [2022, 2023, 2024]) -> pd.DataFrame:
    """
    Full pipeline: download 13-F data, infer trades, map tickers.
    Returns a DataFrame ready for feature engineering and Model 2 training.
    """
    all_inferred = []
    
    for year in years:
        for q in range(1, 4):  # Compare Q1→Q2, Q2→Q3, Q3→Q4
            try:
                q1_data = download_13f_quarter(year, q)
                q2_data = download_13f_quarter(year, q + 1)
                quarter_end = f"{year}-{(q * 3):02d}-30"
                inferred = infer_trades_from_holdings(q1_data, q2_data, quarter_end)
                all_inferred.append(inferred)
            except Exception as e:
                print(f"[13f] Warning: Could not process {year} Q{q}→Q{q+1}: {e}")
    
    # Also compare Q4 → next year Q1
    for year in years[:-1]:
        try:
            q4_data = download_13f_quarter(year, 4)
            q1_next = download_13f_quarter(year + 1, 1)
            inferred = infer_trades_from_holdings(q4_data, q1_next, f"{year}-12-31")
            all_inferred.append(inferred)
        except Exception as e:
            print(f"[13f] Warning: Could not process {year} Q4 → {year+1} Q1: {e}")
    
    df = pd.concat(all_inferred, ignore_index=True)
    
    # Map CUSIPs to tickers
    unique_cusips = df["cusip"].dropna().unique().tolist()
    print(f"[13f] Mapping {len(unique_cusips)} CUSIPs to tickers via OpenFIGI...")
    ticker_map = cusip_to_ticker(unique_cusips)
    df["ticker"] = df["cusip"].map(ticker_map)
    df = df.dropna(subset=["ticker"])
    df = df[df["ticker"].str.match(r"^[A-Z]{1,5}$", na=False)]
    
    print(f"[13f] Baseline dataset: {len(df)} inferred fund trades.")
    df.to_csv("data/raw/baseline_trades_raw.csv", index=False)
    return df

if __name__ == "__main__":
    build_baseline_dataset()
```

---

## 7. ML Scoring Engine

### 7.1 Feature Vectors (V2)

Both models use the **same 9 features** (V2) computed the same way. The only difference is the population they were trained on. V2 expanded from 5 to 9 features and changed `disclosure_lag` to `log1p(days)` to eliminate its dominance over detections.

| Feature | Congressional Trades | Baseline (13-F) Trades |
|---|---|---|
| `cohort_alpha` | 30-day forward return vs SPY | 30-day forward return vs SPY (same computation) |
| `pre_trade_alpha` | 30-day pre-trade return vs SPY | Computed (same as Model 1) — V2: now active |
| `proximity_days` | Days to nearest sector-relevant vote (median-imputed) | Fixed at median — fund managers have no votes |
| `bill_proximity` | Days to nearest sector-relevant bill (median-imputed) | Fixed at median — fund managers have no bills |
| `has_proximity_data` | 1 if politician had a real sector vote within 90 days, 0 otherwise | Fixed at **0** — fund managers have no votes |
| `committee_relevance` | 0.0–1.0 continuous committee oversight score | Fixed at **0.0** — fund managers are not on committees |
| `amount_zscore` | Trade amount z-score within politician's history | Fixed at **0.0** — not comparable to institutional trades |
| `cluster_score` | Count of other politicians trading same ticker within ±7 days | Fixed at **0** — not applicable to fund rebalancing |
| `disclosure_lag` | `log1p(days)` from trade to STOCK Act filing | Fixed at **0** — 13-F quarterly filing is the norm |

> **Key insight:** Political features (proximity_days, bill_proximity, has_proximity_data, committee_relevance, amount_zscore, cluster_score, disclosure_lag) are fixed/zero for baseline trades. Model 2 learns from `cohort_alpha` + `pre_trade_alpha` (V2) — what normal market returns and momentum look like for institutional investors. Congressional trades that score high on Model 2 are anomalous because their financial performance exceeds what large institutional investors achieve.
>
> **V2 change:** `donor_overlap` was dropped (0% coverage). Four new features added: `pre_trade_alpha`, `bill_proximity`, `amount_zscore`, `cluster_score`. `disclosure_lag` changed from raw days to `log1p(days)` — this eliminated the V1 problem where disclosure_lag drove ~61% of flagged detections.

### 7.2 Dual Scoring Pipeline

```python
# scoring/dual_scorer.py
"""
Loads both trained models and scores every new congressional trade
against both baselines simultaneously.
"""
import joblib
import numpy as np
import pandas as pd
from pathlib import Path

FEATURES = ["cohort_alpha", "pre_trade_alpha", "proximity_days",
            "bill_proximity", "has_proximity_data",
            "committee_relevance", "amount_zscore",
            "cluster_score", "disclosure_lag"]

def load_models() -> tuple:
    cohort_pipeline   = joblib.load("model/cohort_model_v2.pkl")
    baseline_pipeline = joblib.load("model/baseline_model_v2.pkl")
    return cohort_pipeline, baseline_pipeline

def normalize_score(raw_scores: np.ndarray) -> np.ndarray:
    """Convert Isolation Forest decision_function output to 0–100 index."""
    clipped = np.clip(raw_scores, -0.5, 0.5)
    return ((-clipped + 0.5) / 1.0 * 100).astype(int).clip(0, 100)

def assign_quadrant(cohort_index: int, baseline_index: int,
                    threshold: int = 60) -> str:
    if cohort_index >= threshold and baseline_index >= threshold:
        return "SEVERE"
    elif cohort_index < threshold and baseline_index >= threshold:
        return "SYSTEMIC"
    elif cohort_index >= threshold and baseline_index < threshold:
        return "OUTLIER"
    else:
        return "UNREMARKABLE"

def score_trades(df: pd.DataFrame) -> pd.DataFrame:
    """
    Score a DataFrame of congressional trades against both models.
    Returns the input DataFrame with added dual-score columns.
    """
    cohort_pipeline, baseline_pipeline = load_models()
    X = df[FEATURES]
    
    # ── Model 1: Cohort ──────────────────────────────────────
    cohort_scaler  = cohort_pipeline.named_steps["scaler"]
    cohort_iforest = cohort_pipeline.named_steps["iforest"]
    cohort_raw     = cohort_iforest.decision_function(
                        cohort_scaler.transform(X))
    df["cohort_label"]          = cohort_pipeline.predict(X)
    df["cohort_raw_score"]      = cohort_raw
    df["cohort_index"]          = normalize_score(cohort_raw)
    df["cohort_confidence_low"]  = (df["cohort_index"] - 5).clip(0, 100)
    df["cohort_confidence_high"] = (df["cohort_index"] + 5).clip(0, 100)
    
    # ── Model 2: Baseline ────────────────────────────────────
    baseline_scaler  = baseline_pipeline.named_steps["scaler"]
    baseline_iforest = baseline_pipeline.named_steps["iforest"]
    baseline_raw     = baseline_iforest.decision_function(
                          baseline_scaler.transform(X))
    df["baseline_label"]          = baseline_pipeline.predict(X)
    df["baseline_raw_score"]      = baseline_raw
    df["baseline_index"]          = normalize_score(baseline_raw)
    df["baseline_confidence_low"]  = (df["baseline_index"] - 5).clip(0, 100)
    df["baseline_confidence_high"] = (df["baseline_index"] + 5).clip(0, 100)
    
    # ── Combined ─────────────────────────────────────────────
    df["severity_quadrant"] = df.apply(
        lambda r: assign_quadrant(r["cohort_index"], r["baseline_index"]),
        axis=1
    )
    df["audit_triggered"] = (
        (df["cohort_index"] >= 70) | (df["baseline_index"] >= 70)
    )
    
    return df
```

### 7.3 Nightly Scoring Job

```python
# scoring/nightly_job.py
import asyncio
from db import get_session
from scoring.dual_scorer import score_trades
from scoring.feature_builder import build_feature_dataframe
from gemini.auditor import run_audit
from scoring.systemic_stats import update_systemic_stats

async def run_nightly_scoring():
    async with get_session() as session:
        # 1. Fetch all unscored trades
        result = await session.execute("""
            SELECT t.* FROM trades t
            LEFT JOIN anomaly_scores a ON t.id = a.trade_id
            WHERE a.trade_id IS NULL
        """)
        trades = result.fetchall()
        if not trades:
            print("[scorer] No new trades to score.")
            return

        # 2. Build feature vectors
        df = await build_feature_dataframe(trades, session)

        # 3. Score against both models
        scored_df = score_trades(df)

        # 4. Write dual scores to DB
        for _, row in scored_df.iterrows():
            await session.execute("""
                INSERT INTO anomaly_scores (
                    trade_id,
                    cohort_raw_score, cohort_label, cohort_index,
                    cohort_confidence_low, cohort_confidence_high,
                    baseline_raw_score, baseline_label, baseline_index,
                    baseline_confidence_low, baseline_confidence_high,
                    severity_quadrant, audit_triggered,
                    feat_cohort_alpha, feat_pre_trade_alpha,
                    feat_proximity_days, feat_bill_proximity,
                    feat_has_proximity_data, feat_committee_relevance,
                    feat_amount_zscore, feat_cluster_score,
                    feat_disclosure_lag
                ) VALUES (
                    :tid,
                    :c_raw, :c_lbl, :c_idx, :c_clo, :c_chi,
                    :b_raw, :b_lbl, :b_idx, :b_clo, :b_chi,
                    :quad, :audit,
                    :alpha, :pre_alpha,
                    :prox, :bill_prox,
                    :has_prox, :comm_rel,
                    :amt_z, :cluster, :lag
                )
            """, {
                "tid":    int(row["id"]),
                "c_raw":  row["cohort_raw_score"],
                "c_lbl":  int(row["cohort_label"]),
                "c_idx":  int(row["cohort_index"]),
                "c_clo":  int(row["cohort_confidence_low"]),
                "c_chi":  int(row["cohort_confidence_high"]),
                "b_raw":  row["baseline_raw_score"],
                "b_lbl":  int(row["baseline_label"]),
                "b_idx":  int(row["baseline_index"]),
                "b_clo":  int(row["baseline_confidence_low"]),
                "b_chi":  int(row["baseline_confidence_high"]),
                "quad":   row["severity_quadrant"],
                "audit":  bool(row["audit_triggered"]),
                "alpha":  row["cohort_alpha"],
                "prox":   int(row["proximity_days"]),
                "has_prox":  int(row["has_proximity_data"]),
                "comm_rel": float(row["committee_relevance"]),
                "lag":      int(row["disclosure_lag"]),
            })
        await session.commit()

        # 5. Trigger Gemini for high-score trades
        audit_df = scored_df[scored_df["audit_triggered"]]
        print(f"[scorer] Scored {len(scored_df)} trades. "
              f"Triggering {len(audit_df)} Gemini audits.")
        for _, row in audit_df.iterrows():
            await run_audit(trade_id=int(row["id"]), session=session)

        # 6. Update platform-level systemic stats
        await update_systemic_stats(session)

if __name__ == "__main__":
    asyncio.run(run_nightly_scoring())
```

---

## 8. FastAPI Backend

### Key Endpoints

```python
# routers/systemic.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from db import get_session

router = APIRouter(prefix="/api/v1", tags=["systemic"])

@router.get("/systemic")
async def get_systemic_stats(session: AsyncSession = Depends(get_session)):
    """
    Returns platform-level systemic insight:
    what % of congressional trades would be flagged
    against the institutional investor baseline?
    Powers the homepage Systemic Dashboard.
    """
    result = await session.execute("""
        SELECT * FROM systemic_stats ORDER BY computed_at DESC LIMIT 1
    """)
    return dict(result.fetchone())

@router.get("/leaderboard")
async def get_leaderboard(
    quadrant: str = None,  # filter by SEVERE, SYSTEMIC, OUTLIER
    limit: int = 20,
    session: AsyncSession = Depends(get_session)
):
    """Top anomalous trades, optionally filtered by severity quadrant."""
    where = f"AND a.severity_quadrant = '{quadrant}'" if quadrant else ""
    result = await session.execute(f"""
        SELECT t.*, p.full_name, p.party, p.state,
               a.cohort_index, a.baseline_index, a.severity_quadrant
        FROM trades t
        JOIN politicians p ON t.politician_id = p.id
        JOIN anomaly_scores a ON t.id = a.trade_id
        WHERE a.audit_triggered = TRUE {where}
        ORDER BY (a.cohort_index + a.baseline_index) DESC
        LIMIT :lim
    """, {"lim": limit})
    return [dict(r) for r in result.fetchall()]
```

---

## 9. Gemini Agentic Auditor

The Gemini auditor is updated to receive **both scores** as context and to explain the dual-model finding. A new tool `get_systemic_context` is added to let Gemini reference the platform-level systemic stats when explaining a SYSTEMIC-quadrant trade.

```python
# gemini/auditor.py  (dual-model version)

SYSTEM_PROMPT = """
You are a non-partisan financial ethics auditor. You have access to TWO anomaly
scores for every trade:

1. COHORT INDEX (0–100): How anomalous this trade is compared to all other
   congressional trades. A high score means this trade is unusual even by
   congressional standards.

2. BASELINE INDEX (0–100): How anomalous this trade is compared to institutional
   fund managers with no legislative access (SEC 13-F filers). A high score here
   means the trade looks unusual to a normal investor with no political information.

The combination determines severity:
- SEVERE (both high): Individual AND systemic concern.
- SYSTEMIC (baseline high, cohort low): The trade looks normal within Congress
  but abnormal in the real world — which may indicate systemic information
  advantages rather than individual wrongdoing.
- OUTLIER (cohort high, baseline low): Unusual within Congress but trades like
  a normal investor. Lower concern.
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
  "narrative": "<2-4 paragraphs>",
  "evidence": [{"type": "...", "description": "...", "source": "..."}],
  "bill_excerpt": "<direct quote or null>",
  "caveats": "<limitations of this analysis>"
}
""".strip()

# The initial message now includes BOTH scores
def build_initial_message(trade) -> str:
    return f"""
Investigate the following congressional trade:

Politician: {trade.full_name} (ID: {trade.politician_id})
Ticker: {trade.ticker} | Sector: {trade.industry_sector or 'unknown'}
Trade: {trade.trade_type.upper()} on {trade.trade_date}
Disclosed: {trade.disclosure_date} ({trade.disclosure_lag_days} days after trade)
Amount Estimate: ${trade.amount_midpoint:,}

─── DUAL MODEL SCORES ──────────────────────────────
Cohort Index  (vs. Congress):          {trade.cohort_index}/100
Baseline Index (vs. fund managers):    {trade.baseline_index}/100
Severity Quadrant:                     {trade.severity_quadrant}

─── FEATURE BREAKDOWN ──────────────────────────────
30-day cohort alpha:         {trade.feat_cohort_alpha:.4f}
Days to nearest vote:        {trade.feat_proximity_days}
Has proximity vote data:     {'YES' if trade.feat_has_proximity_data else 'NO'}
Committee relevance score:   {trade.feat_committee_relevance:.2f}
Disclosure lag:              {trade.feat_disclosure_lag} days

Use your tools to investigate. Focus your explanation on which of the two scores
is more significant and why the severity quadrant is {trade.severity_quadrant}.
""".strip()
```

---

## 10. Next.js Frontend

### Pages

| Route | Description |
|---|---|
| `/` | **Systemic Dashboard**: Platform-level finding — what % of congressional trades deviate from institutional investor norms |
| `/leaderboard` | All flagged trades, filterable by quadrant (SEVERE / SYSTEMIC / OUTLIER) |
| `/politician/[id]` | Profile: committees, donor sectors, trade history with dual scores |
| `/trade/[id]` | Individual trade: dual score breakdown + full Gemini audit report |
| `/about` | Methodology, dual-model explanation, disclaimers |

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

const QUADRANT_DESCRIPTIONS = {
  SEVERE:       "Unusual within Congress AND vs. normal investors",
  SYSTEMIC:     "Normal within Congress, but abnormal vs. normal investors",
  OUTLIER:      "Unusual within Congress, but normal vs. investors",
  UNREMARKABLE: "Normal on both measures",
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
      <div className="text-center text-xs text-gray-500 mt-1">
        {QUADRANT_DESCRIPTIONS[quadrant]}
      </div>
    </div>
  );
}
```

### Systemic Dashboard Component

```typescript
// components/SystemicInsight.tsx
interface SystemicStats {
  totalTradesScored: number;
  pctFlaggedByBaseline: number;
  systemicCount: number;
  severeCount: number;
  topSystemicSector: string;
}

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
      <p className="text-orange-600 text-sm mt-3">
        Most active sector: <strong>{stats.topSystemicSector}</strong> ·{" "}
        {stats.systemicCount.toLocaleString()} systemic trades ·{" "}
        {stats.severeCount.toLocaleString()} severe trades
      </p>
    </div>
  );
}
```

---

## 11. Deployment & Scheduling

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
      - ./house_advantage_schema.sql:/docker-entrypoint-initdb.d/schema.sql

  backend:
    build: ./backend
    environment:
      DATABASE_URL: mysql+aiomysql://root:${MYSQL_ROOT_PASSWORD}@mysql:3306/house_advantage
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      CONGRESS_GOV_API_KEY: ${CONGRESS_GOV_API_KEY}
      FEC_API_KEY: ${FEC_API_KEY}
      GOVINFO_API_KEY: ${GOVINFO_API_KEY}
      OPENFIGI_API_KEY: ${OPENFIGI_API_KEY}
    ports: ["8000:8000"]
    command: uvicorn main:app --host 0.0.0.0 --port 8000

  scheduler:
    build: ./backend
    environment:
      DATABASE_URL: mysql+aiomysql://root:${MYSQL_ROOT_PASSWORD}@mysql:3306/house_advantage
      GEMINI_API_KEY: ${GEMINI_API_KEY}
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
```

---

## 12. Legal & Ethical Safeguards

- **Naming:** Output is called **"Trade Anomaly Index"** — never "corruption score"
- **Quadrant framing:** SYSTEMIC trades are explicitly framed as a possible *systemic* pattern, not individual wrongdoing
- **Mandatory disclaimer** on every trade card and report:

> *"The Trade Anomaly Index is generated by automated statistical models. A high score means a trade is a statistical outlier relative to its comparison population — it does NOT constitute evidence of illegal activity or wrongdoing. The Cohort Index compares against all congressional trades; the Baseline Index compares against institutional fund managers. All data sourced from public STOCK Act disclosures and SEC filings."*

- All source URLs link back to the original government filing

---

## 13. MVP Scope vs. V2 Roadmap

### ✅ MVP
- [ ] Dual-model scoring pipeline (cohort + baseline)
- [ ] SEC 13-F ingestion and baseline trade derivation
- [ ] OpenFIGI CUSIP→ticker resolution
- [ ] Nightly dual-score job
- [ ] `systemic_stats` computed nightly
- [ ] Gemini dual-score audit reports
- [ ] FastAPI `/systemic`, `/leaderboard`, `/politician`, `/audit` endpoints
- [ ] Next.js: Systemic Dashboard, Leaderboard (filterable by quadrant), Politician Profile, Trade Detail
- [ ] Dual Score Badge UI component
- [ ] All disclaimers

### ✅ V2 (Completed — July 2025)
- [x] Feature expansion: 5 → 9 features (pre_trade_alpha, bill_proximity, amount_zscore, cluster_score)
- [x] `disclosure_lag` changed from raw days to `log1p(days)` — eliminated 61% detection dominance
- [x] Model 2 upgraded: 1 → 2 active features (added pre_trade_alpha)
- [x] V1 models preserved as `cohort_model.pkl` / `baseline_model.pkl`
- [x] V2 models: `cohort_model_v2.pkl` / `baseline_model_v2.pkl`
- [x] Full scoring: 9,720 trades scored. SEVERE 14 | SYSTEMIC 379 | OUTLIER 78 | UNREMARKABLE 9,249
- [x] V1→V2 comparison validated: 889 trades (9.1%) changed quadrant, disclosure_lag dominance eliminated

### 🗓 V3 Roadmap
- Longitudinal tracking (how a politician's scores change over time)
- Per-sector systemic breakdown
- Alert subscriptions
- Bill ghostwriter detection
- Network graph (donor → politician → vote → trade)
- Quarterly model retraining pipeline with MLflow

---

## 14. Environment Variables & API Keys

```bash
# .env
MYSQL_ROOT_PASSWORD=your_password
GEMINI_API_KEY=           # aistudio.google.com/app/apikey        (free tier)
CONGRESS_GOV_API_KEY=     # api.congress.gov                      (free)
FEC_API_KEY=              # api.open.fec.gov/developers           (free)
GOVINFO_API_KEY=          # api.govinfo.gov/developers            (free)
OPENFIGI_API_KEY=         # openfigi.com/api                      (free)
# yfinance: no key needed
# SEC 13-F bulk CSVs: no key needed
# House Clerk disclosures: no key needed
# Senate eFD filings: no key needed
```

---

*House Advantage MVP Blueprint v3.1 · July 2025 · UCI*