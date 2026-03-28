"""
Step 1e: Build the 5-feature matrix for Model 1 (Cohort Model).

Features:
  1. cohort_alpha        — 30-day forward return minus SPY return
  2. proximity_days      — days to nearest vote (sector-matched preferred); median-imputed
  3. has_proximity_data  — 1 if real vote data, 0 if median-imputed
  4. committee_relevance — 0.0–1.0 committee oversight score (multi-sector aware)
  5. disclosure_lag      — days from trade to STOCK Act filing

Input:  data/cleaned/congressional_trades_clean.csv + supporting CSVs
Output: data/features/model1_features.csv
"""
import json
import numpy as np
import pandas as pd
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend" / "data" / "raw"

FEATURES = [
    "cohort_alpha", "proximity_days", "has_proximity_data",
    "committee_relevance", "disclosure_lag",
]

# ── Ticker → sector map ──────────────────────────────────────────────────────
TICKER_SECTOR_MAP = json.loads((DATA / "_combined_sector_map.json").read_text())

# ── Multi-sector committee map ────────────────────────────────────────────────
COMMITTEE_SECTORS = {
    "House Committee on Agriculture":                                        ["agriculture"],
    "House Committee on Armed Services":                                     ["defense"],
    "House Committee on Energy and Commerce":                                ["energy", "healthcare", "tech", "telecom"],
    "House Committee on Financial Services":                                 ["finance"],
    "Senate Committee on Agriculture, Nutrition, and Forestry":              ["agriculture"],
    "Senate Committee on Armed Services":                                    ["defense"],
    "Senate Committee on Banking, Housing, and Urban Affairs":               ["finance"],
    "Senate Committee on Commerce, Science, and Transportation":             ["tech", "telecom"],
    "Senate Committee on Energy and Natural Resources":                      ["energy"],
    "Senate Committee on Finance":                                           ["finance", "healthcare"],
    "Senate Committee on Health, Education, Labor, and Pensions":            ["healthcare"],
    "House Committee on Science, Space, and Technology":                     ["tech"],
    "House Committee on Natural Resources":                                  ["energy", "agriculture"],
    "House Committee on Transportation and Infrastructure":                  ["defense"],
    "Senate Committee on Environment and Public Works":                      ["energy"],
    "House Committee on Veterans' Affairs":                                  ["healthcare"],
    "Senate Committee on Veterans' Affairs":                                 ["healthcare"],
    "House Committee on Ways and Means":                                     ["finance", "healthcare"],
    "House Committee on Education and the Workforce":                        ["healthcare"],
    "House Committee on Homeland Security":                                  ["defense", "tech"],
    "Senate Committee on Homeland Security and Governmental Affairs":        ["defense", "tech"],
}

CROSS_CUTTING = {
    "House Permanent Select Committee on Intelligence":  {"defense": 0.5, "tech": 0.5},
    "Senate Select Committee on Intelligence":           {"defense": 0.5, "tech": 0.5},
    "House Committee on Appropriations":                 {s: 0.4 for s in ["defense", "finance", "healthcare", "energy", "tech", "agriculture", "telecom"]},
    "Senate Committee on Appropriations":                {s: 0.4 for s in ["defense", "finance", "healthcare", "energy", "tech", "agriculture", "telecom"]},
}


# ── Price helpers ─────────────────────────────────────────────────────────────
def load_price_cache() -> dict:
    """Load all price CSVs. Handles both 'Date'/'Close' and 'date'/'close' columns."""
    cache = {}
    for f in (DATA / "prices").glob("*.csv"):
        if f.name.startswith("_"):
            continue
        df = pd.read_csv(f)
        # Normalise column names to lowercase
        df.columns = [c.lower() for c in df.columns]
        if "date" not in df.columns:
            continue
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
        cache[f.stem.upper()] = df.sort_values("date").reset_index(drop=True)
    return cache


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


# ── Proximity ─────────────────────────────────────────────────────────────────
def compute_proximity_days(row: pd.Series, votes: pd.DataFrame) -> int:
    trade_date = row["trade_date"]
    pid = row.get("politician_id")
    sector = row.get("industry_sector")

    if sector and pid:
        # Normalise sector to list for multi-sector tickers
        sectors = sector if isinstance(sector, list) else [sector]
        relevant = votes[
            (votes["member_id"] == pid) &
            (votes["related_sector"].isin(sectors))
        ]
        if not relevant.empty:
            deltas = (relevant["vote_date"] - trade_date).abs().dt.days
            min_d = deltas.min()
            if min_d <= 90:
                return int(min_d)

    if pid:
        any_votes = votes[votes["member_id"] == pid]
        if not any_votes.empty:
            deltas = (any_votes["vote_date"] - trade_date).abs().dt.days
            min_d = deltas.min()
            if min_d <= 90:
                return int(min_d)

    return 999


# ── Committee relevance ───────────────────────────────────────────────────────
def compute_committee_relevance(row: pd.Series, memberships: pd.DataFrame) -> float:
    raw_sector = row.get("industry_sector")
    pid = row.get("politician_id")
    if not raw_sector or not pid:
        return 0.0

    sectors = raw_sector if isinstance(raw_sector, list) else [raw_sector]

    pol_memberships = memberships[memberships["politician_id"] == pid]
    if pol_memberships.empty:
        return 0.0

    best = 0.0
    for _, m in pol_memberships.iterrows():
        cname = str(m.get("committee_name", ""))
        rank = str(m.get("rank_in_committee", "")).lower()

        for sector in sectors:
            if cname in CROSS_CUTTING:
                weight = CROSS_CUTTING[cname].get(sector, 0.0)
                if weight > 0 and ("chair" in rank or "ranking" in rank):
                    weight = min(weight * 1.3, 1.0)
                best = max(best, weight)
                continue

            if cname in COMMITTEE_SECTORS:
                if sector in COMMITTEE_SECTORS[cname]:
                    if "chair" in rank or "ranking" in rank:
                        weight = 1.0
                    else:
                        weight = 0.7
                    best = max(best, weight)

    return round(best, 2)


