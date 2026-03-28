"""Quantify the impact of multi-sector ticker mapping on committee_relevance."""
import json, pandas as pd
from collections import defaultdict

m = json.load(open("backend/data/raw/_combined_sector_map.json"))
trades = pd.read_csv("backend/data/raw/congressional_trades_raw.csv")
memberships = pd.read_csv("backend/data/raw/committee_memberships_raw.csv")
politicians = pd.read_csv("backend/data/raw/politicians_raw.csv")

# ── Build name resolver ──
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
    clean = " ".join(
        clean.replace(" mrs ", " ").replace(" mr ", " ").replace(" dr ", " ").split()
    )
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


trades["bioguide_id"] = trades["politician_id"].apply(resolve)
trades["industry_sector"] = trades["ticker"].map(m)

# ── Committee maps ──
COMMITTEE_SECTORS = {
    "House Committee on Agriculture": ["agriculture"],
    "House Committee on Armed Services": ["defense"],
    "House Committee on Energy and Commerce": ["energy", "healthcare", "tech", "telecom"],
    "House Committee on Financial Services": ["finance"],
    "Senate Committee on Agriculture, Nutrition, and Forestry": ["agriculture"],
    "Senate Committee on Armed Services": ["defense"],
    "Senate Committee on Banking, Housing, and Urban Affairs": ["finance"],
    "Senate Committee on Commerce, Science, and Transportation": ["tech", "telecom"],
    "Senate Committee on Energy and Natural Resources": ["energy"],
    "Senate Committee on Finance": ["finance", "healthcare"],
    "Senate Committee on Health, Education, Labor, and Pensions": ["healthcare"],
    "House Committee on Science, Space, and Technology": ["tech"],
    "House Committee on Natural Resources": ["energy", "agriculture"],
    "House Committee on Transportation and Infrastructure": ["defense"],
    "Senate Committee on Environment and Public Works": ["energy"],
    "House Committee on Veterans' Affairs": ["healthcare"],
    "Senate Committee on Veterans' Affairs": ["healthcare"],
    "House Committee on Ways and Means": ["finance", "healthcare"],
    "House Committee on Education and the Workforce": ["healthcare"],
    "House Committee on Homeland Security": ["defense", "tech"],
    "Senate Committee on Homeland Security and Governmental Affairs": ["defense", "tech"],
}
CROSS_CUTTING = {
    "House Permanent Select Committee on Intelligence": {"defense": 0.5, "tech": 0.5},
    "Senate Select Committee on Intelligence": {"defense": 0.5, "tech": 0.5},
    "House Committee on Appropriations": {
        s: 0.4
        for s in ["defense", "finance", "healthcare", "energy", "tech", "agriculture", "telecom"]
    },
    "Senate Committee on Appropriations": {
        s: 0.4
        for s in ["defense", "finance", "healthcare", "energy", "tech", "agriculture", "telecom"]
    },
}

# Build pol_access: bioguide → {sector: max_weight}
pol_access = defaultdict(lambda: defaultdict(float))
for _, row in memberships.iterrows():
    pid = row["politician_id"]
    cname = str(row.get("committee_name", ""))
    rank = str(row.get("rank_in_committee", "")).lower()
    if cname in CROSS_CUTTING:
        for sec, w in CROSS_CUTTING[cname].items():
            weight = w
            if "chair" in rank or "ranking" in rank:
                weight = min(w * 1.3, 1.0)
            pol_access[pid][sec] = max(pol_access[pid][sec], weight)
    elif cname in COMMITTEE_SECTORS:
        for sec in COMMITTEE_SECTORS[cname]:
            weight = 1.0 if ("chair" in rank or "ranking" in rank) else 0.7
            pol_access[pid][sec] = max(pol_access[pid][sec], weight)

