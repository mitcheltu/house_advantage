from backend.db.connection import get_engine
from sqlalchemy import text

engine = get_engine()
conn = engine.connect()
tables = [r[0] for r in conn.execute(text("SHOW TABLES"))]
total = 0
for t in sorted(tables):
    cnt = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
    total += cnt
    print(f"  {t:30s} {cnt:>10,}")
print(f"  {'TOTAL':30s} {total:>10,}")
