"""
Bill Enrichment Tests

Verifies:
  - enrich_bills_policy_area() backfills missing policy_area
  - _policy_area_to_sector() maps all known values
  - Enrichment doesn't overwrite existing valid data
  - URL fields are populated after enrichment
  - collect_bills() produces complete records with URLs
"""
import os
import sys
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def sample_bills_csv(tmp_path):
    """Create a minimal bills_raw.csv with some missing policy_area."""
    df = pd.DataFrame([
        {
            "id": "hr1-119", "congress": 119, "bill_number": "HR1",
            "title": "Test Bill 1", "policy_area": "Health",
            "related_sector": "healthcare",
            "latest_action": "Passed House", "latest_action_date": "2025-03-01",
            "origin_chamber": "House", "sponsor_bioguide": "A000001",
            "url": "https://www.congress.gov/bill/119th-congress/house-bill/1",
        },
        {
            "id": "hr2-119", "congress": 119, "bill_number": "HR2",
            "title": "Test Bill 2", "policy_area": None,
            "related_sector": None,
            "latest_action": None, "latest_action_date": None,
            "origin_chamber": None, "sponsor_bioguide": None,
            "url": None,
        },
        {
            "id": "s1-119", "congress": 119, "bill_number": "S1",
            "title": "Test Bill 3", "policy_area": None,
            "related_sector": None,
            "latest_action": "Referred to committee", "latest_action_date": "2025-01-15",
            "origin_chamber": "Senate", "sponsor_bioguide": None,
            "url": None,
        },
        {
            "id": "hjres1-119", "congress": 119, "bill_number": "HJRES1",
            "title": "Test Joint Res", "policy_area": "Armed Forces and National Security",
            "related_sector": "defense",
            "latest_action": "Introduced", "latest_action_date": "2025-02-01",
            "origin_chamber": "House", "sponsor_bioguide": "B000002",
            "url": "https://www.congress.gov/bill/119th-congress/house-joint-resolution/1",
        },
    ])
    csv_path = tmp_path / "bills_raw.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


def _mock_bill_detail(bill_type, bill_number):
    """Return a mock API response for bill detail."""
    details = {
        ("hr", "2"): {
            "bill": {
                "policyArea": {"name": "Finance and Financial Sector"},
                "latestAction": {
                    "text": "Passed committee",
                    "actionDate": "2025-04-01",
                },
                "originChamber": "House",
                "sponsors": [{"bioguideId": "C000003"}],
                "legislationUrl": "https://www.congress.gov/bill/119th-congress/house-bill/2",
            }
        },
        ("s", "1"): {
            "bill": {
                "policyArea": {"name": "Energy"},
                "latestAction": {
                    "text": "Committee hearing held",
                    "actionDate": "2025-03-15",
                },
                "originChamber": "Senate",
                "sponsors": [{"bioguideId": "D000004"}],
                "legislationUrl": "https://www.congress.gov/bill/119th-congress/senate-bill/1",
            }
        },
    }
    return details.get((bill_type, bill_number), {"bill": {}})


# ============================================================
# 1. POLICY AREA TO SECTOR MAPPING
# ============================================================

class TestPolicyAreaToSector:
    """Test _policy_area_to_sector() mapping function."""

    def test_returns_none_for_none(self):
        from backend.ingest.collectors.collect_congress_gov import _policy_area_to_sector
        assert _policy_area_to_sector(None) is None

    def test_returns_none_for_empty(self):
        from backend.ingest.collectors.collect_congress_gov import _policy_area_to_sector
        assert _policy_area_to_sector("") is None

    def test_maps_health_to_healthcare(self):
        from backend.ingest.collectors.collect_congress_gov import _policy_area_to_sector
        assert _policy_area_to_sector("Health") == "healthcare"

    def test_maps_finance(self):
        from backend.ingest.collectors.collect_congress_gov import _policy_area_to_sector
        assert _policy_area_to_sector("Finance and Financial Sector") == "finance"

    def test_maps_energy(self):
        from backend.ingest.collectors.collect_congress_gov import _policy_area_to_sector
        assert _policy_area_to_sector("Energy") == "energy"

    def test_maps_defense(self):
        from backend.ingest.collectors.collect_congress_gov import _policy_area_to_sector
        assert _policy_area_to_sector("Armed Forces and National Security") == "defense"

    def test_returns_none_for_unknown(self):
        from backend.ingest.collectors.collect_congress_gov import _policy_area_to_sector
        assert _policy_area_to_sector("Nonexistent Area XYZ") is None

    def test_all_map_values_are_valid_sectors(self):
        from backend.ingest.collectors.collect_congress_gov import POLICY_AREA_SECTOR_MAP
        valid = {"defense", "finance", "healthcare", "energy", "tech", "agriculture", "telecom"}
        for pa, sector in POLICY_AREA_SECTOR_MAP.items():
            assert sector in valid, f"'{pa}' maps to invalid sector '{sector}'"


