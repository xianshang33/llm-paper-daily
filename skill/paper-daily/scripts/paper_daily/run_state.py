from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .defaults import (
    DEFAULT_METADATA_ARTIFACT_DIR,
    DEFAULT_PENDING_METADATA_PATH,
    DEFAULT_RUN_STATE_DIR,
    DEFAULT_SUMMARY_ARTIFACT_DIR,
)
from .metadata import load_metadata_payload, metadata_is_complete, resolve_metadata_artifact_dir
from .summary import validate_summary_artifacts


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_run_state_dir(repo_root: Path, run_state_dir: str | Path = DEFAULT_RUN_STATE_DIR) -> Path:
    path = Path(run_state_dir)
    return path if path.is_absolute() else repo_root / path


def run_state_path(repo_root: Path, date: str, run_state_dir: str | Path = DEFAULT_RUN_STATE_DIR) -> Path:
    return resolve_run_state_dir(repo_root, run_state_dir) / f"{date}.json"


def pending_metadata_path(repo_root: Path, pending_path: str | Path = DEFAULT_PENDING_METADATA_PATH) -> Path:
    path = Path(pending_path)
    return path if path.is_absolute() else repo_root / path


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict | list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def default_run_state(date: str) -> dict:
    return {
        "schema_version": "v1",
        "date": date,
        "status": "missing",
        "selected_ids": [],
        "selected": [],
        "metadata": {},
        "summary": {},
        "finalize_ready": False,
        "blocking": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def load_run_state(repo_root: Path, date: str, run_state_dir: str | Path = DEFAULT_RUN_STATE_DIR) -> dict:
    payload = read_json(run_state_path(repo_root, date, run_state_dir), default_run_state(date))
    payload.setdefault("date", date)
    payload.setdefault("selected", [])
    payload.setdefault("selected_ids", [item.get("arxiv_id") for item in payload["selected"] if item.get("arxiv_id")])
    payload.setdefault("metadata", {})
    payload.setdefault("summary", {})
    payload.setdefault("blocking", [])
    return payload


def save_run_state(repo_root: Path, state: dict, run_state_dir: str | Path = DEFAULT_RUN_STATE_DIR) -> Path:
    state["updated_at"] = utc_now()
    return write_json(run_state_path(repo_root, state["date"], run_state_dir), state)


def record_candidate_run(
    repo_root: Path,
    *,
    date: str,
    selected: list[dict],
    preferred_date: str,
    attempted_dates: list[str],
    candidate_pool: list[dict] | None = None,
    selection_target: int | None = None,
    run_state_dir: str | Path = DEFAULT_RUN_STATE_DIR,
) -> dict:
    existing = load_run_state(repo_root, date, run_state_dir)
    state = {
        **existing,
        "date": date,
        "preferred_date": preferred_date,
        "attempted_dates": attempted_dates,
        "status": "candidate_ready",
        "candidate_pool": candidate_pool if candidate_pool is not None else selected,
        "selection_target": selection_target if selection_target is not None else len(selected),
        "selected": selected,
        "selected_ids": [candidate["arxiv_id"] for candidate in selected],
    }
    if existing.get("selected_ids") != state["selected_ids"]:
        state.pop("finalized_at", None)
    save_run_state(repo_root, state, run_state_dir)
    return state


def assess_run_state(
    repo_root: Path,
    *,
    date: str,
    summary_artifact_dir: str | Path = DEFAULT_SUMMARY_ARTIFACT_DIR,
    metadata_artifact_dir: str | Path = DEFAULT_METADATA_ARTIFACT_DIR,
    run_state_dir: str | Path = DEFAULT_RUN_STATE_DIR,
) -> dict:
    state = load_run_state(repo_root, date, run_state_dir)
    paper_ids = list(state.get("selected_ids") or [])
    selection_target = int(state.get("selection_target") or len(paper_ids))
    summary_results = validate_summary_artifacts(repo_root / summary_artifact_dir if not Path(summary_artifact_dir).is_absolute() else summary_artifact_dir, paper_ids)
    metadata_dir = resolve_metadata_artifact_dir(repo_root, metadata_artifact_dir)
    metadata_results = [metadata_readiness(metadata_dir, paper_id) for paper_id in paper_ids]

    missing_summary = [item["paper_id"] for item in summary_results if not item["ok"]]
    incomplete_metadata = [item["paper_id"] for item in metadata_results if not item["ok"]]
    blocking = []
    if not paper_ids:
        blocking.append({"kind": "candidate", "paper_ids": [], "message": "No selected candidate pack exists for this date."})
    elif len(paper_ids) < selection_target:
        blocking.append({
            "kind": "candidate",
            "paper_ids": paper_ids,
            "message": f"Only {len(paper_ids)} metadata-complete candidates selected; target is {selection_target}.",
        })
    if missing_summary:
        blocking.append({"kind": "summary", "paper_ids": missing_summary})
    if incomplete_metadata:
        blocking.append({"kind": "metadata", "paper_ids": incomplete_metadata})

    state["summary"] = {
        "ok": len(missing_summary) == 0 and bool(paper_ids),
        "complete": len(paper_ids) - len(missing_summary),
        "missing": missing_summary,
        "items": summary_results,
    }
    state["metadata"] = {
        "ok": len(incomplete_metadata) == 0 and bool(paper_ids),
        "complete": len(paper_ids) - len(incomplete_metadata),
        "missing_or_incomplete": incomplete_metadata,
        "items": metadata_results,
    }
    state["finalize_ready"] = bool(paper_ids) and not blocking
    state["blocking"] = blocking
    if state["finalize_ready"]:
        state["status"] = "final_published" if state.get("finalized_at") else "final_ready"
    elif paper_ids:
        state["status"] = "finalize_blocked"
    else:
        state["status"] = "missing"
    save_run_state(repo_root, state, run_state_dir)
    return state


def metadata_readiness(metadata_dir: Path, paper_id: str) -> dict:
    path = metadata_dir / f"{paper_id}.json"
    try:
        payload = load_metadata_payload(metadata_dir, paper_id)
    except Exception as exc:
        return {"paper_id": paper_id, "ok": False, "path": str(path), "error": str(exc)}
    return {
        "paper_id": paper_id,
        "ok": metadata_is_complete(payload),
        "path": str(path),
        "metadata_source": payload.get("metadata_source"),
        "metadata_status": payload.get("metadata_status"),
        "missing_fields": payload.get("metadata_missing_fields", []),
    }


def load_pending_metadata(repo_root: Path, pending_path: str | Path = DEFAULT_PENDING_METADATA_PATH) -> dict:
    payload = read_json(pending_metadata_path(repo_root, pending_path), {"schema_version": "v1", "tasks": []})
    payload.setdefault("schema_version", "v1")
    payload.setdefault("tasks", [])
    return payload


def save_pending_metadata(repo_root: Path, payload: dict, pending_path: str | Path = DEFAULT_PENDING_METADATA_PATH) -> Path:
    payload["updated_at"] = utc_now()
    return write_json(pending_metadata_path(repo_root, pending_path), payload)


def enqueue_metadata_tasks(
    repo_root: Path,
    *,
    date: str,
    candidates: list[dict],
    pending_path: str | Path = DEFAULT_PENDING_METADATA_PATH,
) -> dict:
    queue = load_pending_metadata(repo_root, pending_path)
    by_key = {(task.get("date"), task.get("paper_id")): task for task in queue["tasks"]}
    now = utc_now()
    for candidate in candidates:
        paper_id = candidate["arxiv_id"]
        key = (date, paper_id)
        task = by_key.get(key)
        if task and task.get("status") in {"api_complete", "html_complete"}:
            continue
        by_key[key] = {
            **(task or {}),
            "date": date,
            "paper_id": paper_id,
            "candidate": candidate,
            "status": (task or {}).get("status", "api_pending"),
            "retry_count": int((task or {}).get("retry_count", 0)),
            "next_retry_at": (task or {}).get("next_retry_at", now),
            "last_error": (task or {}).get("last_error"),
            "created_at": (task or {}).get("created_at", now),
            "updated_at": now,
        }
    queue["tasks"] = sorted(by_key.values(), key=lambda item: (item.get("date", ""), item.get("paper_id", "")))
    save_pending_metadata(repo_root, queue, pending_path)
    return queue


def update_metadata_task(
    repo_root: Path,
    *,
    date: str,
    paper_id: str,
    updates: dict,
    pending_path: str | Path = DEFAULT_PENDING_METADATA_PATH,
) -> dict:
    queue = load_pending_metadata(repo_root, pending_path)
    for task in queue["tasks"]:
        if task.get("date") == date and task.get("paper_id") == paper_id:
            task.update(updates)
            task["updated_at"] = utc_now()
            break
    save_pending_metadata(repo_root, queue, pending_path)
    return queue
