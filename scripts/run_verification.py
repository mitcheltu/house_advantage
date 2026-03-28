"""Run key verification queries from verify_model_v2.sql and display results."""
import pymysql

c = pymysql.connect(host='localhost', port=3307, user='root', password='changeme', database='house_advantage')
cur = c.cursor()

def run(title, sql):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    # Header
    print(" | ".join(f"{c:>15s}" for c in cols))
    print("-" * (17 * len(cols)))
    for r in rows:
        vals = []
        for v in r:
            if v is None:
                vals.append(f"{'NULL':>15s}")
            elif isinstance(v, float):
                vals.append(f"{v:>15.3f}")
            else:
                vals.append(f"{str(v):>15s}")
        print(" | ".join(vals))
    if not rows:
        print("  (no results)")
    return rows

# 1. Overall health
run("1. SCORING HEALTH CHECK", """
SELECT severity_quadrant, COUNT(*) AS cnt,
       ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER(),1) AS pct,
       ROUND(AVG(cohort_index),1) AS avg_C,
       ROUND(AVG(baseline_index),1) AS avg_B,
       SUM(audit_triggered) AS audits
FROM anomaly_scores
GROUP BY severity_quadrant
ORDER BY FIELD(severity_quadrant,'SEVERE','SYSTEMIC','OUTLIER','UNREMARKABLE')
""")

# 2. Pelosi TEM
run("2. PELOSI — TEMPUS AI (TEM) — Jan 2025", """
SELECT t.ticker, t.trade_type, t.trade_date, t.amount_lower, t.amount_upper,
       a.cohort_index, a.baseline_index, a.severity_quadrant,
       ROUND(a.feat_cohort_alpha,3) AS alpha
FROM trades t JOIN politicians p ON t.politician_id=p.id
JOIN anomaly_scores a ON a.trade_id=t.id
WHERE p.full_name LIKE '%Pelosi%' AND t.ticker='TEM'
""")

# 3. Pelosi PANW
run("3. PELOSI — PALO ALTO NETWORKS (PANW) — Feb 2024", """
SELECT t.ticker, t.trade_type, t.trade_date, t.amount_lower, t.amount_upper,
       a.cohort_index, a.baseline_index, a.severity_quadrant,
       ROUND(a.feat_cohort_alpha,3) AS alpha
FROM trades t JOIN politicians p ON t.politician_id=p.id
JOIN anomaly_scores a ON a.trade_id=t.id
WHERE p.full_name LIKE '%Pelosi%' AND t.ticker='PANW'
""")

# 5. TSLA election cluster
run("5. TSLA TRADES — OCT/NOV 2024 ELECTION CLUSTER", """
SELECT p.full_name, p.party, t.trade_type, t.trade_date,
       a.cohort_index, a.baseline_index, a.severity_quadrant,
       ROUND(a.feat_cohort_alpha,3) AS alpha
FROM trades t JOIN politicians p ON t.politician_id=p.id
JOIN anomaly_scores a ON a.trade_id=t.id
WHERE t.ticker='TSLA' AND t.trade_date BETWEEN '2024-10-01' AND '2024-11-30'
ORDER BY t.trade_date
""")

# 7. UNH April 2025 cluster
run("7. UNH TRADES — APR 2025 CRASH CLUSTER", """
SELECT p.full_name, p.party, t.trade_type, t.trade_date,
       a.cohort_index, a.baseline_index, a.severity_quadrant,
       ROUND(a.feat_cohort_alpha,3) AS alpha,
       a.feat_committee_relevance AS comm_rel
FROM trades t JOIN politicians p ON t.politician_id=p.id
JOIN anomaly_scores a ON a.trade_id=t.id
WHERE t.ticker='UNH' AND t.trade_date BETWEEN '2025-03-01' AND '2025-06-01'
ORDER BY t.trade_date
""")

# 14. Party breakdown
run("14. PARTY BREAKDOWN — BIAS CHECK", """
SELECT p.party,
       COUNT(*) AS total_trades,
       SUM(CASE WHEN a.severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END) AS flagged,
       ROUND(SUM(CASE WHEN a.severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END)*100.0/COUNT(*),2) AS flag_rate,
       ROUND(AVG(a.cohort_index),1) AS avg_C,
       ROUND(AVG(a.baseline_index),1) AS avg_B
FROM trades t JOIN politicians p ON t.politician_id=p.id
LEFT JOIN anomaly_scores a ON a.trade_id=t.id
GROUP BY p.party
""")