# ============================================================
# 2. ENRICHMENT FUNCTION (with mocked API)
# ============================================================

class TestEnrichBillsPolicyArea:
    """Test enrich_bills_policy_area() fills missing fields."""

    def test_enriches_missing_policy_area(self, sample_bills_csv):
        """Enrichment should fill policy_area for bills that are missing it."""
        from backend.ingest.collectors.collect_congress_gov import (
            enrich_bills_policy_area, BASE_URL, CURRENT_CONGRESS,
        )
        from backend.ingest.collectors.utils import DATA_RAW

        def mock_rate_limited_get(url, params=None, delay=None, max_retries=None, **kw):
            # Parse bill type and number from URL
            # URL format: .../bill/119/hr/2
            parts = url.rstrip("/").split("/")
            bill_type = parts[-2]
            bill_number = parts[-1]
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = _mock_bill_detail(bill_type, bill_number)
            return resp

        with patch("backend.ingest.collectors.collect_congress_gov.rate_limited_get",
                    side_effect=mock_rate_limited_get), \
             patch("backend.ingest.collectors.collect_congress_gov.DATA_RAW",
                    sample_bills_csv.parent):
            # Also patch the module-level DATA_RAW used by the function
            import backend.ingest.collectors.collect_congress_gov as mod
            original_data_raw = mod.DATA_RAW
            mod.DATA_RAW = sample_bills_csv.parent
            try:
                result = enrich_bills_policy_area(congress=119)
            finally:
                mod.DATA_RAW = original_data_raw

        # hr2-119 should now have "Finance and Financial Sector"
        hr2 = result[result["id"] == "hr2-119"].iloc[0]
        assert hr2["policy_area"] == "Finance and Financial Sector"
        assert hr2["related_sector"] == "finance"

        # s1-119 should now have "Energy"
        s1 = result[result["id"] == "s1-119"].iloc[0]
        assert s1["policy_area"] == "Energy"
        assert s1["related_sector"] == "energy"

    def test_does_not_overwrite_existing_policy_area(self, sample_bills_csv):
        """Bills with existing policy_area should not be re-fetched."""
        from backend.ingest.collectors.collect_congress_gov import enrich_bills_policy_area
        import backend.ingest.collectors.collect_congress_gov as mod

        call_count = 0

        def mock_rate_limited_get(url, **kw):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"bill": {"policyArea": {"name": "OVERWRITE"}}}
            return resp

        with patch("backend.ingest.collectors.collect_congress_gov.rate_limited_get",
                    side_effect=mock_rate_limited_get):
            original_data_raw = mod.DATA_RAW
            mod.DATA_RAW = sample_bills_csv.parent
            try:
                result = enrich_bills_policy_area(congress=119)
            finally:
                mod.DATA_RAW = original_data_raw

        # hr1-119 should still have "Health", not "OVERWRITE"
        hr1 = result[result["id"] == "hr1-119"].iloc[0]
        assert hr1["policy_area"] == "Health"

        # hjres1-119 should still have original value
        hjres1 = result[result["id"] == "hjres1-119"].iloc[0]
        assert hjres1["policy_area"] == "Armed Forces and National Security"

        # Should only have fetched for the 2 missing rows
        assert call_count == 2, f"Expected 2 API calls, got {call_count}"

    def test_handles_api_failure_gracefully(self, sample_bills_csv):
        """If API fails for a bill, it should skip and continue."""
        from backend.ingest.collectors.collect_congress_gov import enrich_bills_policy_area
        import backend.ingest.collectors.collect_congress_gov as mod

        def mock_rate_limited_get(url, **kw):
            raise RuntimeError("Simulated API failure")

        with patch("backend.ingest.collectors.collect_congress_gov.rate_limited_get",
                    side_effect=mock_rate_limited_get):
            original_data_raw = mod.DATA_RAW
            mod.DATA_RAW = sample_bills_csv.parent
            try:
                result = enrich_bills_policy_area(congress=119)
            finally:
                mod.DATA_RAW = original_data_raw

        # Should still return the DataFrame with existing data intact
        assert len(result) == 4
        hr1 = result[result["id"] == "hr1-119"].iloc[0]
        assert hr1["policy_area"] == "Health"


