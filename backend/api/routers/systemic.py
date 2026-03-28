from fastapi import APIRouter, Query
from sqlalchemy import text

from backend.db.connection import get_engine

router = APIRouter(prefix="/api/v1", tags=["systemic"])


@router.get("/systemic")
def get_systemic_stats() -> dict:
    engine = get_engine()
    sql = text(
        """
        SELECT
          COUNT(*) AS total_scored,
          SUM(CASE WHEN severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END) AS severe_count,
          SUM(CASE WHEN severity_quadrant = 'SYSTEMIC' THEN 1 ELSE 0 END) AS systemic_count,
          SUM(CASE WHEN severity_quadrant = 'OUTLIER' THEN 1 ELSE 0 END) AS outlier_count,
          SUM(CASE WHEN severity_quadrant = 'UNREMARKABLE' THEN 1 ELSE 0 END) AS unremarkable_count,
          ROUND(AVG(cohort_index), 2) AS avg_cohort_index,
          ROUND(AVG(baseline_index), 2) AS avg_baseline_index,
          SUM(CASE WHEN audit_triggered = 1 THEN 1 ELSE 0 END) AS audit_triggered_count
        FROM anomaly_scores
        """
    )

    with engine.connect() as conn:
        row = conn.execute(sql).mappings().first()

    total = int(row["total_scored"] or 0)

    def pct(v: int) -> float:
        return round((v / total) * 100, 2) if total else 0.0

    severe = int(row["severe_count"] or 0)
    systemic = int(row["systemic_count"] or 0)
    outlier = int(row["outlier_count"] or 0)
    unremarkable = int(row["unremarkable_count"] or 0)
    audit_triggered = int(row["audit_triggered_count"] or 0)

    return {
        "total_scored": total,
        "quadrants": {
            "SEVERE": {"count": severe, "pct": pct(severe)},
            "SYSTEMIC": {"count": systemic, "pct": pct(systemic)},
            "OUTLIER": {"count": outlier, "pct": pct(outlier)},
            "UNREMARKABLE": {"count": unremarkable, "pct": pct(unremarkable)},
        },
        "audit_triggered": {"count": audit_triggered, "pct": pct(audit_triggered)},
        "averages": {
            "cohort_index": float(row["avg_cohort_index"] or 0.0),
            "baseline_index": float(row["avg_baseline_index"] or 0.0),
        },
    }


@router.get("/leaderboard")
def get_leaderboard(
    quadrant: str | None = Query(default=None, description="SEVERE|SYSTEMIC|OUTLIER|UNREMARKABLE"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    engine = get_engine()

    where = ""
    params: dict[str, object] = {"limit": limit, "offset": offset}
    if quadrant:
        where = "WHERE a.severity_quadrant = :quadrant"
        params["quadrant"] = quadrant.upper()

    sql = text(
        f"""
        SELECT
          t.id AS trade_id,
          t.trade_date,
          t.ticker,
          t.trade_type,
          t.amount_midpoint,
          t.industry_sector,
          p.id AS politician_id,
          p.bioguide_id,
          p.full_name,
          p.party,
          p.state,
          a.cohort_index,
          a.baseline_index,
          a.severity_quadrant,
          a.audit_triggered,
          GREATEST(a.cohort_index, a.baseline_index) AS max_index
        FROM anomaly_scores a
        JOIN trades t ON t.id = a.trade_id
        LEFT JOIN politicians p ON p.id = t.politician_id
        {where}
        ORDER BY max_index DESC, t.trade_date DESC
        LIMIT :limit OFFSET :offset
        """
    )

    count_sql = text(
        f"""
        SELECT COUNT(*) AS total
        FROM anomaly_scores a
        {('WHERE a.severity_quadrant = :quadrant' if quadrant else '')}
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
        total_row = conn.execute(count_sql, {k: v for k, v in params.items() if k == "quadrant"}).mappings().first()

    return {
        "items": [dict(r) for r in rows],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(rows),
            "total": int(total_row["total"] or 0),
        },
        "filters": {"quadrant": quadrant.upper() if quadrant else None},
    }
