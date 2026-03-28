"""
Step 1e-v2: Build the 9-feature matrix for Model 1 V2 (Cohort Model).

V2 Features:
  1. cohort_alpha        — 30-day forward return minus SPY return
  2. pre_trade_alpha     — 5-day pre-trade excess return vs SPY
  3. proximity_days      — days to nearest vote; median-imputed
  4. bill_proximity      — days to nearest sector-matched bill action
  5. has_proximity_data  — 1 if real vote data, 0 if median-imputed
  6. committee_relevance — 0.0–1.0 committee oversight score
  7. amount_zscore       — personal trade-size anomaly (log scale)
  8. cluster_score       — count of other politicians trading same ticker ±7d
  9. disclosure_lag      — log1p(days from trade to filing)

Input:  DB (trades, stock_prices, politician_votes, votes, bills,
        committee_memberships, committees)
Output: data/features/model1_v2_features.csv
"""
import json
import numpy as np
import pandas as pd
import pymysql
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DB_CFG = dict(host="localhost", port=3307, user="root",
              password="changeme", database="house_advantage")

FEATURES = [
    "cohort_alpha", "pre_trade_alpha", "proximity_days", "bill_proximity",
    "has_proximity_data", "committee_relevance", "amount_zscore",
    "cluster_score", "disclosure_lag",
]

TICKER_SECTOR_MAP = json.loads(
    (ROOT / "backend" / "data" / "raw" / "_combined_sector_map.json").read_text()
)

COMMITTEE_KEYWORD_SECTORS = {
    "agriculture":     ["agriculture"],
    "armed services":  ["defense"],
    "energy":          ["energy"],
    "natural resources": ["energy", "agriculture"],
    "commerce":        ["tech", "telecom"],
    "financial":       ["finance"],
    "banking":         ["finance"],
    "finance":         ["finance", "healthcare"],
    "health":          ["healthcare"],
    "veterans":        ["healthcare"],
    "science":         ["tech"],
    "homeland":        ["defense", "tech"],
    "ways and means":  ["finance", "healthcare"],
    "education":       ["healthcare"],
    "transportation":  ["defense"],
}
CROSS_CUTTING_KEYWORDS = {
    "intelligence": {"defense": 0.5, "tech": 0.5},
    "appropriations": {s: 0.4 for s in [
        "defense", "finance", "healthcare", "energy", "tech", "agriculture", "telecom"
    ]},
}
BILL_SECTOR_MAP = {
    "Agriculture and Food": "agriculture",
    "Armed Forces and National Security": "defense",
    "Commerce": "tech",
    "Economics and Public Finance": "finance",
    "Energy": "energy",
    "Finance and Financial Sector": "finance",
    "Health": "healthcare",
    "Science, Technology, Communications": "tech",
    "Transportation and Public Works": "defense",
    "Environmental Protection": "energy",
    "Public Lands and Natural Resources": "energy",
    "Foreign Trade and International Finance": "finance",
}


# ── Price helpers ─────────────────────────────────────────────────────────────

def load_price_cache(conn) -> dict:
    df = pd.read_sql(
        "SELECT ticker, price_date AS date, close FROM stock_prices",
        conn, parse_dates=["date"],
    )
    cache = {}
    for ticker, grp in df.groupby("ticker"):
        cache[ticker.upper()] = grp.sort_values("date").reset_index(drop=True)
    return cache


def get_price(ticker, date, cache):
    df = cache.get(ticker)
    if df is None:
        return None
    subset = df[df["date"] >= date]
    return float(subset.iloc[0]["close"]) if not subset.empty else None


def get_price_before(ticker, date, cache):
    df = cache.get(ticker)
    if df is None:
        return None
    subset = df[df["date"] <= date]
    return float(subset.iloc[-1]["close"]) if not subset.empty else None


def compute_cohort_alpha(ticker, trade_date, cache):
    p0 = get_price(ticker, trade_date, cache)
    p1 = get_price(ticker, trade_date + timedelta(days=30), cache)
    s0 = get_price("SPY", trade_date, cache)
    s1 = get_price("SPY", trade_date + timedelta(days=30), cache)
    if None in (p0, p1, s0, s1) or p0 == 0 or s0 == 0:
        return np.nan
    return (p1 - p0) / p0 - (s1 - s0) / s0


def compute_pre_trade_alpha(ticker, trade_date, cache):
    p1 = get_price_before(ticker, trade_date, cache)
    p0 = get_price_before(ticker, trade_date - timedelta(days=7), cache)
    s1 = get_price_before("SPY", trade_date, cache)
    s0 = get_price_before("SPY", trade_date - timedelta(days=7), cache)
    if None in (p0, p1, s0, s1) or p0 == 0 or s0 == 0:
        return np.nan
    return (p1 - p0) / p0 - (s1 - s0) / s0


# ── Committee relevance ──────────────────────────────────────────────────────

