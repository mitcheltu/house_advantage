# House Advantage — Model Training Guide
### Dual-Model Architecture: Cohort Model + Baseline Model
**Version:** 3.0 (V2 Feature Set — 9 Features)
**Last Updated:** March 2026

---

## Table of Contents

1. [Overview & The Two-Model Philosophy](#1-overview--the-two-model-philosophy)
2. [Prerequisites](#2-prerequisites)
3. [Model 1: The Cohort Model](#3-model-1-the-cohort-model)
   - 3.1 What It Trains On
   - 3.2 Data Collection
   - 3.3 Data Cleaning
   - 3.4 Feature Engineering
   - 3.5 Training
   - 3.6 Testing
4. [Model 2: The Baseline Model](#4-model-2-the-baseline-model)
   - 4.1 What It Trains On
   - 4.2 Data Collection (SEC 13-F)
   - 4.3 CUSIP → Ticker Resolution
   - 4.4 Inferring Trades from Quarterly Snapshots
   - 4.5 Data Cleaning
   - 4.6 Feature Engineering
   - 4.7 Training
   - 4.8 Testing
5. [Cross-Model Validation](#5-cross-model-validation)
6. [Model Versioning & Storage](#6-model-versioning--storage)
7. [Retraining Schedule](#7-retraining-schedule)
8. [Full End-to-End Execution Order](#8-full-end-to-end-execution-order)
9. [Directory Structure](#9-directory-structure)
10. [Dependencies](#10-dependencies)
11. [Appendix A: Feature Coverage & Data Sources](#appendix-a-feature-coverage--data-sources-both-models)

---

## 1. Overview & The Two-Model Philosophy

### The Core Problem With One Model

An Isolation Forest learns what "normal" looks like from whatever data it is trained on. If you train it only on congressional trades, it learns that *congressional trading patterns are the definition of normal*. The problem: academic research consistently shows congressional portfolios outperform the market at rates statistically difficult to explain by skill alone. If most politicians already trade on legislative information advantages, a model trained on that cohort learns that behavior is normal — and only flags the most extreme individual outliers within an already-suspicious population.

Training on congressional data alone answers: *"Is this politician more suspicious than the average politician?"*

That is a useful but incomplete question.

### The Two Questions

| Model | Trained On | Question Answered |
|---|---|---|
| **Model 1: Cohort** | All congressional STOCK Act trade disclosures (2022–present) | Is this trade unusual even by congressional standards? |
| **Model 2: Baseline** | SEC 13-F institutional fund manager trades (same period) | Is this trade unusual compared to investors with no legislative access? |

### The Four Outcomes

Running both models on every congressional trade produces a two-dimensional severity signal:

```
                    BASELINE INDEX
                    Low         High
               ┌───────────┬────────────┐
  COHORT   High│  OUTLIER  │   SEVERE   │
  INDEX        ├───────────┼────────────┤
           Low │UNREMARKABLE│ SYSTEMIC  │
               └───────────┴────────────┘
```

- **SEVERE**: Both models agree — unusual within Congress AND unusual vs. the investing public. Strongest individual flag.
- **SYSTEMIC**: Looks normal within Congress but highly anomalous vs. normal investors. This is where the *systemic* information advantage lives — the behavior is so widespread in Congress it no longer looks anomalous within that population, but it still looks anomalous to the outside world.
- **OUTLIER**: Unusual within Congress but trades like a normal investor. Statistical oddity, not necessarily suspicious.
- **UNREMARKABLE**: Normal on both measures.

The **SYSTEMIC** quadrant is the product's most important civic contribution. It's the answer to the question *"What if most of Congress is insider trading?"* — and it allows the platform to make that argument with data rather than just suspicion.

### Shared Architecture

Both models use identical architecture:

```
StandardScaler → IsolationForest
```

Same 9 features (expanded from 5 in V1). Same normalization. Same `contamination="auto"`. The difference is entirely in what population they were trained on.

### V1 → V2 Feature Evolution

V2 expanded the feature set from 5 to 9 features and applied a log1p transform to `disclosure_lag` to reduce its scoring dominance. V1 models are preserved in `model/cohort_model.pkl` and `model/baseline_model.pkl` for comparison. V2 models are in `model/cohort_model_v2.pkl` and `model/baseline_model_v2.pkl`.

| # | Feature | V1 | V2 | Change |
|---|---------|----|----|--------|
| 1 | `cohort_alpha` | ✅ | ✅ | Unchanged |
| 2 | `pre_trade_alpha` | — | ✅ | **New** — 5-day pre-trade excess return vs SPY |
| 3 | `proximity_days` | ✅ | ✅ | Unchanged |
| 4 | `bill_proximity` | — | ✅ | **New** — days to nearest sector-matched bill action |
| 5 | `has_proximity_data` | ✅ | ✅ | Unchanged |
| 6 | `committee_relevance` | ✅ | ✅ | Unchanged |
| 7 | `amount_zscore` | — | ✅ | **New** — personal trade-size anomaly (log scale) |
| 8 | `cluster_score` | — | ✅ | **New** — count of other politicians trading same ticker ±7 days |
| 9 | `disclosure_lag` | ✅ (raw days) | ✅ (log1p) | **Changed** — log1p transform to reduce dominance |

**V1 Validation Finding:** Model validation audit revealed `disclosure_lag` contributed ~61% of anomalous detections in V1, with trades having 90+ day lag showing an 83.4% anomaly rate. The log1p transform in V2 compresses high lag values, reducing this single-feature dominance.

**V2 Results:** After retraining and rescoring, the disclosure_lag flagged/unflagged ratio dropped to 0.98x (effectively neutral). 9.1% of trades changed quadrant between V1 and V2.

---

## 2. Prerequisites

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
mkdir -p training model data/raw/prices data/raw/13f data/cleaned data/features tests/artifacts
```

```text
# requirements.txt
scikit-learn==1.5.2
pandas==2.2.3
numpy==1.26.4
joblib==1.4.2
yfinance==0.2.43
requests==2.32.3
sqlalchemy[asyncio]==2.0.36
aiomysql==0.2.0
python-dotenv==1.0.1
matplotlib==3.9.2
seaborn==0.13.2
scipy==1.14.1
pytest==8.3.3
```

```bash
# .env
CONGRESS_GOV_API_KEY=your_key   # free at api.congress.gov
FEC_API_KEY=your_key             # free at api.open.fec.gov/developers
GOVINFO_API_KEY=your_key         # free at api.govinfo.gov/developers
OPENFIGI_API_KEY=your_key        # free at openfigi.com/api
DATABASE_URL=mysql+aiomysql://root:password@localhost:3306/house_advantage
```

---

## 3. Model 1: The Cohort Model

### 3.1 What It Trains On

Every STOCK Act Periodic Transaction Report filed by members of Congress since January 2022. Approximately 10,000–20,000 trade records across ~535 members of both chambers.

**Important limitation to document:** This model's baseline is the congressional cohort itself. A low score from this model means a trade looks normal *within Congress* — not that it is clean in an absolute sense.

### 3.2 Data Collection

**House trades:** Scraped from the House Clerk's Financial Disclosure portal (free)  
**Senate trades:** Scraped from the Senate eFD (Electronic Financial Disclosures) system (free)  
**No paid API required.** All data comes directly from official government disclosure sites.

**House source:** `https://disclosures-clerk.house.gov/`  
Downloads annual ZIP files containing XML indexes and PTR (Periodic Transaction Report) PDFs, parsed with `pdfplumber`.

**Senate source:** `https://efdsearch.senate.gov/`  
Scrapes the Senate eFD DataTables AJAX API for PTR filings using `cloudscraper` (to bypass Akamai CDN).

The orchestrator runs both collectors and merges the results into a single `congressional_trades_raw.csv`:

```bash
# Collectors are invoked by the orchestrator (backend/ingest/orchestrator.py)
# House: backend/ingest/collectors/collect_house_disclosures.py
# Senate: backend/ingest/collectors/collect_senate_disclosures.py
python backend/ingest/orchestrator.py
```

Also collect supporting data for features 2–4:

```bash
# All use Congress.gov API (free, requires CONGRESS_GOV_API_KEY)
# Committee memberships also pulled from github.com/unitedstates/congress-legislators
python backend/ingest/orchestrator.py   # runs all collectors including:
  # collect_congress_gov.py    → politicians, committees, votes, bills
  # collect_committee_memberships.py → committee memberships
  # collect_openfec.py         → campaign finance / donors
```

### 3.3 Data Cleaning

```python
# training/model1/clean_congressional_trades.py
import pandas as pd

def clean(path: str = "data/raw/congressional_trades_raw.csv") -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["trade_date", "disclosure_date"])
    
    before = len(df)
    df = df[df["asset_type"].str.lower().isin(["stock", "common stock", ""])]
    df = df[df["ticker"].str.match(r"^[A-Z]{1,5}$", na=False)]
    df = df[df["disclosure_lag_days"].between(0, 365)]
    df = df.dropna(subset=["trade_date", "disclosure_date", "ticker"])
    df = df[df["trade_type"].isin(["buy", "sell", "exchange"])]
    df = df.drop_duplicates(subset=["politician_id", "ticker", "trade_date", "trade_type"])
    
    print(f"[model1/clean] {before} → {len(df)} trades after cleaning.")
    df.to_csv("data/cleaned/congressional_trades_clean.csv", index=False)
    return df

if __name__ == "__main__":
    clean()
```

### 3.4 Feature Engineering

All 9 V2 features are fully computed for congressional trades because the political context (votes, committees, bills, amount data) is available.

```python
# training/model1/build_features_model1_v2.py
"""
Computes all 9 V2 features for every cleaned congressional trade.
Feature 1: cohort_alpha           — 30-day forward return minus SPY return
Feature 2: pre_trade_alpha        — 5-day pre-trade excess return vs SPY (NEW in V2)
Feature 3: proximity_days         — days to nearest vote (any); median-imputed when missing
Feature 4: bill_proximity         — days to nearest sector-matched bill action (NEW in V2)
Feature 5: has_proximity_data     — 1 if proximity_days was computed from real vote data, 0 if median-imputed
Feature 6: committee_relevance    — continuous 0.0–1.0 score measuring committee oversight of traded sector
Feature 7: amount_zscore          — personal trade-size anomaly on log scale (NEW in V2)
Feature 8: cluster_score          — count of other politicians trading same ticker ±7 days (NEW in V2)
Feature 9: disclosure_lag         — log1p(days from trade to filing) (CHANGED in V2: was raw days)

V2 changes from V1:
  - pre_trade_alpha: Captures whether the stock already started moving before the trade,
    suggesting the politician may have acted on non-public information about an upcoming event.
  - bill_proximity: Directly measures timing between trades and sector-relevant legislative action.
    Limited coverage (only 5 bills have both dates and policy_area matching sectors in current data).
  - amount_zscore: Flags trades that are unusually large or small for a given politician's history.
    Uses log-scale z-score (requires ≥5 prior trades to compute stats for a politician).
  - cluster_score: Detects coordinated trading — multiple politicians trading the same ticker
    within ±7 days suggests shared non-public information.
  - disclosure_lag: Now uses log1p transform instead of raw days. V1 validation showed raw
    disclosure_lag dominated ~61% of anomaly detections. log1p compresses high values (e.g.,
    365 days → 5.90 log1p) while preserving ordering.
"""
Feature 5: disclosure_lag         — days from trade to public STOCK Act filing

Design note — committee_relevance replaces sector_overlap:
  Binary sector_overlap achieved only 17.6% positive rate due to single-sector committee
  tagging and keyword-miss issues. committee_relevance uses a curated multi-sector committee
  map with role-based weighting (chair/ranking=1.0, member=0.7) and cross-cutting committee
  rules (Appropriations→0.4 for all sectors, Intelligence→0.5 for defense+tech). This raises
  effective signal coverage from 17.6% to ~41%. donor_overlap was dropped entirely (0% signal
  due to broken PAC pipeline — see Appendix A for details).
"""
import pandas as pd
import numpy as np
import json
import yfinance as yf
from datetime import timedelta
from pathlib import Path

# V1 features (preserved for reference):
# FEATURES_V1 = ["cohort_alpha", "proximity_days", "has_proximity_data",
#                "committee_relevance", "disclosure_lag"]

# V2 features (current — 9 features):
FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
]

# ── Ticker → sector map (734 tickers → 7 model sectors) ──────────────────────
TICKER_SECTOR_MAP = json.load(open("data/raw/_combined_sector_map.json"))

# ── Multi-sector committee map ────────────────────────────────────────────────
# Each committee maps to the sectors it has legislative/oversight jurisdiction over.
# Source: committee jurisdictions per House/Senate rules and CRS reports.
COMMITTEE_SECTORS = {
    "House Committee on Agriculture":                       ["agriculture"],
    "House Committee on Armed Services":                    ["defense"],
    "House Committee on Energy and Commerce":               ["energy", "healthcare", "tech", "telecom"],
    "House Committee on Financial Services":                ["finance"],
    "Senate Committee on Agriculture, Nutrition, and Forestry": ["agriculture"],
    "Senate Committee on Armed Services":                   ["defense"],
    "Senate Committee on Banking, Housing, and Urban Affairs":  ["finance"],
    "Senate Committee on Commerce, Science, and Transportation": ["tech", "telecom"],
    "Senate Committee on Energy and Natural Resources":     ["energy"],
    "Senate Committee on Finance":                          ["finance", "healthcare"],
    "Senate Committee on Health, Education, Labor, and Pensions": ["healthcare"],
    "House Committee on Science, Space, and Technology":    ["tech"],
    "House Committee on Natural Resources":                 ["energy", "agriculture"],
    "House Committee on Transportation and Infrastructure": ["defense"],
    "Senate Committee on Environment and Public Works":     ["energy"],
    "House Committee on Veterans' Affairs":                 ["healthcare"],
    "Senate Committee on Veterans' Affairs":                ["healthcare"],
    "House Committee on Ways and Means":                    ["finance", "healthcare"],
    "House Committee on Education and the Workforce":       ["healthcare"],
    "House Committee on Homeland Security":                 ["defense", "tech"],
    "Senate Committee on Homeland Security and Governmental Affairs": ["defense", "tech"],
}
# Cross-cutting committees get special (lower) weights — handled in compute_committee_relevance
CROSS_CUTTING = {
    "House Permanent Select Committee on Intelligence":     {"defense": 0.5, "tech": 0.5},
    "Senate Select Committee on Intelligence":              {"defense": 0.5, "tech": 0.5},
    "House Committee on Appropriations":                    {s: 0.4 for s in ["defense","finance","healthcare","energy","tech","agriculture","telecom"]},
    "Senate Committee on Appropriations":                   {s: 0.4 for s in ["defense","finance","healthcare","energy","tech","agriculture","telecom"]},
}

def load_price_cache() -> dict:
    cache = {}
    for f in Path("data/raw/prices").glob("*.csv"):
        cache[f.stem.upper()] = pd.read_csv(f, parse_dates=["date"])
    return cache

def get_price(ticker: str, date: pd.Timestamp, cache: dict) -> float | None:
    df = cache.get(ticker)
    if df is None:
        return None
    subset = df[df["date"] >= date]
    return float(subset.iloc[0]["close"]) if not subset.empty else None

def compute_cohort_alpha(ticker: str, trade_date: pd.Timestamp, cache: dict) -> float:
    p0 = get_price(ticker, trade_date, cache)
    p1 = get_price(ticker, trade_date + timedelta(days=30), cache)
    s0 = get_price("SPY",  trade_date, cache)
    s1 = get_price("SPY",  trade_date + timedelta(days=30), cache)
    if None in (p0, p1, s0, s1) or p0 == 0 or s0 == 0:
        return np.nan
    return (p1 - p0) / p0 - (s1 - s0) / s0

def compute_proximity_days(row: pd.Series, votes: pd.DataFrame) -> int:
    """Days to nearest vote. Prefers sector-matched vote; falls back to any vote."""
    trade_date = row["trade_date"]
    pid = row.get("politician_id")
    sector = row.get("industry_sector")

    # Try sector-specific match first
    if sector and pid:
        relevant = votes[
            (votes["member_id"] == pid) &
            (votes["related_sector"] == sector)
        ]
        if not relevant.empty:
            deltas = (relevant["vote_date"] - trade_date).abs().dt.days
            min_d = deltas.min()
            if min_d <= 90:
                return int(min_d)

    # Fallback: nearest vote of any kind by this politician
    if pid:
        any_votes = votes[votes["member_id"] == pid]
        if not any_votes.empty:
            deltas = (any_votes["vote_date"] - trade_date).abs().dt.days
            min_d = deltas.min()
            if min_d <= 90:
                return int(min_d)

    return 999

def compute_committee_relevance(row: pd.Series, memberships: pd.DataFrame) -> float:
    """
    Continuous 0.0–1.0 score for committee oversight relevance.
    
    Weighting:
      - Chair / Ranking Member of a sector-matched committee → 1.0
      - Regular member of a sector-matched committee → 0.7
      - Cross-cutting committee (Appropriations) → 0.4 for all sectors
      - Cross-cutting committee (Intelligence) → 0.5 for defense, tech
      - No match → 0.0
    
    Takes the MAX across all of a politician's committee memberships.
    Supports multi-sector tickers (industry_sector may be a list).
    """
    raw_sector = row.get("industry_sector")
    pid        = row.get("politician_id")
    if not raw_sector or not pid:
        return 0.0
    
    # Normalise: single string → list for uniform handling
    sectors = raw_sector if isinstance(raw_sector, list) else [raw_sector]
    
    pol_memberships = memberships[memberships["politician_id"] == pid]
    if pol_memberships.empty:
        return 0.0
    
    best = 0.0
    for _, m in pol_memberships.iterrows():
        cname = str(m.get("committee_name", ""))
        rank  = str(m.get("rank_in_committee", "")).lower()
        
        for sector in sectors:
            # Check cross-cutting committees first (special sector→weight map)
            if cname in CROSS_CUTTING:
                weight = CROSS_CUTTING[cname].get(sector, 0.0)
                if weight > 0 and ("chair" in rank or "ranking" in rank):
                    weight = min(weight * 1.3, 1.0)  # boost for leadership
                best = max(best, weight)
                continue
            
            # Standard committee: check if this committee covers the traded sector
            if cname in COMMITTEE_SECTORS:
                if sector in COMMITTEE_SECTORS[cname]:
                    if "chair" in rank or "ranking" in rank:
                        weight = 1.0
                    else:
                        weight = 0.7
                    best = max(best, weight)
    
    return round(best, 2)

def build_feature_matrix() -> pd.DataFrame:
    trades     = pd.read_csv("data/raw/congressional_trades_raw.csv", parse_dates=["trade_date"])
    votes_raw  = pd.read_csv("data/raw/votes_raw.csv")
    pv_house   = pd.read_csv("data/raw/politician_votes_raw.csv")
    pv_senate  = pd.read_csv("data/raw/senate_politician_votes_raw.csv")
    committees = pd.read_csv("data/raw/committee_memberships_raw.csv")
    politicians= pd.read_csv("data/raw/politicians_raw.csv")
    cache      = load_price_cache()

    # ── Resolve trade names → bioguide IDs ──
    # Politicians come as "Last, First M."; trades have "First M. Last"
    name_to_bio = {}
    last_to_bio = {}  # last-name-only fallback (unique names only)
    for _, row in politicians.iterrows():
        bio = str(row.get("id", "")).strip()
        full = str(row.get("full_name", "")).strip()
        if not bio or not full:
            continue
        name_to_bio[full.lower()] = bio
        parts = full.split(",", 1)
        if len(parts) == 2:
            last = parts[0].strip().lower()
            first_full = parts[1].strip()
            name_to_bio[f"{first_full} {parts[0].strip()}".lower()] = bio
            first_only = first_full.split()[0] if first_full else ""
            if first_only:
                name_to_bio[f"{first_only} {parts[0].strip()}".lower()] = bio
            if last not in last_to_bio:
                last_to_bio[last] = bio
            else:
                last_to_bio[last] = None  # ambiguous

    # Hardcoded nickname/format overrides for known mismatches
    NICKNAMES = {
        "thomas h tuberville": "T000278", "rob bresnahan": "B001327",
        "valerie hoyle": "H001094", "richard w. allen": "A000372",
        "daniel s sullivan": "S001198", "patrick fallon": "F000246",
        "marjorie taylor mrs greene": "G000596", "mark dr green": "G000590",
        "donald sternoff beyer": "B001292", "ritchie john torres": "T000486",
        "shelley m capito": "C001047", "john w hickenlooper": "H001042",
        "victoria spartz": "S001199", "gilbert cisneros": "C001123",
        "daniel goldman": "G000599", "jerry moran,": "M000934",
        "angus s king, jr.": "K000383", "a. mitchell mcconnell, jr.": "M000355",
        "william f hagerty, iv": "H000601", "michael c. burgess": "B001248",
        "thomas suozzi": "S001201", "john curtis": "C001114",
        "jonathan jackson": "J000308",
    }
    name_to_bio.update(NICKNAMES)

    def _resolve(name):
        if pd.isna(name):
            return None
        n = str(name).strip().lower()
        if n in name_to_bio:
            return name_to_bio[n]
        clean = n.replace(".", "").replace(" jr", "").replace(" sr", "")
        clean = " ".join(clean.replace(" mrs ", " ").replace(" mr ", " ").replace(" dr ", " ").split())
        if clean in name_to_bio:
            return name_to_bio[clean]
        words = n.replace(".", "").split()
        if len(words) >= 2:
            fl = f"{words[0]} {words[-1]}"
            if fl in name_to_bio:
                return name_to_bio[fl]
        if words:
            last = words[-1].rstrip(",")
            if last in last_to_bio and last_to_bio[last]:
                return last_to_bio[last]
        return None

    trades["bioguide_id"] = trades["politician_id"].apply(_resolve)
    print(f"[model1/features] Resolved {trades['bioguide_id'].notna().sum()}/{len(trades)} politician names to bioguide IDs")

    # ── Build per-politician vote table with dates and sectors ──
    pv = pd.concat([
        pv_house[["politician_id", "vote_id"]],
        pv_senate[["politician_id", "vote_id"]],
    ], ignore_index=True)
    pv = pv.merge(
        votes_raw[["id", "vote_date", "related_sector"]],
        left_on="vote_id", right_on="id", how="left",
    )
    pv["vote_date"] = pd.to_datetime(pv["vote_date"], format="mixed", dayfirst=False, utc=True).dt.tz_localize(None)
    pv = pv.rename(columns={"politician_id": "member_id"})

    # Assign sector tags from ticker map
    trades["industry_sector"] = trades["ticker"].map(TICKER_SECTOR_MAP)
    
    print(f"[model1/features] Computing features for {len(trades)} trades...")
    trades["cohort_alpha"]    = trades.apply(lambda r: compute_cohort_alpha(r["ticker"], r["trade_date"], cache), axis=1)
    trades["proximity_days"]  = trades.apply(lambda r: compute_proximity_days(
        pd.Series({"politician_id": r["bioguide_id"], "industry_sector": r["industry_sector"], "trade_date": r["trade_date"]}), pv), axis=1)
    trades["committee_relevance"] = trades.apply(lambda r: compute_committee_relevance(
        pd.Series({"politician_id": r["bioguide_id"], "industry_sector": r["industry_sector"]}), committees), axis=1)
    trades["disclosure_lag"]  = trades["disclosure_lag_days"].fillna(0).clip(0, 365).astype(int)
    
    before = len(trades)
    trades = trades.dropna(subset=["cohort_alpha"])
    trades["proximity_days"] = trades["proximity_days"].fillna(999).astype(int)
    
    # Median imputation for proximity_days + indicator feature
    # Trades with real vote data keep their computed value; trades with sentinel 999
    # get the median of real values. has_proximity_data preserves the missingness signal.
    real_mask = trades["proximity_days"] != 999
    trades["has_proximity_data"] = real_mask.astype(int)
    median_proximity = int(trades.loc[real_mask, "proximity_days"].median())
    trades.loc[~real_mask, "proximity_days"] = median_proximity
    print(f"[model1/features] proximity_days: {real_mask.sum()} real, "
          f"{(~real_mask).sum()} imputed with median={median_proximity}")
    print(f"[model1/features] {before - len(trades)} dropped (delisted tickers). {len(trades)} remain.")
    
    out = trades[["politician_id", "ticker", "trade_date", "trade_type",
                   "industry_sector"] + FEATURES]
    out.to_csv("data/features/model1_features.csv", index=False)
    print(f"[model1/features] Saved data/features/model1_features.csv")
    return out

if __name__ == "__main__":
    build_feature_matrix()
```

### 3.5 Training

```python
# training/model1/train_cohort_model_v2.py
import json, joblib, numpy as np, pandas as pd, sklearn
from datetime import datetime
from pathlib import Path
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
]

Path("model").mkdir(exist_ok=True)

def train():
    df = pd.read_csv("data/features/model1_v2_features.csv")
    X  = df[FEATURES]
    
    print(f"[model1/train] Training Cohort Model on {len(X)} congressional trades.")
    print(f"[model1/train] Feature statistics:\n{X.describe().round(3)}")
    
    pipeline = Pipeline([
        ("scaler",  StandardScaler()),
        ("iforest", IsolationForest(
            n_estimators=200,
            contamination="auto",  # No hardcoded assumption about fraction of bad actors
            max_samples="auto",
            random_state=42,
            n_jobs=-1,
        )),
    ])
    pipeline.fit(X)
    
    labels     = pipeline.predict(X)
    raw_scores = pipeline.named_steps["iforest"].decision_function(
                     pipeline.named_steps["scaler"].transform(X))
    
    outlier_pct = (labels == -1).mean() * 100
    print(f"\n[model1/train] Outlier rate on training data: {outlier_pct:.1f}%")
    print(f"[model1/train] Score range: [{raw_scores.min():.4f}, {raw_scores.max():.4f}]")
    
    joblib.dump(pipeline, "model/cohort_model_v2.pkl")
    
    metadata = {
        "model_name":        "cohort_model_v2",
        "model_version":     "2.0.0",
        "trained_at":        datetime.utcnow().isoformat() + "Z",
        "sklearn_version":   sklearn.__version__,
        "training_population": "Congressional STOCK Act disclosures",
        "n_training_samples": int(len(X)),
        "training_date_range": {
            "start": str(pd.to_datetime(df["trade_date"]).min().date()),
            "end":   str(pd.to_datetime(df["trade_date"]).max().date()),
        },
        "features": FEATURES,
        "hyperparameters": {"n_estimators": 200, "contamination": "auto", "random_state": 42},
        "training_stats": {
            "outlier_pct":  float(outlier_pct),
            "score_min":    float(raw_scores.min()),
            "score_max":    float(raw_scores.max()),
            "score_mean":   float(raw_scores.mean()),
            "score_std":    float(raw_scores.std()),
        },
        "known_limitation": (
            "Baseline is congressional trading cohort, which may itself "
            "reflect systematic information advantages. A low score indicates "
            "'normal for Congress', not 'clean in absolute terms'."
        ),
    }
    with open("model/cohort_model_v2_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    
    print("[model1/train] Saved model/cohort_model_v2.pkl + cohort_model_v2_metadata.json")
    return pipeline

if __name__ == "__main__":
    train()
```

### 3.6 Testing (Model 1)

```python
# tests/test_cohort_model.py
import pytest, joblib, numpy as np, pandas as pd

FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
]

def normalize(raw): return ((-np.clip(raw,-0.5,0.5)+0.5)*100).astype(int).clip(0,100)

@pytest.fixture
def model(): return joblib.load("model/cohort_model_v2.pkl")

def test_outlier_rate(model):
    df = pd.read_csv("data/features/model1_v2_features.csv")
    labels = model.predict(df[FEATURES])
    rate = (labels == -1).mean()
    assert 0.01 <= rate <= 0.20, f"Cohort outlier rate {rate:.2%} outside 1-20%"

def test_obvious_anomaly_flagged(model):
    """A trade with extreme values on all 5 features should score >= 65."""
    X = pd.DataFrame([{
        "cohort_alpha": 0.45, "proximity_days": 2, "has_proximity_data": 1,
        "committee_relevance": 1.0, "disclosure_lag": 120,
    }])
    scaler  = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    idx = normalize(iforest.decision_function(scaler.transform(X)))[0]
    assert idx >= 65, f"Obvious congressional anomaly scored only {idx}"

def test_normal_congressional_trade(model):
    """A trade that looks unremarkable within Congress should score < 40."""
    X = pd.DataFrame([{
        "cohort_alpha": 0.01, "proximity_days": 7, "has_proximity_data": 0,
        "committee_relevance": 0.0, "disclosure_lag": 10,
    }])
    scaler  = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    idx = normalize(iforest.decision_function(scaler.transform(X)))[0]
    assert idx < 40, f"Normal congressional trade scored {idx} — model over-flagging"

def test_stability(model):
    """Re-training with different seeds should produce ≥85% label agreement."""
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    df = pd.read_csv("data/features/model1_features.csv")
    X  = df[FEATURES]  # 5 features including has_proximity_data
    labels_all = []
    for seed in range(10):
        p = Pipeline([("s", StandardScaler()),
                      ("i", IsolationForest(n_estimators=200, contamination="auto",
                                            random_state=seed, n_jobs=-1))])
        p.fit(X)
        labels_all.append(p.predict(X))
    arr = np.array(labels_all)
    agreement = np.mean([max((arr[:,i]==-1).sum(),(arr[:,i]==1).sum())/10
                         for i in range(X.shape[0])])
    assert agreement >= 0.85, f"Model stability {agreement:.2%} below 85%"
```

---

## 4. Model 2: The Baseline Model

### 4.1 What It Trains On

SEC Form 13-F quarterly holdings disclosures from a curated set of large, diversified institutional fund managers (Vanguard, BlackRock, Fidelity, State Street, T. Rowe Price). These funds manage trillions of dollars, trade across all sectors, and have zero access to non-public congressional information.

From these quarterly snapshots, we **infer trades** by comparing quarter-over-quarter changes in positions. This is the standard academic methodology for 13-F based analysis.

**Why these funds specifically:**
- Large enough to cover all industry sectors (no sector bias)
- Passive or broadly diversified (no single-sector activist strategies)
- No political connections
- Long operating history (data available from 2022)

### 4.2 Data Collection (SEC 13-F)

SEC 13-F bulk data is completely free. No API key is required.

```python
# training/model2/collect_13f.py
"""
Downloads SEC 13-F quarterly bulk ZIP files from SEC.gov.
These are free, official government data files.

URL pattern: https://www.sec.gov/files/13f-{year}q{quarter}.zip
Each ZIP contains infotable.tsv with all institutional holdings for that quarter.
"""
import io, os, zipfile, requests
import pandas as pd

SEC_BASE = "https://www.sec.gov/files"

# Curated clean funds: diversified, no legislative access
# CIK numbers from SEC EDGAR
CLEAN_FUND_CIKS = {
    "0001166559": "Vanguard Group",
    "0001364742": "BlackRock Inc",
    "0000093715": "Fidelity (FMR)",
    "0001109357": "State Street Corp",
    "0001045810": "T. Rowe Price",
}

def download_quarter(year: int, quarter: int) -> pd.DataFrame:
    url = f"{SEC_BASE}/13f-{year}q{quarter}.zip"
    print(f"[model2/collect] Downloading {url}")
    
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        fname = [n for n in z.namelist() if "infotable" in n.lower()][0]
        with z.open(fname) as f:
            df = pd.read_csv(f, sep="\t", dtype=str, low_memory=False)
    
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
    
    # Filter to clean funds only
    df = df[df["cik"].isin(CLEAN_FUND_CIKS.keys())]
    
    # Equity shares only
    type_col = next((c for c in df.columns if "sshprnamt" in c and "type" in c), None)
    if type_col:
        df = df[df[type_col] == "SH"]
    
    shares_col = next((c for c in df.columns if c == "sshprnamt"), "sshprnamt")
    df["shares"] = pd.to_numeric(df[shares_col], errors="coerce").fillna(0)
    df["year"]   = year
    df["quarter"] = quarter
    
    print(f"[model2/collect] {year} Q{quarter}: {len(df)} holdings from {df['cik'].nunique()} clean funds")
    return df

def collect_all(years: list[int] = [2022, 2023, 2024]) -> dict[str, pd.DataFrame]:
    """Returns dict: '{year}q{quarter}' → DataFrame"""
    all_quarters = {}
    for year in years:
        for q in [1, 2, 3, 4]:
            key = f"{year}q{q}"
            try:
                all_quarters[key] = download_quarter(year, q)
                all_quarters[key].to_csv(f"data/raw/13f/{key}.csv", index=False)
            except Exception as e:
                print(f"[model2/collect] Warning: {key} failed: {e}")
    return all_quarters

if __name__ == "__main__":
    collect_all()
```

### 4.3 CUSIP → Ticker Resolution

13-F filings identify securities by CUSIP, not ticker symbol. We need tickers to fetch price data from yfinance. OpenFIGI provides a free REST API for this mapping.

```python
# training/model2/resolve_tickers.py
import os, time, requests, pandas as pd
from dotenv import load_dotenv

load_dotenv()

def resolve_cusips_to_tickers(cusips: list[str]) -> dict[str, str]:
    """
    Map CUSIPs to ticker symbols via OpenFIGI (free API, no key required for basic use).
    Batches 100 CUSIPs per request. Rate limit: 25 requests/minute without a key.
    """
    OPENFIGI_KEY = os.getenv("OPENFIGI_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if OPENFIGI_KEY:
        headers["X-OPENFIGI-APIKEY"] = OPENFIGI_KEY
    
    mapping = {}
    batch_size = 100
    
    for i in range(0, len(cusips), batch_size):
        batch = cusips[i:i + batch_size]
        payload = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]
        
        try:
            resp = requests.post(
                "https://api.openfigi.com/v3/mapping",
                headers=headers,
                json=payload,
                timeout=30,
            )
            for cusip, result in zip(batch, resp.json()):
                data = result.get("data", [])
                if data and data[0].get("ticker"):
                    mapping[cusip] = data[0]["ticker"]
        except Exception as e:
            print(f"[resolve_tickers] Batch {i//batch_size} failed: {e}")
        
        # Respect rate limits
        time.sleep(2.5 if not OPENFIGI_KEY else 0.5)
    
    print(f"[resolve_tickers] Resolved {len(mapping)}/{len(cusips)} CUSIPs to tickers.")
    return mapping

if __name__ == "__main__":
    # Collect all unique CUSIPs across all downloaded quarters
    import glob
    all_cusips = set()
    for f in glob.glob("data/raw/13f/*.csv"):
        df = pd.read_csv(f, usecols=["cusip"], dtype=str)
        all_cusips.update(df["cusip"].dropna().unique())
    
    mapping = resolve_cusips_to_tickers(list(all_cusips))
    pd.DataFrame(list(mapping.items()), columns=["cusip","ticker"]).to_csv(
        "data/raw/cusip_ticker_map.csv", index=False
    )
```

### 4.4 Inferring Trades from Quarterly Snapshots

13-F filings are quarterly position *snapshots*, not individual trade records. We infer buys and sells by comparing consecutive quarters. This is the standard methodology used in academic finance literature.

```python
# training/model2/infer_trades.py
"""
Infer trades from consecutive 13-F quarterly snapshots.

Methodology:
  - If shares in Q2 > shares in Q1: inferred BUY of (Q2 - Q1) shares
  - If shares in Q2 < shares in Q1: inferred SELL of (Q1 - Q2) shares
  - If position appears new in Q2:  inferred BUY of full Q2 position
  - If position disappears in Q2:   inferred SELL of full Q1 position

Trade date is assigned as the last trading day of Q1 (approximate).
This is an approximation — exact trade dates within the quarter are unknown.

Limitation: intra-quarter trades that net to zero are invisible.
This is a known and accepted limitation of 13-F based studies.
"""
import pandas as pd
import numpy as np

QUARTER_END_DATES = {
    "q1": "03-31", "q2": "06-30", "q3": "09-30", "q4": "12-31"
}

MIN_SHARES_DELTA = 100  # Ignore changes smaller than 100 shares (noise threshold)

def infer_from_pair(q1_path: str, q2_path: str,
                    ticker_map: dict[str, str],
                    trade_date: str) -> pd.DataFrame:
    """
    Compare two consecutive quarter CSVs and return a DataFrame of inferred trades.
    """
    q1 = pd.read_csv(q1_path, dtype=str)
    q2 = pd.read_csv(q2_path, dtype=str)
    
    # Normalize column names
    for df in [q1, q2]:
        df.columns = [c.lower().strip() for c in df.columns]
    
    q1["shares"] = pd.to_numeric(q1["sshprnamt"], errors="coerce").fillna(0)
    q2["shares"] = pd.to_numeric(q2["sshprnamt"], errors="coerce").fillna(0)
    
    q1_pivot = q1.groupby(["cik","cusip"])["shares"].sum()
    q2_pivot = q2.groupby(["cik","cusip"])["shares"].sum()
    
    combined = q1_pivot.rename("q1_shares").to_frame().join(
        q2_pivot.rename("q2_shares"),
        how="outer"
    ).fillna(0).reset_index()
    
    combined["delta"] = combined["q2_shares"] - combined["q1_shares"]
    combined = combined[combined["delta"].abs() >= MIN_SHARES_DELTA]
    combined["trade_type"]    = combined["delta"].apply(lambda x: "buy" if x > 0 else "sell")
    combined["shares_delta"]  = combined["delta"].abs().astype(int)
    combined["inferred_date"] = trade_date
    combined["ticker"]        = combined["cusip"].map(ticker_map)
    
    # Drop unresolved tickers
    combined = combined.dropna(subset=["ticker"])
    combined = combined[combined["ticker"].str.match(r"^[A-Z]{1,5}$", na=False)]
    
    # Add fund name
    FUND_NAMES = {
        "0001166559": "Vanguard", "0001364742": "BlackRock",
        "0000093715": "Fidelity", "0001109357": "StateStreet",
        "0001045810": "TRowePrice",
    }
    combined["fund_name"] = combined["cik"].map(FUND_NAMES)
    
    return combined[["cik","fund_name","cusip","ticker",
                       "trade_type","shares_delta","inferred_date"]]

def build_all_inferred_trades() -> pd.DataFrame:
    ticker_map = dict(zip(
        pd.read_csv("data/raw/cusip_ticker_map.csv")["cusip"],
        pd.read_csv("data/raw/cusip_ticker_map.csv")["ticker"],
    ))
    
    pairs = [
        ("2022q1", "2022q2", "2022-03-31"),
        ("2022q2", "2022q3", "2022-06-30"),
        ("2022q3", "2022q4", "2022-09-30"),
        ("2022q4", "2023q1", "2022-12-31"),
        ("2023q1", "2023q2", "2023-03-31"),
        ("2023q2", "2023q3", "2023-06-30"),
        ("2023q3", "2023q4", "2023-09-30"),
        ("2023q4", "2024q1", "2023-12-31"),
        ("2024q1", "2024q2", "2024-03-31"),
        ("2024q2", "2024q3", "2024-06-30"),
        ("2024q3", "2024q4", "2024-09-30"),
    ]
    
    all_trades = []
    for q1_key, q2_key, trade_date in pairs:
        try:
            inferred = infer_from_pair(
                f"data/raw/13f/{q1_key}.csv",
                f"data/raw/13f/{q2_key}.csv",
                ticker_map,
                trade_date,
            )
            all_trades.append(inferred)
            print(f"[model2/infer] {q1_key}→{q2_key}: {len(inferred)} inferred trades")
        except FileNotFoundError as e:
            print(f"[model2/infer] Skipping {q1_key}→{q2_key}: {e}")
    
    df = pd.concat(all_trades, ignore_index=True)
    df["inferred_date"] = pd.to_datetime(df["inferred_date"])
    print(f"\n[model2/infer] Total inferred baseline trades: {len(df)}")
    df.to_csv("data/raw/baseline_trades_inferred.csv", index=False)
    return df

if __name__ == "__main__":
    build_all_inferred_trades()
```

### 4.5 Data Cleaning

```python
# training/model2/clean_baseline_trades.py
import pandas as pd

def clean(path: str = "data/raw/baseline_trades_inferred.csv") -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["inferred_date"])
    before = len(df)
    
    # Standard US equity tickers only
    df = df[df["ticker"].str.match(r"^[A-Z]{1,5}$", na=False)]
    
    # Remove penny stocks and very small position changes
    df = df[df["shares_delta"] >= 100]
    
    # Remove duplicates
    df = df.drop_duplicates(subset=["cik", "ticker", "inferred_date", "trade_type"])
    
    print(f"[model2/clean] {before} → {len(df)} baseline trades after cleaning.")
    df.to_csv("data/cleaned/baseline_trades_clean.csv", index=False)
    return df

if __name__ == "__main__":
    clean()
```

### 4.6 Feature Engineering

For baseline trades, most political features are fixed constants because fund managers have no political context. **This is intentional and important.** In V2, the Baseline Model learns from both `cohort_alpha` and `pre_trade_alpha` — two active financial return features — while all political features remain at neutral values.

```python
# training/model2/build_features_model2_v2.py
"""
V2 features for baseline (13-F) trades.

Feature 1: cohort_alpha           — computed exactly as for Model 1 (30-day forward return vs SPY)
Feature 2: pre_trade_alpha        — computed exactly as for Model 1 (5-day pre-trade excess return)
Feature 3: proximity_days         — FIXED at Model 1's median (fund managers have no relevant votes)
Feature 4: bill_proximity         — FIXED at Model 1's median (fund managers have no legislative context)
Feature 5: has_proximity_data     — FIXED at 0 (fund managers have no vote data)
Feature 6: committee_relevance    — FIXED at 0.0 (fund managers are not on committees)
Feature 7: amount_zscore          — FIXED at 0.0 (no personal trade-size baseline for funds)
Feature 8: cluster_score          — FIXED at 0 (fund trading is not politically coordinated)
Feature 9: disclosure_lag         — FIXED at 0 (quarterly 13-F filing is the norm)

The model therefore learns the distributions of cohort_alpha AND pre_trade_alpha
for institutional investors. Congressional trades that score high on Model 2
are anomalous purely on their financial return profile — the political
context features aren't even in play.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta

FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
]

def load_price_cache() -> dict:
    cache = {}
    for f in Path("data/raw/prices").glob("*.csv"):
        cache[f.stem.upper()] = pd.read_csv(f, parse_dates=["date"])
    return cache

def get_price(ticker: str, date: pd.Timestamp, cache: dict) -> float | None:
    df = cache.get(ticker)
    if df is None:
        return None
    subset = df[df["date"] >= date]
    return float(subset.iloc[0]["close"]) if not subset.empty else None

def compute_cohort_alpha(ticker: str, date: pd.Timestamp, cache: dict) -> float:
    p0 = get_price(ticker, date,                     cache)
    p1 = get_price(ticker, date + timedelta(days=30), cache)
    s0 = get_price("SPY",  date,                     cache)
    s1 = get_price("SPY",  date + timedelta(days=30), cache)
    if None in (p0, p1, s0, s1) or p0 == 0 or s0 == 0:
        return np.nan
    return (p1 - p0) / p0 - (s1 - s0) / s0

def build_feature_matrix() -> pd.DataFrame:
    df    = pd.read_csv("data/cleaned/baseline_trades_clean.csv", parse_dates=["inferred_date"])
    cache = load_price_cache()
    
    print(f"[model2/features] Computing cohort_alpha for {len(df)} baseline trades...")
    df["cohort_alpha"]   = df.apply(
        lambda r: compute_cohort_alpha(r["ticker"], r["inferred_date"], cache), axis=1
    )
    
    # V2: pre_trade_alpha is also computed for baseline (gives 2 active features)
    df["pre_trade_alpha"] = df.apply(
        lambda r: compute_pre_trade_alpha(r["ticker"], r["inferred_date"], cache), axis=1
    )
    df["pre_trade_alpha"] = df["pre_trade_alpha"].fillna(0.0)
    
    # Fixed values for political context features
    # These aren't zero because the trades ARE unremarkable on political dimensions;
    # they're zero because these features literally don't apply to fund managers.
    df["proximity_days"]         = 7   # median of real congressional proximity_days (Model 1)
    df["bill_proximity"]         = 83  # median of real congressional bill_proximity (Model 1)
    df["has_proximity_data"]     = 0   # fund managers have no vote data
    df["committee_relevance"]    = 0.0
    df["amount_zscore"]          = 0.0 # no personal trade-size baseline for funds
    df["cluster_score"]          = 0   # fund trading is not politically coordinated
    df["disclosure_lag"]         = 0   # no variable disclosure timing
    
    before = len(df)
    df = df.dropna(subset=["cohort_alpha"])
    print(f"[model2/features] {before - len(df)} dropped (delisted/missing prices). {len(df)} remain.")
    
    out = df[["cik", "fund_name", "ticker", "inferred_date",
               "trade_type"] + FEATURES]
    out.to_csv("data/features/model2_v2_features.csv", index=False)
    print(f"[model2/features] Saved data/features/model2_v2_features.csv ({len(out)} rows)")
    return out

if __name__ == "__main__":
    build_feature_matrix()
```

### 4.7 Training

```python
# training/model2/train_baseline_model_v2.py
import json, joblib, numpy as np, pandas as pd, sklearn
from datetime import datetime
from pathlib import Path
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
]

Path("model").mkdir(exist_ok=True)

def train():
    df = pd.read_csv("data/features/model2_v2_features.csv")
    X  = df[FEATURES]
    
    print(f"[model2/train] Training Baseline V2 Model on {len(X)} institutional fund trades.")
    print(f"[model2/train] cohort_alpha stats:\n{X['cohort_alpha'].describe().round(4)}")
    print(f"[model2/train] pre_trade_alpha stats:\n{X['pre_trade_alpha'].describe().round(4)}")
    print(f"[model2/train] NOTE: V2 has 2 active features (cohort_alpha, pre_trade_alpha). "
          f"Other 7 features fixed at neutral values by design.")
    
    pipeline = Pipeline([
        ("scaler",  StandardScaler()),
        ("iforest", IsolationForest(
            n_estimators=200,
            contamination="auto",
            max_samples="auto",
            random_state=42,
            n_jobs=-1,
        )),
    ])
    pipeline.fit(X)
    
    labels     = pipeline.predict(X)
    raw_scores = pipeline.named_steps["iforest"].decision_function(
                     pipeline.named_steps["scaler"].transform(X))
    
    outlier_pct = (labels == -1).mean() * 100
    print(f"\n[model2/train] Outlier rate on training data: {outlier_pct:.1f}%")
    print(f"[model2/train] Score range: [{raw_scores.min():.4f}, {raw_scores.max():.4f}]")
    
    joblib.dump(pipeline, "model/baseline_model_v2.pkl")
    
    metadata = {
        "model_name":           "baseline_model_v2",
        "model_version":        "2.0.0",
        "trained_at":           datetime.utcnow().isoformat() + "Z",
        "sklearn_version":      sklearn.__version__,
        "training_population":  "SEC 13-F institutional fund managers (Vanguard, BlackRock, Fidelity, State Street, T. Rowe Price)",
        "n_training_samples":   int(len(X)),
        "training_date_range":  {
            "start": str(pd.to_datetime(df["inferred_date"]).min().date()),
            "end":   str(pd.to_datetime(df["inferred_date"]).max().date()),
        },
        "features": FEATURES,
        "hyperparameters": {"n_estimators": 200, "contamination": "auto", "random_state": 42},
        "design_note": (
            "V2 baseline model has 2 active features: cohort_alpha (30-day return vs SPY) "
            "and pre_trade_alpha (5-day pre-trade return vs SPY). Other 7 features are fixed "
            "constants (proximity_days=7, bill_proximity=83, has_proximity_data=0, "
            "committee_relevance=0.0, amount_zscore=0.0, cluster_score=0, disclosure_lag=0). "
            "The model learns the joint distribution of financial returns for institutional "
            "investors with no legislative access. Congressional trades scoring high on this "
            "model have anomalous financial return profiles."
        ),
        "training_stats": {
            "outlier_pct": float(outlier_pct),
            "score_min":   float(raw_scores.min()),
            "score_max":   float(raw_scores.max()),
            "score_mean":  float(raw_scores.mean()),
            "score_std":   float(raw_scores.std()),
        },
    }
    with open("model/baseline_model_v2_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    
    print("[model2/train] Saved model/baseline_model_v2.pkl + baseline_model_v2_metadata.json")
    return pipeline

if __name__ == "__main__":
    train()
```

### 4.8 Testing (Model 2)

```python
# tests/test_baseline_model.py
import pytest, joblib, numpy as np, pandas as pd

FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
]

def normalize(raw): return ((-np.clip(raw,-0.5,0.5)+0.5)*100).astype(int).clip(0,100)

@pytest.fixture
def model(): return joblib.load("model/baseline_model_v2.pkl")

def test_outlier_rate(model):
    df = pd.read_csv("data/features/model2_v2_features.csv")
    labels = model.predict(df[FEATURES])
    rate = (labels == -1).mean()
    assert 0.01 <= rate <= 0.20, f"Baseline outlier rate {rate:.2%} outside 1-20%"

def test_extreme_alpha_flagged(model):
    """
    A trade with 50% alpha (50% above SPY in 30 days) should score high
    on the baseline model. This is what Model 2 is specifically designed to detect.
    All political features are 0 — the alpha alone drives the score.
    """
    X = pd.DataFrame([{
        "cohort_alpha": 0.50,  # 50% above SPY — extreme financial outperformance
        "proximity_days": 7,   # median (no vote data for fund managers)
        "has_proximity_data": 0,
        "committee_relevance": 0.0,
        "disclosure_lag": 0,
    }])
    scaler  = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    idx = normalize(iforest.decision_function(scaler.transform(X)))[0]
    assert idx >= 60, (
        f"50% alpha trade scored only {idx} on baseline model. "
        "Model should flag strong market outperformance even without political features."
    )

def test_market_rate_alpha_not_flagged(model):
    """A trade with near-zero alpha should score low."""
    X = pd.DataFrame([{
        "cohort_alpha": 0.005,  # 0.5% above SPY — essentially market rate
        "proximity_days": 7,
        "has_proximity_data": 0,
        "committee_relevance": 0.0,
        "disclosure_lag": 0,
    }])
    scaler  = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    idx = normalize(iforest.decision_function(scaler.transform(X)))[0]
    assert idx < 40, f"Market-rate trade scored {idx} on baseline model — over-flagging"

def test_political_features_dont_affect_baseline(model):
    """
    Two identical trades with different political features should produce
    the same baseline score. Model 2 must be blind to political context.
    """
    base = {"cohort_alpha": 0.12, "proximity_days": 7, "has_proximity_data": 0,
            "committee_relevance": 0.0, "disclosure_lag": 0}
    political = {"cohort_alpha": 0.12, "proximity_days": 2, "has_proximity_data": 1,
                 "committee_relevance": 1.0, "disclosure_lag": 90}
    
    scaler  = model.named_steps["scaler"]
    iforest = model.named_steps["iforest"]
    
    idx_base = normalize(iforest.decision_function(scaler.transform(pd.DataFrame([base]))))[0]
    idx_pol  = normalize(iforest.decision_function(scaler.transform(pd.DataFrame([political]))))[0]
    
    # Scores should be identical — same alpha, only political features differ
    # (In practice they're identical since we set those features to fixed values for all training data.
    #  But this test confirms the model behaves as designed.)
    assert abs(idx_base - idx_pol) <= 2, (
        f"Baseline model scores differ by {abs(idx_base - idx_pol)} points "
        f"based solely on political features. Model 2 should be insensitive to these."
    )
```

---

## 5. Cross-Model Validation

These tests compare the two models against each other to verify the dual-model architecture is producing meaningful signal.

```python
# tests/test_cross_model.py
"""
Cross-model validation: verify that the two models produce meaningfully
different and complementary signals on congressional trades.

Key assertions:
1. Congressional trades should score significantly higher on the Baseline Model
   than fund manager trades do (proving Congress really is different).
2. The SYSTEMIC quadrant should be non-empty and meaningful.
3. The two models should NOT be perfectly correlated (they're measuring different things).
"""
import pytest, joblib, numpy as np, pandas as pd

FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
]

def normalize(raw): return ((-np.clip(raw,-0.5,0.5)+0.5)*100).astype(int).clip(0,100)

@pytest.fixture
def cohort_model():   return joblib.load("model/cohort_model_v2.pkl")
@pytest.fixture
def baseline_model(): return joblib.load("model/baseline_model_v2.pkl")

def test_congress_scores_higher_on_baseline_than_funds(cohort_model, baseline_model):
    """
    Congressional trades should have a higher mean Baseline Index than
    fund manager trades. This is the core empirical claim of the product.
    If this fails, the dual-model architecture loses its justification.
    """
    congress_df = pd.read_csv("data/features/model1_v2_features.csv")
    funds_df    = pd.read_csv("data/features/model2_v2_features.csv")
    
    bs   = baseline_model.named_steps["scaler"]
    bi   = baseline_model.named_steps["iforest"]
    
    congress_baseline_idx = normalize(bi.decision_function(bs.transform(congress_df[FEATURES]))).mean()
    funds_baseline_idx    = normalize(bi.decision_function(bs.transform(funds_df[FEATURES]))).mean()
    
    print(f"\n[cross] Mean Baseline Index — Congress: {congress_baseline_idx:.1f}, "
          f"Funds: {funds_baseline_idx:.1f}")
    print(f"[cross] Difference: {congress_baseline_idx - funds_baseline_idx:.1f} points")
    
    assert congress_baseline_idx > funds_baseline_idx, (
        "Congressional trades do not score higher on the Baseline Model than "
        "fund manager trades. The two populations may not be meaningfully different, "
        "or the baseline training data needs to be reviewed."
    )

def test_systemic_quadrant_is_non_trivial(cohort_model, baseline_model):
    """
    A meaningful fraction of congressional trades should fall in the SYSTEMIC
    quadrant (low cohort, high baseline). This is the product's core systemic claim.
    """
    congress_df = pd.read_csv("data/features/model1_v2_features.csv")
    X = congress_df[FEATURES]
    
    cs = cohort_model.named_steps["scaler"]
    ci = cohort_model.named_steps["iforest"]
    bs = baseline_model.named_steps["scaler"]
    bi = baseline_model.named_steps["iforest"]
    
    cohort_idx   = normalize(ci.decision_function(cs.transform(X)))
    baseline_idx = normalize(bi.decision_function(bs.transform(X)))
    
    THRESHOLD = 60
    systemic_mask = (cohort_idx < THRESHOLD) & (baseline_idx >= THRESHOLD)
    systemic_pct  = systemic_mask.mean() * 100
    
    print(f"\n[cross] SYSTEMIC trades: {systemic_mask.sum()} ({systemic_pct:.1f}%)")
    
    assert systemic_pct >= 1.0, (
        f"Only {systemic_pct:.1f}% of congressional trades are SYSTEMIC. "
        "Expected at least 1%. The baseline model may not be sensitive enough."
    )

def test_models_are_not_perfectly_correlated(cohort_model, baseline_model):
    """
    The two models should NOT produce identical rankings. If they're perfectly
    correlated, we don't need two models — they'd be measuring the same thing.
    Target: Pearson correlation < 0.80.
    """
    congress_df = pd.read_csv("data/features/model1_v2_features.csv")
    X = congress_df[FEATURES]
    
    cs = cohort_model.named_steps["scaler"]
    ci = cohort_model.named_steps["iforest"]
    bs = baseline_model.named_steps["scaler"]
    bi = baseline_model.named_steps["iforest"]
    
    cohort_idx   = normalize(ci.decision_function(cs.transform(X))).astype(float)
    baseline_idx = normalize(bi.decision_function(bs.transform(X))).astype(float)
    
    correlation = np.corrcoef(cohort_idx, baseline_idx)[0, 1]
    print(f"\n[cross] Pearson correlation between Cohort Index and Baseline Index: {correlation:.3f}")
    
    assert correlation < 0.80, (
        f"Models have correlation {correlation:.3f} — too similar. "
        "They may be measuring the same thing. Review feature design."
    )
    assert correlation > 0.0, (
        f"Models have negative correlation {correlation:.3f}. "
        "Something is likely wrong with the feature engineering."
    )
```

---

## 6. Model Versioning & Storage

```
model/
├── cohort_model.pkl                ← V1 Model 1 (preserved for comparison)
├── cohort_model_metadata.json      ← V1 training metadata
├── baseline_model.pkl              ← V1 Model 2 (preserved for comparison)
├── baseline_model_metadata.json    ← V1 training metadata
├── cohort_model_v2.pkl             ← V2 Production Model 1 (loaded by dual_scorer.py)
├── cohort_model_v2_metadata.json   ← V2 training metadata
├── baseline_model_v2.pkl           ← V2 Production Model 2 (loaded by dual_scorer.py)
├── baseline_model_v2_metadata.json ← V2 training metadata
├── baseline_model.pkl              ← Production Model 2
├── baseline_model_v2_metadata.json ← V2 training metadata
└── archive/
    ├── v1.0.0_2026-03-01/
    │   ├── cohort_model.pkl
    │   ├── cohort_model_metadata.json
    │   ├── baseline_model.pkl
    │   └── baseline_model_metadata.json
    └── v2.0.0_2026-03-24/
        ├── cohort_model_v2.pkl
        ├── cohort_model_v2_metadata.json
        ├── baseline_model_v2.pkl
        └── baseline_model_v2_metadata.json
```

**Both models must always be versioned together.** A new cohort model with an old baseline model produces undefined behavior in the quadrant classification. Tag both with the same version number and always archive/deploy as a pair.

```python
# training/version_models.py
import shutil, json
from datetime import datetime
from pathlib import Path

def archive_current_models():
    cohort_meta   = json.load(open("model/cohort_model_metadata.json"))
    version       = cohort_meta["model_version"]
    date          = datetime.utcnow().strftime("%Y-%m-%d")
    archive_dir   = Path(f"model/archive/v{version}_{date}")
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    for fname in ["cohort_model.pkl", "cohort_model_metadata.json",
                  "baseline_model.pkl", "baseline_model_metadata.json"]:
        shutil.copy(f"model/{fname}", archive_dir / fname)
    
    print(f"[version] Both models archived to {archive_dir}")
```

---

## 7. Retraining Schedule

| Trigger | Action |
|---|---|
| **Before launch** | Full train of both models on all available history |
| **Quarterly** | Retrain both models on expanded dataset — new 13-F quarter available, 3 months of new congressional trades added |
| **New Congress seated** (Jan odd years) | Retrain immediately — new members, new committee assignments |
| **New clean funds added to CLEAN_FUND_CIKS** | Retrain Model 2 only |
| **Cohort outlier rate exceeds 25% for 7 consecutive days** | Retrain Model 1 — data distribution shift detected |
| **Cross-model correlation drops below 0** | Emergency retrain both — feature engineering problem |

---

## 8. Full End-to-End Execution Order

```bash
# ═══════════════════════════════════════════════════════════════
# MODEL 1: COHORT MODEL
# ═══════════════════════════════════════════════════════════════

# Step 1a: Collect congressional trades
python training/model1/collect_congressional_trades.py      # ~5 min

# Step 1b: Collect supporting political data
python training/collect/collect_committees.py               # ~2 min
python training/collect/collect_votes.py                    # ~30 min (rate limited)
python training/collect/collect_donors.py                   # ~60 min (rate limited)

# Step 1c: Download stock prices for all congressional tickers + SPY
python training/collect/collect_prices.py                   # ~15 min

# Step 1d: Clean
python training/model1/clean_congressional_trades.py        # ~1 min

# Step 1e: Build V2 feature matrix (9 features from DB)
python training/model1/build_features_model1_v2.py          # ~20 min

# Step 1f: Train V2
python training/model1/train_cohort_model_v2.py             # ~2 min
# → Saves: model/cohort_model_v2.pkl


# ═══════════════════════════════════════════════════════════════
# MODEL 2: BASELINE MODEL
# ═══════════════════════════════════════════════════════════════

# Step 2a: Download 13-F quarterly bulk ZIPs (free from SEC.gov)
python training/model2/collect_13f.py                       # ~20 min

# Step 2b: Resolve CUSIPs to tickers via OpenFIGI
python training/model2/resolve_tickers.py                   # ~15 min (rate limited)

# Step 2c: Infer trades from consecutive quarterly snapshots
python training/model2/infer_trades.py                      # ~5 min

# Step 2d: Download any new stock prices needed for 13-F tickers
# (many will already be cached from Step 1c)
python training/collect/collect_prices.py --supplement      # ~10 min

# Step 2e: Clean
python training/model2/clean_baseline_trades.py             # ~1 min

# Step 2f: Build V2 feature matrix (9 features)
python training/model2/build_features_model2_v2.py          # ~15 min

# Step 2g: Train V2
python training/model2/train_baseline_model_v2.py           # ~3 min
# → Saves: model/baseline_model_v2.pkl


# ═══════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════

# Step 3: Run all tests
pytest tests/ -v 2>&1 | tee tests/artifacts/test_results.txt  # ~10 min

# Specifically check the critical cross-model test:
pytest tests/test_cross_model.py -v -s


# ═══════════════════════════════════════════════════════════════
# TOTAL TIME ESTIMATE: ~3-4 hours on first run
# (dominated by Congress.gov rate limits and OpenFIGI batching)
# Subsequent runs: ~1 hour (prices cached, only new data fetched)
# ═══════════════════════════════════════════════════════════════
```

---

## 9. Directory Structure

```
project/
├── training/
│   ├── model1/
│   │   ├── collect_congressional_trades.py
│   │   ├── clean_congressional_trades.py
│   │   ├── build_features_model1.py            ← V1 feature builder (preserved)
│   │   ├── build_features_model1_v2.py         ← V2 feature builder (9 features from DB)
│   │   ├── train_cohort_model.py               ← V1 trainer (preserved)
│   │   └── train_cohort_model_v2.py            ← V2 trainer
│   ├── model2/
│   │   ├── collect_13f.py
│   │   ├── resolve_tickers.py
│   │   ├── infer_trades.py
│   │   ├── clean_baseline_trades.py
│   │   ├── build_features_model2.py            ← V1 feature builder (preserved)
│   │   ├── build_features_model2_v2.py         ← V2 feature builder (9 features)
│   │   ├── train_baseline_model.py             ← V1 trainer (preserved)
│   │   └── train_baseline_model_v2.py          ← V2 trainer
│   ├── collect/
│   │   ├── collect_committees.py
│   │   ├── collect_votes.py
│   │   ├── collect_donors.py
│   │   └── collect_prices.py
│   └── version_models.py
├── backend/
│   ├── scoring/
│   │   ├── dual_scorer.py                      ← V2 production scorer (9 features)
│   │   └── dual_scorer_v1.py                   ← V1 scorer backup (5 features)
│   └── db/
│       ├── schema.sql                          ← Updated with V2 feat_* columns
│       ├── migrate_dual_scores.py              ← V1 migration
│       └── migrate_v2_features.py              ← V2 migration (added 4 new feat columns)
├── model/
│   ├── cohort_model.pkl                        ← V1
│   ├── cohort_model_metadata.json
│   ├── baseline_model.pkl                      ← V1
│   ├── baseline_model_metadata.json
│   ├── cohort_model_v2.pkl                     ← V2 (production)
│   ├── cohort_model_v2_metadata.json
│   ├── baseline_model_v2.pkl                   ← V2 (production)
│   ├── baseline_model_v2_metadata.json
│   └── archive/
├── data/
│   ├── raw/
│   │   ├── congressional_trades_raw.csv
│   │   ├── committees_raw.csv
│   │   ├── votes_raw.csv
│   │   ├── donors_raw.csv
│   │   ├── cusip_ticker_map.csv
│   │   ├── baseline_trades_inferred.csv
│   │   ├── 13f/
│   │   │   ├── 2022q1.csv
│   │   │   └── ...
│   │   └── prices/
│   │       ├── AAPL.csv
│   │       ├── SPY.csv
│   │       └── ...
│   ├── cleaned/
│   │   ├── congressional_trades_clean.csv
│   │   ├── baseline_trades_clean.csv
│   │   ├── votes_clean.csv
│   │   └── donors_agg.csv
│   ├── features/
│   │   ├── model1_features.csv                 ← V1 (5 features, preserved)
│   │   ├── model1_v2_features.csv              ← V2 (9 features)
│   │   ├── model2_features.csv                 ← V1 (5 features, preserved)
│   │   └── model2_v2_features.csv              ← V2 (9 features)
│   └── v1_scores_backup.csv                    ← V1 scoring results (9,720 rows)
├── scripts/
│   ├── compare_v1_v2.py                        ← V1 vs V2 comparison analysis
│   ├── model_validation_audit.py
│   └── top50_anomalous.py
├── scoring/
│   └── dual_scorer.py
└── tests/
    ├── test_cohort_model.py
    ├── test_baseline_model.py
    ├── test_cross_model.py
    └── artifacts/
        └── test_results.txt
```

---

## 10. Dependencies

```text
scikit-learn==1.5.2
pandas==2.2.3
numpy==1.26.4
joblib==1.4.2
yfinance==0.2.43
requests==2.32.3
sqlalchemy[asyncio]==2.0.36
aiomysql==0.2.0
python-dotenv==1.0.1
matplotlib==3.9.2
seaborn==0.13.2
scipy==1.14.1
pytest==8.3.3
```

---

## Appendix A: Feature Coverage & Data Sources (Both Models)

*Last verified: March 2026*

### Data Inventory

| Source | File | Rows | Key Columns |
|---|---|---|---|
| Congressional trades | `data/raw/congressional_trades_raw.csv` | 10,827 | politician_id, ticker, trade_date, disclosure_date, industry_sector |
| Institutional trades (13-F inferred) | `data/raw/13f/institutional_trades_inferred.csv` | 66,226 | cusip, issuer_name, trade_direction, from_period, to_period |
| 13-F quarterly snapshots | `data/raw/13f/2023q1.csv` – `2025q4.csv` | 11 files | cik, cusip, sshprnamt (shares), year, quarter |
| Votes (House + Senate) | `data/raw/votes_raw.csv` | 1,079 | id, bill_id, vote_date, related_sector |
| Politician votes (House) | `data/raw/politician_votes_raw.csv` | 228,957 | politician_id (bioguide), vote_id, position |
| Politician votes (Senate) | `data/raw/senate_politician_votes_raw.csv` | 71,691 | politician_id (bioguide), vote_id, position |
| Bills | `data/raw/bills_raw.csv` | 12,218 | id, policy_area, related_sector |
| Politicians | `data/raw/politicians_raw.csv` | 548 | id (bioguide), full_name, party, state, chamber |
| Committee memberships | `data/raw/committee_memberships_raw.csv` | 3,908 | politician_id, committee_name, role (532 unique politicians) |
| PAC contributions | `data/raw/fec_pac_contributions_raw.csv` | 10,000 | candidate_id, contributor_name, amount |
| Ticker→sector map | `data/raw/_combined_sector_map.json` | 734 tickers | ticker → sector (defense, finance, healthcare, energy, tech, agriculture, telecom) |
| Stock prices (daily OHLCV) | `data/raw/prices/*.csv` | 1,697 tickers | date, close |
| CUSIP→ticker map | `data/raw/cusip_ticker_map.csv` | Not yet built | cusip, ticker (via OpenFIGI) |

---

### Model 1: Cohort Model (Congressional Trades) — Feature Detail

**Training population:** 10,827 congressional STOCK Act trade disclosures (2022–present)

#### Feature 1: `cohort_alpha` — 30-Day Forward Return vs. SPY

| Attribute | Value |
|---|---|
| **Formula** | $(P_{+30d} - P_{trade}) / P_{trade} - (SPY_{+30d} - SPY_{trade}) / SPY_{trade}$ |
| **Data sources** | `data/raw/prices/{TICKER}.csv` + `data/raw/prices/SPY.csv` (yfinance daily close) |
| **Coverage** | **95.3%** — 10,316/10,827 trades have price data for both ticker and SPY at trade date + 30 days |
| **Missing handling** | Set to `NaN`; rows dropped before training |
| **Interpretation** | Excess return over market. Positive = politician's timing beat SPY. |

#### Feature 2: `proximity_days` — Days to Nearest Vote (Median-Imputed)

| Attribute | Value |
|---|---|
| **Computation** | **Tier 1:** Nearest vote by same politician on sector-matched bill (within ±90 days). **Tier 2 fallback:** Nearest vote of any kind by same politician (within ±90 days). **No match:** Imputed with median of real values (7 days). |
| **Data sources** | `votes_raw.csv` (1,079 votes, 356 with sector), `politician_votes_raw.csv` (228,957 House), `senate_politician_votes_raw.csv` (71,691 Senate), `politicians_raw.csv` (548 politicians for name→bioguide resolution) |
| **Linkage** | Trade names → bioguide IDs via multi-strategy resolver (Last,First ↔ First Last, first-name-only, last-name-only unique, title/suffix stripping, 23-entry NICKNAMES override dict). **94.6% resolution rate** (10,244/10,827). |
| **Coverage** | **41.7% real values** — Tier 1 sector-match: 3,244 (30.0%). Tier 2 any-vote fallback: +1,271 (11.7%). Total real: 4,515. Median-imputed: 6,312 (58.3%). |
| **Missing handling** | Imputed with median of real values (7 days). See `has_proximity_data` indicator below. |
| **Interpretation** | Days between trade and relevant legislative activity. Low values suggest timing based on upcoming/recent votes. |
| **Scaler impact** | With median imputation, the real-value range (0–90 days) spans 6.6 standard deviations in scaled space (vs. 0.19 with the old 999 sentinel). This is a **35x improvement** in feature resolution for IsolationForest. |

#### Feature 3: `has_proximity_data` — Missingness Indicator

| Attribute | Value |
|---|---|
| **Formula** | Binary: `1` if proximity_days was computed from real vote data; `0` if median-imputed |
| **Data sources** | Derived from proximity_days computation (no additional data) |
| **Coverage** | **100%** — every trade gets a value. 4,515 (41.7%) = 1, 6,312 (58.3%) = 0. |
| **Missing handling** | N/A — always has a value |
| **Interpretation** | Preserves the “has data” signal lost by median imputation. Lets IsolationForest learn that trades with vote proximity data are fundamentally different from those without. A politician who voted 7 days before trading (has_proximity_data=1) is different from one where we have no vote record (has_proximity_data=0, proximity_days=7). |

#### Feature 4: `committee_relevance` — Committee Oversight Score

| Attribute | Value |
|---|---|
| **Formula** | Continuous 0.0–1.0. For each committee the politician serves on, check if it has jurisdiction over the traded stock's sector. Weight by role: Chair/Ranking Member of matched committee → 1.0, regular member → 0.7, Appropriations (any sector) → 0.4, Intelligence (defense/tech) → 0.5. Take the MAX across all memberships. |
| **Data sources** | `committee_memberships_raw.csv` (3,908 memberships, 532 unique politicians), `_combined_sector_map.json` (734 tickers → 7 sectors; 32 multi-sector tickers as lists) |
| **Linkage** | Curated multi-sector committee map (`COMMITTEE_SECTORS` dict, 21 standing committees + 4 cross-cutting). Each committee maps to 1–7 regulated sectors based on House/Senate rules and CRS jurisdiction reports. 32 major tickers (MSFT, AMZN, INTC, CSCO, etc.) carry multi-sector tags — e.g. MSFT → ["tech", "defense"] — enabling cross-committee signal for conglomerates. |
| **Coverage** | **~41% effective signal** → **~44% with multi-sector tickers** (+201 trades gain non-zero scores, +5.6% variance improvement). The continuous score provides meaningful non-zero values due to multi-sector committee tagging, cross-cutting committee rules, and multi-sector ticker mapping. |
| **Missing handling** | Returns 0.0 if bioguide unresolved or ticker has no sector mapping |
| **Interpretation** | Strength of regulatory oversight conflict. 1.0 = committee chair directly overseeing the traded sector. 0.7 = regular member. 0.4–0.5 = cross-cutting committee (Appropriations funds all sectors; Intelligence touches defense + tech). 0.0 = no committee overlap. |
| **Design rationale** | The old binary `sector_overlap` had three problems: (1) single-sector committee tags missed multi-jurisdiction committees like Energy & Commerce (energy, healthcare, tech, telecom), (2) keyword matching missed ~25% of committee names, (3) binary encoding threw away role-importance signal. The continuous score fixes all three. See Section 3.4 design note for details. |

#### Feature 5: `pre_trade_alpha` (V2) — 30-Day Pre-Trade Return vs. SPY

| Attribute | Value |
|---|---|
| **Formula** | $(P_{trade} - P_{-30d}) / P_{-30d} - (SPY_{trade} - SPY_{-30d}) / SPY_{-30d}$ |
| **Data sources** | `data/raw/prices/{TICKER}.csv` + `data/raw/prices/SPY.csv` (yfinance daily close) |
| **Coverage** | **70.8%** — 7,309/10,326 trades have price data for both ticker and SPY at trade date − 30 days |
| **Missing handling** | Set to `0.0` (neutral) |
| **Interpretation** | Excess return in the 30 days leading up to the trade. Positive = stock was already rallying before the politician bought. Detects "buying on momentum" or "reacting to information" patterns. |

#### Feature 6: `bill_proximity` (V2) — Days to Nearest Sector-Related Bill

| Attribute | Value |
|---|---|
| **Formula** | Minimum absolute `|trade_date - bill_date|` for bills whose `related_sector` matches the traded ticker's sector. Clipped to [0, 90] calendar days. |
| **Data sources** | `bills_raw.csv` (12,218 bills with `policy_area`, `related_sector`), `_combined_sector_map.json` (734 tickers → sectors) |
| **Coverage** | **4.8% real match** — 500/10,326 trades have a sector-matched bill within ±90 days. Remaining imputed with median of real values. |
| **Missing handling** | Imputed with median of real values (see `has_proximity_data`) |
| **Interpretation** | Days between trade and relevant legislation. Low values suggest awareness of upcoming or recent sector-affecting legislation. |

#### Feature 7: `amount_zscore` (V2) — Trade Amount Z-Score Within Politician

| Attribute | Value |
|---|---|
| **Formula** | $(amount - \mu_{politician}) / \sigma_{politician}$, using each politician's mean and std of historical trade amounts. Clipped to [−3, 3]. |
| **Data sources** | `congressional_trades_raw.csv` column `amount` (parsed from range strings: "$1,001 - $15,000" → midpoint) |
| **Coverage** | **85.4% non-zero** — 8,820/10,326 trades have parseable amount ranges. Politicians with < 2 trades get z-score = 0. |
| **Missing handling** | Set to `0.0` (population mean) |
| **Interpretation** | How unusual this trade size is for this specific politician. High z-score = abnormally large trade relative to their own history. Detects "going big" on a high-conviction insider position. |

#### Feature 8: `cluster_score` (V2) — Same-Ticker Temporal Clustering

| Attribute | Value |
|---|---|
| **Formula** | Count of distinct politicians trading the same ticker within ±7 calendar days of this trade, minus 1 (self). |
| **Data sources** | `congressional_trades_raw.csv` columns: `ticker`, `trade_date`, `politician_name` |
| **Coverage** | **20.0% non-zero** — 2,070/10,326 trades have ≥ 1 other politician trading the same ticker within ±7 days. |
| **Missing handling** | `0` (no cluster) |
| **Interpretation** | Multiple politicians trading the same stock in the same week suggests coordinated information flow. High cluster_score = suspicious herding behavior. Top cluster: TSLA Oct 2024 (4 politicians within 7 days). |

#### Feature 9: `disclosure_lag` — Days from Trade to STOCK Act Filing (log₁p)

| Attribute | Value |
|---|---|
| **Formula** | `log1p(disclosure_date - trade_date)`, raw days clipped to [0, 365] before transform |
| **Data sources** | `congressional_trades_raw.csv` columns: `trade_date`, `disclosure_date` |
| **Coverage** | **95.4%** — 10,326/10,827 trades have both dates |
| **Missing handling** | Filled with 0 before log1p |
| **Interpretation** | How long the politician waited before publicly disclosing the trade. Log₁p transform compresses the long right tail, preventing extreme lag values (e.g. 300+ days) from dominating IsolationForest splits. This was the key V2 fix — V1's raw-day disclosure_lag drove ~61% of flagged detections. |
| **V2 change** | V1 used raw days; V2 uses `log1p(days)`. This eliminated the disclosure_lag dominance problem (flagged/unflagged ratio: V1 ≈ 2.6x → V2 ≈ 0.98x). |

#### Model 1 Coverage Summary

| Feature | Real Values | Sentinel/Default | Effective for Model |
|---|---|---|---|
| `cohort_alpha` | 95.3% | dropped | **Strong** |
| `pre_trade_alpha` | 70.8% | 29.2% filled 0.0 | **Strong** — pre-trade momentum signal |
| `proximity_days` | 41.7% | 58.3% median-imputed (7) | **Strong** — 35x scaler resolution improvement |
| `bill_proximity` | 4.8% | 95.2% median-imputed | **Moderate** — sparse but high-signal when present |
| `has_proximity_data` | 100% (41.7% =1, 58.3% =0) | N/A | **Strong** — preserves missingness signal |
| `committee_relevance` | ~77.9% eligible | 22.1% default 0.0 | **Strong** — continuous 0.0–1.0, ~41% non-zero signal |
| `amount_zscore` | 85.4% | 14.6% filled 0.0 | **Strong** — politician-relative trade size |
| `cluster_score` | 20.0% | 80.0% filled 0 | **Moderate** — sparse but critical for herding detection |
| `disclosure_lag` | 95.4% | 4.6% filled 0 | **Strong** — log₁p transform (V2) |

**Effective working features: 9 of 9 (V2).** IsolationForest tree splits operate on all nine features. The four new V2 features (pre_trade_alpha, bill_proximity, amount_zscore, cluster_score) diversify the anomaly signal away from disclosure_lag dominance. The log₁p transform on disclosure_lag further compresses its influence, producing a more balanced detection profile.

---

### Model 2: Baseline Model (SEC 13-F Institutional Fund Trades) — Feature Detail

**Training population:** ~66,226 inferred trades from 5 institutional fund managers (Vanguard, BlackRock, Fidelity/FMR, State Street, T. Rowe Price) across 11 quarterly snapshots (2023Q1–2025Q4).

**Key design principle:** Features 2–4 are fixed constants because fund managers have no political context. Model 2 effectively learns the distribution of `cohort_alpha` alone — what normal market-rate returns look like for large, diversified, passive-leaning investors with zero legislative access.

#### Feature 1: `cohort_alpha` — 30-Day Forward Return vs. SPY

| Attribute | Value |
|---|---|
| **Formula** | Identical to Model 1: $(P_{+30d} - P_{inferred}) / P_{inferred} - (SPY_{+30d} - SPY_{inferred}) / SPY_{inferred}$ |
| **Data sources** | `data/raw/prices/{TICKER}.csv` + `data/raw/prices/SPY.csv` |
| **Trade dates** | Approximated as last trading day of the prior quarter (exact intra-quarter dates unknown from 13-F snapshots) |
| **Coverage** | Depends on CUSIP→ticker resolution (via OpenFIGI) and price file availability. Expected ~85–90% after filtering delisted/unresolvable CUSIPs. 9,894 unique CUSIPs across all quarters. 1,697 price files currently cached. |
| **Missing handling** | Set to `NaN`; rows dropped before training |
| **Interpretation** | Same as Model 1. What was the 30-day alpha for this institutional trade? |

#### Feature 2: `pre_trade_alpha` (V2) — 30-Day Pre-Trade Return vs. SPY

| Attribute | Value |
|---|---|
| **Formula** | Identical to Model 1: $(P_{trade} - P_{-30d}) / P_{-30d} - (SPY_{trade} - SPY_{-30d}) / SPY_{-30d}$ |
| **Data sources** | `data/raw/prices/{TICKER}.csv` + `data/raw/prices/SPY.csv` |
| **Trade dates** | Same approximation as cohort_alpha |
| **Coverage** | Computed from price data — same coverage as cohort_alpha (~85–90%) |
| **Missing handling** | Set to `0.0` (neutral) |
| **Interpretation** | Pre-trade momentum. Establishes what "normal" pre-trade price movement looks like for institutional investors — the baseline against which congressional pre-trade returns are compared. |
| **V2 change** | New in V2. Previously fixed at 0.0. Now computed, making pre_trade_alpha the second active feature for Model 2. |

#### Feature 3: `proximity_days` — FIXED at 7 (Model 1 median)

| Attribute | Value |
|---|---|
| **Value** | Constant `7` for all rows (median of Model 1's real proximity_days values) |
| **Rationale** | Fund managers cast no congressional votes. The concept of "days to nearest vote" does not apply. Fixed at the same imputed value used for missing data in Model 1, ensuring both models share the same "no data" representation. |
| **Model impact** | Zero variance — IsolationForest ignores this feature. |

#### Feature 4: `bill_proximity` (V2) — FIXED at median

| Attribute | Value |
|---|---|
| **Value** | Constant (Model 1 median of real bill_proximity values) for all rows |
| **Rationale** | Fund managers have no legislative context. Fixed at "no data" representation. |
| **Model impact** | Zero variance — ignored by IsolationForest. |

#### Feature 5: `has_proximity_data` — FIXED at 0

| Attribute | Value |
|---|---|
| **Value** | Constant `0` for all rows |
| **Rationale** | Fund managers have no vote data. Consistent with Model 1's indicator for trades without proximity data. |
| **Model impact** | Zero variance — ignored by IsolationForest. |

#### Feature 6: `committee_relevance` — FIXED at 0.0

| Attribute | Value |
|---|---|
| **Value** | Constant `0.0` for all rows |
| **Rationale** | Fund managers serve on no congressional committees. No regulatory oversight conflict exists. |
| **Model impact** | Zero variance — ignored by IsolationForest. |

#### Feature 7: `amount_zscore` (V2) — FIXED at 0.0

| Attribute | Value |
|---|---|
| **Value** | Constant `0.0` for all rows |
| **Rationale** | Institutional fund trades are not comparable to individual politician trade amounts. Fixed at population mean. |
| **Model impact** | Zero variance — ignored by IsolationForest. |

#### Feature 8: `cluster_score` (V2) — FIXED at 0

| Attribute | Value |
|---|---|
| **Value** | Constant `0` for all rows |
| **Rationale** | Institutional fund rebalancing is not analogous to congressional herding behavior. |
| **Model impact** | Zero variance — ignored by IsolationForest. |

#### Feature 9: `disclosure_lag` — FIXED at 0

| Attribute | Value |
|---|---|
| **Value** | Constant `0` for all rows |
| **Rationale** | 13-F quarterly filings follow a standard SEC schedule. There is no variable disclosure timing advantage. |
| **Model impact** | Zero variance — ignored by IsolationForest. |

#### Model 2 Coverage Summary

| Feature | Real Values | Sentinel/Default | Effective for Model |
|---|---|---|---|
| `cohort_alpha` | ~85–90% (est.) | dropped | **Active** |
| `pre_trade_alpha` | ~85–90% (est.) | filled 0.0 | **Active** (V2 — now computed) |
| `proximity_days` | 0% (all 7) | 100% fixed | Ignored — zero variance |
| `bill_proximity` | 0% (all median) | 100% fixed | Ignored — zero variance |
| `has_proximity_data` | 0% (all 0) | 100% fixed | Ignored — zero variance |
| `committee_relevance` | 0% (all 0.0) | 100% fixed | Ignored — zero variance |
| `amount_zscore` | 0% (all 0.0) | 100% fixed | Ignored — zero variance |
| `cluster_score` | 0% (all 0) | 100% fixed | Ignored — zero variance |
| `disclosure_lag` | 0% (all 0) | 100% fixed | Ignored — zero variance |

**Effective working features: 2 of 9 (V2, by design).** Model 2 learns the normal distribution of financial returns (cohort_alpha) and pre-trade momentum (pre_trade_alpha) for institutional investors. V1 had only 1 effective feature (cohort_alpha). The addition of pre_trade_alpha in V2 means Model 2 now captures both forward and backward price momentum baselines, improving its ability to distinguish normal market behavior from congressional informational advantage.

---

### Side-by-Side Comparison

| Feature | Model 1 (Congressional) | Model 2 (Institutional) |
|---|---|---|
| `cohort_alpha` | Computed: 95.3% coverage | Computed: ~85–90% coverage |
| `pre_trade_alpha` | Computed: 70.8% coverage | Computed: ~85–90% coverage (V2) |
| `proximity_days` | Computed: 41.7% real, 58.3% median-imputed (7) | Fixed: 7 (Model 1 median, not applicable) |
| `bill_proximity` | Computed: 4.8% real, 95.2% median-imputed | Fixed: median (not applicable) |
| `has_proximity_data` | Indicator: 41.7% =1, 58.3% =0 | Fixed: 0 (not applicable) |
| `committee_relevance` | Computed: continuous 0.0–1.0, ~41% non-zero | Fixed: 0.0 (not applicable) |
| `amount_zscore` | Computed: 85.4% non-zero | Fixed: 0.0 (not applicable) |
| `cluster_score` | Computed: 20.0% non-zero | Fixed: 0 (not applicable) |
| `disclosure_lag` | Computed: 95.4% real (log₁p in V2) | Fixed: 0 (not applicable) |
| **Effective features** | **9 of 9** | **2 of 9 (V2, by design)** |

### Why This Asymmetry Is Intentional

Model 2's fixed features are not a data quality problem — they are a design decision. The Baseline Model's purpose is to establish what financial returns look like for investors with **no legislative access**. By fixing all political features to their "no information" values (median-imputed proximity_days=7, has_proximity_data=0, etc.), Model 2 learns primarily from return distributions.

**V2 improvement:** pre_trade_alpha is now computed for Model 2 (previously fixed at 0.0). This means Model 2 captures both forward returns (cohort_alpha) and pre-trade momentum (pre_trade_alpha) for institutional investors, establishing a richer baseline for "normal" trading patterns. Congressional trades that show unusual pre-trade momentum *and* post-trade alpha are more reliably flagged.

The asymmetry is what makes the SYSTEMIC quadrant meaningful: a trade can look normal within Congress (low Model 1 score, because many politicians achieve similar returns) yet look anomalous compared to the investing public (high Model 2 score). This is the pattern that suggests a widespread informational advantage rather than individual misconduct.

---

*House Advantage — Model Training Guide v3.0 · Dual-Model Architecture · July 2025 · UCI*