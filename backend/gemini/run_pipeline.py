"""CLI entrypoint for daily evidence pipeline."""

from __future__ import annotations

import argparse
import json

from backend.gemini.pipeline_runner import run_daily_evidence_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run House Advantage daily evidence pipeline")
    parser.add_argument("--date", dest="report_date", default=None, help="Report date YYYY-MM-DD")
    parser.add_argument("--contextualize-limit", type=int, default=100)
    parser.add_argument("--severe-media-limit", type=int, default=100)
    args = parser.parse_args()

    result = run_daily_evidence_pipeline(
        report_date=args.report_date,
        contextualize_limit=args.contextualize_limit,
        severe_media_limit=args.severe_media_limit,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
