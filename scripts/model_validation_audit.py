"""
Model Validation Analysis — Data Science Audit
================================================
Checks whether the dual IsolationForest models produce
meaningful, defensible anomaly scores.
"""
import pymysql
import numpy as np
from collections import defaultdict

DB = dict(host="localhost", port=3307, user="root",
          password="changeme", database="house_advantage")


def q(cur, sql):
    cur.execute(sql)
    return cur.fetchall()


def main():
    c = pymysql.connect(**DB)
    cur = c.cursor()

    print("=" * 80)
    print("MODEL VALIDATION ANALYSIS")
    print("=" * 80)

    # ─────────────────────────────────────────────────────────────────────
    # 1. VOLUME BIAS CHECK
    #    Are we just flagging the most active traders?
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n1. VOLUME BIAS CHECK")
    print("-" * 60)

    # Correlation: total trades vs anomalous count
    rows = q(cur, """
        SELECT p.id, COUNT(*) AS total,
               SUM(CASE WHEN a.severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) AS anom
        FROM anomaly_scores a
        JOIN politicians p ON a.politician_id = p.id
        GROUP BY p.id
        HAVING total >= 5
    """)
    totals = np.array([r[1] for r in rows], dtype=float)
    anoms = np.array([r[2] for r in rows], dtype=float)
    corr = np.corrcoef(totals, anoms)[0, 1]
    print(f"Pearson r (total trades vs anomalous count): {corr:.3f}")

    # Better metric: anomalous RATE vs total trades
    rates = anoms / totals
    corr_rate = np.corrcoef(totals, rates)[0, 1]
    print(f"Pearson r (total trades vs anomalous RATE):  {corr_rate:.3f}")
    if abs(corr_rate) < 0.3:
        print("  → LOW volume bias — model is not just flagging active traders ✓")
    elif abs(corr_rate) < 0.5:
        print("  → MODERATE volume bias — some correlation with volume")
    else:
        print("  → HIGH volume bias — model may be proxying for trade count ✗")

    # Top 10 by anomalous RATE (min 10 trades)
    print(f"\nTop 10 by anomalous RATE (min 10 scored trades):")
    rows_rate = q(cur, """
        SELECT p.full_name, p.party, COUNT(*) AS total,
               SUM(CASE WHEN a.severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) AS anom,
               ROUND(SUM(CASE WHEN a.severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rate
        FROM anomaly_scores a
        JOIN politicians p ON a.politician_id = p.id
        GROUP BY p.id
        HAVING total >= 10
        ORDER BY rate DESC
        LIMIT 10
    """)
    for r in rows_rate:
        print(f"  {r[0]:<35} ({r[1]})  {r[3]}/{r[2]} = {r[4]}%")

    # ─────────────────────────────────────────────────────────────────────
    # 2. WHAT FEATURES DRIVE ANOMALY SCORES?
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n2. FEATURE DISTRIBUTION: ANOMALOUS vs UNREMARKABLE")
    print("-" * 60)

    for feat, col in [
        ("cohort_alpha", "feat_cohort_alpha"),
        ("proximity_days", "feat_proximity_days"),
        ("has_proximity_data", "feat_has_proximity_data"),
        ("committee_relevance", "feat_committee_relevance"),
        ("disclosure_lag", "feat_disclosure_lag"),
    ]:
        row_anom = q(cur, f"""
            SELECT ROUND(AVG({col}),4), ROUND(STD({col}),4),
                   ROUND(MIN({col}),4), ROUND(MAX({col}),4)
            FROM anomaly_scores WHERE severity_quadrant != 'UNREMARKABLE'
        """)[0]
        row_norm = q(cur, f"""
            SELECT ROUND(AVG({col}),4), ROUND(STD({col}),4),
                   ROUND(MIN({col}),4), ROUND(MAX({col}),4)
            FROM anomaly_scores WHERE severity_quadrant = 'UNREMARKABLE'
        """)[0]
        print(f"\n  {feat}:")
        print(f"    ANOMALOUS:    mean={row_anom[0]:>10}  std={row_anom[1]:>10}  range=[{row_anom[2]}, {row_anom[3]}]")
        print(f"    UNREMARKABLE: mean={row_norm[0]:>10}  std={row_norm[1]:>10}  range=[{row_norm[2]}, {row_norm[3]}]")

    # ─────────────────────────────────────────────────────────────────────
    # 3. SEVERE TRADE DEEP DIVE
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n3. ALL 40 SEVERE TRADES — DEEP DIVE")
    print("-" * 60)
    severe = q(cur, """
        SELECT a.trade_id, p.full_name, p.party, p.chamber, a.ticker,
               a.trade_date, t.trade_type, a.cohort_index, a.baseline_index,
               a.feat_cohort_alpha, a.feat_proximity_days, a.feat_has_proximity_data,
               a.feat_committee_relevance, a.feat_disclosure_lag,
               t.amount_midpoint
        FROM anomaly_scores a
        JOIN politicians p ON a.politician_id = p.id
        JOIN trades t ON a.trade_id = t.id
        WHERE a.severity_quadrant = 'SEVERE'
        ORDER BY (a.cohort_index + a.baseline_index) DESC
    """)
    print(f"{'Name':<30} {'Pty':<4} {'Ticker':<6} {'Date':<12} {'Type':<5} "
          f"{'Coh':<5} {'Base':<5} {'Alpha':<8} {'Prox':<5} {'HasP':<5} "
          f"{'CmtRel':<7} {'Lag':<5} {'Amount'}")
    print("-" * 120)
    for r in severe:
        alpha_str = f"{r[9]:.3f}" if r[9] else "N/A"
        amt = f"${r[14]:,}" if r[14] else "N/A"
        print(f"{r[1]:<30} {r[2]:<4} {r[4]:<6} {str(r[5]):<12} {r[6]:<5} "
              f"{r[7]:<5} {r[8]:<5} {alpha_str:<8} {r[10]:<5} {r[11]:<5} "
              f"{r[12]:<7} {r[13]:<5} {amt}")

    # ─────────────────────────────────────────────────────────────────────
    # 4. PARTY DISTRIBUTION — IS THE MODEL BIASED?
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n4. PARTY BIAS CHECK")
    print("-" * 60)
    party_total = q(cur, """
        SELECT p.party, COUNT(*) FROM anomaly_scores a
        JOIN politicians p ON a.politician_id = p.id
        GROUP BY p.party
    """)
    party_anom = q(cur, """
        SELECT p.party,
               SUM(CASE WHEN a.severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END),
               SUM(CASE WHEN a.severity_quadrant = 'SYSTEMIC' THEN 1 ELSE 0 END),
               SUM(CASE WHEN a.severity_quadrant = 'OUTLIER' THEN 1 ELSE 0 END),
               SUM(CASE WHEN a.severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END),
               COUNT(*)
        FROM anomaly_scores a
        JOIN politicians p ON a.politician_id = p.id
        GROUP BY p.party
    """)
    print(f"{'Party':<8} {'Total':<8} {'Anom':<8} {'Rate':<8} {'SEVERE':<8} {'SYSTEMIC':<9} {'OUTLIER'}")
    for r in party_anom:
        rate = r[4] / r[5] * 100
        print(f"{r[0]:<8} {r[5]:<8} {r[4]:<8} {rate:<7.1f}% {r[1]:<8} {r[2]:<9} {r[3]}")

    # ─────────────────────────────────────────────────────────────────────
    # 5. SECTOR DISTRIBUTION OF ANOMALIES
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n5. SECTOR DISTRIBUTION OF ANOMALIES")
    print("-" * 60)
    sector_data = q(cur, """
        SELECT t.industry_sector,
               COUNT(*) AS total,
               SUM(CASE WHEN a.severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) AS anom,
               ROUND(SUM(CASE WHEN a.severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rate,
               ROUND(AVG(a.cohort_index), 1) AS avg_coh,
               ROUND(AVG(a.baseline_index), 1) AS avg_base
        FROM anomaly_scores a
        JOIN trades t ON a.trade_id = t.id
        GROUP BY t.industry_sector
        ORDER BY rate DESC
    """)
    print(f"{'Sector':<15} {'Total':<8} {'Anom':<8} {'Rate':<8} {'AvgCoh':<8} {'AvgBase'}")
    for r in sector_data:
        s = r[0] if r[0] else "(none)"
        print(f"{s:<15} {r[1]:<8} {r[2]:<8} {r[3]:<7}% {r[4]:<8} {r[5]}")

    # ─────────────────────────────────────────────────────────────────────
    # 6. DISCLOSURE LAG vs ANOMALY SCORE
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n6. DISCLOSURE LAG ANALYSIS")
    print("-" * 60)
    lag_data = q(cur, """
        SELECT CASE
                 WHEN feat_disclosure_lag <= 7 THEN '0-7d'
                 WHEN feat_disclosure_lag <= 30 THEN '8-30d'
                 WHEN feat_disclosure_lag <= 60 THEN '31-60d'
                 WHEN feat_disclosure_lag <= 90 THEN '61-90d'
                 ELSE '90d+'
               END AS lag_bucket,
               COUNT(*) AS total,
               ROUND(AVG(cohort_index), 1) AS avg_coh,
               ROUND(AVG(baseline_index), 1) AS avg_base,
               SUM(CASE WHEN severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) AS anom,
               ROUND(SUM(CASE WHEN severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rate
        FROM anomaly_scores
        GROUP BY lag_bucket
        ORDER BY MIN(feat_disclosure_lag)
    """)
    print(f"{'Lag':<10} {'Total':<8} {'Anom':<8} {'ARate':<8} {'AvgCoh':<8} {'AvgBase'}")
    for r in lag_data:
        print(f"{r[0]:<10} {r[1]:<8} {r[4]:<8} {r[5]:<7}% {r[2]:<8} {r[3]}")

    # ─────────────────────────────────────────────────────────────────────
    # 7. COHORT ALPHA DISTRIBUTION — KEY SIGNAL
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n7. COHORT ALPHA (30-day excess return) DISTRIBUTION")
    print("-" * 60)
    alpha_data = q(cur, """
        SELECT CASE
                 WHEN feat_cohort_alpha < -0.10 THEN 'large_loss (<-10%)'
                 WHEN feat_cohort_alpha < -0.03 THEN 'moderate_loss (-10% to -3%)'
                 WHEN feat_cohort_alpha < 0.03  THEN 'normal (-3% to +3%)'
                 WHEN feat_cohort_alpha < 0.10  THEN 'moderate_gain (+3% to +10%)'
                 ELSE 'large_gain (>+10%)'
               END AS alpha_bucket,
               COUNT(*) AS total,
               SUM(CASE WHEN severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) AS anom,
               ROUND(SUM(CASE WHEN severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rate,
               ROUND(AVG(cohort_index), 1) AS avg_coh
        FROM anomaly_scores
        GROUP BY alpha_bucket
        ORDER BY MIN(feat_cohort_alpha)
    """)
    print(f"{'Alpha Range':<30} {'Total':<8} {'Anom':<8} {'ARate':<8} {'AvgCoh'}")
    for r in alpha_data:
        print(f"{r[0]:<30} {r[1]:<8} {r[2]:<8} {r[3]:<7}% {r[4]}")

    # ─────────────────────────────────────────────────────────────────────
    # 8. KNOWN-SCANDAL POLITICIANS CHECK
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n8. KNOWN-SCANDAL POLITICIAN SCORES")
    print("-" * 60)
    print("Checking politicians with known trading controversies:\n")

    known = [
        ("Pelosi", "Nancy Pelosi — spouse's tech trades widely scrutinized"),
        ("Tuberville", "Tommy Tuberville — DOJ investigated, 100+ late disclosures"),
        ("Burr", "Richard Burr — DOJ investigated COVID-era trades (charges dropped)"),
        ("Loeffler", "Kelly Loeffler — sold stocks after COVID briefing"),
        ("Perdue", "David Perdue — investigated for stock trades during COVID"),
        ("Crenshaw", "Dan Crenshaw — traded defense stocks while on committees"),
        ("Wasserman Schultz", "Debbie Wasserman Schultz — traded near legislation"),
        ("Gottheimer", "Josh Gottheimer — one of most active congressional traders"),
        ("Greene", "Marjorie Taylor Greene — multiple late disclosures"),
    ]
    for name_part, desc in known:
        rows = q(cur, f"""
            SELECT p.full_name, p.party,
                   COUNT(*) AS total,
                   SUM(CASE WHEN a.severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) AS anom,
                   ROUND(SUM(CASE WHEN a.severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rate,
                   SUM(CASE WHEN a.severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END) AS sev,
                   ROUND(AVG(a.cohort_index), 1) AS avg_coh,
                   ROUND(AVG(a.baseline_index), 1) AS avg_base,
                   MAX(a.cohort_index) AS max_coh
            FROM anomaly_scores a
            JOIN politicians p ON a.politician_id = p.id
            WHERE p.full_name LIKE '%{name_part}%'
            GROUP BY p.id
        """)
        if rows:
            for r in rows:
                print(f"  {desc}")
                print(f"    → {r[0]} ({r[1]}): {r[3]}/{r[2]} anomalous ({r[4]}%), "
                      f"{r[5]} SEVERE, avg_coh={r[6]}, max_coh={r[8]}")
        else:
            print(f"  {desc}")
            print(f"    → NOT IN SCORED DATA")
        print()

    # ─────────────────────────────────────────────────────────────────────
    # 9. ARE EXTREME ALPHAS REAL OR NOISE?
    # ─────────────────────────────────────────────────────────────────────
    print("\n9. EXTREME ALPHA TRADES (|alpha| > 15%) — REAL SIGNAL?")
    print("-" * 60)
    extremes = q(cur, """
        SELECT p.full_name, p.party, a.ticker, a.trade_date, t.trade_type,
               ROUND(a.feat_cohort_alpha * 100, 1) AS alpha_pct,
               a.cohort_index, a.baseline_index, a.severity_quadrant,
               a.feat_committee_relevance, a.feat_disclosure_lag
        FROM anomaly_scores a
        JOIN politicians p ON a.politician_id = p.id
        JOIN trades t ON a.trade_id = t.id
        WHERE ABS(a.feat_cohort_alpha) > 0.15
        ORDER BY ABS(a.feat_cohort_alpha) DESC
        LIMIT 20
    """)
    print(f"{'Name':<28} {'Pty':<4} {'Ticker':<6} {'Date':<12} {'Type':<5} "
          f"{'Alpha%':<8} {'Coh':<5} {'Base':<5} {'Quad':<14} {'CmtRel':<7} {'Lag'}")
    for r in extremes:
        print(f"{r[0]:<28} {r[1]:<4} {r[2]:<6} {str(r[3]):<12} {r[4]:<5} "
              f"{r[5]:>6.1f}% {r[6]:<5} {r[7]:<5} {r[8]:<14} {r[9]:<7} {r[10]}")

    # ─────────────────────────────────────────────────────────────────────
    # 10. MODEL SCORE DISTRIBUTION SHAPE
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n10. SCORE DISTRIBUTION SHAPE")
    print("-" * 60)
    for model_name, col in [("Cohort", "cohort_index"), ("Baseline", "baseline_index")]:
        buckets = q(cur, f"""
            SELECT FLOOR({col} / 10) * 10 AS bucket, COUNT(*)
            FROM anomaly_scores
            GROUP BY bucket
            ORDER BY bucket
        """)
        total = sum(r[1] for r in buckets)
        print(f"\n  {model_name} Index Distribution:")
        for r in buckets:
            pct = r[1] / total * 100
            bar = "█" * int(pct)
            print(f"    {int(r[0]):>3}-{int(r[0])+9}: {r[1]:>5} ({pct:>5.1f}%) {bar}")

    # ─────────────────────────────────────────────────────────────────────
    # 11. COMMITTEE RELEVANCE IMPACT
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n11. COMMITTEE RELEVANCE IMPACT")
    print("-" * 60)
    cr_data = q(cur, """
        SELECT CASE
                 WHEN feat_committee_relevance = 0 THEN 'none (0.0)'
                 WHEN feat_committee_relevance < 0.5 THEN 'low (0.01-0.49)'
                 WHEN feat_committee_relevance < 0.8 THEN 'medium (0.5-0.79)'
                 ELSE 'high (0.8-1.0)'
               END AS cr_bucket,
               COUNT(*) AS total,
               SUM(CASE WHEN severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) AS anom,
               ROUND(SUM(CASE WHEN severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rate,
               ROUND(AVG(cohort_index), 1) AS avg_coh
        FROM anomaly_scores
        GROUP BY cr_bucket
        ORDER BY MIN(feat_committee_relevance)
    """)
    print(f"{'Committee Relevance':<25} {'Total':<8} {'Anom':<8} {'ARate':<8} {'AvgCoh'}")
    for r in cr_data:
        print(f"{r[0]:<25} {r[1]:<8} {r[2]:<8} {r[3]:<7}% {r[4]}")

    c.close()


if __name__ == "__main__":
    main()
