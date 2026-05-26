from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def manifest_path(artifact_dir: Path, date: str) -> Path:
    return artifact_dir / date / "manifest.json"


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"date": path.parent.name, "stages": {}, "warnings": [], "latest_error": "", "next_action": ""}
    return json.loads(path.read_text(encoding="utf-8"))


def record_stage(
    *,
    artifact_dir: Path,
    date: str,
    stage: str,
    status: str,
    data: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    error: str = "",
) -> Path:
    path = manifest_path(artifact_dir, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_manifest(path)
    payload["date"] = date
    payload.setdefault("stages", {})
    payload.setdefault("warnings", [])
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["stages"][stage] = {
        "status": status,
        "updated_at": payload["updated_at"],
        "data": data or {},
        "error": error,
    }
    for warning in warnings or []:
        if warning not in payload["warnings"]:
            payload["warnings"].append(warning)
    if error:
        payload["latest_error"] = error
    else:
        payload.setdefault("latest_error", "")
    payload["next_action"] = _next_action(stage, status)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _next_action(stage: str, status: str) -> str:
    if status == "failed" and stage == "queue":
        return "run deep-check, prepare missing provider artifacts, then rerun deep-run"
    if status == "failed" and stage == "daily":
        return "run daily-check, resolve the reported missing dependency, then rerun daily-run"
    if stage == "daily" and status == "completed":
        return "review Notion Paper Inbox and select papers for deep reading"
    if stage == "queue" and status == "completed":
        return "review generated Deep Notes and archive review fields in Notion"
    return "run status for the date and inspect stage details"