def compute_committee_relevance(politician_id, trade_sector, memberships):
    if not trade_sector or politician_id is None:
        return 0.0
    sectors = trade_sector if isinstance(trade_sector, list) else [trade_sector]
    pol_m = memberships[memberships["politician_id"] == politician_id]
    if pol_m.empty:
        return 0.0

    best = 0.0
    for _, m in pol_m.iterrows():
        cname_lower = str(m["committee_name"]).lower()
        role = str(m.get("role", "")).lower()
        for sector in sectors:
            is_cross = False
            for kw, sector_map in CROSS_CUTTING_KEYWORDS.items():
                if kw in cname_lower:
                    weight = sector_map.get(sector, 0.0)
                    if weight > 0 and ("chair" in role or "ranking" in role):
                        weight = min(weight * 1.3, 1.0)
                    best = max(best, weight)
                    is_cross = True
                    break
            if is_cross:
                continue
            for kw, kw_sectors in COMMITTEE_KEYWORD_SECTORS.items():
                if kw in cname_lower and sector in kw_sectors:
                    weight = 1.0 if ("chair" in role or "ranking" in role) else 0.7
                    best = max(best, weight)
                    break
            db_sector = m.get("sector_tag")
            if db_sector and db_sector == sector:
                weight = 1.0 if ("chair" in role or "ranking" in role) else 0.7
                best = max(best, weight)
    return round(best, 2)


# ── Main builder ──────────────────────────────────────────────────────────────

