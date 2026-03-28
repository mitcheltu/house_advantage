"""
Bill URL Pipeline Trace Test

Traces ONE bill (HR 144, 119th Congress) through the entire data pipeline
to verify the URL is correct, human-readable, and matches congress.gov.

Pipeline path:
  1. Congress.gov API  →  legislationUrl field
  2. collect_bills()   →  bills_raw.csv "url" column
  3. load_bills()      →  MySQL bills.url column

This test calls the LIVE Congress.gov API for a single bill.
"""
import os
import re
import sys
import pytest
import requests
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Constants ─────────────────────────────────────────────────

CONGRESS = 119
BILL_TYPE = "hr"
BILL_NUMBER = 144
BILL_ID = f"{BILL_TYPE}{BILL_NUMBER}-{CONGRESS}"
EXPECTED_TITLE_FRAGMENT = "Tennessee Valley Authority"
EXPECTED_URL = f"https://www.congress.gov/bill/{CONGRESS}th-congress/house-bill/{BILL_NUMBER}"

BASE_URL = "https://api.congress.gov/v3"

# Human-readable URL pattern:
#   https://www.congress.gov/bill/{N}th-congress/{type-slug}/{number}
# where type-slug is:  hr → house-bill, s → senate-bill,
#                       hjres → house-joint-resolution, sjres → senate-joint-resolution
URL_PATTERN = re.compile(
    r"^https://www\.congress\.gov/bill/\d+\w{2}-congress/"
    r"(house-bill|senate-bill|house-joint-resolution|senate-joint-resolution)"
    r"/\d+$"
)


@pytest.fixture(scope="module")
def api_key():
    key = os.getenv("CONGRESS_GOV_API_KEY", "")
    if not key:
        pytest.skip("CONGRESS_GOV_API_KEY not set")
    return key


# ============================================================
# 1. RAW API: Verify the Congress.gov API returns legislationUrl
# ============================================================

