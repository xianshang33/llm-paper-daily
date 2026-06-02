#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from paper_daily.defaults import (
    DEFAULT_METADATA_ARTIFACT_DIR,
    DEFAULT_RUN_STATE_DIR,
    DEFAULT_SUMMARY_ARTIFACT_DIR,
)
from paper_daily.run_state import assess_run_state


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    state = assess_run_state(
        repo_root,
        date=args.date,
        summary_artifact_dir=args.summary_artifact_dir,
        metadata_artifact_dir=args.metadata_artifact_dir,
        run_state_dir=args.run_state_dir,
    )
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0 if state.get("finalize_ready") else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect paper-daily candidate/final readiness for a date.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--date", required=True)
    parser.add_argument("--summary-artifact-dir", default=DEFAULT_SUMMARY_ARTIFACT_DIR)
    parser.add_argument("--metadata-artifact-dir", default=DEFAULT_METADATA_ARTIFACT_DIR)
    parser.add_argument("--run-state-dir", default=DEFAULT_RUN_STATE_DIR)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