# 18. Multi-politician clusters
run("18. MULTI-POLITICIAN SAME-STOCK SAME-WEEK CLUSTERS", """
SELECT t.ticker, MIN(t.trade_date) AS week_start, MAX(t.trade_date) AS week_end,
       COUNT(DISTINCT t.politician_id) AS unique_pols, COUNT(*) AS trades,
       GROUP_CONCAT(DISTINCT SUBSTRING_INDEX(p.full_name, ',', 1) ORDER BY p.full_name SEPARATOR ', ') AS who,
       ROUND(AVG(a.baseline_index),1) AS avg_B
FROM trades t JOIN politicians p ON t.politician_id=p.id
LEFT JOIN anomaly_scores a ON a.trade_id=t.id
WHERE a.severity_quadrant IN ('SEVERE','SYSTEMIC')
GROUP BY t.ticker, YEARWEEK(t.trade_date,1)
HAVING unique_pols >= 2
ORDER BY unique_pols DESC, avg_B DESC
LIMIT 15
""")

# 19. Systemic signal
run("19. SYSTEMIC SIGNAL — ALPHA BY QUADRANT", """
SELECT 'All scored' AS pop, COUNT(*) AS n,
       ROUND(AVG(feat_cohort_alpha),4) AS mean_alpha,
       ROUND(STD(feat_cohort_alpha),4) AS std_alpha
FROM anomaly_scores
UNION ALL
SELECT 'SYSTEMIC', COUNT(*), ROUND(AVG(feat_cohort_alpha),4), ROUND(STD(feat_cohort_alpha),4)
FROM anomaly_scores WHERE severity_quadrant='SYSTEMIC'
UNION ALL
SELECT 'SEVERE', COUNT(*), ROUND(AVG(feat_cohort_alpha),4), ROUND(STD(feat_cohort_alpha),4)
FROM anomaly_scores WHERE severity_quadrant='SEVERE'
UNION ALL
SELECT 'UNREMARKABLE', COUNT(*), ROUND(AVG(feat_cohort_alpha),4), ROUND(STD(feat_cohort_alpha),4)
FROM anomaly_scores WHERE severity_quadrant='UNREMARKABLE'
""")

# 21. Score calibration
run("21. SCORE CALIBRATION — ALPHA BUCKET vs SCORES", """
SELECT CASE
    WHEN ABS(feat_cohort_alpha) < 0.05 THEN '<5%%'
    WHEN ABS(feat_cohort_alpha) < 0.10 THEN '5-10%%'
    WHEN ABS(feat_cohort_alpha) < 0.20 THEN '10-20%%'
    WHEN ABS(feat_cohort_alpha) < 0.50 THEN '20-50%%'
    ELSE '>50%%'
  END AS alpha_bucket,
  COUNT(*) AS trades,
  ROUND(AVG(cohort_index),1) AS avg_C,
  ROUND(AVG(baseline_index),1) AS avg_B,
  SUM(CASE WHEN severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END) AS flagged
FROM anomaly_scores
GROUP BY alpha_bucket
ORDER BY FIELD(alpha_bucket, '<5%%','5-10%%','10-20%%','20-50%%','>50%%')
""")

# 22. False negative check
run("22. FALSE NEGATIVE CHECK — KNOWN SUSPICIOUS POLITICIANS", """
SELECT p.full_name, p.party,
       COUNT(*) AS total, 
       SUM(CASE WHEN a.severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END) AS flagged,
       ROUND(SUM(CASE WHEN a.severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END)*100.0/COUNT(*),1) AS flag_pct,
       ROUND(AVG(a.baseline_index),1) AS avg_B,
       ROUND(AVG(ABS(a.feat_cohort_alpha)),3) AS avg_abs_alpha
FROM trades t JOIN politicians p ON t.politician_id=p.id
LEFT JOIN anomaly_scores a ON a.trade_id=t.id
WHERE p.full_name LIKE '%Pelosi%'
   OR p.full_name LIKE '%Tuberville%'
   OR p.full_name LIKE '%Crenshaw%'
   OR p.full_name LIKE '%Ossoff%'
   OR p.full_name LIKE '%Lee, Susie%'
   OR p.full_name LIKE '%Greene, Marjorie%'
   OR p.full_name LIKE '%Gottheimer%'
   OR p.full_name LIKE '%McClain, Lisa%'
GROUP BY p.id, p.full_name, p.party
ORDER BY flagged DESC
""")

c.close()
print("\n\nDone. Full SQL queries saved to scripts/verify_model_v2.sql")
