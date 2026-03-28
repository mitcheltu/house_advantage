"""Compare V1 vs V2 scoring results."""
import pandas as pd
import numpy as np
import pymysql

v1 = pd.read_csv("data/v1_scores_backup.csv")
total = len(v1)

print("=" * 60)
print("  V1 vs V2 SCORING COMPARISON")
print("=" * 60)

# --- Quadrant Distribution ---
print("\n--- Quadrant Distribution ---")
header = "{:<18} {:>8} {:>7}  {:>8} {:>7}  {:>8}".format(
    "Quadrant", "V1", "V1%", "V2", "V2%", "Change"
)
print(header)
print("-" * 60)

v1_quads = v1["severity_quadrant"].value_counts()

conn = pymysql.connect(
    host="localhost", port=3307, user="root",
    password="changeme", database="house_advantage"
)
v2_db = pd.read_sql(
    """SELECT a.trade_id, a.politician_id, a.ticker, a.trade_date,
              a.cohort_index, a.baseline_index, a.severity_quadrant,
              a.audit_triggered,
              a.feat_pre_trade_alpha, a.feat_bill_proximity,
              a.feat_amount_zscore, a.feat_cluster_score,
              a.feat_disclosure_lag,
              p.full_name
       FROM anomaly_scores a
       LEFT JOIN politicians p ON a.politician_id = p.id""",
    conn,
)
conn.close()

v2_quads = v2_db["severity_quadrant"].value_counts()

for q in ["SEVERE", "SYSTEMIC", "OUTLIER", "UNREMARKABLE"]:
    v1c = v1_quads.get(q, 0)
    v2c = v2_quads.get(q, 0)
    v1p = v1c / total * 100
    v2p = v2c / total * 100
    row = "{:<18} {:>8} {:>6.1f}%  {:>8} {:>6.1f}%  {:>+8}".format(
        q, v1c, v1p, v2c, v2p, v2c - v1c
    )
    print(row)

v1_audit = int(v1["audit_triggered"].sum())
v2_audit = int(v2_db["audit_triggered"].sum())
row = "{:<18} {:>8} {:>6.1f}%  {:>8} {:>6.1f}%  {:>+8}".format(
    "Audit triggered", v1_audit, v1_audit / total * 100,
    v2_audit, v2_audit / total * 100, v2_audit - v1_audit
)
print(row)

# --- Per-trade comparison ---
merged = v1.merge(v2_db, on="trade_id", suffixes=("_v1", "_v2"))
print("\nMatched trades: {}".format(len(merged)))

changed = merged[merged["severity_quadrant_v1"] != merged["severity_quadrant_v2"]]
print("Trades that changed quadrant: {} ({:.1f}%)".format(
    len(changed), len(changed) / len(merged) * 100
))

# --- Transition Matrix ---
print("\n--- Quadrant Transition Matrix (rows=V1, cols=V2) ---")
trans = pd.crosstab(
    merged["severity_quadrant_v1"], merged["severity_quadrant_v2"], margins=True
)
print(trans.to_string())

# --- Score Distributions ---
print("\n--- Score Distributions ---")
for col in ["cohort_index", "baseline_index"]:
    c1 = col + "_v1"
    c2 = col + "_v2"
    print("{}:".format(col))
    print("  V1: mean={:.1f}, median={:.0f}, std={:.1f}, max={}".format(
        merged[c1].mean(), merged[c1].median(), merged[c1].std(), merged[c1].max()
    ))
    print("  V2: mean={:.1f}, median={:.0f}, std={:.1f}, max={}".format(
        merged[c2].mean(), merged[c2].median(), merged[c2].std(), merged[c2].max()
    ))

# --- Disclosure lag dominance check ---
print("\n--- Disclosure Lag Dominance Check ---")
# V1: trades with disclosure_lag > 90 days had 83.4% anomaly rate
# Check V2: what % of SEVERE/SYSTEMIC/OUTLIER trades have high disclosure lag
v2_flagged = v2_db[v2_db["severity_quadrant"] != "UNREMARKABLE"]
v2_unflagged = v2_db[v2_db["severity_quadrant"] == "UNREMARKABLE"]
if "feat_disclosure_lag" in v2_db.columns and v2_db["feat_disclosure_lag"].notna().any():
    flagged_lag = v2_flagged["feat_disclosure_lag"].mean()
    unflagged_lag = v2_unflagged["feat_disclosure_lag"].mean()
    print("  Mean log1p(disclosure_lag) for flagged trades: {:.2f}".format(flagged_lag))
    print("  Mean log1p(disclosure_lag) for unflagged trades: {:.2f}".format(unflagged_lag))
    print("  Ratio: {:.2f}x".format(flagged_lag / unflagged_lag if unflagged_lag > 0 else float("inf")))

# --- Known politicians of interest ---
print("\n--- Known Politicians Spot Check ---")
known = ["Gottheimer", "Tuberville", "Wasserman Schultz", "Greene", "Britt", "Pelosi"]
for name in known:
    mask_v1 = v1["ticker"].notna()  # placeholder
    # Use merged with politician names from v2
    prows = merged[merged["full_name"].str.contains(name, case=False, na=False)]
    if len(prows) == 0:
        print("  {}: No trades found".format(name))
        continue
    v1_severe = (prows["severity_quadrant_v1"].isin(["SEVERE", "SYSTEMIC", "OUTLIER"])).sum()
    v2_severe = (prows["severity_quadrant_v2"].isin(["SEVERE", "SYSTEMIC", "OUTLIER"])).sum()
    v1_mean_c = prows["cohort_index_v1"].mean()
    v2_mean_c = prows["cohort_index_v2"].mean()
    v1_mean_b = prows["baseline_index_v1"].mean()
    v2_mean_b = prows["baseline_index_v2"].mean()
    print("  {} ({} trades):".format(name, len(prows)))
    print("    V1: {} flagged, cohort_avg={:.1f}, baseline_avg={:.1f}".format(
        v1_severe, v1_mean_c, v1_mean_b
    ))
    print("    V2: {} flagged, cohort_avg={:.1f}, baseline_avg={:.1f}".format(
        v2_severe, v2_mean_c, v2_mean_b
    ))

# --- Top V2 anomalous trades ---
print("\n--- Top 20 Most Anomalous Trades (V2) ---")
v2_db["combined_score"] = v2_db["cohort_index"] + v2_db["baseline_index"]
top20 = v2_db.nlargest(20, "combined_score")
for _, r in top20.iterrows():
    print("  {} | {} | {} | cohort={} baseline={} | {}".format(
        r["full_name"] or "Unknown",
        r["ticker"],
        str(r["trade_date"])[:10],
        r["cohort_index"],
        r["baseline_index"],
        r["severity_quadrant"],
    ))

# --- Trades that moved to SEVERE in V2 ---
print("\n--- Trades that became SEVERE in V2 (weren't in V1) ---")
new_severe = changed[
    (changed["severity_quadrant_v2"] == "SEVERE") &
    (changed["severity_quadrant_v1"] != "SEVERE")
]
for _, r in new_severe.iterrows():
    print("  {} | {} | {} | V1={} -> V2=SEVERE | cohort {}->{}  baseline {}->{}".format(
        r.get("full_name", "?"),
        r["ticker_v2"],
        str(r["trade_date_v2"])[:10],
        r["severity_quadrant_v1"],
        r["cohort_index_v1"], r["cohort_index_v2"],
        r["baseline_index_v1"], r["baseline_index_v2"],
    ))

print("\n" + "=" * 60)
print("  COMPARISON COMPLETE")
print("=" * 60)
