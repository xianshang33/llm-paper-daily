#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAPER_DAILY_SCRIPTS = ROOT / "skill" / "paper-daily" / "scripts"
PAPER_LEARNING_SCRIPTS = ROOT / "skill" / "paper-learning" / "scripts"
for value in (str(PAPER_DAILY_SCRIPTS), str(PAPER_LEARNING_SCRIPTS), str(ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from paper_daily.defaults import DEFAULT_SUMMARY_ARTIFACT_DIR
from paper_daily.summary import validate_summary_artifacts
from paper_learning.config import load_config
from paper_learning.deep_reading_providers import get_deep_reading_provider
from paper_learning.paper_daily_adapter import load_discovered_records
from paper_learning.selected_papers_io import load_deep_reading_request, load_selected_papers


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    run_dir = cfg.runtime.artifact_dir / args.date
    discovered_path = run_dir / "discovered-papers.json"
    canonical_path = cfg.paper_daily.repo_root / "data" / "canonical-papers.json"

    if args.stage == "daily":
        records = load_discovered_records(discovered_path, run_date=args.date)
        if args.limit:
            records = records[: args.limit]
        results = validate_summary_artifacts(args.summary_artifact_dir, [record.paper_id.split(":", 1)[1] for record in records])
    else:
        if args.deep_reading_request_json:
            selected = load_deep_reading_request(args.deep_reading_request_json).selected_papers
        else:
            selected_path = Path(args.selected_papers_json) if args.selected_papers_json else run_dir / "selected-papers.json"
            selected = load_selected_papers(selected_path)
        if args.limit:
            selected = selected[: args.limit]
        provider = get_deep_reading_provider(cfg.deep_reading)
        results = provider.check_ready(selected)

    ok = all(item["ok"] for item in results)
    print(json.dumps({
        "ok": ok,
        "stage": args.stage,
        "date": args.date,
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether required summary or org artifacts are ready for the paper-learning pipeline.")
    parser.add_argument("--config", required=True, help="Path to paper-learning config JSON.")
    parser.add_argument("--date", required=True, help="UTC run date in YYYY-MM-DD format.")
    parser.add_argument("--stage", choices=["daily", "queue"], required=True, help="Which pipeline stage to validate.")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on the number of records checked.")
    parser.add_argument("--deep-reading-request-json", help="Optional deep-reading request JSON for queue-stage validation.")
    parser.add_argument("--selected-papers-json", help="Optional selected-papers JSON for queue-stage validation.")
    parser.add_argument("--summary-artifact-dir", default=DEFAULT_SUMMARY_ARTIFACT_DIR, help="Directory containing summary artifacts for daily-stage validation.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
