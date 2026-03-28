"""One-time migration: add V2 feature columns to anomaly_scores."""
import pymysql

DB_CFG = dict(host="localhost", port=3307, user="root",
              password="changeme", database="house_advantage")

def migrate():
    conn = pymysql.connect(**DB_CFG)
    cur = conn.cursor()

    columns_to_add = [
        ("feat_pre_trade_alpha",  "FLOAT",    "feat_cohort_alpha"),
        ("feat_bill_proximity",   "SMALLINT", "feat_proximity_days"),
        ("feat_amount_zscore",    "FLOAT",    "feat_committee_relevance"),
        ("feat_cluster_score",    "TINYINT",  "feat_amount_zscore"),
    ]

    for col_name, col_type, after_col in columns_to_add:
        try:
            cur.execute(f"ALTER TABLE anomaly_scores ADD COLUMN {col_name} {col_type} AFTER {after_col}")
            print(f"  Added {col_name}")
        except pymysql.err.OperationalError as e:
            if "Duplicate column" in str(e):
                print(f"  {col_name} already exists, skipping")
            else:
                raise

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