def build_feature_matrix() -> pd.DataFrame:
    conn = pymysql.connect(**DB_CFG)

    # Load all data from DB
    print("[model1/v2] Loading data from DB...")
    trades = pd.read_sql("""
        SELECT id AS trade_id, politician_id, ticker, trade_date,
               disclosure_lag_days, industry_sector, amount_midpoint
        FROM trades
    """, conn, parse_dates=["trade_date"])
    print(f"  {len(trades)} trades")

    cache = load_price_cache(conn)
    print(f"  {len(cache)} tickers with prices")

    memberships = pd.read_sql("""
        SELECT cm.politician_id, c.name AS committee_name, cm.role, c.sector_tag
        FROM committee_memberships cm
        JOIN committees c ON cm.committee_id = c.id
    """, conn)
    print(f"  {len(memberships)} committee memberships")

    votes = pd.read_sql("""
        SELECT pv.politician_id, v.vote_date
        FROM politician_votes pv
        JOIN votes v ON pv.vote_id = v.id
        WHERE v.vote_date IS NOT NULL
    """, conn, parse_dates=["vote_date"])
    print(f"  {len(votes)} vote records")

    bills = pd.read_sql("""
        SELECT policy_area, latest_action_date
        FROM bills
        WHERE latest_action_date IS NOT NULL AND policy_area IS NOT NULL
    """, conn, parse_dates=["latest_action_date"])
    print(f"  {len(bills)} bills with dates")

    # Amount stats per politician (for z-score)
    amount_stats = pd.read_sql("""
        SELECT politician_id,
               AVG(LOG(amount_midpoint + 1)) AS log_amt_mean,
               STDDEV(LOG(amount_midpoint + 1)) AS log_amt_std,
               COUNT(*) AS n_trades
        FROM trades
        WHERE politician_id IS NOT NULL AND amount_midpoint IS NOT NULL
        GROUP BY politician_id
        HAVING COUNT(*) >= 5
    """, conn)
    print(f"  Amount stats for {len(amount_stats)} politicians")

    # Cluster counts
    cluster_df = pd.read_sql("""
        SELECT t1.id AS trade_id,
               COUNT(DISTINCT t2.politician_id) AS cluster_count
        FROM trades t1
        JOIN trades t2 ON t1.ticker = t2.ticker
            AND t1.politician_id != t2.politician_id
            AND ABS(DATEDIFF(t1.trade_date, t2.trade_date)) <= 7
            AND t2.politician_id IS NOT NULL
        WHERE t1.politician_id IS NOT NULL
        GROUP BY t1.id
    """, conn)
    print(f"  Cluster counts for {len(cluster_df)} trades")

    conn.close()

    # Resolve sector
    n = len(trades)
    trades["sector"] = trades.apply(
        lambda r: r["industry_sector"] if pd.notna(r["industry_sector"])
        else TICKER_SECTOR_MAP.get(r["ticker"]), axis=1
    )

    # 1. cohort_alpha
    print(f"\n[model1/v2] Computing cohort_alpha for {n} trades...")
    trades["cohort_alpha"] = trades.apply(
        lambda r: compute_cohort_alpha(r["ticker"], r["trade_date"], cache), axis=1
    )
    alpha_ok = trades["cohort_alpha"].notna().sum()
    print(f"  {alpha_ok}/{n} computed")

    # 2. pre_trade_alpha
    print("[model1/v2] Computing pre_trade_alpha...")
    trades["pre_trade_alpha"] = trades.apply(
        lambda r: compute_pre_trade_alpha(r["ticker"], r["trade_date"], cache), axis=1
    )
    pta_ok = trades["pre_trade_alpha"].notna().sum()
    trades["pre_trade_alpha"] = trades["pre_trade_alpha"].fillna(0.0)
    print(f"  {pta_ok}/{n} computed, {n - pta_ok} imputed as 0.0")

    # 3/5. proximity_days + has_proximity_data
    print("[model1/v2] Computing proximity_days...")
    prox_raw = []
    for _, r in trades.iterrows():
        pid = r["politician_id"]
        if pd.isna(pid):
            prox_raw.append(999)
            continue
        pol_votes = votes[votes["politician_id"] == pid]
        if pol_votes.empty:
            prox_raw.append(999)
            continue
        deltas = (pol_votes["vote_date"] - r["trade_date"]).abs().dt.days
        min_d = deltas.min()
        prox_raw.append(int(min_d) if min_d <= 90 else 999)
    trades["proximity_days_raw"] = prox_raw
    real_mask = trades["proximity_days_raw"] != 999
    trades["has_proximity_data"] = real_mask.astype(int)
    median_prox = int(trades.loc[real_mask, "proximity_days_raw"].median()) if real_mask.any() else 7
    trades["proximity_days"] = trades["proximity_days_raw"].where(real_mask, median_prox)
    print(f"  {real_mask.sum()} real, {(~real_mask).sum()} imputed (median={median_prox})")

    # 4. bill_proximity
    print("[model1/v2] Computing bill_proximity...")
    bp_raw = []
    for _, r in trades.iterrows():
        sector = r["sector"]
        if not sector:
            bp_raw.append(999)
            continue
        sectors = sector if isinstance(sector, list) else [sector]
        relevant = bills[bills["policy_area"].map(lambda pa: BILL_SECTOR_MAP.get(pa) in sectors)]
        if relevant.empty:
            bp_raw.append(999)
            continue
        deltas = (relevant["latest_action_date"] - r["trade_date"]).abs().dt.days
        min_d = deltas.min()
        bp_raw.append(int(min_d) if min_d <= 180 else 999)
    trades["bill_proximity_raw"] = bp_raw
    bill_real = trades["bill_proximity_raw"] != 999
    median_bill = int(trades.loc[bill_real, "bill_proximity_raw"].median()) if bill_real.any() else 90
    trades["bill_proximity"] = trades["bill_proximity_raw"].where(bill_real, median_bill)
    print(f"  {bill_real.sum()} real, {(~bill_real).sum()} imputed (median={median_bill})")

    # 6. committee_relevance
    print("[model1/v2] Computing committee_relevance...")
    trades["committee_relevance"] = trades.apply(
        lambda r: compute_committee_relevance(r["politician_id"], r["sector"], memberships),
        axis=1,
    )
    cr_nonzero = (trades["committee_relevance"] > 0).sum()
    print(f"  {cr_nonzero}/{n} non-zero")

    # 7. amount_zscore
    print("[model1/v2] Computing amount_zscore...")
    trades = trades.merge(amount_stats, on="politician_id", how="left")
    trades["log_amt"] = np.log(trades["amount_midpoint"].fillna(8000) + 1)
    has_stats = trades["log_amt_std"].notna() & (trades["log_amt_std"] > 0)
    trades["amount_zscore"] = 0.0
    trades.loc[has_stats, "amount_zscore"] = (
        (trades.loc[has_stats, "log_amt"] - trades.loc[has_stats, "log_amt_mean"])
        / trades.loc[has_stats, "log_amt_std"]
    )
    print(f"  {(trades['amount_zscore'].abs() > 0.01).sum()}/{n} non-zero")

    # 8. cluster_score
    print("[model1/v2] Computing cluster_score...")
    trades = trades.merge(
        cluster_df.rename(columns={"cluster_count": "cluster_score"}),
        on="trade_id", how="left",
    )
    trades["cluster_score"] = trades["cluster_score"].fillna(0).astype(int)
    print(f"  {(trades['cluster_score'] > 0).sum()}/{n} non-zero")

    # 9. disclosure_lag (log1p)
    trades["disclosure_lag"] = np.log1p(trades["disclosure_lag_days"].fillna(0).clip(0, 365))

    # Drop rows without price data
    before = len(trades)
    trades = trades.dropna(subset=["cohort_alpha"])
    print(f"\n[model1/v2] {before - len(trades)} dropped (missing prices). {len(trades)} remain.")

    # Save
    out = trades[["trade_id", "politician_id", "ticker", "trade_date",
                   "industry_sector"] + FEATURES]
    out_path = ROOT / "data" / "features" / "model1_v2_features.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"[model1/v2] Saved {out_path} ({len(out)} rows)")

    print(f"\n[model1/v2] Feature summary:")
    print(out[FEATURES].describe().round(4).to_string())
    return out


if __name__ == "__main__":
    build_feature_matrix()
