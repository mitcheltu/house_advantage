import pymysql
c = pymysql.connect(host='localhost', port=3307, user='root', password='changeme', database='house_advantage')
cur = c.cursor()
tables = ['politicians','committees','committee_memberships','trades','votes',
          'politician_votes','bills','stock_prices','institutional_holdings',
          'institutional_trades','fec_candidates','fec_candidate_totals','cusip_ticker_map']
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"  {t}: {cur.fetchone()[0]}")
c.close()
