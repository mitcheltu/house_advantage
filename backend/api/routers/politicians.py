from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from backend.db.connection import get_engine
from backend.scoring.dual_scorer import _parse_sector

router = APIRouter(prefix="/api/v1", tags=["politicians"])


@router.get("/politicians")
def list_politicians(
    search: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    engine = get_engine()

    where = ""
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if search:
        where = "WHERE LOWER(p.full_name) LIKE :q OR LOWER(p.bioguide_id) LIKE :q OR LOWER(p.state) LIKE :q"
        params["q"] = f"%{search.lower()}%"

    sql = text(
        f"""
        SELECT
          p.id,
          p.bioguide_id,
          p.full_name,
          p.party,
          p.state,
          p.chamber,
          p.district,
          p.start_date,
          p.end_date,
          p.url
        FROM politicians p
        {where}
        ORDER BY p.full_name ASC
        LIMIT :limit OFFSET :offset
        """
    )

    count_sql = text(
        f"""
        SELECT COUNT(*) AS total
        FROM politicians p
        {where}
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
        total_row = conn.execute(count_sql, {k: v for k, v in params.items() if k == "q"}).mappings().first()

    return {
        "items": [dict(r) for r in rows],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(rows),
            "total": int((total_row or {}).get("total") or 0),
        },
        "filters": {"search": search or ""},
    }


@router.get("/politician/{politician_id}")
def get_politician(politician_id: str, limit: int = Query(default=50, ge=1, le=200)) -> dict:
    engine = get_engine()

    is_numeric = politician_id.isdigit()
    where = "p.id = :pid" if is_numeric else "p.bioguide_id = :pid"
    pid_val = int(politician_id) if is_numeric else politician_id

    profile_sql = text(
        f"""
        SELECT p.id, p.bioguide_id, p.full_name, p.party, p.state, p.chamber,
               p.district, p.start_date, p.end_date, p.url
        FROM politicians p
        WHERE {where}
        LIMIT 1
        """
    )

    trades_sql = text(
        f"""
        SELECT
          t.id AS trade_id,
          t.trade_date,
          t.ticker,
          t.company_name,
          t.trade_type,
          t.amount_midpoint,
          t.disclosure_date,
          t.disclosure_lag_days,
          t.industry_sector,
          a.cohort_index,
          a.baseline_index,
          a.severity_quadrant,
          a.audit_triggered,
          ar.id AS audit_report_id,
          ar.headline AS audit_headline,
          ar.risk_level
        FROM politicians p
        JOIN trades t ON t.politician_id = p.id
        LEFT JOIN anomaly_scores a ON a.trade_id = t.id
        LEFT JOIN audit_reports ar ON ar.trade_id = t.id
        WHERE {where}
        ORDER BY t.trade_date DESC
        LIMIT :limit
        """
    )

    agg_sql = text(
        f"""
        SELECT
          COUNT(*) AS total_trades,
          SUM(CASE WHEN a.severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END) AS severe_count,
          SUM(CASE WHEN a.severity_quadrant = 'SYSTEMIC' THEN 1 ELSE 0 END) AS systemic_count,
          SUM(CASE WHEN a.severity_quadrant = 'OUTLIER' THEN 1 ELSE 0 END) AS outlier_count,
          SUM(CASE WHEN a.severity_quadrant = 'UNREMARKABLE' THEN 1 ELSE 0 END) AS unremarkable_count,
          ROUND(AVG(a.cohort_index), 2) AS avg_cohort,
          ROUND(AVG(a.baseline_index), 2) AS avg_baseline
        FROM politicians p
        LEFT JOIN trades t ON t.politician_id = p.id
        LEFT JOIN anomaly_scores a ON a.trade_id = t.id
        WHERE {where}
        """
    )

    with engine.connect() as conn:
        profile = conn.execute(profile_sql, {"pid": pid_val}).mappings().first()
        if not profile:
            raise HTTPException(status_code=404, detail="Politician not found")

        trades = conn.execute(trades_sql, {"pid": pid_val, "limit": limit}).mappings().all()
        aggregate = conn.execute(agg_sql, {"pid": pid_val}).mappings().first()

    return {
        "politician": dict(profile),
        "aggregate": {
            "total_trades": int(aggregate["total_trades"] or 0),
            "quadrants": {
                "SEVERE": int(aggregate["severe_count"] or 0),
                "SYSTEMIC": int(aggregate["systemic_count"] or 0),
                "OUTLIER": int(aggregate["outlier_count"] or 0),
                "UNREMARKABLE": int(aggregate["unremarkable_count"] or 0),
            },
            "avg_cohort_index": float(aggregate["avg_cohort"] or 0.0),
            "avg_baseline_index": float(aggregate["avg_baseline"] or 0.0),
        },
        "trades": [{**dict(t), "sectors": _parse_sector(t.get("industry_sector"))} for t in trades],
    }
