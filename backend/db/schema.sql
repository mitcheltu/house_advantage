-- ============================================================
-- House Advantage — MySQL 8.0 Schema
-- ============================================================
-- Run: mysql -u root -p < backend/db/schema.sql
-- Or use the Python loader: backend/db/setup_db.py
-- ============================================================

CREATE DATABASE IF NOT EXISTS house_advantage
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE house_advantage;

-- ============================================================
-- 1. POLITICIANS
-- ============================================================
CREATE TABLE IF NOT EXISTS politicians (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    bioguide_id    VARCHAR(20)  UNIQUE NOT NULL,
    first_name     VARCHAR(100),
    last_name      VARCHAR(100),
    full_name      VARCHAR(200) NOT NULL,
    party          VARCHAR(50),
    state          VARCHAR(2),
    district       VARCHAR(10),
    chamber        ENUM('House', 'Senate') NOT NULL,
    start_date     DATE,
    end_date       DATE,
    url            VARCHAR(500),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_party (party),
    INDEX idx_state (state),
    INDEX idx_chamber (chamber)
) ENGINE=InnoDB;

-- ============================================================
-- 2. COMMITTEES
-- ============================================================
CREATE TABLE IF NOT EXISTS committees (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    committee_id   VARCHAR(20)  UNIQUE NOT NULL,
    name           VARCHAR(300) NOT NULL,
    chamber        ENUM('House', 'Senate', 'Joint'),
    committee_type VARCHAR(50),
    sector_tag     VARCHAR(100),
    url            VARCHAR(500),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sector (sector_tag),
    INDEX idx_chamber (chamber)
) ENGINE=InnoDB;

-- ============================================================
-- 3. COMMITTEE MEMBERSHIPS
-- ============================================================
CREATE TABLE IF NOT EXISTS committee_memberships (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    politician_id  INT NOT NULL,
    committee_id   INT NOT NULL,
    role           VARCHAR(100),
    start_date     DATE,
    end_date       DATE,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (politician_id) REFERENCES politicians(id) ON DELETE CASCADE,
    FOREIGN KEY (committee_id) REFERENCES committees(id) ON DELETE CASCADE,
    UNIQUE KEY uq_membership (politician_id, committee_id),
    INDEX idx_politician (politician_id),
    INDEX idx_committee (committee_id)
) ENGINE=InnoDB;

-- ============================================================
-- 4. CONGRESSIONAL TRADES (from House Clerk + Senate eFD STOCK Act disclosures)
-- ============================================================
CREATE TABLE IF NOT EXISTS trades (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    politician_id    INT,
    ticker           VARCHAR(10)  NOT NULL,
    company_name     VARCHAR(300),
    trade_type       ENUM('buy', 'sell', 'exchange') NOT NULL,
    trade_date       DATE NOT NULL,
    disclosure_date  DATE,
    disclosure_lag_days INT,
    amount_lower     INT,
    amount_upper     INT,
    amount_midpoint  INT,
    asset_type       VARCHAR(50) DEFAULT 'stock',
    industry_sector  VARCHAR(100),
    source_url       VARCHAR(500),
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (politician_id) REFERENCES politicians(id) ON DELETE SET NULL,
    INDEX idx_ticker (ticker),
    INDEX idx_trade_date (trade_date),
    INDEX idx_politician (politician_id),
    INDEX idx_sector (industry_sector),
    INDEX idx_trade_type (trade_type)
) ENGINE=InnoDB;

-- ============================================================
-- 4b. TRADE SECTORS (junction table for multi-sector support)
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_sectors (
    trade_id  INT          NOT NULL,
    sector    VARCHAR(50)  NOT NULL,
    PRIMARY KEY (trade_id, sector),
    FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE CASCADE,
    INDEX idx_sector (sector)
) ENGINE=InnoDB;

-- ============================================================
-- 5. VOTES (roll call votes from Congress.gov)
-- ============================================================
CREATE TABLE IF NOT EXISTS votes (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    roll_call_id   VARCHAR(50)  UNIQUE NOT NULL,
    chamber        ENUM('House', 'Senate') NOT NULL,
    congress       INT NOT NULL,
    session        INT,
    roll_number    INT,
    question       TEXT,
    result         VARCHAR(100),
    vote_date      DATE,
    url            VARCHAR(500),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_vote_date (vote_date),
    INDEX idx_chamber (chamber),
    INDEX idx_congress (congress)
) ENGINE=InnoDB;

-- ============================================================
-- 6. POLITICIAN VOTES (how each member voted)
-- ============================================================
CREATE TABLE IF NOT EXISTS politician_votes (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    politician_id  INT NOT NULL,
    vote_id        INT NOT NULL,
    position       ENUM('Yes', 'No', 'Not Voting', 'Present') NOT NULL,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (politician_id) REFERENCES politicians(id) ON DELETE CASCADE,
    FOREIGN KEY (vote_id) REFERENCES votes(id) ON DELETE CASCADE,
    UNIQUE KEY uq_pol_vote (politician_id, vote_id),
    INDEX idx_politician (politician_id),
    INDEX idx_vote (vote_id),
    INDEX idx_position (position)
) ENGINE=InnoDB;

