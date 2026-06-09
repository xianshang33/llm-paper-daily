#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_daily.defaults import (
    DEFAULT_DAILY_SELECT,
    DEFAULT_MAX_RESULTS_PER_KEYWORD,
    DEFAULT_METADATA_ARTIFACT_DIR,
    DEFAULT_MIN_SELECT,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_SUMMARY_ARTIFACT_DIR,
)
from paper_daily.discovery import find_next_discovery, select_ranked_candidates
from paper_daily.feed import read_feed_state, write_feed_outputs, write_feed_state
from paper_daily.institutions import load_catalog
from paper_daily.metadata import load_metadata_payload, merge_candidate_with_metadata, metadata_is_complete, resolve_metadata_artifact_dir
from paper_daily.models import PaperCandidate
from paper_daily.render import write_summary_files
from paper_daily.summary import candidate_to_canonical


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    previous_state = read_feed_state(repo_root)
    if args.discovered_json:
        discovered_payload = json.loads(Path(args.discovered_json).read_text(encoding="utf-8"))
        selected_date = discovered_payload["date"]
        attempted_dates = [selected_date]
        discovered = {"ranked": [PaperCandidate(**item) for item in discovered_payload.get("ranked", [])]}
    else:
        skill_root = Path(__file__).resolve().parents[1]
        catalog = load_catalog(skill_root / "references" / "institutions.json")
        from paper_daily.arxiv_client import ArxivClient
        client = ArxivClient(
            delay_seconds=args.delay_seconds,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
            budget_seconds=args.discovery_budget_seconds,
            api_search_budget_seconds=args.api_search_budget_seconds,
        )
        selection = find_next_discovery(
            client=client,
            catalog=catalog,
            preferred_date=args.date,
            analyzed_dates=set(previous_state.get("analyzed_content_dates", [])),
            max_lookback_days=args.backfill_days,
            max_results_per_keyword=args.max_results_per_keyword,
        )
        selected_date = selection["selected_date"]
        attempted_dates = selection["attempted_dates"]
        discovered = selection["discovered"]

        if not selected_date or not discovered:
            print(f"preferred_date={args.date}")
            print("selected=0")
            print(f"attempted_dates={','.join(attempted_dates)}")
            if selection["discovery_errors"]:
                print("discovery_errors:")
                for error in selection["discovery_errors"]:
                    print(f"- {error}")
                print("arXiv discovery failed for one or more attempted queries; not updating state.")
                return 2
            print("No new analyzable papers found in the configured fallback window; not updating state.")
            if selection["skipped_analyzed_dates"]:
                print(f"skipped_already_analyzed={','.join(selection['skipped_analyzed_dates'])}")
            return 0

    if not selected_date or not discovered:
        print(f"preferred_date={args.date}")
        print("selected=0")
        print(f"attempted_dates={','.join(attempted_dates)}")
        return 0

    selected_candidates = select_ranked_candidates(
        discovered["ranked"],
        min_select=args.min_select,
        max_select=args.select,
        score_threshold=args.score_threshold,
    )
    selected = [candidate.to_dict() for candidate in selected_candidates]
    metadata_artifact_dir = resolve_metadata_artifact_dir(repo_root, args.metadata_artifact_dir)
    selected = [merge_candidate_with_metadata(candidate, require_cached_metadata(metadata_artifact_dir, candidate["arxiv_id"])) for candidate in selected]
    canonical = [
        candidate_to_canonical(candidate, run_date=selected_date, summary_artifact_dir=args.summary_artifact_dir)
        for candidate in selected
    ]
    write_summary_files(repo_root, canonical)
    canonical_path, feed_path, state_path = write_feed_outputs(
        repo_root,
        canonical,
        selected_date,
        public_base_url=args.public_base_url,
        source_repo=args.source_repo,
    )
    state_path = write_feed_state(
        repo_root,
        previous_state=previous_state,
        records=canonical,
        preferred_date=args.date,
        attempted_dates=attempted_dates,
        updated=True,
        selected_date=selected_date,
    )
    print(f"preferred_date={args.date}")
    print(f"selected_date={selected_date}")
    print(f"selected={len(canonical)}")
    print(f"canonical={canonical_path}")
    print(f"feed={feed_path}")
    print(f"state={state_path}")
    return 0


def require_cached_metadata(metadata_artifact_dir: Path, paper_id: str) -> dict:
    payload = load_metadata_payload(metadata_artifact_dir, paper_id)
    if not metadata_is_complete(payload):
        raise RuntimeError(
            f"Metadata cache is incomplete for {paper_id}. "
            "Run enrich_metadata.py with a bounded budget before generating feed outputs."
        )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate canonical and feed outputs for paper-daily from runtime-generated summary artifacts.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--date", default=(datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"))
    parser.add_argument("--select", type=int, default=DEFAULT_DAILY_SELECT, help="Maximum number of papers to publish.")
    parser.add_argument("--min-select", type=int, default=DEFAULT_MIN_SELECT, help="Minimum number of papers to publish when filtered candidates allow it.")
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD, help="Score threshold for preferred selection before falling back to the top-ranked minimum set.")
    parser.add_argument("--max-results-per-keyword", type=int, default=DEFAULT_MAX_RESULTS_PER_KEYWORD)
    parser.add_argument("--delay-seconds", type=float, default=3.1)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--discovery-budget-seconds", type=float, default=180.0, help="Global wall-clock budget for arXiv discovery. Use 0 to disable.")
    parser.add_argument("--api-search-budget-seconds", type=float, default=30.0, help="Budget for the first arXiv API search before preserving time for listing fallback. Use 0 to disable.")
    parser.add_argument("--backfill-days", type=int, default=7)
    parser.add_argument("--discovered-json", help="Optional discovery JSON artifact to consume instead of re-running discovery.")
    parser.add_argument("--summary-artifact-dir", default=DEFAULT_SUMMARY_ARTIFACT_DIR, help="Directory containing runtime-generated summary JSON artifacts keyed by arXiv ID.")
    parser.add_argument("--metadata-artifact-dir", default=DEFAULT_METADATA_ARTIFACT_DIR, help="Directory containing cached standardized arXiv metadata keyed by arXiv ID.")
    parser.add_argument("--public-base-url", default="", help="Optional public base URL for summary asset links.")
    parser.add_argument("--source-repo", default="xianshang33/llm-paper-daily", help="Source repository identifier for feed metadata.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
