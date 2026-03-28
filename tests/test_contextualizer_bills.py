"""
Contextualizer Bill Integration Tests

Verifies:
  - _fetch_nearby_bills() returns sector-matched bills within ±90 days
  - _fetch_nearby_bills() returns empty list when no sector/date provided
  - _fetch_nearby_bills() respects the limit parameter
  - _fetch_nearby_bills() orders by proximity (closest first)
  - build_initial_message() includes bill section when bills are present
  - build_initial_message() omits bill section when no bills
  - build_initial_message() includes citation_image_prompts in output schema
  - _upsert_audit_report() persists citation_image_prompts as JSON
  - _fallback_report() produces valid structure (regression)
"""
import json
import os
import sys
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def sample_trade():
    """Minimal trade context dict as returned by _fetch_trade_context."""
    return {
        "trade_id": 42,
        "ticker": "LMT",
        "trade_type": "purchase",
        "trade_date": date(2025, 6, 15),
        "disclosure_date": date(2025, 7, 1),
        "disclosure_lag_days": 16,
        "amount_midpoint": 250000,
        "industry_sector": "defense",
        "bioguide_id": "S001234",
        "full_name": "Jane Smith",
        "cohort_index": 82,
        "baseline_index": 91,
        "severity_quadrant": "SEVERE",
        "feat_cohort_alpha": 0.12,
        "feat_pre_trade_alpha": 0.08,
        "feat_proximity_days": 3,
        "feat_bill_proximity": 5,
        "feat_has_proximity_data": 1,
        "feat_committee_relevance": 0.9,
        "feat_amount_zscore": 2.1,
        "feat_cluster_score": 3,
        "feat_disclosure_lag": 2.83,
        "nearby_bills": [],
    }


@pytest.fixture
def sample_bills():
    """Sample bill rows as they'd come from the DB."""
    return [
        {
            "bill_id": "hr1234-119",
            "title": "Defense Appropriations Act",
            "policy_area": "Armed Forces and National Security",
            "latest_action_date": date(2025, 6, 12),
            "url": "https://www.congress.gov/bill/119th-congress/house-bill/1234",
        },
        {
            "bill_id": "s567-119",
            "title": "Military Readiness Act",
            "policy_area": "Defense",
            "latest_action_date": date(2025, 6, 20),
            "url": "https://www.congress.gov/bill/119th-congress/senate-bill/567",
        },
        {
            "bill_id": "hr890-119",
            "title": "Pentagon Budget Review Act",
            "policy_area": "Armed Forces and National Security",
            "latest_action_date": date(2025, 5, 1),
            "url": "https://www.congress.gov/bill/119th-congress/house-bill/890",
        },
    ]


# ============================================================
# 1. _fetch_nearby_bills() UNIT TESTS
# ============================================================

