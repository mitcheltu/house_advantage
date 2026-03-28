"""Quick verification that pipeline_runner queries work after fixes."""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")

from datetime import date
from backend.gemini.pipeline_runner import (
    _fetch_severe_trade_media_jobs,
    _fetch_severe_trade_ids_for_date,
    _has_ready_video_asset,
    _fetch_citation_image_paths,
)
from backend.gemini.gcs_storage import gcs_enabled

today = date.today()

print(f"GCS enabled: {gcs_enabled()}")
print()

ids = _fetch_severe_trade_ids_for_date(today, limit=5)
print(f"SEVERE trade IDs (limit 5): {ids}")

jobs = _fetch_severe_trade_media_jobs(report_date=today, limit=3)
print(f"SEVERE media jobs (limit 3): {len(jobs)}")
for j in jobs:
    tid = j["trade_id"]
    has_vid = _has_ready_video_asset(tid)
    cit = _fetch_citation_image_paths(tid)
    print(f"  Trade {tid} ({j['ticker']}): video_prompt={len(j.get('video_prompt') or '')} chars, "
          f"narration={len(j.get('narration_script') or '')} chars, "
          f"has_video={has_vid}, citation_imgs={len(cit)}")
