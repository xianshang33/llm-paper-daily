#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_daily.arxiv_client import ArxivClient
from paper_daily.defaults import (
    DEFAULT_DAILY_SELECT,
    DEFAULT_MAX_RESULTS_PER_KEYWORD,
    DEFAULT_MIN_SELECT,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_SUMMARY_ARTIFACT_DIR,
)
from paper_daily.discovery import find_next_discovery, select_ranked_candidates
from paper_daily.institutions import load_catalog
from paper_daily.metadata import metadata_is_complete
from paper_daily.summary import build_summary_runtime_request


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    skill_root = Path(__file__).resolve().parents[1]
    catalog = load_catalog(skill_root / "references" / "institutions.json")
    client = ArxivClient(
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        budget_seconds=args.budget_seconds,
        api_search_budget_seconds=args.api_search_budget_seconds,
        enable_agent_reach_fallback=not args.disable_agent_reach_fallback,
        agent_reach_timeout_seconds=args.agent_reach_timeout_seconds,
    )
    selection = find_next_discovery(
        client=client,
        catalog=catalog,
        preferred_date=args.date,
        analyzed_dates=set(),
        max_lookback_days=args.backfill_days,
        max_results_per_keyword=args.max_results_per_keyword,
    )
    selected_date = selection["selected_date"]
    discovered = selection["discovered"]
    attempted_dates = selection["attempted_dates"]

    if not selected_date or not discovered:
        print(json.dumps({
            "ok": False,
            "preferred_date": args.date,
            "attempted_dates": attempted_dates,
            "discovery_errors": selection["discovery_errors"],
        }, ensure_ascii=False, indent=2))
        return 2 if selection["discovery_errors"] else 0

    complete_ranked = [candidate for candidate in discovered["ranked"] if metadata_is_complete(candidate.to_dict())]
    selected_candidates = select_ranked_candidates(
        complete_ranked,
        min_select=args.min_select,
        max_select=args.select,
        score_threshold=args.score_threshold,
    )
    if len(selected_candidates) < args.select:
        print(json.dumps({
            "ok": False,
            "preferred_date": args.date,
            "selected_date": selected_date,
            "attempted_dates": attempted_dates,
            "metadata_complete": len(complete_ranked),
            "selection_target": args.select,
            "message": "Not enough metadata-complete candidates for summary generation.",
        }, ensure_ascii=False, indent=2))
        return 2
    artifact_dir = (repo_root / args.summary_artifact_dir).resolve() if not Path(args.summary_artifact_dir).is_absolute() else Path(args.summary_artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "paper-daily-summary-artifact",
        "selected_date": selected_date,
        "attempted_dates": attempted_dates,
        "requests": [
            build_summary_runtime_request(candidate.to_dict(), run_date=selected_date, artifact_dir=artifact_dir)
            for candidate in selected_candidates
        ],
    }
    if args.out:
        Path(args.out).expanduser().resolve().write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare runtime paper-daily summary requests for agent skill execution.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--date", default=(datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"))
    parser.add_argument("--select", type=int, default=DEFAULT_DAILY_SELECT)
    parser.add_argument("--min-select", type=int, default=DEFAULT_MIN_SELECT)
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
    parser.add_argument("--max-results-per-keyword", type=int, default=DEFAULT_MAX_RESULTS_PER_KEYWORD)
    parser.add_argument("--delay-seconds", type=float, default=3.1)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--budget-seconds", type=float, default=180.0, help="Global wall-clock budget for arXiv discovery. Use 0 to disable.")
    parser.add_argument("--api-search-budget-seconds", type=float, default=30.0, help="Budget for the first arXiv API search before preserving time for listing fallback. Use 0 to disable.")
    parser.add_argument("--disable-agent-reach-fallback", action="store_true", help="Disable optional Agent Reach / Exa fallback when arXiv discovery is unavailable or suspiciously empty.")
    parser.add_argument("--agent-reach-timeout-seconds", type=float, default=30.0, help="Timeout for the optional Agent Reach / Exa fallback call.")
    parser.add_argument("--backfill-days", type=int, default=7)
    parser.add_argument("--summary-artifact-dir", default=DEFAULT_SUMMARY_ARTIFACT_DIR)
    parser.add_argument("--out", help="Optional JSON output path for the prepared requests.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
