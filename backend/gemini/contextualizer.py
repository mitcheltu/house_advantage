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
from backend.scoring.dual_scorer import BILL_SECTOR_MAP, _parse_sector

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None


SYSTEM_PROMPT = """
You are a non-partisan financial ethics investigator.
Given congressional trade data and dual anomaly scores, produce factual,
concise analysis with no speculation and output strict JSON.

When generating citation_image_prompts, each prompt must instruct an image model
to create a dark-themed infographic citation card with the following design:
- Background: #090d14, text: #e5ebf5, clean sans-serif typography
- Top edge: severity stripe in red (#dc2626 for SEVERE) or amber (#d97706 for SYSTEMIC)
- Large bold title: the bill number and full title (e.g. "H.R. 3847 — National Defense Authorization Act")
- Small badge/pill below title: "Policy Area: {policy_area}"
- Two-column key details: Status (latest action + date), Sponsor (if known),
  Trade Connection (politician name, dollar amount, ticker, timing relative to bill action)
- Bottom: small source URL text (congress.gov link) and watermark "AI-Generated — House Advantage"
- Aspect ratio 16:9, high legibility, no photographs, no real faces, data visualization style
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


def _fetch_nearby_bills(trade_date, trade_sector, limit: int = 3) -> list[dict[str, Any]]:
    """Fetch bills matching the trade's sector within ±90 days of trade_date.

    Returns up to *limit* bills ordered by proximity (closest first).
    """
    if not trade_date or not trade_sector:
        return []

    sectors = trade_sector if isinstance(trade_sector, list) else _parse_sector(trade_sector)
    if not sectors:
        return []

    # Reverse-map: find policy_area values whose BILL_SECTOR_MAP output is in the trade's sectors
    matching_policy_areas = [
        pa for pa, s in BILL_SECTOR_MAP.items() if s in sectors
    ]
    if not matching_policy_areas:
        return []

    # Build parameterised IN clause
    placeholders = ", ".join(f":pa{i}" for i in range(len(matching_policy_areas)))
    params: dict[str, Any] = {f"pa{i}": pa for i, pa in enumerate(matching_policy_areas)}
    params["trade_date"] = str(trade_date)
    params["limit"] = limit

    sql = text(f"""
        SELECT
          bill_id, title, policy_area, latest_action_date, url
        FROM bills
        WHERE policy_area IN ({placeholders})
          AND latest_action_date IS NOT NULL
          AND latest_action_date BETWEEN DATE_SUB(:trade_date, INTERVAL 90 DAY)
                                     AND DATE_ADD(:trade_date, INTERVAL 90 DAY)
        ORDER BY ABS(DATEDIFF(latest_action_date, :trade_date)) ASC
        LIMIT :limit
    """)

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
        return [dict(r) for r in rows]


def build_initial_message(trade: dict[str, Any]) -> str:
    # Build nearby bills section
    bills_section = ""
    nearby_bills = trade.get("nearby_bills") or []
    if nearby_bills:
        bill_lines = []
        for b in nearby_bills:
            bill_lines.append(
                f"  - {b.get('bill_id')}: {b.get('title')}\n"
                f"    Policy Area: {b.get('policy_area')}\n"
                f"    Action Date: {b.get('latest_action_date')}\n"
                f"    URL: {b.get('url') or 'N/A'}"
            )
        bills_section = "\nRelevant Bills (sector-matched, ±90 days):\n" + "\n".join(bill_lines) + "\n"

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
{bills_section}
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
  "video_prompt": "REQUIRED string for SEVERE trades: cinematic visual direction for a ~10s investigative news segment (9:16 vertical). null only for non-SEVERE trades.",
  "narration_script": "REQUIRED string for SEVERE trades: 1-2 sentence TTS narration (~15-25 words) summarising the flagged trade for a news-style video. null only for non-SEVERE trades.",
  "citation_image_prompts": ["one detailed image-generation prompt per relevant bill following the citation card design spec in system instructions, or empty list if no bills"]
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
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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
        if not row:
            return None
        result = dict(row)
        # Parse stringified sector lists from DB into clean display format
        sectors = _parse_sector(result.get("industry_sector"))
        result["industry_sector"] = ", ".join(sectors) if sectors else None

        # Fetch nearby bills matching trade sector within ±90 days
        result["nearby_bills"] = _fetch_nearby_bills(
            trade_date=result.get("trade_date"),
            trade_sector=sectors,
        )

        return result


def _upsert_audit_report(trade_id: int, trade: dict[str, Any], result: ContextualizerResult) -> None:
    payload = result.payload
    quadrant = (trade.get("severity_quadrant") or "UNREMARKABLE").upper()
    risk = _risk_level_for_quadrant(quadrant)

    # Ensure SEVERE trades always have video_prompt and narration_script
    if quadrant == "SEVERE":
        if not payload.get("video_prompt"):
            payload["video_prompt"] = (
                "Dark newsroom desk, scattered legal documents and stock charts, "
                "subtle motion graphics highlighting anomaly data, investigative tone, 9:16"
            )
        if not payload.get("narration_script"):
            payload["narration_script"] = (
                f"House Advantage flagged a {trade.get('ticker')} trade by "
                f"{trade.get('full_name', 'a member of Congress')} in the SEVERE quadrant "
                f"based on dual-model anomaly signals."
            )

    sql = text(
        """
        INSERT INTO audit_reports (
          trade_id, headline, risk_level, severity_quadrant, narrative,
          evidence_json, bill_excerpt, disclaimer, video_prompt, narration_script,
          citation_image_prompts,
          gemini_model, prompt_tokens, output_tokens
        ) VALUES (
          :trade_id, :headline, :risk_level, :severity_quadrant, :narrative,
          :evidence_json, :bill_excerpt, :disclaimer, :video_prompt, :narration_script,
          :citation_image_prompts,
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
          citation_image_prompts = VALUES(citation_image_prompts),
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
        "citation_image_prompts": json.dumps(payload.get("citation_image_prompts") or []),
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
