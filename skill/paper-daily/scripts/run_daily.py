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
    DEFAULT_METADATA_ARTIFACT_DIR,
    DEFAULT_MIN_SELECT,
    DEFAULT_PENDING_METADATA_PATH,
    DEFAULT_RUN_STATE_DIR,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_SUMMARY_ARTIFACT_DIR,
)
from paper_daily.discovery import (
    find_next_discovery,
    load_cached_discovery_for_date,
    paper_candidate_from_dict,
    select_ranked_candidates,
)
from paper_daily.feed import read_feed_state, write_feed_outputs, write_feed_state
from paper_daily.institutions import load_catalog
from paper_daily.local_metadata import load_local_candidate_payload
from paper_daily.metadata import load_metadata_payload, merge_candidate_with_metadata, resolve_metadata_artifact_dir
from paper_daily.metadata import metadata_is_complete
from paper_daily.patch import (
    README_END,
    README_EN_END,
    README_EN_START,
    README_START,
    UPDATES_EN_END,
    UPDATES_EN_START,
    UPDATES_END,
    UPDATES_START,
    ensure_readme_markers,
    patch_updates_block,
    patch_month_block,
    update_readme_timestamps,
)
from paper_daily.render import (
    render_cn_month_block,
    render_en_month_block,
    render_updates_block_en,
    render_updates_block_zh,
    write_summary_files,
)
from paper_daily.run_state import assess_run_state, enqueue_metadata_tasks, record_candidate_run
from paper_daily.ranker import rank_candidates
from paper_daily.summary import candidate_to_canonical


