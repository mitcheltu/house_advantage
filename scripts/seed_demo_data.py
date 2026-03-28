"""
Seed deterministic demo data for local development.

This gives the UI meaningful content without running full ingestion + scoring.

Usage:
    /Users/nicholastweedie/Desktop/house_advantage/.venv/bin/python scripts/seed_demo_data.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.connection import get_engine


DEMO_TRADE_PREFIX = "demo://trade/"


def seed_demo_data() -> None:
    engine = get_engine()

    with engine.begin() as conn:
        # Clean prior demo rows (idempotent reseed)
        conn.execute(
            text(
                """
                DELETE FROM media_assets
                WHERE trade_id IN (
                    SELECT id FROM trades WHERE source_url LIKE :prefix
                )
                """
            ),
            {"prefix": f"{DEMO_TRADE_PREFIX}%"},
        )

        conn.execute(
            text(
                """
                DELETE FROM audit_reports
                WHERE trade_id IN (
                    SELECT id FROM trades WHERE source_url LIKE :prefix
                )
                """
            ),
            {"prefix": f"{DEMO_TRADE_PREFIX}%"},
        )

        conn.execute(
            text(
                """
                DELETE FROM anomaly_scores
                WHERE trade_id IN (
                    SELECT id FROM trades WHERE source_url LIKE :prefix
                )
                """
            ),
            {"prefix": f"{DEMO_TRADE_PREFIX}%"},
        )

        conn.execute(text("DELETE FROM trades WHERE source_url LIKE :prefix"), {"prefix": f"{DEMO_TRADE_PREFIX}%"})
        conn.execute(text("DELETE FROM politicians WHERE bioguide_id LIKE 'DEMO%'") )

        # Politicians
        pol_rows = [
            {
                "bioguide_id": "DEMO0001",
                "full_name": "Alex Harper",
                "party": "Independent",
                "state": "CA",
                "district": "12",
                "chamber": "House",
            },
            {
                "bioguide_id": "DEMO0002",
                "full_name": "Jordan Reeves",
                "party": "Democrat",
                "state": "NY",
                "district": "",
                "chamber": "Senate",
            },
            {
                "bioguide_id": "DEMO0003",
                "full_name": "Morgan Blake",
                "party": "Republican",
                "state": "TX",
                "district": "7",
                "chamber": "House",
            },
        ]

        for row in pol_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO politicians (bioguide_id, full_name, party, state, district, chamber)
                    VALUES (:bioguide_id, :full_name, :party, :state, :district, :chamber)
                    """
                ),
                row,
            )

        pol_map = {
            r.bioguide_id: r.id
            for r in conn.execute(text("SELECT id, bioguide_id FROM politicians WHERE bioguide_id LIKE 'DEMO%'")).mappings().all()
        }

        # Trades
        trade_rows = [
            {
                "politician_id": pol_map["DEMO0001"],
                "ticker": "NVDA",
                "company_name": "NVIDIA Corp",
                "trade_type": "buy",
                "trade_date": date(2026, 3, 27),
                "disclosure_date": date(2026, 3, 29),
                "disclosure_lag_days": 2,
                "amount_lower": 100001,
                "amount_upper": 250000,
                "amount_midpoint": 175000,
                "asset_type": "stock",
                "industry_sector": "tech",
                "source_url": f"{DEMO_TRADE_PREFIX}1",
            },
            {
                "politician_id": pol_map["DEMO0002"],
                "ticker": "LMT",
                "company_name": "Lockheed Martin",
                "trade_type": "buy",
                "trade_date": date(2026, 3, 27),
                "disclosure_date": date(2026, 4, 2),
                "disclosure_lag_days": 6,
                "amount_lower": 50001,
                "amount_upper": 100000,
                "amount_midpoint": 75000,
                "asset_type": "stock",
                "industry_sector": "defense",
                "source_url": f"{DEMO_TRADE_PREFIX}2",
            },
            {
                "politician_id": pol_map["DEMO0003"],
                "ticker": "XOM",
                "company_name": "Exxon Mobil",
                "trade_type": "sell",
                "trade_date": date(2026, 3, 26),
                "disclosure_date": date(2026, 3, 31),
                "disclosure_lag_days": 5,
                "amount_lower": 15001,
                "amount_upper": 50000,
                "amount_midpoint": 32500,
                "asset_type": "stock",
                "industry_sector": "energy",
                "source_url": f"{DEMO_TRADE_PREFIX}3",
            },
            {
                "politician_id": pol_map["DEMO0001"],
                "ticker": "JPM",
                "company_name": "JPMorgan Chase",
                "trade_type": "buy",
                "trade_date": date(2026, 3, 25),
                "disclosure_date": date(2026, 3, 30),
                "disclosure_lag_days": 5,
                "amount_lower": 1001,
                "amount_upper": 15000,
                "amount_midpoint": 8000,
                "asset_type": "stock",
                "industry_sector": "finance",
                "source_url": f"{DEMO_TRADE_PREFIX}4",
            },
            {
                "politician_id": pol_map["DEMO0002"],
                "ticker": "PFE",
                "company_name": "Pfizer",
                "trade_type": "sell",
                "trade_date": date(2026, 3, 24),
                "disclosure_date": date(2026, 3, 28),
                "disclosure_lag_days": 4,
                "amount_lower": 1001,
                "amount_upper": 15000,
                "amount_midpoint": 9000,
                "asset_type": "stock",
                "industry_sector": "healthcare",
                "source_url": f"{DEMO_TRADE_PREFIX}5",
            },
        ]

        for row in trade_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO trades (
                        politician_id, ticker, company_name, trade_type, trade_date,
                        disclosure_date, disclosure_lag_days,
                        amount_lower, amount_upper, amount_midpoint,
                        asset_type, industry_sector, source_url
                    ) VALUES (
                        :politician_id, :ticker, :company_name, :trade_type, :trade_date,
                        :disclosure_date, :disclosure_lag_days,
                        :amount_lower, :amount_upper, :amount_midpoint,
                        :asset_type, :industry_sector, :source_url
                    )
                    """
                ),
                row,
            )

        demo_trades = conn.execute(
            text(
                """
                SELECT id, politician_id, ticker, trade_date, source_url
                FROM trades
                WHERE source_url LIKE :prefix
                ORDER BY id
                """
            ),
            {"prefix": f"{DEMO_TRADE_PREFIX}%"},
        ).mappings().all()

        score_by_source = {
            f"{DEMO_TRADE_PREFIX}1": (92, 95, "SEVERE", 1),
            f"{DEMO_TRADE_PREFIX}2": (44, 90, "SYSTEMIC", 1),
            f"{DEMO_TRADE_PREFIX}3": (81, 41, "OUTLIER", 1),
            f"{DEMO_TRADE_PREFIX}4": (22, 19, "UNREMARKABLE", 0),
            f"{DEMO_TRADE_PREFIX}5": (35, 33, "UNREMARKABLE", 0),
        }

        # Anomaly scores
        for t in demo_trades:
            cohort_idx, baseline_idx, quadrant, audit_triggered = score_by_source[t.source_url]
            conn.execute(
                text(
                    """
                    INSERT INTO anomaly_scores (
                        trade_id, politician_id, ticker, trade_date,
                        cohort_raw_score, cohort_label, cohort_index,
                        baseline_raw_score, baseline_label, baseline_index,
                        severity_quadrant, audit_triggered,
                        feat_cohort_alpha, feat_pre_trade_alpha,
                        feat_proximity_days, feat_bill_proximity,
                        feat_has_proximity_data, feat_committee_relevance,
                        feat_amount_zscore, feat_cluster_score,
                        feat_disclosure_lag, model_version
                    ) VALUES (
                        :trade_id, :politician_id, :ticker, :trade_date,
                        :cohort_raw_score, :cohort_label, :cohort_index,
                        :baseline_raw_score, :baseline_label, :baseline_index,
                        :severity_quadrant, :audit_triggered,
                        :feat_cohort_alpha, :feat_pre_trade_alpha,
                        :feat_proximity_days, :feat_bill_proximity,
                        :feat_has_proximity_data, :feat_committee_relevance,
                        :feat_amount_zscore, :feat_cluster_score,
                        :feat_disclosure_lag, :model_version
                    )
                    """
                ),
                {
                    "trade_id": t.id,
                    "politician_id": t.politician_id,
                    "ticker": t.ticker,
                    "trade_date": t.trade_date,
                    "cohort_raw_score": -0.10,
                    "cohort_label": -1 if cohort_idx >= 60 else 1,
                    "cohort_index": cohort_idx,
                    "baseline_raw_score": -0.14,
                    "baseline_label": -1 if baseline_idx >= 60 else 1,
                    "baseline_index": baseline_idx,
                    "severity_quadrant": quadrant,
                    "audit_triggered": audit_triggered,
                    "feat_cohort_alpha": 0.032,
                    "feat_pre_trade_alpha": 0.011,
                    "feat_proximity_days": 3,
                    "feat_bill_proximity": 6,
                    "feat_has_proximity_data": 1,
                    "feat_committee_relevance": 0.72,
                    "feat_amount_zscore": 1.9,
                    "feat_cluster_score": 2,
                    "feat_disclosure_lag": 5,
                    "model_version": "demo-seed-v1",
                },
            )

        # Audit reports for severe + systemic
        eligible = [
            t for t in demo_trades if score_by_source[t.source_url][2] in {"SEVERE", "SYSTEMIC"}
        ]
        for t in eligible:
            quadrant = score_by_source[t.source_url][2]
            risk = "very_high" if quadrant == "SEVERE" else "high"
            conn.execute(
                text(
                    """
                    INSERT INTO audit_reports (
                        trade_id, headline, risk_level, severity_quadrant,
                        narrative, evidence_json, bill_excerpt, disclaimer,
                        video_prompt, narration_script, gemini_model,
                        prompt_tokens, output_tokens
                    ) VALUES (
                        :trade_id, :headline, :risk_level, :severity_quadrant,
                        :narrative, :evidence_json, :bill_excerpt, :disclaimer,
                        :video_prompt, :narration_script, :gemini_model,
                        :prompt_tokens, :output_tokens
                    )
                    """
                ),
                {
                    "trade_id": t.id,
                    "headline": f"{t.ticker} trade flagged as {quadrant}",
                    "risk_level": risk,
                    "severity_quadrant": quadrant,
                    "narrative": "Dual-model scoring flagged this trade for elevated statistical anomaly signals. This is a lead for scrutiny, not proof of misconduct.",
                    "evidence_json": json.dumps(
                        {
                            "key_factors": [
                                "high baseline index",
                                "large amount midpoint",
                                "short disclosure lag",
                            ],
                            "score_driver": "both" if quadrant == "SEVERE" else "baseline",
                        }
                    ),
                    "bill_excerpt": None,
                    "disclaimer": "Automated anomaly scoring is informational and not a legal determination.",
                    "video_prompt": "Investigative newsroom, subtle chart overlays, documentary tone, vertical 9:16.",
                    "narration_script": f"House Advantage flagged a {t.ticker} trade in the {quadrant} quadrant for public-interest review.",
                    "gemini_model": "demo-seed",
                    "prompt_tokens": 420,
                    "output_tokens": 190,
                },
            )

        # One demo media pair attached to the top severe trade
        severe_trade = next(t for t in demo_trades if score_by_source[t.source_url][2] == "SEVERE")
        audit_report_id = conn.execute(
            text("SELECT id FROM audit_reports WHERE trade_id = :trade_id"),
            {"trade_id": severe_trade.id},
        ).scalar()

        conn.execute(
            text(
                """
                INSERT INTO media_assets (
                    trade_id, audit_report_id, asset_type, storage_url,
                    file_size_bytes, duration_seconds, resolution,
                    generation_status, error_message, model_used
                ) VALUES (
                    :trade_id, :audit_report_id, 'video', :storage_url,
                    :file_size_bytes, :duration_seconds, :resolution,
                    'ready', NULL, :model_used
                )
                """
            ),
            {
                "trade_id": severe_trade.id,
                "audit_report_id": audit_report_id,
                "storage_url": "demo://media/trade_severe_video.mp4",
                "file_size_bytes": 3_450_000,
                "duration_seconds": 31.2,
                "resolution": "1080x1920",
                "model_used": "demo-veo",
            },
        )

        conn.execute(
            text(
                """
                INSERT INTO media_assets (
                    trade_id, audit_report_id, asset_type, storage_url,
                    file_size_bytes, duration_seconds,
                    generation_status, error_message, model_used
                ) VALUES (
                    :trade_id, :audit_report_id, 'audio', :storage_url,
                    :file_size_bytes, :duration_seconds,
                    'ready', NULL, :model_used
                )
                """
            ),
            {
                "trade_id": severe_trade.id,
                "audit_report_id": audit_report_id,
                "storage_url": "demo://media/trade_severe_audio.mp3",
                "file_size_bytes": 510_000,
                "duration_seconds": 30.7,
                "model_used": "demo-tts",
            },
        )

        # Daily report seed for home-date and pipeline visibility
        covered_ids = [t.id for t in demo_trades if t.trade_date == date(2026, 3, 27)]
        conn.execute(
            text(
                """
                INSERT INTO daily_reports (
                    report_date, trade_ids_covered, narration_script, veo_prompt,
                    video_url, audio_url, duration_seconds, generation_status
                ) VALUES (
                    :report_date, :trade_ids_covered, :narration_script, :veo_prompt,
                    :video_url, :audio_url, :duration_seconds, :generation_status
                )
                ON DUPLICATE KEY UPDATE
                    trade_ids_covered = VALUES(trade_ids_covered),
                    narration_script = VALUES(narration_script),
                    veo_prompt = VALUES(veo_prompt),
                    video_url = VALUES(video_url),
                    audio_url = VALUES(audio_url),
                    duration_seconds = VALUES(duration_seconds),
                    generation_status = VALUES(generation_status),
                    generated_at = CURRENT_TIMESTAMP
                """
            ),
            {
                "report_date": date(2026, 3, 27),
                "trade_ids_covered": json.dumps(covered_ids),
                "narration_script": "This is a demo daily bulletin generated from seeded anomaly data for local product validation.",
                "veo_prompt": "Neutral broadcast set, civic-tech style lower thirds, short investigative opener, 9:16.",
                "video_url": "demo://daily/2026-03-27.mp4",
                "audio_url": "demo://daily/2026-03-27.mp3",
                "duration_seconds": 30.0,
                "generation_status": "ready",
            },
        )


if __name__ == "__main__":
    seed_demo_data()
    print("Seeded demo data successfully.")
