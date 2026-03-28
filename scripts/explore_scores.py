"""Quick exploration of anomaly scoring results."""
import pymysql

c = pymysql.connect(host='localhost', port=3307, user='root', password='changeme', database='house_advantage')
cur = c.cursor()

print('=== MOST FLAGGED POLITICIANS (SEVERE+SYSTEMIC) ===')
cur.execute("""
SELECT p.full_name, p.party, p.chamber, p.state,
       COUNT(*) as flagged,
       SUM(CASE WHEN a.severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END) as severe,
       SUM(CASE WHEN a.severity_quadrant = 'SYSTEMIC' THEN 1 ELSE 0 END) as systemic,
       ROUND(AVG(a.cohort_index),1) as avg_cohort,
       ROUND(AVG(a.baseline_index),1) as avg_baseline,
       COUNT(DISTINCT t.ticker) as unique_tickers
FROM anomaly_scores a
JOIN trades t ON a.trade_id = t.id
JOIN politicians p ON t.politician_id = p.id
WHERE a.severity_quadrant IN ('SEVERE','SYSTEMIC')
GROUP BY p.id, p.full_name, p.party, p.chamber, p.state
ORDER BY flagged DESC
LIMIT 20
""")
for r in cur.fetchall():
    print(f'{r[0]:30s} | {r[1]} {r[2]:6s} {r[3]:2s} | flagged={r[4]} severe={r[5]} systemic={r[6]} | avgC={r[7]} avgB={r[8]} | tickers={r[9]}')

print('\n=== MOST FLAGGED TICKERS ===')
cur.execute("""
SELECT t.ticker, t.industry_sector,
       COUNT(*) as flagged,
       SUM(CASE WHEN a.severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END) as severe,
       SUM(CASE WHEN a.severity_quadrant = 'SYSTEMIC' THEN 1 ELSE 0 END) as systemic,
       SUM(CASE WHEN t.trade_type = 'buy' THEN 1 ELSE 0 END) as buys,
       SUM(CASE WHEN t.trade_type = 'sell' THEN 1 ELSE 0 END) as sells,
       COUNT(DISTINCT t.politician_id) as unique_politicians,
       ROUND(AVG(a.feat_cohort_alpha),3) as avg_alpha
FROM anomaly_scores a
JOIN trades t ON a.trade_id = t.id
WHERE a.severity_quadrant IN ('SEVERE','SYSTEMIC')
GROUP BY t.ticker, t.industry_sector
ORDER BY flagged DESC
LIMIT 20
""")
for r in cur.fetchall():
    sector = str(r[1] or 'N/A')[:20]
    print(f'{r[0]:6s} {sector:20s} | flagged={r[2]} severe={r[3]} systemic={r[4]} | B={r[5]} S={r[6]} | pols={r[7]} alpha={r[8]}')

print('\n=== FLAGGED TRADES BY MONTH ===')
cur.execute("""
SELECT DATE_FORMAT(t.trade_date, '%%Y-%%m') as month,
       COUNT(*) as flagged,
       SUM(CASE WHEN a.severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END) as severe,
       SUM(CASE WHEN a.severity_quadrant = 'SYSTEMIC' THEN 1 ELSE 0 END) as systemic
FROM anomaly_scores a
JOIN trades t ON a.trade_id = t.id
WHERE a.severity_quadrant IN ('SEVERE','SYSTEMIC')
GROUP BY month
ORDER BY month DESC
LIMIT 24
""")
for r in cur.fetchall():
    print(f'{r[0]} | flagged={r[1]} severe={r[2]} systemic={r[3]}')

print('\n=== COMMITTEE OVERLAP: FLAGGED TRADES WHERE POLITICIAN SITS ON RELEVANT COMMITTEE ===')
cur.execute("""
SELECT p.full_name, p.party, p.state, t.ticker, t.industry_sector, t.trade_type, t.trade_date,
       a.cohort_index, a.baseline_index, a.severity_quadrant,
       a.feat_cohort_alpha, a.feat_committee_relevance,
       GROUP_CONCAT(DISTINCT cm2.name SEPARATOR '; ') as committees
FROM anomaly_scores a
JOIN trades t ON a.trade_id = t.id
JOIN politicians p ON t.politician_id = p.id
LEFT JOIN committee_memberships cm ON cm.politician_id = p.id
LEFT JOIN committees cm2 ON cm2.id = cm.committee_id
WHERE a.severity_quadrant IN ('SEVERE','SYSTEMIC')
  AND a.feat_committee_relevance > 0
GROUP BY a.id, p.full_name, p.party, p.state, t.ticker, t.industry_sector,
         t.trade_type, t.trade_date, a.cohort_index, a.baseline_index,
         a.severity_quadrant, a.feat_cohort_alpha, a.feat_committee_relevance
ORDER BY a.feat_committee_relevance DESC, (a.cohort_index + a.baseline_index) DESC
LIMIT 20
""")
for r in cur.fetchall():
    comms = (r[12] or '')[:80]
    print(f'{r[0]:25s} {r[1]} {r[2]:2s} | {r[3]:5s} {r[4] or "N/A":15s} {r[5]:4s} {r[6]} | C={r[7]} B={r[8]} {r[9]:12s} | alpha={r[10]:+.3f} comm_rel={r[11]:.1f}')
    print(f'  Committees: {comms}')

print('\n=== PELOSI TRADES (ALL) ===')
cur.execute("""
SELECT t.ticker, t.trade_type, t.trade_date, t.amount_lower, t.amount_upper,
       a.cohort_index, a.baseline_index, a.severity_quadrant,
       a.feat_cohort_alpha, a.feat_disclosure_lag
FROM trades t
JOIN politicians p ON t.politician_id = p.id
LEFT JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%%Pelosi%%'
ORDER BY t.trade_date DESC
""")
for r in cur.fetchall():
    quad = r[7] or 'unscored'
    print(f'{r[0]:6s} {r[1]:5s} {r[2]} | ${r[3]:>7,}-${r[4]:>7,} | C={r[5]} B={r[6]} {quad:12s} | alpha={r[8]} lag={r[9]}')

c.close()