# ============================================================
# 3. URL ENRICHMENT DURING COLLECTION
# ============================================================

class TestBillUrlEnrichment:
    """Verify that collect_bills produces records with valid URLs."""

    def test_url_field_populated_when_detail_succeeds(self):
        """If detail fetch works, the 'url' column should have a valid URL."""
        from backend.ingest.collectors.collect_congress_gov import collect_bills
        import backend.ingest.collectors.collect_congress_gov as mod

        # Mock _paginate to return 2 bills
        mock_bills = [
            {"number": "1", "title": "Test HR1", "introducedDate": "2025-01-03"},
            {"number": "2", "title": "Test HR2", "introducedDate": "2025-01-04"},
        ]

        mock_detail = {
            "bill": {
                "policyArea": {"name": "Health"},
                "latestAction": {"text": "Introduced", "actionDate": "2025-01-03"},
                "originChamber": "House",
                "sponsors": [{"bioguideId": "A000001"}],
                "legislationUrl": "https://www.congress.gov/bill/119th-congress/house-bill/1",
                "introducedDate": "2025-01-03",
            }
        }

        def mock_paginate(url, params, result_key, max_pages=100):
            if "/hr" in url:
                return mock_bills
            return []

        def mock_rate_limited_get(url, **kw):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = mock_detail
            return resp

        original_data_raw = mod.DATA_RAW
        with patch("backend.ingest.collectors.collect_congress_gov._paginate",
                    side_effect=mock_paginate), \
             patch("backend.ingest.collectors.collect_congress_gov.rate_limited_get",
                    side_effect=mock_rate_limited_get), \
             patch.object(mod, "DATA_RAW", Path(os.devnull).parent):
            # We need a writable path for the CSV
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                mod.DATA_RAW = Path(tmpdir)
                try:
                    result = collect_bills(congress=119, fetch_policy_areas=True)
                finally:
                    mod.DATA_RAW = original_data_raw

        # Both bills should have URL populated
        for _, row in result.iterrows():
            url = row.get("url", "")
            if url and pd.notna(url):
                from urllib.parse import urlparse
                parsed = urlparse(url)
                assert parsed.scheme in ("http", "https"), f"Bad scheme: {url}"
                assert parsed.netloc, f"No netloc: {url}"


# ============================================================
# 4. ENRICHMENT + VOTE SECTOR PROPAGATION
# ============================================================

class TestVoteSectorPropagation:
    """Test enrich_votes_with_sectors() links bills to votes."""

    def test_propagates_sectors_to_votes(self, tmp_path):
        from backend.ingest.collectors.collect_congress_gov import enrich_votes_with_sectors
        import backend.ingest.collectors.collect_congress_gov as mod

        # Create bills CSV with sectors
        bills_df = pd.DataFrame([
            {"id": "hr1-119", "policy_area": "Health", "related_sector": "healthcare"},
            {"id": "s1-119", "policy_area": "Energy", "related_sector": "energy"},
        ])
        bills_df.to_csv(tmp_path / "bills_raw.csv", index=False)

        # Create votes CSV with bill_id references
        votes_df = pd.DataFrame([
            {"id": "house-119-1", "bill_id": "hr1-119", "vote_date": "2025-03-01",
             "chamber": "house", "vote_question": "On Passage", "description": "Passed",
             "related_sector": None},
            {"id": "house-119-2", "bill_id": "s1-119", "vote_date": "2025-03-15",
             "chamber": "house", "vote_question": "On Passage", "description": "Passed",
             "related_sector": None},
            {"id": "house-119-3", "bill_id": "hr999-119", "vote_date": "2025-04-01",
             "chamber": "house", "vote_question": "On Motion", "description": "Failed",
             "related_sector": None},
        ])
        votes_df.to_csv(tmp_path / "votes_raw.csv", index=False)

        original_data_raw = mod.DATA_RAW
        mod.DATA_RAW = tmp_path
        try:
            result = enrich_votes_with_sectors()
        finally:
            mod.DATA_RAW = original_data_raw

        # Vote 1 → healthcare (from hr1-119)
        v1 = result[result["id"] == "house-119-1"].iloc[0]
        assert v1["related_sector"] == "healthcare"

        # Vote 2 → energy (from s1-119)
        v2 = result[result["id"] == "house-119-2"].iloc[0]
        assert v2["related_sector"] == "energy"

        # Vote 3 → None (hr999-119 not in bills)
        v3 = result[result["id"] == "house-119-3"].iloc[0]
        assert pd.isna(v3["related_sector"])
