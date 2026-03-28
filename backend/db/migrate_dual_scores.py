"""One-time migration: recreate anomaly_scores with dual-model columns."""
import pymysql

c = pymysql.connect(
    host="localhost", port=3307, user="root",
    password="changeme", database="house_advantage",
)
cur = c.cursor()

cur.execute("DROP TABLE IF EXISTS audit_reports")
cur.execute("DROP TABLE IF EXISTS anomaly_scores")
c.commit()
print("Dropped old tables")

cur.execute("""
CREATE TABLE anomaly_scores (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    trade_id                INT NOT NULL UNIQUE,
    politician_id           INT,
    ticker                  VARCHAR(10),
    trade_date              DATE,

    cohort_raw_score        FLOAT NOT NULL,
    cohort_label            TINYINT NOT NULL,
    cohort_index            TINYINT UNSIGNED NOT NULL,

    baseline_raw_score      FLOAT NOT NULL,
    baseline_label          TINYINT NOT NULL,
    baseline_index          TINYINT UNSIGNED NOT NULL,

    severity_quadrant       ENUM('SEVERE','SYSTEMIC','OUTLIER','UNREMARKABLE') NOT NULL,
    audit_triggered         BOOLEAN DEFAULT FALSE,

    feat_cohort_alpha       FLOAT,
    feat_proximity_days     SMALLINT,
    feat_has_proximity_data TINYINT,
    feat_committee_relevance FLOAT,
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
) ENGINE=InnoDB
""")

cur.execute("""
CREATE TABLE audit_reports (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    trade_id         INT,
    politician_id    INT,
    anomaly_score_id INT,
    summary          TEXT,
    risk_level       ENUM('low','medium','high','critical'),
    evidence_json    JSON,
    recommendation   TEXT,
    model_used       VARCHAR(100),
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE SET NULL,
    FOREIGN KEY (politician_id) REFERENCES politicians(id) ON DELETE SET NULL,
    FOREIGN KEY (anomaly_score_id) REFERENCES anomaly_scores(id) ON DELETE SET NULL,
    INDEX idx_risk (risk_level),
    INDEX idx_politician (politician_id)
) ENGINE=InnoDB
""")

c.commit()
print("Tables recreated with dual-model schema")

cur.execute("DESCRIBE anomaly_scores")
for r in cur.fetchall():
    print(r)

c.close()
