"""
Fix remaining data gaps before model retraining.

Gap 1: committees.sector_tag — apply expanded keyword mapping
Gap 2: missing stock prices — download 196 missing tickers via yfinance
Gap 3: trades.industry_sector — expand _combined_sector_map.json with ETFs

Usage:
    python scripts/fix_data_gaps.py committees   # Fix gap 1
    python scripts/fix_data_gaps.py prices       # Fix gap 2
    python scripts/fix_data_gaps.py sectors      # Fix gap 3
    python scripts/fix_data_gaps.py all          # Fix all gaps
    python scripts/fix_data_gaps.py verify       # Check coverage after fixes
"""
import sys
import os
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from backend.db.connection import get_engine
from backend.ingest.collectors.collect_congress_gov import COMMITTEE_SECTOR_MAP


# ── Gap 1: Fix committees.sector_tag ─────────────────────────────────────────

def fix_committees():
    """Apply expanded COMMITTEE_SECTOR_MAP to all committee rows in DB."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name, sector_tag FROM committees")
        ).fetchall()

        updated = 0
        for row in rows:
            cid, name, current_tag = row
            # Re-derive sector using the expanded keyword map
            name_lower = name.lower()
            new_sector = None
            for keyword, sector in COMMITTEE_SECTOR_MAP.items():
                if keyword.lower() in name_lower:
                    new_sector = sector
                    break

            if new_sector and new_sector != current_tag:
                conn.execute(
                    text("UPDATE committees SET sector_tag = :sector WHERE id = :id"),
                    {"sector": new_sector, "id": cid},
                )
                updated += 1

        conn.commit()

    # Report
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM committees")).scalar()
        tagged = conn.execute(
            text("SELECT COUNT(*) FROM committees WHERE sector_tag IS NOT NULL")
        ).scalar()
        print(f"Committees: {tagged}/{total} tagged ({100*tagged/total:.1f}%)")
        print(f"  Updated {updated} rows this run")

        # Show remaining NULLs
        nulls = conn.execute(
            text("SELECT name FROM committees WHERE sector_tag IS NULL ORDER BY name")
        ).fetchall()
        if nulls:
            print(f"  {len(nulls)} committees still NULL (cross-cutting/procedural):")
            for r in nulls:
                print(f"    - {r[0]}")


# ── Gap 2: Fix missing stock prices ──────────────────────────────────────────

def fix_prices():
    """Download missing price data for tickers that have trades but no prices."""
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        print("ERROR: yfinance and pandas required. pip install yfinance pandas")
        return

    engine = get_engine()
    price_dir = Path(__file__).resolve().parent.parent / "backend" / "data" / "raw" / "prices"
    price_dir.mkdir(parents=True, exist_ok=True)

    # Find tickers with trades but no price data
    with engine.connect() as conn:
        missing = conn.execute(text("""
            SELECT DISTINCT t.ticker
            FROM trades t
            LEFT JOIN stock_prices sp ON t.ticker = sp.ticker
            WHERE sp.ticker IS NULL
              AND t.ticker IS NOT NULL
              AND t.ticker REGEXP '^[A-Za-z]+$'
              AND CHAR_LENGTH(t.ticker) <= 5
            ORDER BY t.ticker
        """)).fetchall()

    tickers = [r[0] for r in missing]
    print(f"Found {len(tickers)} tickers with trades but no price data")

    if not tickers:
        print("Nothing to do!")
        return

    downloaded = 0
    failed = []
    for i, ticker in enumerate(tickers):
        csv_path = price_dir / f"{ticker}.csv"
        if csv_path.exists() and csv_path.stat().st_size > 100:
            downloaded += 1
            continue

        try:
            df = yf.download(ticker, period="2y", progress=False, timeout=10)
            if df is not None and len(df) > 0:
                df.to_csv(csv_path)
                downloaded += 1
                if (i + 1) % 20 == 0:
                    print(f"  Progress: {i+1}/{len(tickers)} ({downloaded} downloaded)")
            else:
                failed.append(ticker)
        except Exception as e:
            failed.append(ticker)
            if (i + 1) % 20 == 0:
                print(f"  Progress: {i+1}/{len(tickers)} ({downloaded} downloaded)")

    print(f"\nResults: {downloaded}/{len(tickers)} tickers downloaded")
    if failed:
        print(f"  {len(failed)} failed: {', '.join(failed[:20])}")
        if len(failed) > 20:
            print(f"  ... and {len(failed)-20} more")

    # Load new prices into DB
    print("\nLoading new prices into stock_prices table...")
    loaded = 0
    for ticker in tickers:
        csv_path = price_dir / f"{ticker}.csv"
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path, parse_dates=["Date"])
            if len(df) == 0:
                continue
            # Normalize column names (yfinance sometimes uses multi-level headers)
            if "Close" in df.columns:
                records = []
                for _, row in df.iterrows():
                    records.append({
                        "ticker": ticker,
                        "price_date": row["Date"].strftime("%Y-%m-%d"),
                        "close_price": float(row["Close"]),
                        "volume": int(row.get("Volume", 0)) if pd.notna(row.get("Volume")) else 0,
                    })
                if records:
                    with engine.connect() as conn:
                        conn.execute(
                            text("""
                                INSERT IGNORE INTO stock_prices (ticker, price_date, close_price, volume)
                                VALUES (:ticker, :price_date, :close_price, :volume)
                            """),
                            records,
                        )
                        conn.commit()
                    loaded += 1
        except Exception as e:
            print(f"  Warning: could not load {ticker}: {e}")

    print(f"Loaded prices for {loaded} tickers into DB")


# ── Gap 3: Fix trades.industry_sector (expand sector map with ETFs) ──────────

# ETF/fund → sector mappings for common ETFs in the dataset
ETF_SECTOR_MAP = {
    # Treasury / Fixed Income → finance
    "SHY": "finance", "IEF": "finance", "TLT": "finance", "SGOV": "finance",
    "BIL": "finance", "TBLL": "finance", "USFR": "finance", "TFLO": "finance",
    "VGSH": "finance", "SHV": "finance", "SCHO": "finance", "FLOT": "finance",
    "GOVT": "finance", "VMBS": "finance", "MBB": "finance", "JMBS": "finance",
    "AGG": "finance", "BND": "finance", "BNDX": "finance", "SCHZ": "finance",
    "VCSH": "finance", "VCIT": "finance", "LQD": "finance", "HYG": "finance",
    "JNK": "finance", "MINT": "finance", "NEAR": "finance", "JPST": "finance",
    "GBIL": "finance", "CARY": "finance", "ICSH": "finance", "FLRN": "finance",
    "JAAA": "finance", "CLOA": "finance", "SRLN": "finance", "BKLN": "finance",
    "TLH": "finance", "SCHP": "finance", "AGZ": "finance", "CMBS": "finance",
    "GIGB": "finance", "PIMCO": "finance",
    # Broad Market / S&P 500 → finance (market-wide)
    "SPY": "finance", "IVV": "finance", "VOO": "finance", "VTI": "finance",
    "ITOT": "finance", "SCHB": "finance", "SPTM": "finance",
    "IVW": "finance", "IVE": "finance",  # S&P 500 Growth / Value
    "QQQ": "tech", "QQQM": "tech", "VGT": "tech", "XLK": "tech",
    "IWM": "finance", "IWF": "finance", "IWD": "finance",
    "MDY": "finance", "IJR": "finance", "IJH": "finance",
    "TNA": "finance", "TZA": "finance",  # 3x leveraged small cap
    "ARKK": "tech", "ARKW": "tech", "ARKG": "healthcare", "ARKF": "finance",
    # Crypto → finance
    "BITB": "finance", "IBIT": "finance", "FBTC": "finance", "GBTC": "finance",
    "ETHE": "finance", "BITO": "finance",
    # Energy ETFs
    "XLE": "energy", "VDE": "energy", "IEO": "energy", "OIH": "energy",
    "AMLP": "energy", "EMLP": "energy", "USO": "energy", "UNG": "energy",
    "XOP": "energy", "FCG": "energy", "TPYP": "energy",
    # Commodities → energy/finance
    "SLV": "finance", "GLD": "finance", "IAU": "finance",
    "PALL": "energy", "PPLT": "energy", "FTGC": "energy",
    "DBC": "energy", "PDBC": "energy", "GSG": "energy",
    # Healthcare ETFs
    "XLV": "healthcare", "VHT": "healthcare", "IBB": "healthcare",
    "XBI": "healthcare", "IHI": "healthcare",
    # Defense ETFs
    "ITA": "defense", "PPA": "defense", "XAR": "defense", "DFEN": "defense",
    # Agriculture ETFs
    "DBA": "agriculture", "MOO": "agriculture", "VEGI": "agriculture",
    # Telecom ETFs
    "IYZ": "telecom", "VOX": "telecom", "XLC": "telecom", "FCOM": "telecom",
    # Financials ETFs
    "XLF": "finance", "VFH": "finance", "KBE": "finance", "KRE": "finance",
    "IAI": "finance",
    # Real Estate → finance
    "VNQ": "finance", "SCHH": "finance", "IYR": "finance",
    "VNQI": "finance",  # Global ex-US Real Estate
    # Utilities → energy
    "XLU": "energy", "VPU": "energy",
    # International / EM → finance
    "EFA": "finance", "VEA": "finance", "IEFA": "finance", "VWO": "finance",
    "EEM": "finance", "SCHE": "finance", "IEMG": "finance",
    "GEM": "finance",  # Goldman Sachs EM Equity
    "SMCY": "finance",  # RBC BlueBay
    # Dividend / Income → finance
    "VYM": "finance", "SCHD": "finance", "DVY": "finance", "HDV": "finance",
    "JEPI": "finance", "JEPQ": "finance", "DIVO": "finance",
    # Individual stocks with known sectors (common ones missing from sector map)
    "STX": "tech",  # Seagate
    "CHRW": "finance",  # C.H. Robinson (logistics)
    "RS": "defense",  # Reliance Steel (defense supplier)
}


def fix_sectors():
    """Expand _combined_sector_map.json with ETF classifications and update DB."""
    map_path = (
        Path(__file__).resolve().parent.parent
        / "backend" / "data" / "raw" / "_combined_sector_map.json"
    )

    # Load existing map
    if map_path.exists():
        with open(map_path) as f:
            sector_map = json.load(f)
    else:
        sector_map = {}

    # Add ETF mappings (don't overwrite existing entries)
    added = 0
    for ticker, sector in ETF_SECTOR_MAP.items():
        if ticker not in sector_map:
            sector_map[ticker] = sector
            added += 1

    # Save updated map
    with open(map_path, "w") as f:
        json.dump(sector_map, f, indent=2, sort_keys=True)
    print(f"Sector map: {len(sector_map)} total entries ({added} new ETFs added)")

    # Update trades.industry_sector in DB for newly mapped tickers
    engine = get_engine()
    with engine.connect() as conn:
        updated = 0
        for ticker, sector in ETF_SECTOR_MAP.items():
            result = conn.execute(
                text("""
                    UPDATE trades
                    SET industry_sector = :sector
                    WHERE ticker = :ticker
                      AND (industry_sector IS NULL OR industry_sector = '')
                """),
                {"sector": sector, "ticker": ticker},
            )
            updated += result.rowcount

        # Also update trade_sectors junction table
        for ticker, sector in ETF_SECTOR_MAP.items():
            # Get trade IDs for this ticker that don't have a sector entry
            trade_ids = conn.execute(
                text("""
                    SELECT t.id FROM trades t
                    LEFT JOIN trade_sectors ts ON t.id = ts.trade_id AND ts.sector = :sector
                    WHERE t.ticker = :ticker AND ts.trade_id IS NULL
                """),
                {"ticker": ticker, "sector": sector},
            ).fetchall()

            if trade_ids:
                conn.execute(
                    text("INSERT IGNORE INTO trade_sectors (trade_id, sector) VALUES (:tid, :sector)"),
                    [{"tid": r[0], "sector": sector} for r in trade_ids],
                )

        conn.commit()

    print(f"Updated {updated} trade rows with new sector tags")

    # Report coverage
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM trades")).scalar()
        null_sector = conn.execute(
            text("SELECT COUNT(*) FROM trades WHERE industry_sector IS NULL OR industry_sector = ''")
        ).scalar()
        ts_coverage = conn.execute(
            text("SELECT COUNT(DISTINCT trade_id) FROM trade_sectors")
        ).scalar()
        print(f"Trades: {total - null_sector}/{total} with industry_sector ({100*(total-null_sector)/total:.1f}%)")
        print(f"Trade_sectors junction: {ts_coverage}/{total} trades covered ({100*ts_coverage/total:.1f}%)")


# ── Verify all gaps ──────────────────────────────────────────────────────────

def verify():
    """Print coverage stats for all three gaps."""
    engine = get_engine()
    with engine.connect() as conn:
        # Committees
        total_c = conn.execute(text("SELECT COUNT(*) FROM committees")).scalar()
        tagged_c = conn.execute(
            text("SELECT COUNT(*) FROM committees WHERE sector_tag IS NOT NULL")
        ).scalar()
        print(f"Committees: {tagged_c}/{total_c} tagged ({100*tagged_c/total_c:.1f}%)")

        # Prices
        tickers_needing = conn.execute(text("""
            SELECT COUNT(DISTINCT t.ticker)
            FROM trades t
            LEFT JOIN stock_prices sp ON t.ticker = sp.ticker
            WHERE sp.ticker IS NULL AND t.ticker IS NOT NULL
              AND t.ticker REGEXP '^[A-Za-z]+$' AND CHAR_LENGTH(t.ticker) <= 5
        """)).scalar()
        total_tickers = conn.execute(
            text("SELECT COUNT(DISTINCT ticker) FROM trades WHERE ticker IS NOT NULL")
        ).scalar()
        price_tickers = conn.execute(
            text("SELECT COUNT(DISTINCT ticker) FROM stock_prices")
        ).scalar()
        print(f"Price tickers: {price_tickers}/{total_tickers} have data ({tickers_needing} still missing)")

        # Trades
        total_t = conn.execute(text("SELECT COUNT(*) FROM trades")).scalar()
        null_t = conn.execute(
            text("SELECT COUNT(*) FROM trades WHERE industry_sector IS NULL OR industry_sector = ''")
        ).scalar()
        ts = conn.execute(
            text("SELECT COUNT(DISTINCT trade_id) FROM trade_sectors")
        ).scalar()
        print(f"Trades: {total_t - null_t}/{total_t} with industry_sector ({100*(total_t-null_t)/total_t:.1f}%)")
        print(f"Trade_sectors: {ts}/{total_t} covered ({100*ts/total_t:.1f}%)")

        # Bills (for reference)
        total_b = conn.execute(text("SELECT COUNT(*) FROM bills")).scalar()
        usable_b = conn.execute(text("""
            SELECT COUNT(*) FROM bills
            WHERE policy_area IS NOT NULL AND latest_action_date IS NOT NULL
        """)).scalar()
        print(f"Bills: {usable_b}/{total_b} usable for bill_proximity ({100*usable_b/total_b:.1f}%)")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "committees":
        fix_committees()
    elif cmd == "prices":
        fix_prices()
    elif cmd == "sectors":
        fix_sectors()
    elif cmd == "all":
        print("=" * 60)
        print("GAP 1: Fixing committees.sector_tag")
        print("=" * 60)
        fix_committees()
        print()
        print("=" * 60)
        print("GAP 2: Fixing missing stock prices")
        print("=" * 60)
        fix_prices()
        print()
        print("=" * 60)
        print("GAP 3: Fixing trades.industry_sector")
        print("=" * 60)
        fix_sectors()
        print()
        print("=" * 60)
        print("VERIFICATION")
        print("=" * 60)
        verify()
    elif cmd == "verify":
        verify()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
