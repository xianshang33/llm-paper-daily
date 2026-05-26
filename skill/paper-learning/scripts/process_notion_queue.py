#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import replace

from paper_learning.classifier import load_research_areas
from paper_learning.config import load_config
from paper_learning.deep_reading_providers import get_deep_reading_provider
from paper_learning.models import DeepReadingRequest, SelectedPaper
from paper_learning.notion_client import NotionClient
from paper_learning.queue_pipeline import process_selected_papers
from paper_learning.selected_papers_io import LocalSelectedPapersNotion, load_deep_reading_request, load_selected_papers


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    if args.dry_run:
        cfg = replace(
            cfg,
            notion=replace(cfg.notion, dry_run=True),
            runtime=replace(cfg.runtime, dry_run=True),
        )

    if args.selected_papers_json and not args.dry_run:
        print(json.dumps({
            "ok": False,
            "status": "failed",
            "message": "--selected-papers-json is rehearsal-only and requires --dry-run.",
        }, ensure_ascii=False, indent=2))
        return 1

    active_areas = load_research_areas(cfg.classification.default_research_areas_path)
    try:
        selected, notion, local_mode = _load_queue_selection(args, cfg)
    except _QueueInputError as exc:
        print(json.dumps(exc.payload, ensure_ascii=False, indent=2))
        return 1
    if args.limit:
        selected = selected[: args.limit]

    provider = get_deep_reading_provider(cfg.deep_reading)
    readiness_targets = _readiness_targets(selected, force=args.force)
    readiness = provider.check_ready(readiness_targets)
    missing = [item for item in readiness if not item["ok"]]
    if missing:
        payload = {
            "ok": False,
            "status": "failed",
            "message": "queue stage blocked: missing or invalid ljg-paper Org artifacts",
            "data": {
                "selected_count": len(selected),
                "validated_count": len(readiness_targets),
                "readiness": readiness,
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    result = process_selected_papers(
        notion=notion,
        deep_reader=provider.read,
        active_areas=active_areas,
        selected_papers=selected,
        force=args.force,
        artifact_dir=cfg.runtime.artifact_dir,
        date=_queue_date(selected),
    )
    payload = result.to_dict()
    if local_mode:
        payload["data"]["local_status_updates"] = notion.status_updates
        payload["data"]["local_note_creates"] = notion.note_creates
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def _load_queue_selection(args: argparse.Namespace, cfg) -> tuple[list[SelectedPaper], object, bool]:
    if args.deep_reading_request_json:
        request = load_deep_reading_request(args.deep_reading_request_json)
        _ensure_request_is_confirmed(request, request_path=args.deep_reading_request_json)
        if args.dry_run:
            return request.selected_papers, LocalSelectedPapersNotion(request.selected_papers), True

        notion = NotionClient(cfg.notion)
        return _refresh_selected_from_notion(notion, request.selected_papers), notion, False

    if args.selected_papers_json:
        selected = load_selected_papers(args.selected_papers_json)
        return selected, LocalSelectedPapersNotion(selected), True

    notion = NotionClient(cfg.notion)
    return notion.query_selected_papers(), notion, False


def _ensure_request_is_confirmed(request: DeepReadingRequest, *, request_path: str) -> None:
    if request.requires_confirmation and not request.confirmed:
        raise _QueueInputError({
            "ok": False,
            "status": "failed",
            "message": "deep-reading request requires confirmation before execution",
            "data": {
                "request_path": request_path,
                "selector_type": request.selector_type,
                "candidates": [
                    {
                        "paper_id": paper.record.paper_id,
                        "title": paper.record.title,
                    }
                    for paper in request.selected_papers
                ],
            },
        })


def _refresh_selected_from_notion(notion: NotionClient, requested: list[SelectedPaper]) -> list[SelectedPaper]:
    page_ids = [paper.notion_page_id for paper in requested]
    live_by_page_id = {
        paper.notion_page_id: paper
        for paper in notion.get_papers_by_page_ids(page_ids)
    }
    missing = [paper.notion_page_id for paper in requested if paper.notion_page_id not in live_by_page_id]
    if missing:
        raise _QueueInputError({
            "ok": False,
            "status": "failed",
            "message": "could not refresh current Notion state for all requested papers",
            "data": {
                "missing_page_ids": missing,
            },
        })

    refreshed: list[SelectedPaper] = []
    for requested_paper in requested:
        live_paper = live_by_page_id[requested_paper.notion_page_id]
        refreshed.append(SelectedPaper(
            notion_page_id=live_paper.notion_page_id,
            record=live_paper.record,
            human_instruction=requested_paper.human_instruction or live_paper.human_instruction,
            existing_research_area_ids=list(live_paper.existing_research_area_ids),
            existing_deep_note_id=live_paper.existing_deep_note_id,
        ))
    return refreshed


def _readiness_targets(selected: list[SelectedPaper], *, force: bool) -> list[SelectedPaper]:
    if force:
        return list(selected)
    return [paper for paper in selected if not paper.existing_deep_note_id]


def _queue_date(selected: list[SelectedPaper]) -> str:
    for paper in selected:
        if paper.record.run_date:
            return paper.record.run_date
    return ""


class _QueueInputError(Exception):
    def __init__(self, payload: dict):
        super().__init__(payload.get("message", "invalid queue input"))
        self.payload = payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process selected papers from Notion.")
    parser.add_argument("--config", required=True, help="Path to paper-learning config JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Force the Notion adapter into dry-run mode.")
    parser.add_argument("--limit", type=int, default=0, help="Limit selected papers processed; 0 means no limit.")
    parser.add_argument("--force", action="store_true", help="Reprocess papers that already have a deep note relation.")
    parser.add_argument("--deep-reading-request-json", help="Optional deep-reading request JSON artifact to use as the resolved paper set.")
    parser.add_argument("--selected-papers-json", help="Optional local selected-papers JSON artifact to use instead of querying Notion.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
