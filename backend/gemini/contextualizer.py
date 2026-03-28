"""
Gemini per-trade contextualizer.

Reads scored trade context from MySQL, generates structured analysis with Gemini,
and upserts results into audit_reports.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text

from backend.db.connection import get_engine

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None


SYSTEM_PROMPT = """
You are a non-partisan financial ethics investigator.
Given congressional trade data and dual anomaly scores, produce factual,
concise analysis with no speculation and output strict JSON.
""".strip()


@dataclass
class ContextualizerResult:
    payload: dict[str, Any]
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None


def _risk_level_for_quadrant(quadrant: str) -> str:
    mapping = {
        "SEVERE": "very_high",
        "SYSTEMIC": "high",
        "OUTLIER": "medium",
        "UNREMARKABLE": "low",
    }
    return mapping.get((quadrant or "").upper(), "medium")


def _safe_json_loads(raw: str) -> dict[str, Any]:
    text_raw = raw.strip()
    if text_raw.startswith("```"):
        text_raw = text_raw.strip("`")
        if text_raw.startswith("json"):
            text_raw = text_raw[4:].strip()
    return json.loads(text_raw)


def build_initial_message(trade: dict[str, Any]) -> str:
    return f"""
Investigate this congressional trade and produce JSON output only.

Politician: {trade.get('full_name')} ({trade.get('bioguide_id')})
Ticker: {trade.get('ticker')}
Trade Type: {trade.get('trade_type')}
Trade Date: {trade.get('trade_date')}
Disclosure Date: {trade.get('disclosure_date')}
Disclosure Lag Days: {trade.get('disclosure_lag_days')}
Amount Midpoint: {trade.get('amount_midpoint')}
Industry Sector: {trade.get('industry_sector')}

Cohort Index: {trade.get('cohort_index')}
Baseline Index: {trade.get('baseline_index')}
Severity Quadrant: {trade.get('severity_quadrant')}

Feature Snapshot:
- cohort_alpha: {trade.get('feat_cohort_alpha')}
- pre_trade_alpha: {trade.get('feat_pre_trade_alpha')}
- proximity_days: {trade.get('feat_proximity_days')}
- bill_proximity: {trade.get('feat_bill_proximity')}
- has_proximity_data: {trade.get('feat_has_proximity_data')}
- committee_relevance: {trade.get('feat_committee_relevance')}
- amount_zscore: {trade.get('feat_amount_zscore')}
- cluster_score: {trade.get('feat_cluster_score')}
- disclosure_lag: {trade.get('feat_disclosure_lag')}

Output schema:
{{
  "headline": "string <= 120 chars",
  "narrative": "2-4 sentence explanation",
  "bill_excerpt": "string or null",
  "evidence_json": {{
    "key_factors": ["string"],
    "score_driver": "cohort|baseline|both"
  }},
  "disclaimer": "string",
  "video_prompt": "string or null",
  "narration_script": "string or null"
}}
""".strip()


def _fallback_report(trade: dict[str, Any]) -> ContextualizerResult:
    quadrant = (trade.get("severity_quadrant") or "UNREMARKABLE").upper()
    severe = quadrant == "SEVERE"
    payload = {
        "headline": f"{trade.get('ticker')} trade flagged as {quadrant.lower()} by dual-model analysis",
        "narrative": (
            f"This trade received cohort index {trade.get('cohort_index')} and "
            f"baseline index {trade.get('baseline_index')}, placing it in the {quadrant} quadrant. "
            "The score reflects statistical anomaly features, not proof of wrongdoing."
        ),
        "bill_excerpt": None,
        "evidence_json": {
            "key_factors": [
                f"cohort_index={trade.get('cohort_index')}",
                f"baseline_index={trade.get('baseline_index')}",
                f"proximity_days={trade.get('feat_proximity_days')}",
                f"committee_relevance={trade.get('feat_committee_relevance')}",
            ],
            "score_driver": "both" if severe else "baseline",
        },
        "disclaimer": "Automated anomaly scoring is an investigative lead, not a legal determination.",
        "video_prompt": (
            "Dark newsroom desk, legal documents, subtle motion graphics, investigative tone, 9:16"
            if severe
            else None
        ),
        "narration_script": (
            f"House Advantage flagged a {trade.get('ticker')} trade in the {quadrant} quadrant based on dual-model anomaly signals."
            if severe
            else None
        ),
    }
    return ContextualizerResult(payload=payload, model="fallback")


def _generate_with_gemini(initial_message: str) -> ContextualizerResult:
    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

    if not api_key or genai is None:
        raise RuntimeError("Gemini client unavailable or GEMINI_API_KEY not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=model_name, system_instruction=SYSTEM_PROMPT)
    response = model.generate_content(initial_message)
    parsed = _safe_json_loads(response.text)

    usage = getattr(response, "usage_metadata", None)
    return ContextualizerResult(
        payload=parsed,
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
        model=model_name,
    )


def _fetch_trade_context(trade_id: int) -> dict[str, Any] | None:
    engine = get_engine()
    sql = text(
        """
        SELECT
          t.id AS trade_id,
          t.ticker,
          t.trade_type,
          t.trade_date,
          t.disclosure_date,
          t.disclosure_lag_days,
          t.amount_midpoint,
          t.industry_sector,
          p.bioguide_id,
          p.full_name,
          a.cohort_index,
          a.baseline_index,
          a.severity_quadrant,
          a.feat_cohort_alpha,
          a.feat_pre_trade_alpha,
          a.feat_proximity_days,
          a.feat_bill_proximity,
          a.feat_has_proximity_data,
          a.feat_committee_relevance,
          a.feat_amount_zscore,
          a.feat_cluster_score,
          a.feat_disclosure_lag
        FROM trades t
        JOIN anomaly_scores a ON a.trade_id = t.id
        LEFT JOIN politicians p ON p.id = t.politician_id
        WHERE t.id = :trade_id
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"trade_id": trade_id}).mappings().first()
        return dict(row) if row else None


