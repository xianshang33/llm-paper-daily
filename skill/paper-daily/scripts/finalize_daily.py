#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from paper_daily.defaults import (
    DEFAULT_METADATA_ARTIFACT_DIR,
    DEFAULT_RUN_STATE_DIR,
    DEFAULT_SUMMARY_ARTIFACT_DIR,
)
from paper_daily.feed import read_feed_state, write_feed_outputs, write_feed_state
from paper_daily.metadata import load_metadata_payload, merge_candidate_with_metadata, resolve_metadata_artifact_dir
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
    patch_month_block,
    patch_updates_block,
    update_readme_timestamps,
)
from paper_daily.render import (
    render_cn_month_block,
    render_en_month_block,
    render_updates_block_en,
    render_updates_block_zh,
    write_summary_files,
)
from paper_daily.run_state import assess_run_state, load_run_state, save_run_state
from paper_daily.summary import candidate_to_canonical


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    readiness = assess_run_state(
        repo_root,
        date=args.date,
        summary_artifact_dir=args.summary_artifact_dir,
        metadata_artifact_dir=args.metadata_artifact_dir,
        run_state_dir=args.run_state_dir,
    )
    if not readiness.get("finalize_ready"):
        print(f"date={args.date}")
        print(f"status={readiness.get('status')}")
        for block in readiness.get("blocking", []):
            print(f"blocking_{block['kind']}={','.join(block.get('paper_ids', []))}")
        return 2

    state = load_run_state(repo_root, args.date, args.run_state_dir)
    metadata_dir = resolve_metadata_artifact_dir(repo_root, args.metadata_artifact_dir)
    selected = [
        merge_candidate_with_metadata(candidate, load_metadata_payload(metadata_dir, candidate["arxiv_id"]))
        for candidate in state["selected"]
    ]
    canonical = [
        candidate_to_canonical(candidate, run_date=args.date, summary_artifact_dir=args.summary_artifact_dir)
        for candidate in selected
    ]

    previous_state = read_feed_state(repo_root)
    write_summary_files(repo_root, canonical)
    ensure_readme_markers(repo_root)
    canonical_path, feed_path, _ = write_feed_outputs(
        repo_root,
        canonical,
        args.date,
        public_base_url=args.public_base_url,
        source_repo=args.source_repo,
    )

    month_key = args.date[:7]
    cn_block = render_cn_month_block(canonical, month_key)
    en_block = render_en_month_block(canonical, month_key)
    run_now = datetime.now()
    patch_month_block(repo_root / "README.md", README_START, README_END, cn_block, month_key=month_key, paper_id=canonical[0].paper_id)
    patch_month_block(repo_root / "README_en.md", README_EN_START, README_EN_END, en_block, month_key=month_key, paper_id=canonical[0].paper_id)
    should_refresh_updates = (
        not previous_state.get("latest_updates_date") or args.date >= previous_state.get("latest_updates_date")
    )
    if should_refresh_updates:
        patch_updates_block(repo_root / "README.md", UPDATES_START, UPDATES_END, render_updates_block_zh(canonical, now=run_now))
        patch_updates_block(repo_root / "README_en.md", UPDATES_EN_START, UPDATES_EN_END, render_updates_block_en(canonical, now=run_now))
        update_readme_timestamps(repo_root / "README.md", locale="zh", now=run_now)
        update_readme_timestamps(repo_root / "README_en.md", locale="en", now=run_now)

    state_path = write_feed_state(
        repo_root,
        previous_state=previous_state,
        records=canonical,
        preferred_date=state.get("preferred_date", args.date),
        attempted_dates=state.get("attempted_dates", [args.date]),
        updated=True,
        selected_date=args.date,
    )
    state["status"] = "final_published"
    state["finalized_at"] = datetime.now().isoformat()
    save_run_state(repo_root, state, args.run_state_dir)

    print(f"date={args.date}")
    print("status=final_published")
    print(f"selected={len(canonical)}")
    print(f"canonical={canonical_path}")
    print(f"feed={feed_path}")
    print(f"state={state_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote a ready paper-daily candidate run into official README/feed/state artifacts.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--date", required=True)
    parser.add_argument("--summary-artifact-dir", default=DEFAULT_SUMMARY_ARTIFACT_DIR)
    parser.add_argument("--metadata-artifact-dir", default=DEFAULT_METADATA_ARTIFACT_DIR)
    parser.add_argument("--run-state-dir", default=DEFAULT_RUN_STATE_DIR)
    parser.add_argument("--public-base-url", default="")
    parser.add_argument("--source-repo", default="xianshang33/llm-paper-daily")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