-- ============================================================
-- 7. BILLS
-- ============================================================
CREATE TABLE IF NOT EXISTS bills (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    bill_id           VARCHAR(50)  UNIQUE NOT NULL,
    congress          INT NOT NULL,
    bill_type         VARCHAR(20),
    bill_number       INT,
    title             TEXT,
    policy_area       VARCHAR(200),
    latest_action     TEXT,
    latest_action_date DATE,
    origin_chamber    ENUM('House', 'Senate'),
    sponsor_bioguide  VARCHAR(20),
    url               VARCHAR(500),
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_congress (congress),
    INDEX idx_policy_area (policy_area),
    INDEX idx_sponsor (sponsor_bioguide)
) ENGINE=InnoDB;

-- ============================================================
-- 8. STOCK PRICES (daily OHLCV from yfinance)
-- ============================================================
CREATE TABLE IF NOT EXISTS stock_prices (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    ticker     VARCHAR(10)  NOT NULL,
    price_date DATE         NOT NULL,
    open_price DECIMAL(12,4),
    high       DECIMAL(12,4),
    low        DECIMAL(12,4),
    close      DECIMAL(12,4) NOT NULL,
    volume     BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ticker_date (ticker, price_date),
    INDEX idx_ticker (ticker),
    INDEX idx_date (price_date)
) ENGINE=InnoDB;

-- ============================================================
-- 9. INSTITUTIONAL HOLDINGS (SEC 13-F)
-- ============================================================
CREATE TABLE IF NOT EXISTS institutional_holdings (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    fund_name    VARCHAR(200),
    fund_cik     VARCHAR(20),
    cusip        VARCHAR(9)   NOT NULL,
    ticker       VARCHAR(10),
    issuer_name  VARCHAR(300),
    shares       BIGINT,
    value_x1000  BIGINT,
    year         INT          NOT NULL,
    quarter      INT          NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_cusip (cusip),
    INDEX idx_ticker (ticker),
    INDEX idx_period (year, quarter),
    INDEX idx_fund (fund_cik)
) ENGINE=InnoDB;

-- ============================================================
-- 10. INSTITUTIONAL TRADES (inferred from 13-F QoQ changes)
-- ============================================================
CREATE TABLE IF NOT EXISTS institutional_trades (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    cusip           VARCHAR(9)   NOT NULL,
    ticker          VARCHAR(10),
    issuer_name     VARCHAR(300),
    shares_prior    BIGINT,
    shares_current  BIGINT,
    share_change    BIGINT,
    trade_direction ENUM('new_position', 'exit_position', 'increase', 'decrease') NOT NULL,
    from_period     VARCHAR(10),
    to_period       VARCHAR(10),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_cusip (cusip),
    INDEX idx_ticker (ticker),
    INDEX idx_direction (trade_direction),
    INDEX idx_period (to_period)
) ENGINE=InnoDB;

-- ============================================================
-- 11. FEC CANDIDATES
-- ============================================================
CREATE TABLE IF NOT EXISTS fec_candidates (
    id                     INT AUTO_INCREMENT PRIMARY KEY,
    candidate_id           VARCHAR(20)  UNIQUE NOT NULL,
    name                   VARCHAR(200),
    party                  VARCHAR(100),
    state                  VARCHAR(2),
    district               VARCHAR(10),
    office                 ENUM('House', 'Senate'),
    incumbent_challenge    VARCHAR(50),
    election_year          INT,
    principal_committee_id VARCHAR(20),
    created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_party (party),
    INDEX idx_state (state),
    INDEX idx_election_year (election_year)
) ENGINE=InnoDB;

-- ============================================================
-- 12. FEC CANDIDATE FINANCIAL TOTALS
-- ============================================================
CREATE TABLE IF NOT EXISTS fec_candidate_totals (
    id                           INT AUTO_INCREMENT PRIMARY KEY,
    candidate_id                 VARCHAR(20) NOT NULL,
    total_receipts               DECIMAL(15,2),
    total_disbursements          DECIMAL(15,2),
    cash_on_hand                 DECIMAL(15,2),
    total_individual_contributions DECIMAL(15,2),
    total_pac_contributions      DECIMAL(15,2),
    election_year                INT,
    created_at                   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES fec_candidates(candidate_id) ON DELETE CASCADE,
    INDEX idx_candidate (candidate_id),
    INDEX idx_year (election_year)
) ENGINE=InnoDB;

-- ============================================================
-- 13. CUSIP→TICKER MAP (from OpenFIGI)
-- ============================================================
CREATE TABLE IF NOT EXISTS cusip_ticker_map (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    cusip         VARCHAR(9)   UNIQUE NOT NULL,
    ticker        VARCHAR(10),
    name          VARCHAR(300),
    market_sector VARCHAR(100),
    exchange      VARCHAR(20),
    figi          VARCHAR(20),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ticker (ticker)
) ENGINE=InnoDB;

