"""Examine committee sector_tag, trade industry_sector, and missing price tickers."""
from sqlalchemy import text
from backend.db.connection import get_engine

engine = get_engine()
with engine.connect() as conn:
    # 1. Committees WITH sector_tag
    print("=== COMMITTEES WITH sector_tag ===")
    rows = conn.execute(text(
        "SELECT name, sector_tag FROM committees WHERE sector_tag IS NOT NULL ORDER BY sector_tag, name"
    )).fetchall()
    for r in rows:
        print(f"  [{r[1]}] {r[0]}")
    print(f"  Total with tag: {len(rows)}")

    print()
    print("=== COMMITTEES WITHOUT sector_tag (sample) ===")
    rows = conn.execute(text(
        "SELECT name FROM committees WHERE sector_tag IS NULL ORDER BY name LIMIT 40"
    )).fetchall()
    for r in rows:
        print(f"  {r[0]}")
    total_no_tag = conn.execute(text(
        "SELECT COUNT(*) FROM committees WHERE sector_tag IS NULL"
    )).scalar()
    print(f"  Total without tag: {total_no_tag}")

    # 2. trades.industry_sector distribution and what's null
    print()
    print("=== TRADES industry_sector distribution ===")
    rows = conn.execute(text(
        "SELECT industry_sector, COUNT(*) as cnt FROM trades GROUP BY industry_sector ORDER BY cnt DESC"
    )).fetchall()
    for r in rows:
        print(f"  {r[0]}: {r[1]}")

    # Sample tickers missing sector
    print()
    print("=== SAMPLE TICKERS WITH NULL industry_sector (top 20 by trade count) ===")
    rows = conn.execute(text(
        "SELECT ticker, company_name, COUNT(*) as cnt FROM trades "
        "WHERE industry_sector IS NULL GROUP BY ticker, company_name ORDER BY cnt DESC LIMIT 20"
    )).fetchall()
    for r in rows:
        print(f"  {r[0]} ({r[1]}): {r[2]} trades")

    # 3. Missing price tickers - are they delisted/renamed?
    print()
    print("=== MISSING PRICE TICKERS (sample, by trade count) ===")
    rows = conn.execute(text(
        "SELECT t.ticker, t.company_name, COUNT(*) as cnt, MIN(t.trade_date) as first, MAX(t.trade_date) as last "
        "FROM trades t LEFT JOIN stock_prices sp ON t.ticker = sp.ticker "
        "WHERE sp.ticker IS NULL GROUP BY t.ticker, t.company_name ORDER BY cnt DESC LIMIT 25"
    )).fetchall()
    for r in rows:
        print(f"  {r[0]} ({r[1]}): {r[2]} trades, range {r[3]} to {r[4]}")

    # 4. Check trade_sectors table
    print()
    print("=== TRADE_SECTORS coverage ===")
    ts_total = conn.execute(text("SELECT COUNT(*) FROM trade_sectors")).scalar()
    trade_total = conn.execute(text("SELECT COUNT(*) FROM trades")).scalar()
    print(f"  trade_sectors rows: {ts_total}/{trade_total} trades ({ts_total/trade_total*100:.1f}%)")
    rows = conn.execute(text(
        "SELECT sector, COUNT(*) as cnt FROM trade_sectors GROUP BY sector ORDER BY cnt DESC"
    )).fetchall()
    for r in rows:
        print(f"  {r[0]}: {r[1]}")

    # How many trades have sector via trade_sectors but NOT industry_sector?
    covered = conn.execute(text(
        "SELECT COUNT(*) FROM trades t "
        "JOIN trade_sectors ts ON t.id = ts.trade_id "
        "WHERE t.industry_sector IS NULL"
    )).scalar()
    print(f"  Trades with NULL industry_sector but covered by trade_sectors: {covered}")