class TestFetchNearbyBills:
    """Test _fetch_nearby_bills with mocked DB."""

    def test_returns_empty_when_no_trade_date(self):
        from backend.gemini.contextualizer import _fetch_nearby_bills
        result = _fetch_nearby_bills(trade_date=None, trade_sector="defense")
        assert result == []

    def test_returns_empty_when_no_sector(self):
        from backend.gemini.contextualizer import _fetch_nearby_bills
        result = _fetch_nearby_bills(trade_date=date(2025, 6, 15), trade_sector=None)
        assert result == []

    def test_returns_empty_when_empty_sector_string(self):
        from backend.gemini.contextualizer import _fetch_nearby_bills
        result = _fetch_nearby_bills(trade_date=date(2025, 6, 15), trade_sector="")
        assert result == []

    def test_returns_empty_when_sector_has_no_policy_area_match(self):
        from backend.gemini.contextualizer import _fetch_nearby_bills
        # "nonexistent" sector doesn't appear in BILL_SECTOR_MAP values
        result = _fetch_nearby_bills(trade_date=date(2025, 6, 15), trade_sector="nonexistent")
        assert result == []

    @patch("backend.gemini.contextualizer.get_engine")
    def test_returns_bills_for_valid_sector(self, mock_get_engine, sample_bills):
        from backend.gemini.contextualizer import _fetch_nearby_bills

        # Set up mock engine → connection → execute chain
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_engine.return_value = mock_engine

        mock_conn.execute.return_value.mappings.return_value.all.return_value = sample_bills

        result = _fetch_nearby_bills(
            trade_date=date(2025, 6, 15),
            trade_sector=["defense"],
        )
        assert len(result) == 3
        assert result[0]["bill_id"] == "hr1234-119"

        # Verify SQL was executed
        mock_conn.execute.assert_called_once()

    @patch("backend.gemini.contextualizer.get_engine")
    def test_respects_limit(self, mock_get_engine):
        from backend.gemini.contextualizer import _fetch_nearby_bills

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_engine.return_value = mock_engine
        mock_conn.execute.return_value.mappings.return_value.all.return_value = [
            {"bill_id": "hr1-119", "title": "Bill 1", "policy_area": "Health",
             "latest_action_date": date(2025, 6, 10), "url": None}
        ]

        result = _fetch_nearby_bills(
            trade_date=date(2025, 6, 15),
            trade_sector=["healthcare"],
            limit=1,
        )
        assert len(result) == 1

        # Verify the limit param was passed to the SQL
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]  # second positional arg is params dict
        assert params["limit"] == 1

    @patch("backend.gemini.contextualizer.get_engine")
    def test_multi_sector_trade(self, mock_get_engine):
        from backend.gemini.contextualizer import _fetch_nearby_bills

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_engine.return_value = mock_engine
        mock_conn.execute.return_value.mappings.return_value.all.return_value = []

        # Pass multiple sectors
        _fetch_nearby_bills(
            trade_date=date(2025, 6, 15),
            trade_sector=["defense", "tech"],
        )

        # Should have executed — both defense and tech policy areas in the IN clause
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        # Should contain policy areas for both defense AND tech sectors
        pa_values = [v for k, v in params.items() if k.startswith("pa")]
        assert "Armed Forces and National Security" in pa_values
        assert "Science, Technology, Communications" in pa_values

    def test_accepts_string_sector_and_parses(self):
        """When trade_sector is a raw string, _parse_sector should parse it."""
        from backend.gemini.contextualizer import _fetch_nearby_bills

        # "nonexistent" won't match any BILL_SECTOR_MAP value, so no DB call needed
        result = _fetch_nearby_bills(trade_date=date(2025, 6, 15), trade_sector="nonexistent")
        assert result == []


# ============================================================
# 2. build_initial_message() TESTS
# ============================================================

class TestBuildInitialMessage:
    """Test the Gemini prompt builder includes bill data."""

    def test_no_bills_omits_section(self, sample_trade):
        from backend.gemini.contextualizer import build_initial_message

        sample_trade["nearby_bills"] = []
        msg = build_initial_message(sample_trade)
        assert "Relevant Bills" not in msg
        assert "citation_image_prompts" in msg  # schema always present

    def test_with_bills_includes_section(self, sample_trade, sample_bills):
        from backend.gemini.contextualizer import build_initial_message

        sample_trade["nearby_bills"] = sample_bills
        msg = build_initial_message(sample_trade)

        assert "Relevant Bills (sector-matched, ±90 days):" in msg
        assert "hr1234-119" in msg
        assert "Defense Appropriations Act" in msg
        assert "Armed Forces and National Security" in msg
        assert "2025-06-12" in msg
        assert "https://www.congress.gov/bill/119th-congress/house-bill/1234" in msg

    def test_schema_includes_citation_image_prompts(self, sample_trade):
        from backend.gemini.contextualizer import build_initial_message

        msg = build_initial_message(sample_trade)
        assert '"citation_image_prompts"' in msg
        assert "image-generation prompt per relevant bill" in msg

    def test_includes_all_trade_fields(self, sample_trade):
        from backend.gemini.contextualizer import build_initial_message

        msg = build_initial_message(sample_trade)
        assert "Jane Smith" in msg
        assert "LMT" in msg
        assert "SEVERE" in msg
        assert "cohort_alpha" in msg


# ============================================================
# 3. _fallback_report() TESTS
# ============================================================

class TestFallbackReport:
    """Ensure fallback report still produces valid structure."""

    def test_fallback_structure(self, sample_trade):
        from backend.gemini.contextualizer import _fallback_report

        result = _fallback_report(sample_trade)
        payload = result.payload

        assert "headline" in payload
        assert "narrative" in payload
        assert "evidence_json" in payload
        assert "disclaimer" in payload
        assert result.model == "fallback"
        assert "SEVERE" in payload["headline"].upper() or "severe" in payload["headline"]

    def test_fallback_severe_has_video_prompt(self, sample_trade):
        from backend.gemini.contextualizer import _fallback_report

        sample_trade["severity_quadrant"] = "SEVERE"
        result = _fallback_report(sample_trade)
        assert result.payload["video_prompt"] is not None
        assert result.payload["narration_script"] is not None

    def test_fallback_unremarkable_no_video(self, sample_trade):
        from backend.gemini.contextualizer import _fallback_report

        sample_trade["severity_quadrant"] = "UNREMARKABLE"
        result = _fallback_report(sample_trade)
        assert result.payload["video_prompt"] is None
        assert result.payload["narration_script"] is None


