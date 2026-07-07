#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_daily.arxiv_client import ArxivClient
from paper_daily.defaults import DEFAULT_DAILY_SELECT, DEFAULT_MAX_RESULTS_PER_KEYWORD
from paper_daily.discovery import discover_ranked
from paper_daily.filters import DEFAULT_CATEGORIES, DEFAULT_KEYWORDS
from paper_daily.institutions import load_catalog


def main() -> int:
    args = parse_args()
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
    discovered = discover_ranked(
        client=client,
        catalog=catalog,
        date=args.date,
        keywords=args.keywords,
        categories=args.categories,
        max_results_per_keyword=args.max_results_per_keyword,
    )
    ranked = discovered["ranked"]
    complete_ranked = [candidate for candidate in ranked if candidate_is_summary_ready(candidate.to_dict())]
    selected = complete_ranked[: args.select]

    payload = {
        "date": args.date,
        "keywords": args.keywords,
        "categories": args.categories,
        "query_totals": discovered["query_totals"],
        "counts": discovered["counts"] | {
            "candidate_pool": len(ranked),
            "metadata_complete": len(complete_ranked),
            "selected": len(selected),
            "selection_target": args.select,
        },
        "selected": [candidate.to_dict() for candidate in selected],
        "candidate_pool": [candidate.to_dict() for candidate in ranked],
        "ranked": [candidate.to_dict() for candidate in ranked],
    }

    output_path = resolve_output_path(args, skill_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_report(payload)
    print(f"\nout: {output_path}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recall daily Agent/LLM papers from arXiv with broad coverage.")
    parser.add_argument("--date", default=default_utc_date(), help="UTC arXiv submitted date, YYYY-MM-DD.")
    parser.add_argument("--keywords", nargs="+", default=DEFAULT_KEYWORDS, help="Priority keyword order.")
    parser.add_argument("--categories", nargs="+", default=DEFAULT_CATEGORIES, help="arXiv categories.")
    parser.add_argument("--max-results-per-keyword", type=int, default=DEFAULT_MAX_RESULTS_PER_KEYWORD)
    parser.add_argument("--select", type=int, default=DEFAULT_DAILY_SELECT, help="Number of ranked papers to print or emit.")
    parser.add_argument("--delay-seconds", type=float, default=3.1)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--budget-seconds", type=float, default=180.0, help="Global wall-clock budget for arXiv discovery. Use 0 to disable.")
    parser.add_argument("--api-search-budget-seconds", type=float, default=30.0, help="Budget for the first arXiv API search before preserving time for listing fallback. Use 0 to disable.")
    parser.add_argument("--disable-agent-reach-fallback", action="store_true", help="Disable optional Agent Reach / Exa fallback when arXiv discovery is unavailable or suspiciously empty.")
    parser.add_argument("--agent-reach-timeout-seconds", type=float, default=30.0, help="Timeout for the optional Agent Reach / Exa fallback call.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--out", help="Write JSON output to a specific file. Defaults to skill/paper-daily/output/discovered-YYYY-MM-DD.json.")
    return parser.parse_args()


def default_utc_date() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def print_report(payload: dict) -> None:
    print(f"date: {payload['date']}")
    print(f"keywords: {', '.join(payload['keywords'])}")
    print(f"categories: {', '.join(payload['categories'])}")
    print(f"query_totals: {payload['query_totals']}")
    print(f"counts: {payload['counts']}")
    print("")
    for index, candidate in enumerate(payload["selected"], start=1):
        matches = candidate["institution_matches"] + candidate["lab_matches"]
        match_text = ", ".join(matches) if matches else "UNKNOWN_FROM_ARXIV"
        print(f"{index}. score={candidate['score']} {candidate['arxiv_id']} [{candidate['priority_keyword']}] {candidate['title']}")
        print(f"   categories: {', '.join(candidate['categories'])}")
        print(f"   institutions: {match_text}")
        print(f"   reasons: {', '.join(candidate['reasons'])}")
        print(f"   abs: {candidate['abs_url']}")
        if candidate["pdf_url"]:
            print(f"   pdf: {candidate['pdf_url']}")


def resolve_output_path(args: argparse.Namespace, skill_root: Path) -> Path:
    if args.out:
        return Path(args.out).expanduser().resolve()
    return (skill_root / "output" / f"discovered-{args.date}.json").resolve()


def candidate_is_summary_ready(candidate: dict) -> bool:
    required = ["title", "abstract", "authors", "published", "categories", "abs_url", "pdf_url"]
    return all(candidate.get(key) not in (None, "", []) for key in required)


if __name__ == "__main__":
    sys.exit(main())
