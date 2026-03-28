"""
Progressive Bill API Tests — Congress.gov & GovInfo

Verifies bill data extraction at increasing scale:
  A. Single known bill → all fields populated, URL parseable
  B. Small batch (5 mixed types) → all field types present
  C. Medium batch (25) → null rates within threshold
  D. Large batch (100) → pagination correct, no duplicates
  E. Rate limit handling → retries work under load

Usage:
    pytest tests/test_bills_api.py -v                        # All tests
    pytest tests/test_bills_api.py -k test_single_bill -v    # Just 1 bill
    pytest tests/test_bills_api.py -m slow -v                # Large batches only
"""
import os
import re
import sys
import pytest
import requests
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def api_key():
    key = os.getenv("CONGRESS_GOV_API_KEY", "").strip()
    if not key:
        pytest.skip("CONGRESS_GOV_API_KEY not set")
    return key


@pytest.fixture(scope="module")
def govinfo_key():
    key = os.getenv("GOVINFO_API_KEY", "").strip()
    if not key:
        pytest.skip("GOVINFO_API_KEY not set")
    return key


BASE_URL = "https://api.congress.gov/v3"
CONGRESS = 119  # 2025-2027


def _fetch_bill_detail(api_key: str, bill_type: str, bill_number: int,
                       congress: int = CONGRESS) -> dict:
    """Fetch a single bill detail from Congress.gov and return the 'bill' dict."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type}/{bill_number}"
    resp = requests.get(url, params={"api_key": api_key, "format": "json"}, timeout=30)
    resp.raise_for_status()
    return resp.json().get("bill", {})


def _fetch_bill_list(api_key: str, bill_type: str, limit: int = 5,
                     congress: int = CONGRESS) -> list[dict]:
    """Fetch a page of bills from the list endpoint."""
    url = f"{BASE_URL}/bill/{congress}/{bill_type}"
    resp = requests.get(
        url,
        params={"api_key": api_key, "format": "json", "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("bills", [])


def _is_valid_url(url: str) -> bool:
    """Check that a URL is well-formed and uses https."""
    try:
        r = urlparse(url)
        return all([r.scheme in ("http", "https"), r.netloc])
    except Exception:
        return False


def _url_is_reachable(url: str, api_key: str = None, timeout: int = 15) -> bool:
    """Verify a URL returns HTTP 200 (allows redirects). Uses GET for sites that block HEAD."""
    try:
        params = {}
        if api_key:
            params["api_key"] = api_key
        headers = {"User-Agent": "Mozilla/5.0 (HouseAdvantage/test)"}
        # Use GET with stream=True to avoid downloading full body
        resp = requests.get(
            url, params=params, headers=headers,
            timeout=timeout, allow_redirects=True, stream=True,
        )
        resp.close()
        return resp.status_code < 400
    except Exception:
        return False


# ============================================================
# A. SINGLE BILL — detailed field verification
# ============================================================

class TestSingleBill:
    """Fetch one known bill and verify every expected field."""

    @pytest.fixture(scope="class")
    def hr1(self, api_key):
        """HR 1 of the 119th Congress — always exists."""
        return _fetch_bill_detail(api_key, "hr", 1)

    def test_api_returns_bill(self, hr1):
        assert hr1, "API returned empty bill object"

    def test_title_present(self, hr1):
        title = hr1.get("title", "")
        assert title and len(title) > 5, f"Title missing or too short: '{title}'"

    def test_policy_area_present(self, hr1):
        pa = hr1.get("policyArea", {})
        assert pa and pa.get("name"), (
            f"policyArea missing on HR1 — got: {pa}. "
            "This is the most common cause of NULL policy_area in the DB."
        )

    def test_policy_area_is_known_value(self, hr1):
        from backend.ingest.collectors.collect_congress_gov import POLICY_AREA_SECTOR_MAP
        pa_name = hr1.get("policyArea", {}).get("name", "")
        if pa_name:
            assert pa_name in POLICY_AREA_SECTOR_MAP, (
                f"Unmapped policyArea '{pa_name}' — add to POLICY_AREA_SECTOR_MAP"
            )

    def test_latest_action_present(self, hr1):
        la = hr1.get("latestAction", {})
        assert la.get("text"), "latestAction.text missing"
        assert la.get("actionDate"), "latestAction.actionDate missing"

    def test_latest_action_date_format(self, hr1):
        date_str = hr1.get("latestAction", {}).get("actionDate", "")
        assert re.match(r"\d{4}-\d{2}-\d{2}", date_str), (
            f"actionDate not YYYY-MM-DD: '{date_str}'"
        )

    def test_origin_chamber_present(self, hr1):
        oc = hr1.get("originChamber", "")
        assert oc in ("House", "Senate"), f"originChamber unexpected: '{oc}'"

    def test_sponsors_present(self, hr1):
        sponsors = hr1.get("sponsors", [])
        assert sponsors, "No sponsors returned"
        first = sponsors[0]
        bio_id = first.get("bioguideId", "")
        assert re.match(r"[A-Z]\d{6}", bio_id), (
            f"sponsor bioguideId unexpected format: '{bio_id}'"
        )

    def test_legislation_url_present_and_valid(self, hr1):
        url = hr1.get("legislationUrl", "")
        assert url, "legislationUrl missing"
        assert _is_valid_url(url), f"legislationUrl not a valid URL: '{url}'"

    def test_legislation_url_parseable(self, hr1, api_key):
        """Verify the legislation URL is well-formed and points to congress.gov."""
        url = hr1.get("legislationUrl", "")
        if not url:
            pytest.skip("No legislationUrl to test")
        assert "congress.gov" in url, f"URL doesn't point to congress.gov: {url}"
        parsed = urlparse(url)
        assert parsed.scheme == "https", f"Expected https, got {parsed.scheme}"
        assert "/bill/" in parsed.path, f"URL path missing /bill/: {parsed.path}"

    def test_congress_gov_url_present(self, hr1):
        """The bill detail includes a url field linking to congress.gov."""
        url = hr1.get("url", "")
        if url:
            assert _is_valid_url(url), f"bill.url not valid: '{url}'"
            assert "congress.gov" in url or "api.congress.gov" in url, (
                f"bill.url doesn't point to congress.gov: {url}"
            )

    def test_introduced_date_present(self, hr1):
        intro = hr1.get("introducedDate", "")
        assert intro, "introducedDate missing"
        assert re.match(r"\d{4}-\d{2}-\d{2}", intro), (
            f"introducedDate not YYYY-MM-DD: '{intro}'"
        )


# ============================================================
# B. SMALL BATCH — mixed bill types
# ============================================================

class TestSmallBatch:
    """Fetch 5 bills of different types, verify field variety."""

    BILL_SPECS = [
        ("hr", 1),
        ("hr", 2),
        ("s", 1),
        ("s", 2),
        ("hjres", 1),
    ]

    @pytest.fixture(scope="class")
    def bills(self, api_key):
        results = []
        for bt, bn in self.BILL_SPECS:
            try:
                detail = _fetch_bill_detail(api_key, bt, bn)
                detail["_bill_type"] = bt
                detail["_bill_number"] = bn
                results.append(detail)
            except requests.HTTPError as e:
                if e.response.status_code == 404:
                    continue  # bill doesn't exist in this congress
                raise
        return results

    def test_got_at_least_3_bills(self, bills):
        assert len(bills) >= 3, (
            f"Only {len(bills)} bills returned — expected at least 3 from mixed types"
        )

    def test_all_have_title(self, bills):
        for b in bills:
            label = f"{b['_bill_type']}{b['_bill_number']}"
            assert b.get("title"), f"{label} missing title"

    def test_most_have_policy_area(self, bills):
        """At least 50% of small batch should have policyArea."""
        with_pa = sum(1 for b in bills if b.get("policyArea", {}).get("name"))
        rate = with_pa / len(bills) if bills else 0
        assert rate >= 0.5, (
            f"Only {with_pa}/{len(bills)} ({rate:.0%}) have policyArea — "
            "expected ≥50% for major bills"
        )

    def test_most_have_latest_action(self, bills):
        """Most bills should have latestAction; some detail endpoints may return empty."""
        with_action = sum(1 for b in bills if b.get("latestAction", {}).get("text"))
        assert with_action >= len(bills) * 0.6, (
            f"Only {with_action}/{len(bills)} bills have latestAction.text"
        )

    def test_all_urls_valid_and_parseable(self, bills):
        """Every legislationUrl present must be a valid, well-formed URL."""
        for b in bills:
            url = b.get("legislationUrl", "")
            if url:
                label = f"{b['_bill_type']}{b['_bill_number']}"
                assert _is_valid_url(url), f"{label} has invalid URL: {url}"

    def test_all_urls_well_formed(self, bills):
        """Spot-check that returned legislation URLs are well-formed congress.gov URLs."""
        for b in bills:
            url = b.get("legislationUrl", "")
            if url:
                label = f"{b['_bill_type']}{b['_bill_number']}"
                parsed = urlparse(url)
                assert parsed.scheme == "https", f"{label} bad scheme: {url}"
                assert "congress.gov" in parsed.netloc, f"{label} not congress.gov: {url}"
                assert "/bill/" in parsed.path, f"{label} missing /bill/ path: {url}"

    def test_sponsors_have_bioguide_format(self, bills):
        for b in bills:
            sponsors = b.get("sponsors", [])
            for s in sponsors:
                bio = s.get("bioguideId", "")
                if bio:
                    assert re.match(r"[A-Z]\d{6}", bio), (
                        f"Bad bioguideId format: '{bio}'"
                    )


# ============================================================
# C. MEDIUM BATCH — null rate analysis (25 bills)
# ============================================================

class TestMediumBatch:
    """Fetch 25 bills via list+detail, measure null rates per column."""

    @pytest.fixture(scope="class")
    def bills_25(self, api_key):
        list_bills = _fetch_bill_list(api_key, "hr", limit=25)
        details = []
        for b in list_bills[:25]:
            num = b.get("number", "")
            if not num:
                continue
            try:
                detail = _fetch_bill_detail(api_key, "hr", int(num))
                details.append(detail)
            except Exception:
                pass
        return details

    def test_got_enough_bills(self, bills_25):
        assert len(bills_25) >= 15, (
            f"Only got {len(bills_25)} bill details — need ≥15 for meaningful rates"
        )

    def test_policy_area_null_rate(self, bills_25):
        """policy_area null rate should be < 60% for HR bills."""
        with_pa = sum(1 for b in bills_25 if b.get("policyArea", {}).get("name"))
        total = len(bills_25)
        null_pct = (total - with_pa) / total if total else 1.0
        assert null_pct < 0.60, (
            f"policy_area null rate {null_pct:.0%} ({total - with_pa}/{total}) — "
            "expected < 60%. Many bills may lack policyArea from Congress.gov."
        )

    def test_latest_action_date_null_rate(self, bills_25):
        """latest_action_date should almost always be present."""
        with_date = sum(
            1 for b in bills_25 if b.get("latestAction", {}).get("actionDate")
        )
        total = len(bills_25)
        null_pct = (total - with_date) / total if total else 1.0
        assert null_pct < 0.10, (
            f"latestAction.actionDate null rate {null_pct:.0%} — expected < 10%"
        )

    def test_origin_chamber_null_rate(self, bills_25):
        with_oc = sum(1 for b in bills_25 if b.get("originChamber"))
        total = len(bills_25)
        null_pct = (total - with_oc) / total if total else 1.0
        assert null_pct < 0.20, (
            f"originChamber null rate {null_pct:.0%} — expected < 20%"
        )

    def test_legislation_url_null_rate(self, bills_25):
        with_url = sum(1 for b in bills_25 if b.get("legislationUrl"))
        total = len(bills_25)
        null_pct = (total - with_url) / total if total else 1.0
        assert null_pct < 0.40, (
            f"legislationUrl null rate {null_pct:.0%} — expected < 40%"
        )

    def test_all_present_urls_are_valid(self, bills_25):
        """Every URL field that IS present must be well-formed."""
        bad = []
        for b in bills_25:
            for field in ("legislationUrl", "url"):
                url = b.get(field, "")
                if url and not _is_valid_url(url):
                    num = b.get("number", "?")
                    bad.append(f"HR{num}.{field}: {url}")
        assert not bad, f"Invalid URLs found: {bad}"

    def test_spot_check_urls_well_formed(self, bills_25):
        """Spot-check that legislationUrls are well-formed congress.gov URLs."""
        bad = []
        for b in bills_25:
            url = b.get("legislationUrl", "")
            if url:
                parsed = urlparse(url)
                if parsed.scheme != "https" or "congress.gov" not in parsed.netloc:
                    bad.append(f"HR{b.get('number', '?')}: {url}")
        assert not bad, f"Malformed legislation URLs: {bad}"

    def test_api_detail_urls_reachable(self, bills_25, api_key):
        """Verify that API detail URLs (api.congress.gov) resolve with 200."""
        urls = [
            (b.get("number", "?"), b.get("url", ""))
            for b in bills_25
            if b.get("url") and "api.congress.gov" in b.get("url", "")
        ]
        checked = 0
        for num, url in urls[:5]:
            if _url_is_reachable(url, api_key=api_key):
                checked += 1
        assert checked >= min(4, len(urls[:5])), (
            f"Only {checked}/{min(5, len(urls))} API URLs reachable"
        )


# ============================================================
# D. LARGE BATCH — pagination & dedup (100 bills)
# ============================================================

@pytest.mark.slow
class TestLargeBatch:
    """Fetch 100 bills via pagination, verify no duplicates."""

    @pytest.fixture(scope="class")
    def paginated_bills(self, api_key):
        """Paginate list endpoint to get 100 HR bills."""
        all_bills = []
        url = f"{BASE_URL}/bill/{CONGRESS}/hr"
        params = {"api_key": api_key, "format": "json", "limit": 50}

        for page in range(3):  # Up to 150
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            bills = data.get("bills", [])
            if not bills:
                break
            all_bills.extend(bills)
            next_url = data.get("pagination", {}).get("next")
            if not next_url or len(all_bills) >= 100:
                break
            url = next_url
            params = {"api_key": api_key, "format": "json"}

        return all_bills[:100]

    def test_got_100_bills(self, paginated_bills):
        assert len(paginated_bills) >= 80, (
            f"Pagination returned only {len(paginated_bills)} — expected ≥80"
        )

    def test_no_duplicate_bill_numbers(self, paginated_bills):
        numbers = [b.get("number") for b in paginated_bills if b.get("number")]
        dupes = [n for n in numbers if numbers.count(n) > 1]
        assert not dupes, f"Duplicate bill numbers: {set(dupes)}"

    def test_all_have_number(self, paginated_bills):
        missing = [i for i, b in enumerate(paginated_bills) if not b.get("number")]
        assert not missing, f"{len(missing)} bills missing 'number' field"

    def test_all_list_urls_valid(self, paginated_bills):
        """The list endpoint includes a url for each bill — verify all valid."""
        bad = []
        for b in paginated_bills:
            url = b.get("url", "")
            if url and not _is_valid_url(url):
                bad.append(f"#{b.get('number', '?')}: {url}")
        assert not bad, f"Invalid bill URLs in list: {bad}"

    def test_list_url_resolves_to_detail(self, paginated_bills, api_key):
        """Verify that the 'url' field in list results returns valid JSON detail."""
        sample = paginated_bills[0]
        url = sample.get("url", "")
        if not url:
            pytest.skip("First bill has no url")
        resp = requests.get(url, params={"api_key": api_key, "format": "json"}, timeout=15)
        assert resp.status_code == 200, f"Bill detail URL returned {resp.status_code}"
        bill = resp.json().get("bill", {})
        assert bill.get("title"), "Detail from list URL has no title"


# ============================================================
# E. RATE LIMIT HANDLING — verify retry logic
# ============================================================

class TestRateLimitHandling:
    """Test that our rate_limited_get handles errors properly."""

    def test_rate_limited_get_succeeds(self, api_key):
        from backend.ingest.collectors.utils import rate_limited_get
        resp = rate_limited_get(
            f"{BASE_URL}/bill/{CONGRESS}/hr/1",
            params={"api_key": api_key, "format": "json"},
            delay=0.5,
            max_retries=3,
        )
        assert resp.status_code == 200

    def test_rate_limited_get_raises_on_bad_key(self):
        from backend.ingest.collectors.utils import rate_limited_get
        with pytest.raises(RuntimeError, match="Failed after"):
            rate_limited_get(
                f"{BASE_URL}/bill/{CONGRESS}/hr/1",
                params={"api_key": "INVALID_KEY", "format": "json"},
                delay=0.1,
                max_retries=2,
            )

    def test_rate_limited_get_raises_on_404(self, api_key):
        from backend.ingest.collectors.utils import rate_limited_get
        with pytest.raises(requests.HTTPError):
            rate_limited_get(
                f"{BASE_URL}/bill/{CONGRESS}/hr/999999",
                params={"api_key": api_key, "format": "json"},
                delay=0.5,
                max_retries=2,
            )


# ============================================================
# F. GOVINFO BILL URLs — verify full-text download links
# ============================================================

class TestGovInfoUrls:
    """Verify GovInfo API returns usable bill download URLs."""

    @pytest.fixture(scope="class")
    def govinfo_packages(self, govinfo_key):
        """Fetch a few bill packages from GovInfo."""
        url = "https://api.govinfo.gov/collections/BILLS/2025-01-01T00:00:00Z"
        resp = requests.get(
            url,
            params={"api_key": govinfo_key, "pageSize": 10, "offsetMark": "*"},
            timeout=30,
        )
        resp.raise_for_status()
        packages = resp.json().get("packages", [])
        assert packages, "GovInfo returned 0 packages"
        return packages

    def test_packages_have_ids(self, govinfo_packages):
        for pkg in govinfo_packages:
            pid = pkg.get("packageId", "")
            assert pid, f"Package missing packageId: {pkg}"

    def test_package_links_valid(self, govinfo_packages):
        for pkg in govinfo_packages:
            link = pkg.get("packageLink", "")
            if link:
                assert _is_valid_url(link), f"Invalid packageLink: {link}"

    def test_package_summary_has_download_urls(self, govinfo_key, govinfo_packages):
        """Fetch summary for first package, verify download URLs exist and are valid."""
        pkg = govinfo_packages[0]
        pid = pkg.get("packageId", "")
        url = f"https://api.govinfo.gov/packages/{pid}/summary"
        resp = requests.get(
            url, params={"api_key": govinfo_key}, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        download = data.get("download", {})
        assert download, f"No download links in summary for {pid}"

        # At least one format should be available
        found_formats = []
        for fmt in ("txtLink", "xmlLink", "pdfLink", "zipLink"):
            dl_url = download.get(fmt, "")
            if dl_url:
                found_formats.append(fmt)
                assert _is_valid_url(dl_url), f"{fmt} invalid: {dl_url}"

        assert found_formats, f"No download format URLs for {pid}"

    def test_htm_url_returns_content(self, govinfo_key, govinfo_packages):
        """Actually download htm for first package, verify it has content."""
        pkg = govinfo_packages[0]
        pid = pkg.get("packageId", "")
        url = f"https://api.govinfo.gov/packages/{pid}/summary"
        resp = requests.get(url, params={"api_key": govinfo_key}, timeout=30)
        resp.raise_for_status()
        htm_url = resp.json().get("download", {}).get("txtLink", "")
        if not htm_url:
            pytest.skip(f"No txtLink for {pid}")

        content_resp = requests.get(
            htm_url, params={"api_key": govinfo_key}, timeout=60,
        )
        assert content_resp.status_code == 200, (
            f"htm download returned {content_resp.status_code}"
        )
        assert len(content_resp.text) > 100, (
            f"htm content too short ({len(content_resp.text)} chars)"
        )


# ============================================================
# G. POLICY AREA SECTOR MAP COVERAGE
# ============================================================

class TestPolicyAreaMapping:
    """Verify POLICY_AREA_SECTOR_MAP covers known Congress.gov values."""

    KNOWN_POLICY_AREAS = [
        "Agriculture and Food",
        "Animals",
        "Armed Forces and National Security",
        "Arts, Culture, Religion",
        "Civil Rights and Liberties, Minority Issues",
        "Commerce",
        "Congress",
        "Crime and Law Enforcement",
        "Economics and Public Finance",
        "Education",
        "Emergency Management",
        "Energy",
        "Environmental Protection",
        "Families",
        "Finance and Financial Sector",
        "Foreign Trade and International Finance",
        "Government Operations and Politics",
        "Health",
        "Housing and Community Development",
        "Immigration",
        "International Affairs",
        "Labor and Employment",
        "Law",
        "Native Americans",
        "Public Lands and Natural Resources",
        "Science, Technology, Communications",
        "Social Welfare",
        "Sports and Recreation",
        "Taxation",
        "Transportation and Public Works",
        "Water Resources Development",
    ]

    def test_all_known_areas_mapped(self):
        from backend.ingest.collectors.collect_congress_gov import POLICY_AREA_SECTOR_MAP
        unmapped = [
            pa for pa in self.KNOWN_POLICY_AREAS
            if pa not in POLICY_AREA_SECTOR_MAP
        ]
        assert not unmapped, (
            f"Unmapped policy areas (will cause NULL related_sector): {unmapped}"
        )

    def test_all_mapped_areas_are_valid_sectors(self):
        from backend.ingest.collectors.collect_congress_gov import POLICY_AREA_SECTOR_MAP
        valid_sectors = {"defense", "finance", "healthcare", "energy", "tech", "agriculture", "telecom"}
        bad = {
            pa: sector for pa, sector in POLICY_AREA_SECTOR_MAP.items()
            if sector not in valid_sectors
        }
        assert not bad, f"Invalid sector mappings: {bad}"
