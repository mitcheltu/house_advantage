from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from backend.db.connection import get_engine

router = APIRouter(prefix="/api/v1", tags=["prices"])


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


@router.get("/prices")
def get_prices(
    ticker: str = Query(..., min_length=1, max_length=10),
    start: str | None = Query(default=None, description="YYYY-MM-DD"),
    end: str | None = Query(default=None, description="YYYY-MM-DD"),
    limit: int = Query(default=200, ge=10, le=2000),
) -> dict:
    start_date = _parse_date(start)
    end_date = _parse_date(end)

    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="start must be <= end")

    engine = get_engine()
    params: dict[str, object] = {"ticker": ticker.upper(), "limit": limit}

    where = "WHERE ticker = :ticker"
    if start_date:
        where += " AND price_date >= :start"
        params["start"] = start_date
    if end_date:
        where += " AND price_date <= :end"
        params["end"] = end_date

    sql = text(
        f"""
        SELECT price_date, close
        FROM stock_prices
        {where}
        ORDER BY price_date ASC
        LIMIT :limit
        """
    )

    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
    except ProgrammingError:
        return {
            "ticker": ticker.upper(),
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
            "count": 0,
            "prices": [],
            "warning": "stock_prices table not available",
        }

    return {
        "ticker": ticker.upper(),
        "start": start_date.isoformat() if start_date else None,
        "end": end_date.isoformat() if end_date else None,
        "count": len(rows),
        "prices": [
            {"date": row["price_date"].isoformat(), "close": float(row["close"])}
            for row in rows
        ],
    }
