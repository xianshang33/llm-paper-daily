#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_daily.arxiv_client import ArxivClient
from paper_daily.defaults import DEFAULT_METADATA_ARTIFACT_DIR, DEFAULT_PENDING_METADATA_PATH, DEFAULT_RUN_STATE_DIR
from paper_daily.discovery import paper_candidate_from_dict
from paper_daily.metadata import (
    load_cached_metadata_if_complete,
    normalize_metadata_payload,
    resolve_metadata_artifact_dir,
    write_metadata_payload,
)
from paper_daily.run_state import (
    assess_run_state,
    enqueue_metadata_tasks,
    load_pending_metadata,
    load_run_state,
    save_pending_metadata,
)


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    client = ArxivClient(
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        budget_seconds=args.budget_seconds,
    )
    metadata_artifact_dir = resolve_metadata_artifact_dir(repo_root, args.metadata_artifact_dir)

    if args.date:
        candidates = load_candidates(args, repo_root=repo_root)
        if candidates:
            enqueue_metadata_tasks(repo_root, date=args.date, candidates=candidates, pending_path=args.pending_metadata)
        result = run_worker(
            repo_root=repo_root,
            date=args.date,
            client=client,
            metadata_artifact_dir=metadata_artifact_dir,
            pending_path=args.pending_metadata,
            budget_seconds=args.budget_seconds,
            max_papers=args.max_papers,
            api_retry_limit=args.api_retry_limit,
            fallback=args.fallback,
            fallback_backoff_seconds=args.fallback_backoff_seconds,
            force_due=args.force_due,
            run_state_dir=args.run_state_dir,
        )
    else:
        candidates = load_candidates(args, repo_root=repo_root)
        if not candidates:
            raise RuntimeError("No candidates supplied. Pass --date, --discovered-json, or --arxiv-id.")
        result = run_direct(
            candidates=candidates,
            client=client,
            metadata_artifact_dir=metadata_artifact_dir,
            fallback=args.fallback,
            api_retry_limit=args.api_retry_limit,
        )

    print(json.dumps(
        {
            **result,
            "metadata_artifact_dir": str(metadata_artifact_dir),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def run_worker(
    *,
    repo_root: Path,
    date: str,
    client: ArxivClient,
    metadata_artifact_dir: Path,
    pending_path: str,
    budget_seconds: float,
    max_papers: int,
    api_retry_limit: int,
    fallback: str,
    fallback_backoff_seconds: int,
    force_due: bool,
    run_state_dir: str,
) -> dict:
    started = time.monotonic()
    queue = load_pending_metadata(repo_root, pending_path)
    now = datetime.now(timezone.utc)
    eligible = [
        task for task in queue["tasks"]
        if task.get("date") == date
        and task.get("status") not in {"api_complete", "html_complete", "failed_exhausted"}
        and (force_due or parse_datetime(task.get("next_retry_at")) <= now)
    ]
    # Prioritize the papers this run actually needs to finalize. The pending
    # queue holds the full discovery candidate pool (often 100+ tasks/date),
    # while only the selected pack gates finalize. Without this ordering the
    # bounded worker takes eligible[:max_papers] from the front and burns its
    # budget on unselected candidates, starving the selected pack across runs.
    selected_rank = _selected_rank(repo_root, date, run_state_dir)
    eligible.sort(key=lambda task: selected_rank.get(task.get("paper_id"), len(selected_rank)))
    # Bound the work for this slice up front so the batch fetch and the per-task
    # fallback operate on the same set.
    slice_ = eligible[:max_papers] if max_papers else eligible

    # Batch fast-path: resolve everything still uncached in ONE id_list request
    # instead of one request per paper. This is the primary arXiv 429 mitigation —
    # it keeps request volume an order of magnitude lower so we stay under the
    # rate limit in the common case. On a network/HTTP error (429, timeout) the
    # whole batch backs off together and we fall through to the per-task path,
    # which carries the retry accounting and HTML fallback.
    batched_ids = {
        task["paper_id"]
        for task in slice_
        if load_cached_metadata_if_complete(metadata_artifact_dir, task["paper_id"]) is None
    }
    batch_found: dict = {}
    if batched_ids:
        try:
            batch_found = client.fetch_metadata_batch(sorted(batched_ids))
        except Exception:
            batch_found = {}

    processed = []
    for task in slice_:
        if budget_seconds and time.monotonic() - started >= budget_seconds:
            break
        candidate = batch_found.get(task["paper_id"])
        if candidate is not None:
            processed.append(_record_api_success(task, candidate, metadata_artifact_dir))
            continue
        processed.append(process_task(
            task,
            client=client,
            metadata_artifact_dir=metadata_artifact_dir,
            api_retry_limit=api_retry_limit,
            fallback=fallback,
            fallback_backoff_seconds=fallback_backoff_seconds,
        ))

    processed_by_key = {(item["date"], item["paper_id"]): item for item in processed}
    for task in queue["tasks"]:
        key = (task.get("date"), task.get("paper_id"))
        if key in processed_by_key:
            task.update(processed_by_key[key])
    save_pending_metadata(repo_root, queue, pending_path)
    state = assess_run_state(
        repo_root,
        date=date,
        metadata_artifact_dir=metadata_artifact_dir,
        run_state_dir=run_state_dir,
    )
    return {
        "date": date,
        "processed": processed,
        "processed_count": len(processed),
        "remaining_eligible": max(0, len(eligible) - len(processed)),
        "run_status": state.get("status"),
        "finalize_ready": state.get("finalize_ready"),
    }


def _selected_rank(repo_root: Path, date: str, run_state_dir: str) -> dict:
    """Map each selected paper_id to its selection order so the bounded worker
    services the finalize-gating pack before unselected candidates."""
    try:
        state = load_run_state(repo_root, date, run_state_dir)
    except Exception:
        return {}
    return {paper_id: idx for idx, paper_id in enumerate(state.get("selected_ids") or [])}


def _record_api_success(task: dict, candidate, metadata_artifact_dir: Path) -> dict:
    """Persist an arXiv-API metadata payload and build the completed task record.
    Shared by the batch fast-path and the per-task fallback so both write the
    artifact identically."""
    payload = normalize_metadata_payload(candidate.to_dict(), source="arxiv-api", status="complete")
    write_metadata_payload(metadata_artifact_dir, payload)
    return {
        **task,
        "status": "api_complete",
        "retry_count": task.get("retry_count", 0),
        "last_error": None,
        "metadata_source": "arxiv-api",
    }


def process_task(
    task: dict,
    *,
    client: ArxivClient,
    metadata_artifact_dir: Path,
    api_retry_limit: int,
    fallback: str,
    fallback_backoff_seconds: int,
) -> dict:
    paper_id = task["paper_id"]
    cached = load_cached_metadata_if_complete(metadata_artifact_dir, paper_id)
    if cached is not None:
        status = "api_complete" if cached.get("metadata_source") == "arxiv-api" else "html_complete"
        return {**task, "status": status, "last_error": None, "metadata_source": cached.get("metadata_source")}

    try:
        remote_candidates = client.get_by_arxiv_ids([paper_id])
        if not remote_candidates:
            raise RuntimeError("arXiv API returned no entry")
        return _record_api_success(task, remote_candidates[0], metadata_artifact_dir)
    except Exception as exc:
        retry_count = int(task.get("retry_count", 0)) + 1
        last_error = str(exc)

    if fallback != "none" and retry_count >= api_retry_limit:
        try:
            hydrated = client.hydrate_candidate_from_abs(paper_candidate_from_dict(task["candidate"]))
            payload = normalize_metadata_payload(
                hydrated.to_dict(),
                source=hydrated.metadata_source or "abs-html",
                status=hydrated.metadata_status or "complete",
            )
            write_metadata_payload(metadata_artifact_dir, payload)
            return {
                **task,
                "status": "html_complete",
                "retry_count": retry_count,
                "last_error": last_error,
                "metadata_source": payload.get("metadata_source"),
            }
        except Exception as fallback_exc:
            return {
                **task,
                "status": "failed_exhausted",
                "retry_count": retry_count,
                "last_error": f"api: {last_error}; fallback: {fallback_exc}",
                "next_retry_at": (datetime.now(timezone.utc) + timedelta(seconds=fallback_backoff_seconds)).isoformat(),
            }

    return {
        **task,
        "status": "api_retrying",
        "retry_count": retry_count,
        "last_error": last_error,
        "next_retry_at": next_retry_at(retry_count),
    }


def run_direct(
    *,
    candidates: list[dict],
    client: ArxivClient,
    metadata_artifact_dir: Path,
    fallback: str,
    api_retry_limit: int,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    tasks = [
        {
            "date": "",
            "paper_id": candidate["arxiv_id"],
            "candidate": candidate,
            "status": "api_pending",
            "retry_count": max(0, api_retry_limit - 1),
            "next_retry_at": now,
        }
        for candidate in candidates
    ]

    batched_ids = {
        task["paper_id"]
        for task in tasks
        if load_cached_metadata_if_complete(metadata_artifact_dir, task["paper_id"]) is None
    }
    batch_found: dict = {}
    if batched_ids:
        try:
            batch_found = client.fetch_metadata_batch(sorted(batched_ids))
        except Exception:
            batch_found = {}

    processed = []
    for task in tasks:
        candidate = batch_found.get(task["paper_id"])
        if candidate is not None:
            processed.append(_record_api_success(task, candidate, metadata_artifact_dir))
            continue
        processed.append(process_task(
            task,
            client=client,
            metadata_artifact_dir=metadata_artifact_dir,
            api_retry_limit=api_retry_limit,
            fallback=fallback,
            fallback_backoff_seconds=3600,
        ))
    return {"processed": processed, "processed_count": len(processed)}


def load_candidates(args: argparse.Namespace, *, repo_root: Path) -> list[dict]:
    if args.discovered_json:
        payload = json.loads(Path(args.discovered_json).read_text(encoding="utf-8"))
        ranked = payload.get("selected") or payload.get("ranked") or []
        return ranked[: args.limit] if args.limit else ranked

    if args.date:
        state = load_run_state(repo_root, args.date, args.run_state_dir)
        candidates = state.get("selected") or []
        return candidates[: args.limit] if args.limit else candidates

    candidates = []
    for value in args.arxiv_id:
        for paper_id in value.split(","):
            paper_id = paper_id.strip()
            if not paper_id:
                continue
            candidates.append({
                "arxiv_id": paper_id,
                "version_id": paper_id,
                # Empty placeholder: the real title is filled by the arXiv API or
                # the abs-page parse. Never seed it with the id, which would
                # otherwise survive into the metadata cache as a fake title.
                "title": "",
                "abstract": "",
                "authors": [],
                "categories": [],
                "primary_category": None,
                "published": "",
                "updated": "",
                "abs_url": f"https://arxiv.org/abs/{paper_id}",
                "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
                "priority_keyword": "Agent",
                "keyword_rank": 0,
                "query_total": 0,
            })
    return candidates


def parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def next_retry_at(retry_count: int) -> str:
    backoff = [120, 300, 900, 1800]
    seconds = backoff[min(max(retry_count - 1, 0), len(backoff) - 1)]
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded paper-daily metadata enrichment. API is tried first; fallback is delayed until the retry threshold.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--date", help="Run bounded worker for one paper-daily run date.")
    parser.add_argument("--discovered-json", help="Discovery JSON artifact containing selected/ranked candidates.")
    parser.add_argument("--arxiv-id", action="append", default=[], help="Explicit arXiv IDs to enrich. May be repeated or comma-separated.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit when consuming discovered-json.")
    parser.add_argument("--metadata-artifact-dir", default=DEFAULT_METADATA_ARTIFACT_DIR)
    parser.add_argument("--pending-metadata", default=DEFAULT_PENDING_METADATA_PATH)
    parser.add_argument("--run-state-dir", default=DEFAULT_RUN_STATE_DIR)
    parser.add_argument("--budget-seconds", type=float, default=60.0)
    parser.add_argument("--max-papers", type=int, default=5)
    parser.add_argument("--api-retry-limit", type=int, default=3)
    parser.add_argument("--fallback", choices=["none", "html"], default="html")
    parser.add_argument("--fallback-backoff-seconds", type=int, default=3600)
    parser.add_argument("--force-due", action="store_true", help="Ignore next_retry_at when the skill context decides this worker slice should make progress now.")
    parser.add_argument("--delay-seconds", type=float, default=3.1)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
