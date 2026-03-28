"""
yfinance Collector — Historical Stock Prices

Downloads daily OHLCV data for tickers found in congressional trades,
plus SPY as the market benchmark for cohort_alpha computation.
No API key needed.
"""
import logging
from pathlib import Path

import pandas as pd
import yfinance as yf

from .utils import DATA_RAW

log = logging.getLogger("collector.prices")

BENCHMARK_TICKER = "SPY"
PRICE_DIR = DATA_RAW / "prices"


def collect_prices(
    tickers: list[str] | None = None,
    period: str = "3y",
    interval: str = "1d",
) -> dict[str, pd.DataFrame]:
    """
    Download daily price data for given tickers + SPY benchmark.
    Saves individual CSVs to data/raw/prices/{TICKER}.csv

    Args:
        tickers: List of ticker symbols. If None, reads from congressional_trades_raw.csv.
        period: yfinance download period (e.g. "3y", "5y", "max")
        interval: Price interval (default: "1d")

    Returns:
        Dict of ticker → DataFrame with OHLCV data
    """
    PRICE_DIR.mkdir(parents=True, exist_ok=True)

    # Auto-discover tickers from trade data if not provided
    if tickers is None:
        trades_path = DATA_RAW / "congressional_trades_raw.csv"
        if trades_path.exists():
            trades_df = pd.read_csv(trades_path)
            if "ticker" in trades_df.columns:
                tickers = trades_df["ticker"].dropna().unique().tolist()
                log.info(f"Auto-discovered {len(tickers)} tickers from trade data")
            else:
                log.warning("No 'ticker' column in trades file")
                tickers = []
        else:
            log.warning("No trades file found. Run disclosure collectors first.")
            tickers = []

    # Ensure benchmark is included
    if BENCHMARK_TICKER not in tickers:
        tickers.append(BENCHMARK_TICKER)

    # Remove duplicates and invalid tickers
    tickers = sorted(set(t.upper().strip() for t in tickers if t and t.isalpha() and len(t) <= 5))
    log.info(f"Downloading prices for {len(tickers)} tickers (period={period})...")

    results = {}
    failed = []

    for i, ticker in enumerate(tickers):
        try:
            csv_path = PRICE_DIR / f"{ticker}.csv"

            # Skip if recently downloaded (within last day)
            if csv_path.exists():
                existing = pd.read_csv(csv_path)
                if len(existing) > 0:
                    last_date = pd.to_datetime(existing.iloc[-1].get("Date", "2000-01-01"))
                    if (pd.Timestamp.now() - last_date).days <= 1:
                        log.debug(f"  {ticker}: cached ({len(existing)} rows)")
                        results[ticker] = existing
                        continue

            data = yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )

            if data.empty:
                log.warning(f"  {ticker}: no data returned")
                failed.append(ticker)
                continue

            # Flatten multi-level columns if present
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            data = data.reset_index()
            data.to_csv(csv_path, index=False)
            results[ticker] = data
            log.debug(f"  {ticker}: {len(data)} rows saved")

        except Exception as e:
            log.warning(f"  {ticker}: failed — {e}")
            failed.append(ticker)

        # Progress log every 50 tickers
        if (i + 1) % 50 == 0:
            log.info(f"  Progress: {i + 1}/{len(tickers)} tickers downloaded")

    log.info(f"Price download complete: {len(results)} succeeded, {len(failed)} failed")
    if failed:
        log.info(f"  Failed tickers: {failed[:20]}{'...' if len(failed) > 20 else ''}")

    # Save a manifest of downloaded tickers
    manifest = pd.DataFrame({
        "ticker": list(results.keys()),
        "rows": [len(df) for df in results.values()],
    })
    manifest.to_csv(PRICE_DIR / "_manifest.csv", index=False)

    return results


def get_price_for_ticker(ticker: str) -> pd.DataFrame | None:
    """Load cached price data for a single ticker."""
    csv_path = PRICE_DIR / f"{ticker.upper()}.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path, parse_dates=["Date"])
    return None


if __name__ == "__main__":
    collect_prices()
