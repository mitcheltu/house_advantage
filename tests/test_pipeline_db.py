"""
Pipeline & Database Integration Tests

Verifies:
  - Step 1 (Congress.gov) collectors produce valid CSVs
  - DB schema exists and tables are created
  - CSV data loads correctly into MySQL tables
  - FK resolution works for dependent tables
"""
import os
import sys
import pytest
import pandas as pd
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DATA_RAW = Path(__file__).resolve().parent.parent / "backend" / "data" / "raw"


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db_engine():
    """Provide a SQLAlchemy engine connected to the MySQL database."""
    from backend.db.connection import get_engine
    engine = get_engine()
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def db_conn(db_engine):
    """Provide a raw DB connection for queries."""
    with db_engine.connect() as conn:
        yield conn


def _table_count(conn, table: str) -> int:
    from sqlalchemy import text
    return conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar()


# ============================================================
# 1. DATABASE CONNECTIVITY
# ============================================================

class TestDatabaseConnection:
    """Verify the MySQL database is reachable and configured."""

    def test_connection_alive(self):
        from backend.db.connection import test_connection
        assert test_connection(), "Cannot connect to MySQL — is the container running?"

    def test_database_exists(self, db_conn):
        from sqlalchemy import text
        result = db_conn.execute(text("SELECT DATABASE()")).scalar()
        assert result == "house_advantage"


# ============================================================
# 2. SCHEMA VALIDATION
# ============================================================

EXPECTED_TABLES = [
    "politicians", "committees", "committee_memberships",
    "trades", "votes", "politician_votes", "bills",
    "stock_prices", "institutional_holdings", "institutional_trades",
    "fec_candidates", "fec_candidate_totals", "cusip_ticker_map",
    "anomaly_scores", "audit_reports",
]


class TestSchema:
    """Verify all expected tables exist in the database."""

    def test_all_tables_exist(self, db_conn):
        from sqlalchemy import text
        rows = db_conn.execute(text("SHOW TABLES")).fetchall()
        actual_tables = {r[0] for r in rows}
        for table in EXPECTED_TABLES:
            assert table in actual_tables, f"Table '{table}' missing from database"

    @pytest.mark.parametrize("table,column", [
        ("politicians", "bioguide_id"),
        ("politicians", "full_name"),
        ("politicians", "chamber"),
        ("committees", "committee_id"),
        ("committees", "name"),
        ("trades", "ticker"),
        ("trades", "trade_type"),
        ("trades", "trade_date"),
        ("votes", "roll_call_id"),
        ("bills", "bill_id"),
        ("fec_candidates", "candidate_id"),
    ])
    def test_critical_columns_exist(self, db_conn, table, column):
        from sqlalchemy import text
        rows = db_conn.execute(text(f"SHOW COLUMNS FROM `{table}`")).fetchall()
        col_names = {r[0] for r in rows}
        assert column in col_names, f"Column '{column}' missing from '{table}'"


# ============================================================
# 3. STEP 1 — RAW CSV OUTPUT VALIDATION
# ============================================================