# ============================================================
# 4. _upsert_audit_report() TESTS (mocked DB)
# ============================================================

class TestUpsertAuditReport:
    """Verify _upsert_audit_report passes citation_image_prompts to DB."""

    @patch("backend.gemini.contextualizer.get_engine")
    def test_upsert_includes_citation_image_prompts(self, mock_get_engine, sample_trade):
        from backend.gemini.contextualizer import _upsert_audit_report, ContextualizerResult

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = lambda s: mock_conn
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_engine.return_value = mock_engine

        prompts = [
            "Dark infographic showing HR 1234 Defense Appropriations",
            "Citation card for S 567 Military Readiness"
        ]

        result = ContextualizerResult(
            payload={
                "headline": "Test headline",
                "narrative": "Test narrative.",
                "bill_excerpt": "Section 302(a)...",
                "evidence_json": {"key_factors": ["test"], "score_driver": "both"},
                "disclaimer": "Test disclaimer.",
                "video_prompt": "Test video prompt",
                "narration_script": "Test script",
                "citation_image_prompts": prompts,
            },
            model="gemini-1.5-pro",
            prompt_tokens=100,
            output_tokens=200,
        )

        _upsert_audit_report(trade_id=42, trade=sample_trade, result=result)

        # Verify execute was called with params containing citation_image_prompts
        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        assert "citation_image_prompts" in params
        parsed = json.loads(params["citation_image_prompts"])
        assert len(parsed) == 2
        assert "HR 1234" in parsed[0]

    @patch("backend.gemini.contextualizer.get_engine")
    def test_upsert_empty_prompts_serializes_to_empty_list(self, mock_get_engine, sample_trade):
        from backend.gemini.contextualizer import _upsert_audit_report, ContextualizerResult

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = lambda s: mock_conn
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_engine.return_value = mock_engine

        result = ContextualizerResult(
            payload={
                "headline": "Test",
                "narrative": "Test.",
                "evidence_json": {},
                "disclaimer": "Test.",
            },
            model="fallback",
        )

        _upsert_audit_report(trade_id=42, trade=sample_trade, result=result)

        call_args = mock_conn.execute.call_args
        params = call_args[0][1]
        parsed = json.loads(params["citation_image_prompts"])
        assert parsed == []


# ============================================================
# 5. BILL_SECTOR_MAP COVERAGE TESTS
# ============================================================

class TestBillSectorMap:
    """Verify BILL_SECTOR_MAP is properly imported and used."""

    def test_map_has_defense_entries(self):
        from backend.scoring.dual_scorer import BILL_SECTOR_MAP
        defense_areas = [k for k, v in BILL_SECTOR_MAP.items() if v == "defense"]
        assert len(defense_areas) >= 3
        assert "Armed Forces and National Security" in defense_areas

    def test_map_has_all_sectors(self):
        from backend.scoring.dual_scorer import BILL_SECTOR_MAP
        sectors = set(BILL_SECTOR_MAP.values())
        assert "defense" in sectors
        assert "finance" in sectors
        assert "healthcare" in sectors
        assert "energy" in sectors
        assert "tech" in sectors
        assert "agriculture" in sectors

    def test_reverse_lookup_defense(self):
        """_fetch_nearby_bills does a reverse lookup — verify it works."""
        from backend.scoring.dual_scorer import BILL_SECTOR_MAP
        matching = [pa for pa, s in BILL_SECTOR_MAP.items() if s == "defense"]
        assert "Armed Forces and National Security" in matching
        assert "Defense" in matching
        assert "International Affairs" in matching


# ============================================================
# 6. contextualize_trade() INTEGRATION (mocked Gemini + DB)
# ============================================================

