from fastapi import APIRouter, Query

from backend.gemini.pipeline_runner import run_daily_evidence_pipeline

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.post("/run-daily-evidence")
def run_daily_evidence_job(
    report_date: str | None = Query(default=None, description="YYYY-MM-DD, default UTC today"),
    contextualize_limit: int = Query(default=100, ge=1, le=500),
    severe_media_limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return run_daily_evidence_pipeline(
        report_date=report_date,
        contextualize_limit=contextualize_limit,
        severe_media_limit=severe_media_limit,
    )
