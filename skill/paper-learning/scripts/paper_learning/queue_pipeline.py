from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .classifier import classify_note
from .manifest import record_stage
from .models import DeepNote, OperationResult, ResearchArea, SelectedPaper


DeepReader = Callable[[SelectedPaper], DeepNote]


def process_selected_papers(
    *,
    notion,
    deep_reader: DeepReader,
    active_areas: list[ResearchArea],
    selected_papers: list[SelectedPaper] | None = None,
    limit: int = 0,
    force: bool = False,
    artifact_dir: Path | None = None,
    date: str = "",
) -> OperationResult:
    selected = list(selected_papers) if selected_papers is not None else notion.query_selected_papers()
    if limit:
        selected = selected[:limit]

    processed: list[dict] = []
    ok = True
    for paper in selected:
        if paper.existing_deep_note_id and not force:
            processed.append({"paper_id": paper.record.paper_id, "status": "skipped_existing_deep_note"})
            continue

        notion.update_paper_status(
            paper.notion_page_id,
            {
                "Status": {"status": {"name": "Deep Reading"}},
                "Error": {"rich_text": []},
            },
        )
        try:
            note = deep_reader(paper)
            classification = classify_note(note, active_areas)
            note_area_ids = paper.existing_research_area_ids or classification.area_ids
            note_result = notion.create_deep_note(paper, note, note_area_ids)
            final_properties = {
                "Status": {"status": {"name": "Deep Read Done"}},
                "Archive Confidence": {"select": {"name": classification.confidence}},
                "Archive Review Status": {"select": {"name": classification.review_status}},
                "Proposed Area": _rich_text_or_empty(classification.proposed_area),
                "Error": {"rich_text": []},
            }
            if classification.area_ids and not paper.existing_research_area_ids:
                final_properties["Research Areas"] = {"relation": [{"id": area_id} for area_id in classification.area_ids]}
            if note_result.data.get("id"):
                final_properties["Deep Note"] = {"relation": [{"id": note_result.data["id"]}]}
            notion.update_paper_status(paper.notion_page_id, final_properties)
            processed.append({"paper_id": paper.record.paper_id, "status": "processed"})
        except Exception as exc:
            ok = False
            notion.update_paper_status(
                paper.notion_page_id,
                {
                    "Status": {"status": {"name": "Failed"}},
                    "Error": {"rich_text": [{"text": {"content": str(exc)[:2000]}}]},
                },
            )
            processed.append({"paper_id": paper.record.paper_id, "status": "failed", "error": str(exc)})

    if artifact_dir is not None and date:
        record_stage(
            artifact_dir=artifact_dir,
            date=date,
            stage="queue",
            status="completed" if ok else "failed",
            data={"processed": processed},
            error="" if ok else "queue processing completed with failures",
        )

    return OperationResult(
        ok=ok,
        status="completed" if ok else "failed",
        message="queue processing completed" if ok else "queue processing completed with failures",
        data={"processed": processed},
    )


def _rich_text_or_empty(value: str) -> dict:
    if not value:
        return {"rich_text": []}
    return {"rich_text": [{"text": {"content": value[:2000]}}]}