# ── Name resolution ──────────────────────────────────────────────────────────
def _build_name_resolver(politicians: pd.DataFrame) -> callable:
    name_to_bio = {}
    last_to_bio = {}

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
                last_to_bio[last] = None

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

    def resolve(name):
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

    return resolve


# ── Main ──────────────────────────────────────────────────────────────────────
def build_feature_matrix() -> pd.DataFrame:
    trades = pd.read_csv(
        ROOT / "data" / "cleaned" / "congressional_trades_clean.csv",
        parse_dates=["trade_date"],
    )
    votes_raw = pd.read_csv(DATA / "votes_raw.csv")
    pv_house = pd.read_csv(DATA / "politician_votes_raw.csv")
    pv_senate = pd.read_csv(DATA / "senate_politician_votes_raw.csv")
    committees = pd.read_csv(DATA / "committee_memberships_raw.csv")
    politicians = pd.read_csv(DATA / "politicians_raw.csv")
    cache = load_price_cache()

    print(f"[model1/features] Loaded {len(cache)} price files, "
          f"{len(trades)} trades, {len(committees)} committee memberships")

    # ── Resolve names → bioguide IDs ─────────────────────────────────────────
    resolve = _build_name_resolver(politicians)
    trades["bioguide_id"] = trades["politician_id"].apply(resolve)
    resolved = trades["bioguide_id"].notna().sum()
    print(f"[model1/features] Resolved {resolved}/{len(trades)} politician names "
          f"to bioguide IDs ({resolved/len(trades)*100:.1f}%)")

    # ── Build vote lookup ────────────────────────────────────────────────────
    pv = pd.concat([
        pv_house[["politician_id", "vote_id"]],
        pv_senate[["politician_id", "vote_id"]],
    ], ignore_index=True)
    pv = pv.merge(
        votes_raw[["id", "vote_date", "related_sector"]],
        left_on="vote_id", right_on="id", how="left",
    )
    pv["vote_date"] = pd.to_datetime(
        pv["vote_date"], format="mixed", dayfirst=False, utc=True
    ).dt.tz_localize(None)
    pv = pv.rename(columns={"politician_id": "member_id"})

    # ── Assign sector tags ───────────────────────────────────────────────────
    trades["industry_sector"] = trades["ticker"].map(TICKER_SECTOR_MAP)

    # ── Compute features ─────────────────────────────────────────────────────
    n = len(trades)
    print(f"[model1/features] Computing features for {n} trades...")

    trades["cohort_alpha"] = trades.apply(
        lambda r: compute_cohort_alpha(r["ticker"], r["trade_date"], cache), axis=1
    )
    print(f"[model1/features] cohort_alpha done — "
          f"{trades['cohort_alpha'].notna().sum()}/{n} computed")

    trades["proximity_days"] = trades.apply(
        lambda r: compute_proximity_days(
            pd.Series({
                "politician_id": r["bioguide_id"],
                "industry_sector": r["industry_sector"],
                "trade_date": r["trade_date"],
            }), pv,
        ), axis=1,
    )

    trades["committee_relevance"] = trades.apply(
        lambda r: compute_committee_relevance(
            pd.Series({
                "politician_id": r["bioguide_id"],
                "industry_sector": r["industry_sector"],
            }), committees,
        ), axis=1,
    )

    trades["disclosure_lag"] = trades["disclosure_lag_days"].fillna(0).clip(0, 365).astype(int)

    # ── Drop rows without price data ─────────────────────────────────────────
    before = len(trades)
    trades = trades.dropna(subset=["cohort_alpha"])
    trades["proximity_days"] = trades["proximity_days"].fillna(999).astype(int)

    # ── Median imputation for proximity_days ─────────────────────────────────
    real_mask = trades["proximity_days"] != 999
    trades["has_proximity_data"] = real_mask.astype(int)
    if real_mask.any():
        median_proximity = int(trades.loc[real_mask, "proximity_days"].median())
    else:
        median_proximity = 7
    trades.loc[~real_mask, "proximity_days"] = median_proximity

    print(f"[model1/features] proximity_days: {real_mask.sum()} real, "
          f"{(~real_mask).sum()} imputed with median={median_proximity}")
    print(f"[model1/features] {before - len(trades)} dropped (missing prices). "
          f"{len(trades)} remain.")

    # ── Save ─────────────────────────────────────────────────────────────────
    out = trades[["politician_id", "ticker", "trade_date", "trade_type",
                   "industry_sector"] + FEATURES]
    out_path = ROOT / "data" / "features" / "model1_features.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"[model1/features] Saved {out_path} ({len(out)} rows)")

    # ── Summary stats ────────────────────────────────────────────────────────
    print(f"\n[model1/features] Feature summary:")
    print(out[FEATURES].describe().round(4).to_string())
    return out


if __name__ == "__main__":
    build_feature_matrix()