class TestApiReturnsUrl:
    """Step 1 — Call the same API endpoint the pipeline uses and verify the URL."""

    @pytest.fixture(scope="class")
    def bill_detail(self, api_key):
        """Fetch bill detail exactly as the pipeline does."""
        resp = requests.get(
            f"{BASE_URL}/bill/{CONGRESS}/{BILL_TYPE}/{BILL_NUMBER}",
            params={"api_key": api_key, "format": "json"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("bill", {})

    def test_api_returns_legislation_url(self, bill_detail):
        """API response includes the legislationUrl field."""
        url = bill_detail.get("legislationUrl")
        assert url is not None, (
            f"API response for {BILL_ID} missing 'legislationUrl'. "
            f"Available keys: {list(bill_detail.keys())}"
        )

    def test_url_matches_expected(self, bill_detail):
        """URL equals the known congress.gov page for HR 144."""
        url = bill_detail.get("legislationUrl", "")
        assert url == EXPECTED_URL, (
            f"Expected: {EXPECTED_URL}\n"
            f"Got:      {url}"
        )

    def test_url_is_human_readable(self, bill_detail):
        """URL uses readable slugs, not opaque IDs."""
        url = bill_detail.get("legislationUrl", "")
        assert URL_PATTERN.match(url), (
            f"URL does not match human-readable pattern:\n"
            f"  URL:     {url}\n"
            f"  Pattern: {URL_PATTERN.pattern}"
        )

    def test_url_contains_no_api_key(self, bill_detail):
        """URL is a public congress.gov link, not an API endpoint."""
        url = bill_detail.get("legislationUrl", "")
        assert "api_key" not in url, "URL should not contain API key"
        assert "api.congress.gov" not in url, "URL should be congress.gov, not api.congress.gov"

    def test_title_matches(self, bill_detail):
        """Sanity check — the bill title matches what we expect."""
        title = bill_detail.get("title", "")
        assert EXPECTED_TITLE_FRAGMENT in title, (
            f"Title mismatch: expected '{EXPECTED_TITLE_FRAGMENT}' "
            f"in '{title}'"
        )


# ============================================================
# 2. PIPELINE LOGIC: Verify collect_bills maps URL correctly
# ============================================================

class TestPipelineMapsUrl:
    """Step 2 — Simulate what collect_bills() does for ONE bill."""

    @pytest.fixture(scope="class")
    def pipeline_record(self, api_key):
        """
        Reproduce the exact logic from collect_bills() for HR 144:
          - Call API detail endpoint
          - Extract legislationUrl
          - Build the record dict the same way collect_bills() does
        """
        from backend.ingest.collectors.collect_congress_gov import _policy_area_to_sector
        from backend.ingest.collectors.utils import rate_limited_get

        detail_resp = rate_limited_get(
            f"{BASE_URL}/bill/{CONGRESS}/{BILL_TYPE}/{BILL_NUMBER}",
            params={"api_key": api_key, "format": "json"},
            delay=1.5,
            max_retries=3,
        )
        bill_detail = detail_resp.json().get("bill", {})

        # Exact field extraction from collect_bills()
        policy_area = bill_detail.get("policyArea", {}).get("name")
        latest_action_obj = bill_detail.get("latestAction", {})
        latest_action = latest_action_obj.get("text")
        latest_action_date = latest_action_obj.get("actionDate")
        origin_chamber = bill_detail.get("originChamber")
        sponsors = bill_detail.get("sponsors", [])
        sponsor_bioguide = sponsors[0].get("bioguideId") if sponsors else None
        legislation_url = bill_detail.get("legislationUrl")

        return {
            "id": BILL_ID,
            "congress": CONGRESS,
            "bill_number": f"{BILL_TYPE.upper()}{BILL_NUMBER}",
            "title": bill_detail.get("title", ""),
            "introduced_date": bill_detail.get("introducedDate", ""),
            "policy_area": policy_area,
            "related_sector": _policy_area_to_sector(policy_area),
            "latest_action": latest_action,
            "latest_action_date": latest_action_date,
            "origin_chamber": origin_chamber,
            "sponsor_bioguide": sponsor_bioguide,
            "url": legislation_url,
        }

    def test_record_url_not_none(self, pipeline_record):
        """The pipeline record has a URL."""
        assert pipeline_record["url"] is not None, "Pipeline record URL is None"

    def test_record_url_matches_expected(self, pipeline_record):
        """The pipeline record URL matches the known good URL."""
        assert pipeline_record["url"] == EXPECTED_URL

    def test_record_url_is_human_readable(self, pipeline_record):
        """The URL in the pipeline record is human-readable."""
        assert URL_PATTERN.match(pipeline_record["url"])

    def test_record_bill_id_format(self, pipeline_record):
        """bill_id follows the {type}{number}-{congress} convention."""
        assert pipeline_record["id"] == BILL_ID

    def test_record_has_enrichment_fields(self, pipeline_record):
        """The detail fetch also populated policy_area and sponsor."""
        assert pipeline_record["policy_area"] is not None, "policy_area is missing"
        assert pipeline_record["sponsor_bioguide"] is not None, "sponsor_bioguide is missing"


# ============================================================
# 3. DB LOAD: Verify load_bills() would insert the URL correctly
# ============================================================

class TestDbLoadPreservesUrl:
    """Step 3 — Simulate the CSV→DB transformation from load_bills()."""

    @pytest.fixture(scope="class")
    def db_ready_row(self, api_key):
        """
        Build a 1-row DataFrame the way collect_bills produces it,
        then apply the same transformations load_bills() does.
        """
        import pandas as pd
        from backend.ingest.collectors.utils import rate_limited_get

        detail_resp = rate_limited_get(
            f"{BASE_URL}/bill/{CONGRESS}/{BILL_TYPE}/{BILL_NUMBER}",
            params={"api_key": api_key, "format": "json"},
            delay=1.5,
            max_retries=3,
        )
        bill_detail = detail_resp.json().get("bill", {})

        # Build the CSV row as collect_bills() would
        csv_row = {
            "id": BILL_ID,
            "congress": CONGRESS,
            "bill_number": f"{BILL_TYPE.upper()}{BILL_NUMBER}",
            "title": bill_detail.get("title", ""),
            "url": bill_detail.get("legislationUrl"),
        }
        df = pd.DataFrame([csv_row])

        # Apply the same transformations as load_bills()
        df = df.rename(columns={"id": "bill_id"})

        # Split bill_number "HR144" → bill_type="HR", bill_number=144
        df["bill_type"] = df["bill_number"].apply(
            lambda x: re.match(r'([A-Za-z]+)', str(x)).group(1).upper()
            if pd.notna(x) and re.match(r'([A-Za-z]+)', str(x)) else None
        )
        df["bill_number"] = df["bill_number"].apply(
            lambda x: int(m.group(1)) if pd.notna(x) and (m := re.search(r'(\d+)', str(x))) else None
        )

        return df.iloc[0]

    def test_url_survives_transformation(self, db_ready_row):
        """URL is preserved through the CSV-to-DB transformation."""
        assert db_ready_row["url"] == EXPECTED_URL

    def test_bill_id_preserved(self, db_ready_row):
        """bill_id column is correctly renamed from 'id'."""
        assert db_ready_row["bill_id"] == BILL_ID

    def test_bill_type_extracted(self, db_ready_row):
        """bill_type correctly extracted as 'HR'."""
        assert db_ready_row["bill_type"] == "HR"

    def test_bill_number_is_int(self, db_ready_row):
        """bill_number correctly extracted as integer 144."""
        assert db_ready_row["bill_number"] == BILL_NUMBER


# ============================================================
# 4. URL FORMAT: Verify mapping rules for all bill types
# ============================================================

class TestUrlFormatRules:
    """Verify the expected URL slug for each bill type."""

    @pytest.mark.parametrize("bill_type,slug", [
        ("hr", "house-bill"),
        ("s", "senate-bill"),
        ("hjres", "house-joint-resolution"),
        ("sjres", "senate-joint-resolution"),
    ])
    def test_url_slug_pattern(self, bill_type, slug):
        """Each bill type maps to a human-readable URL slug."""
        example_url = f"https://www.congress.gov/bill/119th-congress/{slug}/1"
        assert URL_PATTERN.match(example_url), (
            f"Pattern failed for {bill_type} → {slug}: {example_url}"
        )
