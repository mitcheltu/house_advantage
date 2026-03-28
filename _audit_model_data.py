"""Audit all DB columns used by model training for null gaps."""
from sqlalchemy import text
from backend.db.connection import get_engine

engine = get_engine()
with engine.connect() as conn:
    # 1. TRADES
    total = conn.execute(text("SELECT COUNT(*) FROM trades")).scalar()
    print(f"=== TRADES ({total:,} rows) ===")
    feat_cols = ['politician_id','ticker','trade_date','disclosure_lag_days','industry_sector','amount_midpoint']
    other_cols = ['disclosure_date','trade_type','company_name','asset_type']
    for col in feat_cols + other_cols:
        nulls = conn.execute(text(f"SELECT COUNT(*) FROM trades WHERE `{col}` IS NULL")).scalar()
        pct = nulls/total*100
        tag = " *** MODEL FEATURE" if col in feat_cols else ""
        print(f"  {col}: {nulls}/{total} NULL ({pct:.1f}%){tag}")

    # 2. BILLS
    print()
    bt = conn.execute(text("SELECT COUNT(*) FROM bills")).scalar()
    print(f"=== BILLS ({bt:,} rows) ===")
    for col in ['policy_area','latest_action_date']:
        nulls = conn.execute(text(f"SELECT COUNT(*) FROM bills WHERE `{col}` IS NULL")).scalar()
        print(f"  {col}: {nulls}/{bt} NULL ({nulls/bt*100:.1f}%) *** MODEL FEATURE")

    # 3. STOCK_PRICES
    print()
    sp = conn.execute(text("SELECT COUNT(*) FROM stock_prices")).scalar()
    print(f"=== STOCK_PRICES ({sp:,} rows) ===")
    for col in ['ticker','price_date','close']:
        nulls = conn.execute(text(f"SELECT COUNT(*) FROM stock_prices WHERE `{col}` IS NULL")).scalar()
        print(f"  {col}: {nulls}/{sp} NULL ({nulls/sp*100:.1f}%) *** MODEL FEATURE")

    spy = conn.execute(text("SELECT COUNT(*) FROM stock_prices WHERE ticker='SPY'")).scalar()
    print(f"  SPY rows: {spy}")

    tickers_in_trades = conn.execute(text("SELECT COUNT(DISTINCT ticker) FROM trades")).scalar()
    tickers_with_prices = conn.execute(text(
        "SELECT COUNT(DISTINCT t.ticker) FROM trades t "
        "JOIN stock_prices sp ON t.ticker = sp.ticker"
    )).scalar()
    missing = conn.execute(text(
        "SELECT DISTINCT t.ticker FROM trades t "
        "LEFT JOIN stock_prices sp ON t.ticker = sp.ticker "
        "WHERE sp.ticker IS NULL ORDER BY t.ticker"
    )).fetchall()
    print(f"  Trade tickers with price data: {tickers_with_prices}/{tickers_in_trades}")
    if missing:
        trades_without_prices = conn.execute(text(
            "SELECT COUNT(*) FROM trades t "
            "LEFT JOIN stock_prices sp ON t.ticker = sp.ticker "
            "WHERE sp.ticker IS NULL"
        )).scalar()
        print(f"  Trades missing price data: {trades_without_prices}/{total} ({trades_without_prices/total*100:.1f}%)")
        print(f"  Missing tickers ({len(missing)}): {[r[0] for r in missing[:30]]}")

    # 4. POLITICIAN_VOTES + VOTES
    print()
    pv = conn.execute(text("SELECT COUNT(*) FROM politician_votes")).scalar()
    print(f"=== POLITICIAN_VOTES ({pv:,} rows) ===")
    for col in ['politician_id','vote_id']:
        nulls = conn.execute(text(f"SELECT COUNT(*) FROM politician_votes WHERE `{col}` IS NULL")).scalar()
        print(f"  {col}: {nulls}/{pv} NULL ({nulls/pv*100:.1f}%)")

    v = conn.execute(text("SELECT COUNT(*) FROM votes")).scalar()
    print(f"=== VOTES ({v:,} rows) ===")
    for col in ['vote_date']:
        nulls = conn.execute(text(f"SELECT COUNT(*) FROM votes WHERE `{col}` IS NULL")).scalar()
        print(f"  {col}: {nulls}/{v} NULL ({nulls/v*100:.1f}%) *** MODEL FEATURE")

    pols_in_trades = conn.execute(text(
        "SELECT COUNT(DISTINCT politician_id) FROM trades WHERE politician_id IS NOT NULL"
    )).scalar()
    pols_with_votes = conn.execute(text(
        "SELECT COUNT(DISTINCT t.politician_id) FROM trades t "
        "JOIN politician_votes pv ON t.politician_id = pv.politician_id"
    )).scalar()
    pols_no_votes = pols_in_trades - pols_with_votes
    trades_no_votes = conn.execute(text(
        "SELECT COUNT(*) FROM trades t "
        "WHERE t.politician_id IS NOT NULL "
        "AND t.politician_id NOT IN (SELECT DISTINCT politician_id FROM politician_votes)"
    )).scalar()
    print(f"  Trade politicians with vote data: {pols_with_votes}/{pols_in_trades}")
    print(f"  Politicians WITHOUT votes: {pols_no_votes} -> {trades_no_votes} trades affected")

    # 5. COMMITTEE_MEMBERSHIPS + COMMITTEES
    print()
    cm = conn.execute(text("SELECT COUNT(*) FROM committee_memberships")).scalar()
    print(f"=== COMMITTEE_MEMBERSHIPS ({cm:,} rows) ===")
    for col in ['politician_id','committee_id','role']:
        nulls = conn.execute(text(f"SELECT COUNT(*) FROM committee_memberships WHERE `{col}` IS NULL")).scalar()
        print(f"  {col}: {nulls}/{cm} NULL ({nulls/cm*100:.1f}%)")

    c = conn.execute(text("SELECT COUNT(*) FROM committees")).scalar()
    print(f"=== COMMITTEES ({c} rows) ===")
    for col in ['name','sector_tag']:
        nulls = conn.execute(text(f"SELECT COUNT(*) FROM committees WHERE `{col}` IS NULL")).scalar()
        tag = " *** MODEL FEATURE" if col == 'sector_tag' else ""
        print(f"  {col}: {nulls}/{c} NULL ({nulls/c*100:.1f}%){tag}")

    pols_with_comm = conn.execute(text(
        "SELECT COUNT(DISTINCT t.politician_id) FROM trades t "
        "JOIN committee_memberships cm ON t.politician_id = cm.politician_id"
    )).scalar()
    trades_no_comm = conn.execute(text(
        "SELECT COUNT(*) FROM trades t "
        "WHERE t.politician_id IS NOT NULL "
        "AND t.politician_id NOT IN (SELECT DISTINCT politician_id FROM committee_memberships)"
    )).scalar()
    print(f"  Trade politicians with committee data: {pols_with_comm}/{pols_in_trades}")
    print(f"  Trades without committee data: {trades_no_comm}/{total} ({trades_no_comm/total*100:.1f}%)")

    # 6. CROSS-TABLE: sector coverage chain
    print()
    print("=== SECTOR COVERAGE CHAIN ===")
    # trades.industry_sector -> used for bill_proximity matching + committee_relevance
    sector_null = conn.execute(text("SELECT COUNT(*) FROM trades WHERE industry_sector IS NULL")).scalar()
    print(f"  trades.industry_sector NULL: {sector_null}/{total} ({sector_null/total*100:.1f}%)")
    # committees.sector_tag -> used for committee_relevance  
    sect_null = conn.execute(text("SELECT COUNT(*) FROM committees WHERE sector_tag IS NULL")).scalar()
    print(f"  committees.sector_tag NULL: {sect_null}/{c} ({sect_null/c*100:.1f}%)")
    # bills.policy_area -> mapped to sector for bill_proximity
    pa_null = conn.execute(text("SELECT COUNT(*) FROM bills WHERE policy_area IS NULL")).scalar()
    print(f"  bills.policy_area NULL: {pa_null}/{bt} ({pa_null/bt*100:.1f}%)")

    # 7. TRADE_SECTORS table
    print()
    ts = conn.execute(text("SELECT COUNT(*) FROM trade_sectors")).scalar()
    print(f"=== TRADE_SECTORS ({ts:,} rows) ===")
    if ts > 0:
        cols = conn.execute(text("SHOW COLUMNS FROM trade_sectors")).fetchall()
        for col_info in cols:
            col = col_info[0]
            if col == 'id':
                continue
            nulls = conn.execute(text(f"SELECT COUNT(*) FROM trade_sectors WHERE `{col}` IS NULL")).scalar()
            print(f"  {col}: {nulls}/{ts} NULL ({nulls/ts*100:.1f}%)")