-- ============================================================
-- 14. ANOMALY SCORES (dual-model output: Cohort + Baseline)
-- ============================================================
CREATE TABLE IF NOT EXISTS anomaly_scores (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    trade_id                INT NOT NULL UNIQUE,
    politician_id           INT,
    ticker                  VARCHAR(10),
    trade_date              DATE,

    -- Cohort model (Model 1)
    cohort_raw_score        FLOAT NOT NULL,
    cohort_label            TINYINT NOT NULL,
    cohort_index            TINYINT UNSIGNED NOT NULL,

    -- Baseline model (Model 2)
    baseline_raw_score      FLOAT NOT NULL,
    baseline_label          TINYINT NOT NULL,
    baseline_index          TINYINT UNSIGNED NOT NULL,

    -- Derived
    severity_quadrant       ENUM('SEVERE','SYSTEMIC','OUTLIER','UNREMARKABLE') NOT NULL,
    audit_triggered         BOOLEAN DEFAULT FALSE,

    -- Feature snapshot
    feat_cohort_alpha       FLOAT,
    feat_pre_trade_alpha    FLOAT,
    feat_proximity_days     SMALLINT,
    feat_bill_proximity     SMALLINT,
    feat_has_proximity_data TINYINT,
    feat_committee_relevance FLOAT,
    feat_amount_zscore      FLOAT,
    feat_cluster_score      TINYINT,
    feat_disclosure_lag     SMALLINT,

    model_version           VARCHAR(50),
    scored_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE CASCADE,
    FOREIGN KEY (politician_id) REFERENCES politicians(id) ON DELETE SET NULL,

    INDEX idx_cohort (cohort_index),
    INDEX idx_baseline (baseline_index),
    INDEX idx_quadrant (severity_quadrant),
    INDEX idx_audit (audit_triggered),
    INDEX idx_politician (politician_id),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB;

-- ============================================================
-- 14b. PAC CONTRIBUTIONS (from FEC)
-- ============================================================
CREATE TABLE IF NOT EXISTS pac_contributions (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    contributor_name     VARCHAR(300),
    contributor_employer VARCHAR(300),
    committee_name       VARCHAR(300),
    candidate_id         VARCHAR(20),
    amount               DECIMAL(15,2),
    receipt_date         DATE,
    state                VARCHAR(2),
    sector_tag           VARCHAR(100),
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_candidate (candidate_id),
    INDEX idx_sector (sector_tag),
    INDEX idx_date (receipt_date)
) ENGINE=InnoDB;

-- ============================================================
-- 15. GEMINI AUDIT REPORTS (V3 — GenMedia-aware)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_reports (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_id            INT NOT NULL UNIQUE,
    generated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    headline            VARCHAR(500),
    risk_level          ENUM('low','medium','high','very_high') NOT NULL,
    severity_quadrant   ENUM('SEVERE','SYSTEMIC','OUTLIER','UNREMARKABLE'),
    narrative           TEXT NOT NULL,
    evidence_json       JSON,
    bill_excerpt        TEXT,
    disclaimer          TEXT NOT NULL,

    -- V3: GenMedia output fields (written by Gemini)
    video_prompt        TEXT,
    narration_script    TEXT,
    citation_image_prompts JSON DEFAULT NULL,

    gemini_model        VARCHAR(80),
    prompt_tokens       INT,
    output_tokens       INT,
    FOREIGN KEY (trade_id) REFERENCES trades(id),
    INDEX idx_risk (risk_level),
    INDEX idx_quadrant (severity_quadrant)
) ENGINE=InnoDB;

-- ============================================================
-- 16. MEDIA ASSETS (V3 — Veo videos + TTS audio)
-- ============================================================
CREATE TABLE IF NOT EXISTS media_assets (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_id            INT NOT NULL,
    audit_report_id     BIGINT,
    asset_type          ENUM('audio','video','thumbnail','citation_image') NOT NULL,
    storage_url         VARCHAR(500) NOT NULL,
    file_size_bytes     INT,
    duration_seconds    FLOAT,
    resolution          VARCHAR(20),
    generation_status   ENUM('pending','generating','ready','failed') NOT NULL DEFAULT 'pending',
    error_message       TEXT,
    model_used          VARCHAR(100),
    generated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE CASCADE,
    FOREIGN KEY (audit_report_id) REFERENCES audit_reports(id) ON DELETE SET NULL,
    INDEX idx_trade (trade_id),
    INDEX idx_type (asset_type),
    INDEX idx_status (generation_status)
) ENGINE=InnoDB;

-- ============================================================
-- 17. DAILY REPORTS (V3 — daily video news reports)
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_reports (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date         DATE NOT NULL UNIQUE,
    trade_ids_covered   JSON,
    narration_script    TEXT,
    veo_prompt          TEXT,
    video_url           VARCHAR(500),
    audio_url           VARCHAR(500),
    duration_seconds    FLOAT,
    generation_status   ENUM('pending','generating','ready','failed') DEFAULT 'pending',
    generated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
