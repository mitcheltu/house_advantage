"""
One-time migration: add citation_image_prompts column to audit_reports
and add 'citation_image' to media_assets.asset_type ENUM.
"""
import pymysql

DB_CFG = dict(host="localhost", port=3307, user="root",
              password="changeme", database="house_advantage")


def migrate():
    conn = pymysql.connect(**DB_CFG)
    cur = conn.cursor()

    # 1. Add citation_image_prompts JSON column to audit_reports
    try:
        cur.execute(
            "ALTER TABLE audit_reports "
            "ADD COLUMN citation_image_prompts JSON DEFAULT NULL"
        )
        print("  Added citation_image_prompts column to audit_reports")
    except pymysql.err.OperationalError as e:
        if "Duplicate column" in str(e):
            print("  citation_image_prompts already exists, skipping")
        else:
            raise

    # 2. Expand media_assets.asset_type ENUM to include 'citation_image'
    try:
        cur.execute(
            "ALTER TABLE media_assets "
            "MODIFY COLUMN asset_type "
            "ENUM('audio','video','thumbnail','citation_image') NOT NULL"
        )
        print("  Updated media_assets.asset_type ENUM to include 'citation_image'")
    except (pymysql.err.OperationalError, pymysql.err.ProgrammingError) as e:
        if "doesn't exist" in str(e):
            print("  media_assets table does not exist yet, skipping ENUM update")
        else:
            print(f"  media_assets ENUM update issue: {e}")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    migrate()
