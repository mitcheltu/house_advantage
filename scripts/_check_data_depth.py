"""Quick check of data dimensions for feature engineering planning."""
import pymysql

conn = pymysql.connect(host="localhost", port=3307, user="root",
                       password="changeme", database="house_advantage")
cur = conn.cursor()

# Trade date range (realistic)
cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM trades WHERE trade_date BETWEEN '2020-01-01' AND '2026-12-31'")
r = cur.fetchone()
print(f"Trade date range: {r[0]} to {r[1]}")

# Amount buckets
cur.execute("""SELECT 
  CASE 
    WHEN amount_midpoint <= 15000 THEN 'A_lt15K'
    WHEN amount_midpoint <= 50000 THEN 'B_15K-50K'
    WHEN amount_midpoint <= 250000 THEN 'C_50K-250K'
    WHEN amount_midpoint <= 1000000 THEN 'D_250K-1M'
    ELSE 'E_1M+'
  END as bucket,
  COUNT(*) 
FROM trades GROUP BY bucket ORDER BY bucket""")
print("\nAmount distribution:")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

# Tickers with enough price data for volatility
cur.execute("""SELECT COUNT(DISTINCT ticker) FROM stock_prices 
               WHERE ticker IN (SELECT DISTINCT ticker FROM trades)""")
print(f"\nTickers with price data: {cur.fetchone()[0]}")

# Sample vote questions
cur.execute("SELECT question FROM votes WHERE question IS NOT NULL LIMIT 5")
print("\nSample vote questions:")
for r in cur.fetchall():
    print(f"  {r[0][:150]}")

# How many politicians trade same ticker within 7 days?
cur.execute("""
    SELECT t1.ticker, t1.trade_date, COUNT(DISTINCT t1.politician_id) as n_pols
    FROM trades t1
    JOIN trades t2 ON t1.ticker = t2.ticker 
        AND t1.politician_id != t2.politician_id
        AND ABS(DATEDIFF(t1.trade_date, t2.trade_date)) <= 7
    GROUP BY t1.ticker, t1.trade_date
    HAVING n_pols >= 3
    ORDER BY n_pols DESC
    LIMIT 10
""")
print("\nCluster trading (3+ pols same ticker within 7 days):")
for r in cur.fetchall():
    print(f"  {r[0]} on {r[1]}: {r[2]} politicians")

# Trades per politician - for personal baseline calculation
cur.execute("""SELECT politician_id, COUNT(*) c FROM trades 
               GROUP BY politician_id ORDER BY c DESC LIMIT 5""")
print("\nTop traders (for personal baseline feasibility):")
for r in cur.fetchall():
    print(f"  politician_id={r[0]}: {r[1]} trades")

cur.execute("""SELECT 
    SUM(CASE WHEN c >= 20 THEN 1 ELSE 0 END) as enough,
    SUM(CASE WHEN c < 20 THEN 1 ELSE 0 END) as too_few
FROM (SELECT politician_id, COUNT(*) c FROM trades GROUP BY politician_id) sub""")
r = cur.fetchone()
print(f"  Politicians with 20+ trades: {r[0]}, under 20: {r[1]}")

conn.close()
