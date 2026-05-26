from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .manifest import record_stage
from .models import DailyPaperRecord, OperationResult
from .report import build_report


def run_daily_pipeline(
    *,
    date: str,
    records: list[DailyPaperRecord],
    notion,
    feishu,
    artifact_dir: Path,
) -> OperationResult:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    inbox_links: dict[str, str] = {}
    paper_results = []
    ok = True

    for record in records:
        result = notion.upsert_paper(record)
        paper_results.append(result.to_dict())
        ok = ok and result.ok
        url = result.data.get("url")
        if url:
            inbox_links[record.paper_id] = url

    report = build_report(date, records)
    notion_report = notion.create_daily_report(report, inbox_links)
    feishu_report = feishu.deliver_report(report, inbox_links)
    ok = ok and notion_report.ok and feishu_report.ok

    artifact = {
        "date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_count": len(records),
        "paper_results": paper_results,
        "notion_report": notion_report.to_dict(),
        "feishu_report": feishu_report.to_dict(),
    }
    artifact_path = artifact_dir / f"{date}.json"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record_stage(
        artifact_dir=artifact_dir,
        date=date,
        stage="daily",
        status="completed" if ok else "failed",
        data={
            "paper_count": len(records),
            "artifact_path": str(artifact_path),
            "notion_report_status": notion_report.status,
            "feishu_report_status": feishu_report.status,
        },
        error="" if ok else "daily pipeline completed with failures",
    )
    return OperationResult(
        ok=ok,
        status="completed" if ok else "failed",
        message="daily pipeline completed" if ok else "daily pipeline completed with failures",
        data={"artifact_path": str(artifact_path)},
    )
