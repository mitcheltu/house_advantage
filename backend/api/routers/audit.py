from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from backend.db.connection import get_engine
from backend.gemini.gcs_storage import resolve_media_url

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit/{trade_id}")
def get_audit(trade_id: int) -> dict:
    engine = get_engine()

    trade_sql = text(
        """
        SELECT
          t.id AS trade_id,
          t.trade_date,
          t.disclosure_date,
          t.disclosure_lag_days,
          t.ticker,
          t.company_name,
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
          a.scored_at
        FROM trades t
        LEFT JOIN politicians p ON p.id = t.politician_id
        LEFT JOIN anomaly_scores a ON a.trade_id = t.id
        WHERE t.id = :trade_id
        LIMIT 1
        """
    )

    audit_sql = text(
        """
        SELECT
          id,
          trade_id,
          generated_at,
          headline,
          risk_level,
          severity_quadrant,
          narrative,
          evidence_json,
          bill_excerpt,
          disclaimer,
          video_prompt,
          narration_script,
          gemini_model,
          prompt_tokens,
          output_tokens
        FROM audit_reports
        WHERE trade_id = :trade_id
        LIMIT 1
        """
    )

    media_sql = text(
        """
        SELECT
          id,
          trade_id,
          audit_report_id,
          asset_type,
          storage_url,
          file_size_bytes,
          duration_seconds,
          resolution,
          generation_status,
          error_message,
          model_used,
          generated_at
        FROM media_assets
        WHERE trade_id = :trade_id
        ORDER BY generated_at DESC
        """
    )

    with engine.connect() as conn:
        trade = conn.execute(trade_sql, {"trade_id": trade_id}).mappings().first()
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")

        audit = conn.execute(audit_sql, {"trade_id": trade_id}).mappings().first()
        media = conn.execute(media_sql, {"trade_id": trade_id}).mappings().all()

    resolved_media = []
    for m in media:
        item = dict(m)
        if item.get("storage_url"):
            item["storage_url"] = resolve_media_url(item["storage_url"])
        resolved_media.append(item)

    return {
        "trade": dict(trade),
        "audit_report": dict(audit) if audit else None,
        "media_assets": resolved_media,
    }
