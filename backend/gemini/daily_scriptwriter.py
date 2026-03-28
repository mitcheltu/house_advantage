"""
Gemini daily scriptwriter.

Aggregates today's flagged trades and writes one row into daily_reports.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from backend.db.connection import get_engine

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None


PROMPT_TEMPLATE = """
You are the scriptwriter for House Advantage.
Write concise JSON only:
{
  "narration_script": "~75 words",
  "veo_prompt": "visual direction string"
}

Date: {report_date}
Flagged Trades:
{items}
""".strip()


def _safe_json(raw: str) -> dict[str, Any]:
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.startswith("json"):
            txt = txt[4:].strip()
    return json.loads(txt)


def _fetch_flagged_for_date(report_date: date) -> list[dict[str, Any]]:
    engine = get_engine()
    sql = text(
        """
        SELECT
          t.id AS trade_id,
          t.ticker,
          t.trade_type,
          t.trade_date,
          t.amount_midpoint,
          p.full_name,
          p.party,
          p.state,
          a.cohort_index,
          a.baseline_index,
          a.severity_quadrant,
          ar.headline,
          ar.narrative
        FROM trades t
        JOIN anomaly_scores a ON a.trade_id = t.id
        LEFT JOIN politicians p ON p.id = t.politician_id
        LEFT JOIN audit_reports ar ON ar.trade_id = t.id
        WHERE t.trade_date = :report_date
          AND a.severity_quadrant IN ('SEVERE', 'SYSTEMIC')
        ORDER BY GREATEST(a.cohort_index, a.baseline_index) DESC
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"report_date": report_date}).mappings().all()
    return [dict(r) for r in rows]


def _fallback_daily_payload(report_date: date, trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "narration_script": f"This is House Advantage for {report_date}. No SEVERE or SYSTEMIC trades were recorded today.",
            "veo_prompt": "Calm newsroom background, subtle data charts, neutral tone, 9:16",
        }

    top = trades[:3]
    mentions = "; ".join(
        f"{t.get('full_name')} {t.get('trade_type')} {t.get('ticker')} ({t.get('severity_quadrant')})"
        for t in top
    )
    return {
        "narration_script": (
            f"This is House Advantage for {report_date}. Today's highest-risk activity includes {mentions}. "
            "These flags are statistical anomalies for public-interest review and not proof of misconduct."
        ),
        "veo_prompt": "Investigative newsroom open, document overlays, market chart motion graphics, serious broadcast tone, 9:16",
    }


def _generate_with_gemini(report_date: date, trades: list[dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
    if not api_key or genai is None:
        raise RuntimeError("Gemini not configured")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=model_name)

    lines = []
    for t in trades[:12]:
        lines.append(
            f"- trade_id={t['trade_id']} | {t.get('full_name')} | {t.get('ticker')} | "
            f"cohort={t.get('cohort_index')} baseline={t.get('baseline_index')} quadrant={t.get('severity_quadrant')}"
        )
        if t.get("headline"):
            lines.append(f"  headline: {t['headline']}")

    prompt = PROMPT_TEMPLATE.format(report_date=report_date.isoformat(), items="\n".join(lines) or "- none")
    response = model.generate_content(prompt)
    payload = _safe_json(response.text)
    return payload, model_name


def _upsert_daily_report(report_date: date, trade_ids: list[int], payload: dict[str, Any], model_name: str | None) -> None:
    engine = get_engine()
    sql = text(
        """
        INSERT INTO daily_reports (
          report_date, trade_ids_covered, narration_script, veo_prompt,
          generation_status, generated_at
        ) VALUES (
          :report_date, :trade_ids_covered, :narration_script, :veo_prompt,
          'pending', CURRENT_TIMESTAMP
        )
        ON DUPLICATE KEY UPDATE
          trade_ids_covered = VALUES(trade_ids_covered),
          narration_script = VALUES(narration_script),
          veo_prompt = VALUES(veo_prompt),
          generated_at = CURRENT_TIMESTAMP
        """
    )

    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "report_date": report_date,
                "trade_ids_covered": json.dumps(trade_ids),
                "narration_script": payload.get("narration_script"),
                "veo_prompt": payload.get("veo_prompt"),
                "model_name": model_name,
            },
        )


def generate_daily_report(report_date: date | None = None) -> dict[str, Any]:
    target_date = report_date or datetime.utcnow().date()
    trades = _fetch_flagged_for_date(target_date)
    trade_ids = [int(t["trade_id"]) for t in trades]

    model_name = None
    try:
        if trades:
            payload, model_name = _generate_with_gemini(target_date, trades)
        else:
            payload = _fallback_daily_payload(target_date, trades)
            model_name = "fallback"
    except Exception:
        payload = _fallback_daily_payload(target_date, trades)
        model_name = "fallback"

    _upsert_daily_report(target_date, trade_ids, payload, model_name)
    return {
        "status": "ok",
        "report_date": target_date.isoformat(),
        "trade_count": len(trades),
        "model": model_name,
    }
