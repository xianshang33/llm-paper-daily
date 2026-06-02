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
from paper_daily.metadata import load_metadata_payload, merge_candidate_with_metadata, resolve_metadata_artifact_dir
from paper_daily.metadata import metadata_is_complete
from paper_daily.run_state import assess_run_state, load_run_state
from paper_daily.summary import build_summary_runtime_request


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
    missing_ids = set(state.get("summary", {}).get("missing", []))
    run_state = load_run_state(repo_root, args.date, args.run_state_dir)
    metadata_dir = resolve_metadata_artifact_dir(repo_root, args.metadata_artifact_dir)
    artifact_dir = resolve_summary_artifact_dir(repo_root, args.summary_artifact_dir)
    candidates = []
    blocked_metadata_ids = []
    for candidate in run_state.get("selected", []):
        if candidate.get("arxiv_id") not in missing_ids:
            continue
        try:
            metadata = load_metadata_payload(metadata_dir, candidate["arxiv_id"])
            if not metadata_is_complete(metadata):
                blocked_metadata_ids.append(candidate["arxiv_id"])
                continue
            candidate = merge_candidate_with_metadata(candidate, metadata)
        except Exception:
            blocked_metadata_ids.append(candidate["arxiv_id"])
            continue
        candidates.append(candidate)

    payload = {
        "mode": "paper-daily-missing-summary-artifacts",
        "date": args.date,
        "blocked_metadata_ids": blocked_metadata_ids,
        "missing_summary_ids": [candidate["arxiv_id"] for candidate in candidates],
        "requests": [
            build_summary_runtime_request(candidate, run_date=args.date, artifact_dir=artifact_dir)
            for candidate in candidates
        ],
    }
    if args.out:
        Path(args.out).expanduser().resolve().write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if blocked_metadata_ids:
        return 2
    return 0 if not candidates else 1


def resolve_summary_artifact_dir(repo_root: Path, summary_artifact_dir: str | Path) -> Path:
    path = Path(summary_artifact_dir)
    return path if path.is_absolute() else repo_root / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare summary requests only for papers missing from a paper-daily run state.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--date", required=True)
    parser.add_argument("--summary-artifact-dir", default=DEFAULT_SUMMARY_ARTIFACT_DIR)
    parser.add_argument("--metadata-artifact-dir", default=DEFAULT_METADATA_ARTIFACT_DIR)
    parser.add_argument("--run-state-dir", default=DEFAULT_RUN_STATE_DIR)
    parser.add_argument("--out", help="Optional JSON output path for the prepared missing-summary requests.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