# ── MULTI-SECTOR overrides ──
MULTI_SECTOR_OVERRIDES = {
    "MSFT": ["tech", "defense"],
    "AMZN": ["tech", "telecom"],
    "GOOG": ["tech", "telecom"],
    "GOOGL": ["tech", "telecom"],
    "META": ["tech", "telecom"],
    "GE": ["defense", "energy", "healthcare"],
    "HON": ["defense", "tech", "energy"],
    "MMM": ["defense", "healthcare"],
    "UNH": ["healthcare", "finance"],
    "VZ": ["telecom", "tech"],
    "T": ["telecom", "tech"],
    "CRM": ["tech", "defense"],
    "ORCL": ["tech", "defense"],
    "IBM": ["tech", "defense"],
    "INTC": ["tech", "defense"],
    "PLTR": ["tech", "defense"],
    "LHX": ["defense", "tech"],
    "CSCO": ["tech", "telecom", "defense"],
    "ACN": ["tech", "defense"],
    "ABT": ["healthcare", "tech"],
    "MDT": ["healthcare", "tech"],
    "TMO": ["healthcare", "tech"],
    "DHR": ["healthcare", "tech"],
    "SYK": ["healthcare", "tech"],
    "BDX": ["healthcare", "tech"],
    "CI": ["healthcare", "finance"],
    "HUM": ["healthcare", "finance"],
    "AIG": ["finance", "healthcare"],
    "BRK.B": ["finance", "energy", "defense"],
    "DUK": ["energy", "tech"],
    "NEE": ["energy", "tech"],
    "QCOM": ["tech", "telecom", "defense"],
    "AVGO": ["tech", "telecom"],
}


def score_single(row):
    bio = row.get("bioguide_id")
    sector = row.get("industry_sector")
    if not bio or not sector or pd.isna(bio) or pd.isna(sector):
        return 0.0
    return pol_access.get(bio, {}).get(sector, 0.0)


def score_multi(row):
    bio = row.get("bioguide_id")
    ticker = row.get("ticker")
    sectors = MULTI_SECTOR_OVERRIDES.get(ticker, None)
    if sectors is None:
        sector = row.get("industry_sector")
        if not bio or not sector or pd.isna(bio) or pd.isna(sector):
            return 0.0
        return pol_access.get(bio, {}).get(sector, 0.0)
    if not bio or pd.isna(bio):
        return 0.0
    access = pol_access.get(bio, {})
    return max((access.get(s, 0.0) for s in sectors), default=0.0)


# ── Score all trades both ways ──
trades["cr_single"] = trades.apply(score_single, axis=1)
trades["cr_multi"] = trades.apply(score_multi, axis=1)

# ── Compare ──
single_nonzero = (trades["cr_single"] > 0).sum()
multi_nonzero = (trades["cr_multi"] > 0).sum()
delta = multi_nonzero - single_nonzero
gained = ((trades["cr_multi"] > 0) & (trades["cr_single"] == 0)).sum()
improved = ((trades["cr_multi"] > trades["cr_single"]) & (trades["cr_single"] > 0)).sum()

print("=== COMMITTEE_RELEVANCE IMPACT ===")
print(
    f"Single-sector: {single_nonzero}/{len(trades)} trades with signal "
    f"({single_nonzero/len(trades)*100:.1f}%)"
)
print(
    f"Multi-sector:  {multi_nonzero}/{len(trades)} trades with signal "
    f"({multi_nonzero/len(trades)*100:.1f}%)"
)
print(f"NEW signal:    +{gained} trades gained committee_relevance > 0")
print(f"BOOSTED:       {improved} trades got a HIGHER score")
print(f"Net coverage:  +{delta} trades ({delta/len(trades)*100:.2f}% of total)")
print()

# Show which tickers gained the most
gained_mask = (trades["cr_multi"] > 0) & (trades["cr_single"] == 0)
if gained_mask.sum() > 0:
    print("Top tickers gaining NEW signal:")
    print(trades[gained_mask]["ticker"].value_counts().head(15).to_string())
    print()

# Show sample improvements
improved_mask = trades["cr_multi"] > trades["cr_single"]
if improved_mask.sum() > 0:
    sample = trades[improved_mask][
        ["politician_id", "ticker", "cr_single", "cr_multi"]
    ].head(10)
    print("Sample improved scores:")
    print(sample.to_string(index=False))
    print()

# Mean/std comparison
print(f"Mean committee_relevance (single): {trades['cr_single'].mean():.4f}")
print(f"Mean committee_relevance (multi):  {trades['cr_multi'].mean():.4f}")
print(f"Std committee_relevance (single):  {trades['cr_single'].std():.4f}")
print(f"Std committee_relevance (multi):   {trades['cr_multi'].std():.4f}")
print()

# Variance improvement matters for IsolationForest
print(f"Variance improvement: {(trades['cr_multi'].var() / trades['cr_single'].var() - 1) * 100:.1f}%")
