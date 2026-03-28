"""
Dual Scorer — scores all congressional trades with both Cohort and Baseline models.

Computes 5 features from DB data, runs both IsolationForest pipelines,
assigns severity quadrants, and writes results to the anomaly_scores table.

Usage:
    python backend/scoring/dual_scorer.py          # score all unscored trades
    python backend/scoring/dual_scorer.py --all    # re-score everything
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pymysql

ROOT = Path(__file__).resolve().parents[2]

# ── DB connection ─────────────────────────────────────────────────────────────
DB_CFG = dict(host="localhost", port=3307, user="root",
              password="changeme", database="house_advantage")

FEATURES = [
    "cohort_alpha", "proximity_days", "has_proximity_data",
    "committee_relevance", "disclosure_lag",
]

# ── Sector map for tickers ────────────────────────────────────────────────────
TICKER_SECTOR_MAP = json.loads(
    (ROOT / "backend" / "data" / "raw" / "_combined_sector_map.json").read_text()
)

# ── Committee → sector mapping (uses DB committee names, not Congress.gov names)
# We match on keywords within committee names to their sector tags.
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


def normalize(raw: np.ndarray) -> np.ndarray:
    """Convert IsolationForest decision_function to 0–100 index."""
    return ((-np.clip(raw, -0.5, 0.5) + 0.5) * 100).astype(int).clip(0, 100)


def assign_quadrant(cohort_idx: int, baseline_idx: int) -> str:
    HIGH = 60
    if cohort_idx >= HIGH and baseline_idx >= HIGH:
        return "SEVERE"
    elif cohort_idx < HIGH and baseline_idx >= HIGH:
        return "SYSTEMIC"
    elif cohort_idx >= HIGH and baseline_idx < HIGH:
        return "OUTLIER"
    else:
        return "UNREMARKABLE"


# ── Load data from DB ─────────────────────────────────────────────────────────

def load_trades(conn, only_unscored: bool = True) -> pd.DataFrame:
    """Load trades (optionally only those without scores)."""
    sql = """
        SELECT t.id AS trade_id, t.politician_id, t.ticker, t.trade_date,
               t.disclosure_date, t.disclosure_lag_days, t.industry_sector
        FROM trades t
    """
    if only_unscored:
        sql += " LEFT JOIN anomaly_scores a ON t.id = a.trade_id WHERE a.id IS NULL"
    return pd.read_sql(sql, conn, parse_dates=["trade_date", "disclosure_date"])


def load_price_cache(conn) -> dict[str, pd.DataFrame]:
    """Load stock prices into a ticker→DataFrame dict for fast lookup."""
    df = pd.read_sql(
        "SELECT ticker, price_date AS date, close FROM stock_prices",
        conn, parse_dates=["date"],
    )
    cache = {}
    for ticker, grp in df.groupby("ticker"):
        cache[ticker.upper()] = grp.sort_values("date").reset_index(drop=True)
    return cache


def load_committee_memberships(conn) -> pd.DataFrame:
    """Load committee memberships with committee name and sector_tag."""
    return pd.read_sql("""
        SELECT cm.politician_id, c.name AS committee_name,
               cm.role, c.sector_tag
        FROM committee_memberships cm
        JOIN committees c ON cm.committee_id = c.id
    """, conn)


def load_vote_lookup(conn) -> pd.DataFrame:
    """Load politician→vote_date mapping for proximity computation."""
    return pd.read_sql("""
        SELECT pv.politician_id, v.vote_date
        FROM politician_votes pv
        JOIN votes v ON pv.vote_id = v.id
        WHERE v.vote_date IS NOT NULL
    """, conn, parse_dates=["vote_date"])


# ── Feature computation ───────────────────────────────────────────────────────

def get_price(ticker: str, date: pd.Timestamp, cache: dict):
    df = cache.get(ticker)
    if df is None:
        return None
    subset = df[df["date"] >= date]
    return float(subset.iloc[0]["close"]) if not subset.empty else None


def compute_cohort_alpha(ticker: str, trade_date: pd.Timestamp, cache: dict) -> float:
    p0 = get_price(ticker, trade_date, cache)
    p1 = get_price(ticker, trade_date + timedelta(days=30), cache)
    s0 = get_price("SPY", trade_date, cache)
    s1 = get_price("SPY", trade_date + timedelta(days=30), cache)
    if None in (p0, p1, s0, s1) or p0 == 0 or s0 == 0:
        return np.nan
    return (p1 - p0) / p0 - (s1 - s0) / s0


def compute_proximity_days(politician_id: int, trade_date: pd.Timestamp,
                           sector: str, votes_df: pd.DataFrame) -> int:
    """Days to nearest vote (sector-matched first, then any)."""
    if politician_id is None:
        return 999

    pol_votes = votes_df[votes_df["politician_id"] == politician_id]
    if pol_votes.empty:
        return 999

    deltas = (pol_votes["vote_date"] - trade_date).abs().dt.days
    min_d = deltas.min()
    return int(min_d) if min_d <= 90 else 999


def _committee_sectors(committee_name: str) -> list[str]:
    """Derive sectors from a committee name via keyword matching."""
    name_lower = committee_name.lower()
    for kw, sector_map in CROSS_CUTTING_KEYWORDS.items():
        if kw in name_lower:
            return list(sector_map.keys())
    for kw, sectors in COMMITTEE_KEYWORD_SECTORS.items():
        if kw in name_lower:
            return sectors
    return []


def compute_committee_relevance(politician_id: int, trade_sector,
                                memberships: pd.DataFrame) -> float:
    """0.0–1.0 score based on committee oversight of the traded sector."""
    if not trade_sector or politician_id is None:
        return 0.0

    sectors = trade_sector if isinstance(trade_sector, list) else [trade_sector]
    pol_m = memberships[memberships["politician_id"] == politician_id]
    if pol_m.empty:
        return 0.0

    best = 0.0
    for _, m in pol_m.iterrows():
        cname = str(m["committee_name"])
        role = str(m.get("role", "")).lower()
        cname_lower = cname.lower()

        for sector in sectors:
            # Check cross-cutting first
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

            # Check keyword-based sector matching
            for kw, kw_sectors in COMMITTEE_KEYWORD_SECTORS.items():
                if kw in cname_lower and sector in kw_sectors:
                    weight = 1.0 if ("chair" in role or "ranking" in role) else 0.7
                    best = max(best, weight)
                    break

            # Also use the sector_tag from the DB if available
            db_sector = m.get("sector_tag")
            if db_sector and db_sector == sector:
                weight = 1.0 if ("chair" in role or "ranking" in role) else 0.7
                best = max(best, weight)

    return round(best, 2)


def build_features(trades: pd.DataFrame, price_cache: dict,
                   memberships: pd.DataFrame, votes: pd.DataFrame) -> pd.DataFrame:
    """Compute all 5 features for a batch of trades."""
    n = len(trades)

    # Resolve sector from ticker map (prefer DB industry_sector, fallback to JSON map)
    trades = trades.copy()
    trades["sector"] = trades.apply(
        lambda r: r["industry_sector"] if pd.notna(r["industry_sector"])
        else TICKER_SECTOR_MAP.get(r["ticker"]), axis=1
    )

    # 1. cohort_alpha
    print(f"  Computing cohort_alpha for {n} trades...")
    trades["cohort_alpha"] = trades.apply(
        lambda r: compute_cohort_alpha(r["ticker"], r["trade_date"], price_cache),
        axis=1,
    )
    alpha_ok = trades["cohort_alpha"].notna().sum()
    print(f"  cohort_alpha: {alpha_ok}/{n} computed ({n - alpha_ok} missing prices)")

    # 2/3. proximity_days + has_proximity_data
    print("  Computing proximity_days...")
    trades["proximity_days_raw"] = trades.apply(
        lambda r: compute_proximity_days(
            r["politician_id"], r["trade_date"], r["sector"], votes
        ), axis=1,
    )
    real_mask = trades["proximity_days_raw"] != 999
    trades["has_proximity_data"] = real_mask.astype(int)
    median_prox = int(trades.loc[real_mask, "proximity_days_raw"].median()) if real_mask.any() else 7
    trades["proximity_days"] = trades["proximity_days_raw"].where(real_mask, median_prox)
    print(f"  proximity_days: {real_mask.sum()} real, {(~real_mask).sum()} imputed (median={median_prox})")

    # 4. committee_relevance
    print("  Computing committee_relevance...")
    trades["committee_relevance"] = trades.apply(
        lambda r: compute_committee_relevance(
            r["politician_id"], r["sector"], memberships
        ), axis=1,
    )
    cr_nonzero = (trades["committee_relevance"] > 0).sum()
    print(f"  committee_relevance: {cr_nonzero}/{n} non-zero ({cr_nonzero/n*100:.1f}%)")

    # 5. disclosure_lag
    trades["disclosure_lag"] = trades["disclosure_lag_days"].fillna(0).clip(0, 365).astype(int)

    return trades


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_and_store(rescore_all: bool = False):
    """Main entry point: compute features, score with both models, write to DB."""

    # Load models
    cohort_model = joblib.load(ROOT / "model" / "cohort_model.pkl")
    baseline_model = joblib.load(ROOT / "model" / "baseline_model.pkl")

    cohort_meta = json.loads((ROOT / "model" / "cohort_model_metadata.json").read_text())
    baseline_meta = json.loads((ROOT / "model" / "baseline_model_metadata.json").read_text())
    model_version = f"cohort_{cohort_meta['trained_at'][:10]}_baseline_{baseline_meta['trained_at'][:10]}"

    conn = pymysql.connect(**DB_CFG)

    try:
        # Load supporting data
        print("[dual_scorer] Loading data from DB...")
        trades = load_trades(conn, only_unscored=not rescore_all)
        if trades.empty:
            print("[dual_scorer] No trades to score.")
            return

        print(f"[dual_scorer] {len(trades)} trades to score")
        price_cache = load_price_cache(conn)
        print(f"[dual_scorer] Loaded prices for {len(price_cache)} tickers")
        memberships = load_committee_memberships(conn)
        print(f"[dual_scorer] Loaded {len(memberships)} committee memberships")
        votes = load_vote_lookup(conn)
        print(f"[dual_scorer] Loaded {len(votes)} vote records")

        # Build features
        print("\n[dual_scorer] Computing features...")
        trades = build_features(trades, price_cache, memberships, votes)

        # Drop trades without cohort_alpha (no price data)
        before = len(trades)
        scoreable = trades.dropna(subset=["cohort_alpha"]).copy()
        dropped = before - len(scoreable)
        print(f"\n[dual_scorer] {dropped} trades dropped (missing prices). "
              f"{len(scoreable)} scoreable.")

        if scoreable.empty:
            print("[dual_scorer] No scoreable trades.")
            return

        # Score with both models
        X = scoreable[FEATURES].values
        print("[dual_scorer] Scoring with Cohort model...")
        cohort_scaler = cohort_model.named_steps["scaler"]
        cohort_iforest = cohort_model.named_steps["iforest"]
        cohort_raw = cohort_iforest.decision_function(cohort_scaler.transform(X))
        cohort_labels = cohort_iforest.predict(cohort_scaler.transform(X))
        cohort_idx = normalize(cohort_raw)

        print("[dual_scorer] Scoring with Baseline model...")
        baseline_scaler = baseline_model.named_steps["scaler"]
        baseline_iforest = baseline_model.named_steps["iforest"]
        baseline_raw = baseline_iforest.decision_function(baseline_scaler.transform(X))
        baseline_labels = baseline_iforest.predict(baseline_scaler.transform(X))
        baseline_idx = normalize(baseline_raw)

        # Assign quadrants
        quadrants = [assign_quadrant(int(c), int(b))
                     for c, b in zip(cohort_idx, baseline_idx)]
        audit_flags = [(int(c) >= 70 or int(b) >= 70)
                       for c, b in zip(cohort_idx, baseline_idx)]

        # Print summary
        from collections import Counter
        qcounts = Counter(quadrants)
        print(f"\n[dual_scorer] Quadrant distribution:")
        for q in ["SEVERE", "SYSTEMIC", "OUTLIER", "UNREMARKABLE"]:
            pct = qcounts.get(q, 0) / len(scoreable) * 100
            print(f"  {q}: {qcounts.get(q, 0)} ({pct:.1f}%)")
        print(f"  Audit triggered: {sum(audit_flags)} ({sum(audit_flags)/len(scoreable)*100:.1f}%)")
        print(f"  Cohort index: mean={cohort_idx.mean():.1f}, "
              f"median={np.median(cohort_idx):.0f}, max={cohort_idx.max()}")
        print(f"  Baseline index: mean={baseline_idx.mean():.1f}, "
              f"median={np.median(baseline_idx):.0f}, max={baseline_idx.max()}")

        # Write to DB
        print(f"\n[dual_scorer] Writing {len(scoreable)} scores to anomaly_scores...")

        if rescore_all:
            cur = conn.cursor()
            cur.execute("DELETE FROM audit_reports")
            cur.execute("DELETE FROM anomaly_scores")
            conn.commit()

        insert_sql = """
            INSERT INTO anomaly_scores (
                trade_id, politician_id, ticker, trade_date,
                cohort_raw_score, cohort_label, cohort_index,
                baseline_raw_score, baseline_label, baseline_index,
                severity_quadrant, audit_triggered,
                feat_cohort_alpha, feat_proximity_days, feat_has_proximity_data,
                feat_committee_relevance, feat_disclosure_lag,
                model_version
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s
            )
        """

        rows = []
        for i, (_, row) in enumerate(scoreable.iterrows()):
            rows.append((
                int(row["trade_id"]),
                int(row["politician_id"]) if pd.notna(row["politician_id"]) else None,
                row["ticker"],
                row["trade_date"].date() if hasattr(row["trade_date"], "date") else row["trade_date"],
                float(cohort_raw[i]),
                int(cohort_labels[i]),
                int(cohort_idx[i]),
                float(baseline_raw[i]),
                int(baseline_labels[i]),
                int(baseline_idx[i]),
                quadrants[i],
                bool(audit_flags[i]),
                float(row["cohort_alpha"]),
                int(row["proximity_days"]),
                int(row["has_proximity_data"]),
                float(row["committee_relevance"]),
                int(row["disclosure_lag"]),
                model_version,
            ))

        cur = conn.cursor()
        batch_size = 500
        for j in range(0, len(rows), batch_size):
            cur.executemany(insert_sql, rows[j:j + batch_size])
            conn.commit()
            if (j // batch_size) % 5 == 0:
                print(f"  Inserted {min(j + batch_size, len(rows))}/{len(rows)}...")

        print(f"\n[dual_scorer] Done. {len(rows)} scores written to anomaly_scores.")

    finally:
        conn.close()


if __name__ == "__main__":
    rescore = "--all" in sys.argv
    score_and_store(rescore_all=rescore)
