"""Top 50 politicians by number of anomalous trades."""
import pymysql

c = pymysql.connect(
    host="localhost", port=3307, user="root",
    password="changeme", database="house_advantage",
)
cur = c.cursor()

cur.execute("""
    SELECT p.full_name, p.party, p.chamber,
           COUNT(*) AS total_trades,
           SUM(CASE WHEN a.severity_quadrant != 'UNREMARKABLE' THEN 1 ELSE 0 END) AS anomalous_trades,
           SUM(CASE WHEN a.severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END) AS severe,
           SUM(CASE WHEN a.severity_quadrant = 'SYSTEMIC' THEN 1 ELSE 0 END) AS systemic,
           SUM(CASE WHEN a.severity_quadrant = 'OUTLIER' THEN 1 ELSE 0 END) AS outlier,
           ROUND(AVG(a.cohort_index), 1) AS avg_cohort,
           ROUND(AVG(a.baseline_index), 1) AS avg_baseline
    FROM anomaly_scores a
    JOIN politicians p ON a.politician_id = p.id
    GROUP BY p.id, p.full_name, p.party, p.chamber
    ORDER BY anomalous_trades DESC, severe DESC, systemic DESC
    LIMIT 50
""")

header = f"{'Name':<35} {'Party':<6} {'Chamber':<8} {'Total':<7} {'Anom':<6} {'SEV':<5} {'SYS':<5} {'OUT':<5} {'AvgCoh':<8} {'AvgBase'}"
print(header)
print("-" * len(header))
for r in cur.fetchall():
    print(f"{r[0]:<35} {r[1]:<6} {r[2]:<8} {r[3]:<7} {r[4]:<6} {r[5]:<5} {r[6]:<5} {r[7]:<5} {r[8]:<8} {r[9]}")

c.close()
