from __future__ import annotations

import json
from pathlib import Path

from .defaults import DEFAULT_METADATA_ARTIFACT_DIR
from .discovery import paper_candidate_from_dict

REQUIRED_METADATA_FIELDS = [
    "arxiv_id",
    "version_id",
    "title",
    "authors",
    "abstract",
    "published",
    "updated",
    "categories",
    "primary_category",
    "abs_url",
    "pdf_url",
]


def metadata_artifact_path(base_dir: str | Path, paper_id: str) -> Path:
    return Path(base_dir) / f"{paper_id}.json"


def load_metadata_payload(base_dir: str | Path, paper_id: str) -> dict:
    path = metadata_artifact_path(base_dir, paper_id)
    if not path.exists():
        raise FileNotFoundError(f"Missing metadata artifact for {paper_id}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def metadata_missing_fields(payload: dict) -> list[str]:
    missing = []
    for key in REQUIRED_METADATA_FIELDS:
        value = payload.get(key)
        if value is None or value == "" or value == []:
            missing.append(key)
    return missing


def metadata_is_complete(payload: dict) -> bool:
    return not metadata_missing_fields(payload)


def normalize_metadata_payload(payload: dict, *, source: str, status: str) -> dict:
    normalized = dict(payload)
    normalized["metadata_source"] = source
    normalized["metadata_status"] = status
    normalized["metadata_missing_fields"] = metadata_missing_fields(normalized)
    return normalized


def write_metadata_payload(base_dir: str | Path, payload: dict) -> Path:
    path = metadata_artifact_path(base_dir, payload["arxiv_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def validate_metadata_artifacts(base_dir: str | Path, paper_ids: list[str]) -> list[dict]:
    results = []
    for paper_id in paper_ids:
        path = metadata_artifact_path(base_dir, paper_id)
        try:
            payload = load_metadata_payload(base_dir, paper_id)
            missing = metadata_missing_fields(payload)
            results.append({
                "paper_id": paper_id,
                "ok": not missing,
                "path": str(path),
                "missing_fields": missing,
                "metadata_source": payload.get("metadata_source"),
            })
        except Exception as exc:
            results.append({"paper_id": paper_id, "ok": False, "path": str(path), "error": str(exc)})
    return results


def resolve_metadata_artifact_dir(repo_root: Path, metadata_artifact_dir: str | Path = DEFAULT_METADATA_ARTIFACT_DIR) -> Path:
    path = Path(metadata_artifact_dir)
    if path.is_absolute():
        return path
    return repo_root / path


def merge_candidate_with_metadata(candidate: dict, metadata: dict) -> dict:
    merged = dict(candidate)
    merged.update({key: value for key, value in metadata.items() if key in REQUIRED_METADATA_FIELDS or key.startswith("metadata_")})
    return merged


def complete_candidates_metadata(candidates: list[dict], *, client, metadata_artifact_dir: Path) -> list[dict]:
    completed: list[dict] = []
    missing_candidates: list[dict] = []

    for candidate in candidates:
        cached = load_cached_metadata_if_complete(metadata_artifact_dir, candidate["arxiv_id"])
        if cached is not None:
            completed.append(merge_candidate_with_metadata(candidate, cached))
            continue
        missing_candidates.append(candidate)

    api_payloads: dict[str, dict] = {}
    if missing_candidates:
        missing_ids = [candidate["arxiv_id"] for candidate in missing_candidates]
        try:
            remote_candidates = client.get_by_arxiv_ids(missing_ids)
            for remote_candidate in remote_candidates:
                payload = normalize_metadata_payload(remote_candidate.to_dict(), source="arxiv-api", status="complete")
                write_metadata_payload(metadata_artifact_dir, payload)
                api_payloads[payload["arxiv_id"]] = payload
        except Exception:
            api_payloads = {}

    for candidate in missing_candidates:
        paper_id = candidate["arxiv_id"]
        if paper_id in api_payloads:
            completed.append(merge_candidate_with_metadata(candidate, api_payloads[paper_id]))
            continue

        hydrated = client.hydrate_candidate_from_abs(paper_candidate_from_dict(candidate))
        payload = normalize_metadata_payload(hydrated.to_dict(), source=hydrated.metadata_source or "abs-html", status=hydrated.metadata_status or "complete")
        write_metadata_payload(metadata_artifact_dir, payload)
        completed.append(merge_candidate_with_metadata(candidate, payload))

    return completed


def load_cached_metadata_if_complete(metadata_artifact_dir: Path, paper_id: str) -> dict | None:
    path = metadata_artifact_path(metadata_artifact_dir, paper_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if metadata_is_complete(payload) else None
