"""One-time migration: create trade_sectors junction table and populate
from existing trades.industry_sector column.

Handles all storage formats: plain strings, JSON arrays, and Python repr lists.
Idempotent — safe to run multiple times.
"""
import ast
import json
import os

import pymysql
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DB_CFG = dict(
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DATABASE", "house_advantage"),
)


def _parse_sector(raw: str | None) -> list[str]:
    """Parse an industry_sector DB value into a list of sector strings."""
    if not raw or not raw.strip():
        return []
    s = raw.strip()
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (ValueError, SyntaxError):
            pass
    return [s]


def migrate():
    conn = pymysql.connect(**DB_CFG)
    cur = conn.cursor()

    # 1. Create table if not exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_sectors (
            trade_id  INT          NOT NULL,
            sector    VARCHAR(50)  NOT NULL,
            PRIMARY KEY (trade_id, sector),
            FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE CASCADE,
            INDEX idx_sector (sector)
        ) ENGINE=InnoDB
    """)
    conn.commit()
    print("trade_sectors table ensured.")

    # 2. Load the authoritative ticker→sector map (includes multi-sector overrides)
    sector_map_path = ROOT / "backend" / "data" / "raw" / "_combined_sector_map.json"
    if not sector_map_path.exists():
        print(f"ERROR: {sector_map_path} not found. Cannot populate trade_sectors.")
        conn.close()
        return
    ticker_sector_map = json.load(open(sector_map_path))

    # 3. Clear and repopulate (idempotent)
    cur.execute("DELETE FROM trade_sectors")
    conn.commit()

    # 4. Read all trades (we need ticker to look up multi-sector from the map)
    cur.execute("SELECT id, ticker, industry_sector FROM trades")
    trades = cur.fetchall()
    print(f"Found {len(trades)} trades total.")

    # 5. Parse and insert — prefer ticker map (has multi-sector), fall back to DB column
    inserted = 0
    multi = 0
    for trade_id, ticker, raw_sector in trades:
        # Look up from the authoritative map first
        map_val = ticker_sector_map.get(ticker) if ticker else None
        if map_val is not None:
            if isinstance(map_val, list):
                sectors = map_val
            else:
                sectors = [str(map_val)]
        elif raw_sector:
            sectors = _parse_sector(raw_sector)
        else:
            continue

        if len(sectors) > 1:
            multi += 1
        for sector in sectors:
            cur.execute(
                "INSERT IGNORE INTO trade_sectors (trade_id, sector) VALUES (%s, %s)",
                (trade_id, sector),
            )
            inserted += 1

    conn.commit()
    print(f"Inserted {inserted} trade_sector rows ({multi} trades have multiple sectors).")

    # 5. Verify
    cur.execute("SELECT sector, COUNT(*) AS cnt FROM trade_sectors GROUP BY sector ORDER BY cnt DESC")
    print("\nSector distribution:")
    for sector, cnt in cur.fetchall():
        print(f"  {sector}: {cnt}")

    cur.execute("""
        SELECT ts.trade_id, t.ticker, GROUP_CONCAT(ts.sector) AS sectors
        FROM trade_sectors ts
        JOIN trades t ON t.id = ts.trade_id
        GROUP BY ts.trade_id
        HAVING COUNT(*) > 1
        LIMIT 10
    """)
    rows = cur.fetchall()
    if rows:
        print(f"\nSample multi-sector trades:")
        for trade_id, ticker, sectors in rows:
            print(f"  trade {trade_id} ({ticker}): {sectors}")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    migrate()