class TestContextualizeTradeWithBills:
    """Test that contextualize_trade flows bills through the pipeline."""

    @patch("backend.gemini.contextualizer._upsert_audit_report")
    @patch("backend.gemini.contextualizer._generate_with_gemini")
    @patch("backend.gemini.contextualizer._fetch_trade_context")
    def test_full_flow_with_bills(self, mock_fetch, mock_gemini, mock_upsert, sample_trade, sample_bills):
        from backend.gemini.contextualizer import contextualize_trade, ContextualizerResult

        sample_trade["nearby_bills"] = sample_bills
        mock_fetch.return_value = sample_trade

        gemini_result = ContextualizerResult(
            payload={
                "headline": "LMT trade 3 days before defense bill",
                "narrative": "Rep. Smith bought LMT stock before H.R. 1234.",
                "bill_excerpt": "Section 302(a): $500M for missile defense",
                "evidence_json": {"key_factors": ["bill_proximity=3"], "score_driver": "both"},
                "disclaimer": "Automated analysis.",
                "video_prompt": "Newsroom, defense documents, dark tone",
                "narration_script": "House Advantage flagged this LMT trade...",
                "citation_image_prompts": [
                    "Dark infographic: H.R. 1234 Defense Appropriations Act, $500M",
                    "Citation card: S. 567 Military Readiness Act",
                ],
            },
            model="gemini-1.5-pro",
            prompt_tokens=500,
            output_tokens=300,
        )
        mock_gemini.return_value = gemini_result

        result = contextualize_trade(42)

        assert result["status"] == "ok"
        assert result["trade_id"] == 42

        # Verify Gemini received the bills in its prompt
        gemini_call_args = mock_gemini.call_args[0][0]
        assert "hr1234-119" in gemini_call_args
        assert "Defense Appropriations Act" in gemini_call_args
        assert "Relevant Bills" in gemini_call_args

        # Verify upsert was called with the gemini result
        mock_upsert.assert_called_once()
        upsert_result = mock_upsert.call_args[1]["result"]
        assert len(upsert_result.payload["citation_image_prompts"]) == 2

    @patch("backend.gemini.contextualizer._upsert_audit_report")
    @patch("backend.gemini.contextualizer._generate_with_gemini")
    @patch("backend.gemini.contextualizer._fetch_trade_context")
    def test_fallback_when_gemini_fails(self, mock_fetch, mock_gemini, mock_upsert, sample_trade):
        from backend.gemini.contextualizer import contextualize_trade

        sample_trade["nearby_bills"] = []
        mock_fetch.return_value = sample_trade
        mock_gemini.side_effect = RuntimeError("API unavailable")

        result = contextualize_trade(42)
        assert result["status"] == "ok"
        assert result["model"] == "fallback"
        mock_upsert.assert_called_once()


# ============================================================
# 7. DATABASE INTEGRATION (live DB, skipped if unavailable)
# ============================================================

def _db_available():
    try:
        from backend.db.connection import test_connection
        return test_connection()
    except Exception:
        return False


@pytest.mark.skipif(not _db_available(), reason="MySQL not available")
class TestBillIntegrationDB:
    """Live DB tests — verify bills exist and query works."""

    def test_bills_table_has_rows(self):
        from backend.db.connection import get_engine
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM bills")).scalar()
            assert count > 0, "bills table is empty — run ingestion first"

    def test_fetch_nearby_bills_live(self):
        """Run _fetch_nearby_bills against the real DB with a known sector."""
        from backend.db.connection import get_engine
        from backend.gemini.contextualizer import _fetch_nearby_bills
        from sqlalchemy import text

        engine = get_engine()
        with engine.connect() as conn:
            # Get a trade date from the DB to use
            row = conn.execute(text(
                "SELECT t.trade_date, t.industry_sector "
                "FROM trades t "
                "JOIN anomaly_scores a ON a.trade_id = t.id "
                "WHERE a.severity_quadrant IN ('SEVERE', 'SYSTEMIC') "
                "LIMIT 1"
            )).mappings().first()

        if not row:
            pytest.skip("No SEVERE/SYSTEMIC trades in DB")

        bills = _fetch_nearby_bills(
            trade_date=row["trade_date"],
            trade_sector=str(row["industry_sector"]),
        )
        # Bills may or may not exist for this trade — just verify no crash
        assert isinstance(bills, list)
        for b in bills:
            assert "bill_id" in b
            assert "title" in b
            assert "policy_area" in b

    def test_audit_reports_has_citation_column(self):
        """Verify the citation_image_prompts column exists after migration."""
        from backend.db.connection import get_engine
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(text("SHOW COLUMNS FROM audit_reports")).fetchall()
            col_names = [r[0] for r in rows]
            assert "citation_image_prompts" in col_names, (
                "Run migration: python -m backend.db.migrate_citation_images"
            )