class TestStep1RawCSVs:
    """Verify Step 1 (Congress.gov) produced valid raw CSV files."""

    def test_politicians_csv_exists(self):
        path = DATA_RAW / "politicians_raw.csv"
        assert path.exists(), "politicians_raw.csv not found"
        assert path.stat().st_size > 1000, "politicians_raw.csv is suspiciously small"

    def test_politicians_csv_has_data(self):
        df = pd.read_csv(DATA_RAW / "politicians_raw.csv")
        assert len(df) >= 400, f"Expected ≥400 politicians, got {len(df)}"

    def test_politicians_csv_columns(self):
        df = pd.read_csv(DATA_RAW / "politicians_raw.csv")
        required = {"id", "full_name", "party", "chamber", "state"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_politicians_no_null_bioguide(self):
        df = pd.read_csv(DATA_RAW / "politicians_raw.csv")
        assert df["id"].isna().sum() == 0, "Found null bioguide IDs"

    def test_politicians_valid_chambers(self):
        df = pd.read_csv(DATA_RAW / "politicians_raw.csv")
        valid = {"house", "senate"}
        actual = set(df["chamber"].str.lower().unique())
        assert actual.issubset(valid), f"Invalid chambers: {actual - valid}"

    def test_politicians_valid_parties(self):
        df = pd.read_csv(DATA_RAW / "politicians_raw.csv")
        valid = {"R", "D", "I"}
        actual = set(df["party"].unique())
        assert actual.issubset(valid), f"Invalid parties: {actual - valid}"

    def test_committees_csv_exists(self):
        path = DATA_RAW / "committees_raw.csv"
        assert path.exists(), "committees_raw.csv not found"
        assert path.stat().st_size > 500, "committees_raw.csv is suspiciously small"

    def test_committees_csv_has_data(self):
        df = pd.read_csv(DATA_RAW / "committees_raw.csv")
        assert len(df) >= 20, f"Expected ≥20 committees, got {len(df)}"

    def test_committees_csv_columns(self):
        df = pd.read_csv(DATA_RAW / "committees_raw.csv")
        required = {"id", "name", "chamber"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_committee_memberships_csv_exists(self):
        path = DATA_RAW / "committee_memberships_raw.csv"
        assert path.exists(), "committee_memberships_raw.csv not found"

    def test_committee_memberships_csv_has_data(self):
        path = DATA_RAW / "committee_memberships_raw.csv"
        if not path.exists():
            pytest.skip("committee_memberships_raw.csv not found")
        df = pd.read_csv(path)
        assert len(df) >= 100, f"Expected ≥100 memberships, got {len(df)}"

    def test_committee_memberships_csv_columns(self):
        path = DATA_RAW / "committee_memberships_raw.csv"
        if not path.exists():
            pytest.skip("committee_memberships_raw.csv not found")
        df = pd.read_csv(path)
        required = {"politician_id", "committee_id"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )


# ============================================================
# 4. DATABASE DATA VALIDATION — Tables with data
# ============================================================

class TestDBDataLoaded:
    """Verify that CSV data was actually inserted into the database."""

    def test_politicians_table_populated(self, db_conn):
        count = _table_count(db_conn, "politicians")
        assert count >= 400, (
            f"Expected ≥400 politicians in DB, got {count}. "
            "Run step 12 (MySQL Load) to populate."
        )

    def test_politicians_have_bioguide_ids(self, db_conn):
        from sqlalchemy import text
        nulls = db_conn.execute(text(
            "SELECT COUNT(*) FROM politicians WHERE bioguide_id IS NULL"
        )).scalar()
        assert nulls == 0, f"{nulls} politicians have NULL bioguide_id"

    def test_politicians_have_valid_chambers(self, db_conn):
        from sqlalchemy import text
        rows = db_conn.execute(text(
            "SELECT DISTINCT chamber FROM politicians"
        )).fetchall()
        chambers = {r[0] for r in rows}
        assert chambers.issubset({"House", "Senate"}), (
            f"Invalid chamber values in DB: {chambers}"
        )

    def test_committees_table_populated(self, db_conn):
        count = _table_count(db_conn, "committees")
        assert count >= 20, (
            f"Expected ≥20 committees in DB, got {count}. "
            "Run step 12 (MySQL Load) to populate."
        )

    def test_fec_candidates_table_populated(self, db_conn):
        count = _table_count(db_conn, "fec_candidates")
        assert count >= 50, (
            f"Expected ≥50 FEC candidates in DB, got {count}."
        )

    def test_fec_totals_table_populated(self, db_conn):
        count = _table_count(db_conn, "fec_candidate_totals")
        assert count >= 50, (
            f"Expected ≥50 FEC totals in DB, got {count}."
        )


# ============================================================
# 5. DATABASE FK INTEGRITY
# ============================================================

class TestDBForeignKeys:
    """Verify FK relationships are intact in loaded data."""

    def test_committee_memberships_fks_valid(self, db_conn):
        """Every membership should point to existing politician and committee."""
        from sqlalchemy import text
        count = _table_count(db_conn, "committee_memberships")
        if count == 0:
            pytest.skip("committee_memberships is empty — FK test N/A")
        orphan_pol = db_conn.execute(text("""
            SELECT COUNT(*) FROM committee_memberships cm
            LEFT JOIN politicians p ON cm.politician_id = p.id
            WHERE p.id IS NULL
        """)).scalar()
        assert orphan_pol == 0, f"{orphan_pol} memberships have orphaned politician_id"

        orphan_com = db_conn.execute(text("""
            SELECT COUNT(*) FROM committee_memberships cm
            LEFT JOIN committees c ON cm.committee_id = c.id
            WHERE c.id IS NULL
        """)).scalar()
        assert orphan_com == 0, f"{orphan_com} memberships have orphaned committee_id"

    def test_trades_politician_fks_valid(self, db_conn):
        """Trades with politician_id set should reference existing politicians."""
        from sqlalchemy import text
        count = _table_count(db_conn, "trades")
        if count == 0:
            pytest.skip("trades is empty — FK test N/A")
        orphans = db_conn.execute(text("""
            SELECT COUNT(*) FROM trades t
            LEFT JOIN politicians p ON t.politician_id = p.id
            WHERE t.politician_id IS NOT NULL AND p.id IS NULL
        """)).scalar()
        assert orphans == 0, f"{orphans} trades have orphaned politician_id"

    def test_fec_totals_candidate_fks_valid(self, db_conn):
        """FEC totals should reference existing candidates."""
        from sqlalchemy import text
        count = _table_count(db_conn, "fec_candidate_totals")
        if count == 0:
            pytest.skip("fec_candidate_totals is empty — FK test N/A")
        orphans = db_conn.execute(text("""
            SELECT COUNT(*) FROM fec_candidate_totals t
            LEFT JOIN fec_candidates c ON t.candidate_id = c.candidate_id
            WHERE c.candidate_id IS NULL
        """)).scalar()
        assert orphans == 0, f"{orphans} FEC totals have orphaned candidate_id"


# ============================================================
# 6. DATA QUALITY CHECKS
# ============================================================

class TestDataQuality:
    """Validate data quality in raw CSVs and DB tables."""

    def test_no_duplicate_politicians_in_db(self, db_conn):
        from sqlalchemy import text
        dupes = db_conn.execute(text("""
            SELECT bioguide_id, COUNT(*) as cnt
            FROM politicians
            GROUP BY bioguide_id
            HAVING cnt > 1
        """)).fetchall()
        assert len(dupes) == 0, f"Duplicate bioguide_ids: {[d[0] for d in dupes]}"

    def test_no_duplicate_committees_in_db(self, db_conn):
        from sqlalchemy import text
        dupes = db_conn.execute(text("""
            SELECT committee_id, COUNT(*) as cnt
            FROM committees
            GROUP BY committee_id
            HAVING cnt > 1
        """)).fetchall()
        assert len(dupes) == 0, f"Duplicate committee_ids: {[d[0] for d in dupes]}"

    def test_trades_csv_has_required_fields(self):
        path = DATA_RAW / "congressional_trades_raw.csv"
        if not path.exists():
            pytest.skip("congressional_trades_raw.csv not found")
        df = pd.read_csv(path)
        required = {"politician_id", "ticker", "trade_type", "trade_date"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_trades_csv_valid_trade_types(self):
        path = DATA_RAW / "congressional_trades_raw.csv"
        if not path.exists():
            pytest.skip("congressional_trades_raw.csv not found")
        df = pd.read_csv(path)
        valid = {"buy", "sell", "exchange"}
        actual = set(df["trade_type"].str.lower().unique())
        assert actual.issubset(valid), f"Invalid trade types: {actual - valid}"

    def test_politicians_csv_unique_bioguide(self):
        df = pd.read_csv(DATA_RAW / "politicians_raw.csv")
        dupes = df[df["id"].duplicated()]
        assert len(dupes) == 0, (
            f"{len(dupes)} duplicate bioguide IDs in CSV: "
            f"{list(dupes['id'].values[:5])}"
        )

    def test_db_politicians_match_csv_count(self, db_conn):
        """DB row count should match CSV row count (after dedup)."""
        df = pd.read_csv(DATA_RAW / "politicians_raw.csv")
        csv_unique = df.drop_duplicates(subset=["id"])
        db_count = _table_count(db_conn, "politicians")
        assert db_count == len(csv_unique), (
            f"DB has {db_count} politicians vs {len(csv_unique)} unique in CSV"
        )

    def test_db_committees_match_csv_count(self, db_conn):
        """DB row count should match CSV row count (after dedup)."""
        df = pd.read_csv(DATA_RAW / "committees_raw.csv")
        csv_unique = df.drop_duplicates(subset=["id"])
        db_count = _table_count(db_conn, "committees")
        assert db_count == len(csv_unique), (
            f"DB has {db_count} committees vs {len(csv_unique)} unique in CSV"
        )


# ============================================================
# 7. STEP 1 API CONNECTIVITY (lightweight — no full pull)
# ============================================================

class TestStep1API:
    """Verify Congress.gov API is reachable with the configured key."""

    def test_congress_api_key_set(self):
        from dotenv import load_dotenv
        load_dotenv()
        key = os.getenv("CONGRESS_GOV_API_KEY", "")
        assert key, "CONGRESS_GOV_API_KEY not set in .env"

    def test_congress_api_reachable(self):
        """Make a single lightweight API call to verify connectivity."""
        import requests
        from dotenv import load_dotenv
        load_dotenv()
        key = os.getenv("CONGRESS_GOV_API_KEY", "")
        if not key:
            pytest.skip("No CONGRESS_GOV_API_KEY")
        resp = requests.get(
            "https://api.congress.gov/v3/member",
            params={"api_key": key, "format": "json", "limit": 1},
            timeout=15,
        )
        assert resp.status_code == 200, (
            f"Congress.gov API returned {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert "members" in data, "Unexpected API response format"


# ============================================================
# 8. DB LOADER UNIT TESTS
# ============================================================

class TestDBLoaderFunctions:
    """Test individual DB loader helper functions."""

    def test_state_to_abbrev(self):
        from backend.db.setup_db import _state_to_abbrev
        assert _state_to_abbrev("California") == "CA"
        assert _state_to_abbrev("new york") == "NY"
        assert _state_to_abbrev("TX") == "TX"
        assert _state_to_abbrev("tx") == "TX"

    def test_capitalize_chamber(self):
        from backend.db.setup_db import _capitalize_chamber
        assert _capitalize_chamber("house") == "House"
        assert _capitalize_chamber("senate") == "Senate"
        assert _capitalize_chamber("joint") == "Joint"
        assert _capitalize_chamber("House") == "House"


# ============================================================
# 9. EMPTY TABLE DIAGNOSTICS
# ============================================================

class TestEmptyTableDiagnostics:
    """Flag tables that should have data but are currently empty."""

    @pytest.mark.parametrize("table,csv_file", [
        ("trades", "congressional_trades_raw.csv"),
        ("committee_memberships", "committee_memberships_raw.csv"),
    ])
    def test_table_populated_if_csv_exists(self, db_conn, table, csv_file):
        """If the raw CSV exists and has data, the DB table should too."""
        csv_path = DATA_RAW / csv_file
        if not csv_path.exists():
            pytest.skip(f"{csv_file} not found")
        csv_df = pd.read_csv(csv_path)
        if csv_df.empty:
            pytest.skip(f"{csv_file} is empty")

        db_count = _table_count(db_conn, table)
        assert db_count > 0, (
            f"Table '{table}' has 0 rows but {csv_file} has {len(csv_df)} rows. "
            f"The DB loader may have a FK resolution issue."
        )