def main() -> int:
    args = parse_args()
    publish_enabled = not args.view_only
    repo_root = Path(args.repo_root).resolve()
    skill_root = Path(__file__).resolve().parents[1]
    catalog = load_catalog(skill_root / "references" / "institutions.json")
    client = ArxivClient(
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        budget_seconds=args.discovery_budget_seconds,
        api_search_budget_seconds=args.api_search_budget_seconds,
    )
    previous_state = read_feed_state(repo_root)
    analyzed_dates = set(previous_state.get("analyzed_content_dates", []))
    previous_latest_updates_date = previous_state.get("latest_updates_date")

    manual_arxiv_ids = parse_arxiv_ids(args.arxiv_id)
    if args.discovered_json:
        discovered_payload = json.loads(Path(args.discovered_json).expanduser().read_text(encoding="utf-8"))
        selected_date = discovered_payload["date"]
        attempted_dates = [selected_date]
        candidate_pool = discovered_payload.get("candidate_pool") or discovered_payload.get("ranked") or discovered_payload.get("selected", [])
        ranked_candidates = select_complete_candidates_from_pool(
            candidate_pool=candidate_pool,
            metadata_artifact_dir=resolve_metadata_artifact_dir(repo_root, args.metadata_artifact_dir),
            catalog=catalog,
        )
        selected_candidates = select_ranked_candidates(
            ranked_candidates,
            min_select=args.min_select,
            max_select=args.select,
            score_threshold=args.score_threshold,
        )
    elif manual_arxiv_ids:
        selected_date = args.date
        selected_candidates = resolve_manual_candidates(client=client, repo_root=repo_root, arxiv_ids=manual_arxiv_ids)
        candidate_pool = [candidate.to_dict() for candidate in selected_candidates]
        attempted_dates = [f"arxiv:{arxiv_id}" for arxiv_id in manual_arxiv_ids]
    else:
        selection = find_next_discovery(
            client=client,
            catalog=catalog,
            preferred_date=args.date,
            analyzed_dates=analyzed_dates,
            max_lookback_days=args.backfill_days,
            max_results_per_keyword=args.max_results_per_keyword,
        )
        selected_date = selection["selected_date"]
        discovered = selection["discovered"]
        attempted_dates = selection["attempted_dates"]

        if selection["discovery_errors"] and (not selected_date or not discovered):
            cached_selection = resolve_cached_discovery(repo_root=repo_root, attempted_dates=attempted_dates)
            if cached_selection:
                selected_date, discovered = cached_selection

        if not selected_date or not discovered:
            print(f"preferred_date={args.date}")
            print(f"mode={'view-only' if args.view_only else 'publish'}")
            print("selected=0")
            print(f"attempted_dates={','.join(attempted_dates)}")
            if selection["discovery_errors"]:
                print("discovery_errors:")
                for error in selection["discovery_errors"]:
                    print(f"- {error}")
                print("arXiv discovery failed for one or more attempted queries; not updating state.")
                return 2
            print("No new analyzable papers found in the configured fallback window.")
            if selection["skipped_analyzed_dates"]:
                print(f"skipped_already_analyzed={','.join(selection['skipped_analyzed_dates'])}")
            return 0

        candidate_pool = [candidate.to_dict() for candidate in discovered["ranked"]]
        ranked_candidates = select_complete_candidates_from_pool(
            candidate_pool=candidate_pool,
            metadata_artifact_dir=resolve_metadata_artifact_dir(repo_root, args.metadata_artifact_dir),
            catalog=catalog,
        )
        selected_candidates = select_ranked_candidates(
            ranked_candidates,
            min_select=args.min_select,
            max_select=args.select,
            score_threshold=args.score_threshold,
        )
    selected = [candidate.to_dict() for candidate in selected_candidates]
    metadata_artifact_dir = resolve_metadata_artifact_dir(repo_root, args.metadata_artifact_dir)
    record_candidate_run(
        repo_root,
        date=selected_date,
        selected=selected,
        preferred_date=args.date,
        attempted_dates=attempted_dates,
        candidate_pool=candidate_pool,
        selection_target=args.select,
        run_state_dir=args.run_state_dir,
    )
    enqueue_metadata_tasks(repo_root, date=selected_date, candidates=candidate_pool, pending_path=args.pending_metadata)
    readiness = assess_run_state(
        repo_root,
        date=selected_date,
        summary_artifact_dir=args.summary_artifact_dir,
        metadata_artifact_dir=args.metadata_artifact_dir,
        run_state_dir=args.run_state_dir,
    )
    if not readiness.get("finalize_ready"):
        print(f"preferred_date={args.date}")
        print(f"mode={'view-only' if args.view_only else 'candidate'}")
        if manual_arxiv_ids:
            print(f"manual_arxiv_ids={','.join(manual_arxiv_ids)}")
        print(f"selected_date={selected_date}")
        print(f"selected={len(selected)}")
        print(f"status={readiness.get('status')}")
        for block in readiness.get("blocking", []):
            print(f"blocking_{block['kind']}={','.join(block.get('paper_ids', []))}")
        print(f"run_state={repo_root / args.run_state_dir / f'{selected_date}.json'}")
        print(f"pending_metadata={repo_root / args.pending_metadata}")
        print("finalize=not_ready")
        return 0

    selected = [
        merge_candidate_with_metadata(candidate, load_metadata_payload(metadata_artifact_dir, candidate["arxiv_id"]))
        for candidate in selected
    ]
    canonical = [
        candidate_to_canonical(candidate, run_date=selected_date, summary_artifact_dir=args.summary_artifact_dir)
        for candidate in selected
    ]

    debug_out_dir = None
    if args.debug_out:
        debug_out_dir = Path(args.debug_out).resolve()
        debug_out_dir.mkdir(parents=True, exist_ok=True)
        (debug_out_dir / "selected-papers.json").write_text(
            json.dumps(selected, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (debug_out_dir / "canonical-papers.json").write_text(
            json.dumps([record.to_dict() for record in canonical], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if publish_enabled:
        write_summary_files(repo_root, canonical)
        ensure_readme_markers(repo_root)
        write_feed_outputs(
            repo_root,
            canonical,
            selected_date,
            public_base_url=args.public_base_url,
            source_repo=args.source_repo,
        )

        month_key = selected_date[:7]
        cn_block = render_cn_month_block(canonical, month_key)
        en_block = render_en_month_block(canonical, month_key)
        run_now = datetime.now()
        patch_month_block(repo_root / "README.md", README_START, README_END, cn_block, month_key=month_key, paper_id=canonical[0].paper_id)
        patch_month_block(repo_root / "README_en.md", README_EN_START, README_EN_END, en_block, month_key=month_key, paper_id=canonical[0].paper_id)
        should_refresh_updates = (
            not previous_latest_updates_date or selected_date >= previous_latest_updates_date
        )
        if should_refresh_updates:
            zh_updates = render_updates_block_zh(canonical, now=run_now)
            en_updates = render_updates_block_en(canonical, now=run_now)
            patch_updates_block(repo_root / "README.md", UPDATES_START, UPDATES_END, zh_updates)
            patch_updates_block(repo_root / "README_en.md", UPDATES_EN_START, UPDATES_EN_END, en_updates)
            update_readme_timestamps(repo_root / "README.md", locale="zh", now=run_now)
            update_readme_timestamps(repo_root / "README_en.md", locale="en", now=run_now)
        write_feed_state(
            repo_root,
            previous_state=previous_state,
            records=canonical,
            preferred_date=args.date,
            attempted_dates=attempted_dates,
            updated=True,
            selected_date=selected_date,
        )

    print(f"preferred_date={args.date}")
    print(f"mode={'view-only' if args.view_only else 'publish'}")
    if manual_arxiv_ids:
        print(f"manual_arxiv_ids={','.join(manual_arxiv_ids)}")
    print(f"selected_date={selected_date}")
    print(f"selected={len(canonical)}")
    print(f"attempted_dates={','.join(attempted_dates)}")
    for record in canonical:
        print(f"- {record.paper_id} {record.title}")
    if debug_out_dir:
        print(f"debug_out: {debug_out_dir}")
    if publish_enabled:
        print(f"patched: {repo_root / 'README.md'}")
        print(f"patched: {repo_root / 'README_en.md'}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the repo-local publishing pipeline. This path consumes external summary artifacts and patches repo artifacts; use discover.py for broad recall.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--date", default=default_utc_date())
    parser.add_argument("--discovered-json", help="Discovery JSON artifact to consume instead of re-running discovery or using manual IDs.")
    parser.add_argument("--arxiv-id", action="append", default=[], help="Manually publish one or more arXiv IDs. May be repeated or comma-separated. When set, --date is used as the display date.")
    parser.add_argument("--select", type=int, default=DEFAULT_DAILY_SELECT, help="Maximum number of papers to publish.")
    parser.add_argument("--min-select", type=int, default=DEFAULT_MIN_SELECT, help="Minimum number of papers to publish when filtered candidates allow it.")
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD, help="Score threshold for preferred selection before falling back to the top-ranked minimum set.")
    parser.add_argument("--max-results-per-keyword", type=int, default=DEFAULT_MAX_RESULTS_PER_KEYWORD)
    parser.add_argument("--delay-seconds", type=float, default=3.1)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--discovery-budget-seconds", type=float, default=180.0, help="Global wall-clock budget for arXiv discovery/manual metadata lookups. Use 0 to disable.")
    parser.add_argument("--api-search-budget-seconds", type=float, default=30.0, help="Budget for the first arXiv API search before preserving time for listing fallback. Use 0 to disable.")
    parser.add_argument("--backfill-days", type=int, default=7)
    parser.add_argument("--view-only", action="store_true", help="Inspect the selected papers without updating README/feed/state/summary artifacts.")
    parser.add_argument("--debug-out", help="Optional directory for debug JSON artifacts.")
    parser.add_argument("--summary-artifact-dir", default=DEFAULT_SUMMARY_ARTIFACT_DIR, help="Directory containing externally generated summary JSON artifacts keyed by arXiv ID.")
    parser.add_argument("--metadata-artifact-dir", default=DEFAULT_METADATA_ARTIFACT_DIR, help="Directory containing cached standardized arXiv metadata keyed by arXiv ID.")
    parser.add_argument("--run-state-dir", default=DEFAULT_RUN_STATE_DIR, help="Directory containing per-date paper-daily run state.")
    parser.add_argument("--pending-metadata", default=DEFAULT_PENDING_METADATA_PATH, help="Path to the pending metadata queue.")
    parser.add_argument("--public-base-url", default="", help="Optional public base URL for summary asset links.")
    parser.add_argument("--source-repo", default="xianshang33/llm-paper-daily", help="Source repository identifier for feed metadata.")
    return parser.parse_args()


def parse_arxiv_ids(values: list[str]) -> list[str]:
    arxiv_ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in value.split(","):
            arxiv_id = part.strip()
            if not arxiv_id or arxiv_id in seen:
                continue
            seen.add(arxiv_id)
            arxiv_ids.append(arxiv_id)
    return arxiv_ids


def default_utc_date() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def resolve_cached_discovery(*, repo_root: Path, attempted_dates: list[str]) -> tuple[str, dict] | None:
    for candidate_date in attempted_dates:
        if candidate_date.startswith("arxiv:"):
            continue
        discovered = load_cached_discovery_for_date(repo_root, candidate_date)
        if discovered and discovered["ranked"]:
            return candidate_date, discovered
    return None


def select_complete_candidates_from_pool(*, candidate_pool: list[dict], metadata_artifact_dir: Path, catalog) -> list:
    complete_candidates = []
    for candidate in candidate_pool:
        merged = dict(candidate)
        try:
            metadata = load_metadata_payload(metadata_artifact_dir, candidate["arxiv_id"])
            if metadata_is_complete(metadata):
                merged = merge_candidate_with_metadata(candidate, metadata)
        except Exception:
            pass
        if metadata_is_complete(merged):
            complete_candidates.append(paper_candidate_from_dict(merged))
    return rank_candidates(complete_candidates, catalog)


def resolve_manual_candidates(*, client: ArxivClient, repo_root: Path, arxiv_ids: list[str]) -> list:
    fallback_candidates = []
    missing_ids = []
    for arxiv_id in arxiv_ids:
        payload = load_local_candidate_payload(repo_root, arxiv_id)
        if payload is None:
            missing_ids.append(arxiv_id)
            continue
        fallback_candidates.append(paper_candidate_from_dict(payload))

    if not missing_ids:
        return fallback_candidates

    resolved_remote = client.get_by_arxiv_ids(missing_ids)
    resolved_by_id = {candidate.arxiv_id: candidate for candidate in resolved_remote}
    merged_candidates = []
    for arxiv_id in arxiv_ids:
        payload = load_local_candidate_payload(repo_root, arxiv_id)
        if payload is not None:
            merged_candidates.append(paper_candidate_from_dict(payload))
            continue
        candidate = resolved_by_id.get(arxiv_id)
        if candidate is None:
            raise RuntimeError(f"Missing metadata for: {arxiv_id}")
        merged_candidates.append(candidate)
    return merged_candidates


if __name__ == "__main__":
    raise SystemExit(main())