def _upsert_audit_report(trade_id: int, trade: dict[str, Any], result: ContextualizerResult) -> None:
    payload = result.payload
    quadrant = (trade.get("severity_quadrant") or "UNREMARKABLE").upper()
    risk = _risk_level_for_quadrant(quadrant)

    sql = text(
        """
        INSERT INTO audit_reports (
          trade_id, headline, risk_level, severity_quadrant, narrative,
          evidence_json, bill_excerpt, disclaimer, video_prompt, narration_script,
          gemini_model, prompt_tokens, output_tokens
        ) VALUES (
          :trade_id, :headline, :risk_level, :severity_quadrant, :narrative,
          :evidence_json, :bill_excerpt, :disclaimer, :video_prompt, :narration_script,
          :gemini_model, :prompt_tokens, :output_tokens
        )
        ON DUPLICATE KEY UPDATE
          generated_at = CURRENT_TIMESTAMP,
          headline = VALUES(headline),
          risk_level = VALUES(risk_level),
          severity_quadrant = VALUES(severity_quadrant),
          narrative = VALUES(narrative),
          evidence_json = VALUES(evidence_json),
          bill_excerpt = VALUES(bill_excerpt),
          disclaimer = VALUES(disclaimer),
          video_prompt = VALUES(video_prompt),
          narration_script = VALUES(narration_script),
          gemini_model = VALUES(gemini_model),
          prompt_tokens = VALUES(prompt_tokens),
          output_tokens = VALUES(output_tokens)
        """
    )

    params = {
        "trade_id": trade_id,
        "headline": payload.get("headline") or "Automated audit report",
        "risk_level": risk,
        "severity_quadrant": quadrant,
        "narrative": payload.get("narrative") or "No narrative generated.",
        "evidence_json": json.dumps(payload.get("evidence_json") or {}),
        "bill_excerpt": payload.get("bill_excerpt"),
        "disclaimer": payload.get("disclaimer") or "Automated analysis; interpret with caution.",
        "video_prompt": payload.get("video_prompt"),
        "narration_script": payload.get("narration_script"),
        "gemini_model": result.model,
        "prompt_tokens": result.prompt_tokens,
        "output_tokens": result.output_tokens,
    }

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(sql, params)


def contextualize_trade(trade_id: int, force: bool = False) -> dict[str, Any]:
    trade = _fetch_trade_context(trade_id)
    if not trade:
        raise ValueError(f"Trade {trade_id} not found or not scored")

    if not force and (trade.get("severity_quadrant") or "").upper() not in {"SEVERE", "SYSTEMIC"}:
        return {"status": "skipped", "reason": "quadrant not eligible", "trade_id": trade_id}

    initial = build_initial_message(trade)

    try:
        result = _generate_with_gemini(initial)
    except Exception:
        result = _fallback_report(trade)

    _upsert_audit_report(trade_id=trade_id, trade=trade, result=result)
    return {
        "status": "ok",
        "trade_id": trade_id,
        "quadrant": trade.get("severity_quadrant"),
        "model": result.model,
    }


def contextualize_flagged_trades(limit: int = 100, since_date: date | None = None) -> dict[str, Any]:
    engine = get_engine()
    base_sql = """
        SELECT t.id AS trade_id
        FROM trades t
        JOIN anomaly_scores a ON a.trade_id = t.id
        WHERE a.severity_quadrant IN ('SEVERE', 'SYSTEMIC')
    """
    params: dict[str, Any] = {"limit": limit}
    if since_date:
        base_sql += " AND t.trade_date >= :since_date"
        params["since_date"] = since_date

    base_sql += " ORDER BY t.trade_date DESC LIMIT :limit"

    with engine.connect() as conn:
        rows = conn.execute(text(base_sql), params).mappings().all()

    processed = 0
    failed: list[dict[str, Any]] = []

    for row in rows:
        tid = int(row["trade_id"])
        try:
            contextualize_trade(tid)
            processed += 1
        except Exception as exc:  # pragma: no cover
            failed.append({"trade_id": tid, "error": str(exc)})

    return {"processed": processed, "failed": failed, "total": len(rows)}
