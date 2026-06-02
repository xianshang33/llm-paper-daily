from __future__ import annotations

import json
from pathlib import Path

from .arxiv_client import normalize_arxiv_id
from .discovery import load_cached_candidate


def load_local_candidate_payload(repo_root: str | Path, arxiv_id: str) -> dict | None:
    repo_root = Path(repo_root)
    normalized_id = normalize_arxiv_id(arxiv_id)

    cached_candidate = load_cached_candidate(repo_root, normalized_id)
    if cached_candidate is not None:
        return cached_candidate.to_dict()

    canonical_candidate = load_candidate_from_canonical(repo_root, normalized_id)
    if canonical_candidate is not None:
        return canonical_candidate

    return load_candidate_from_org(repo_root, normalized_id)


def load_candidate_from_canonical(repo_root: Path, arxiv_id: str) -> dict | None:
    path = repo_root / "data" / "canonical-papers.json"
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("items", []):
        if item.get("paper_id") != arxiv_id:
            continue
        abs_url = item.get("links", {}).get("abs") or f"http://arxiv.org/abs/{arxiv_id}"
        return {
            "arxiv_id": arxiv_id,
            "version_id": abs_url.split("/abs/")[-1],
            "title": item.get("title", arxiv_id),
            "abstract": item.get("abstract", ""),
            "authors": item.get("authors", []),
            "categories": [],
            "primary_category": None,
            "published": item.get("source_discovery", {}).get("captured_at", ""),
            "updated": item.get("source_discovery", {}).get("captured_at", ""),
            "abs_url": abs_url,
            "pdf_url": item.get("links", {}).get("pdf") or abs_url.replace("/abs/", "/pdf/"),
            "priority_keyword": item.get("category_alias", "Agent"),
            "keyword_rank": 0,
            "query_total": 0,
            "institution_matches": [],
            "lab_matches": [],
            "score": 0.0,
            "reasons": ["local-canonical-cache"],
            "metadata_source": "local-canonical-cache",
            "metadata_status": "partial",
        }
    return None


def load_candidate_from_org(repo_root: Path, arxiv_id: str) -> dict | None:
    path = repo_root / "data" / "paper-learning" / "deep-reading-org" / f"arxiv_{arxiv_id}.org"
    if not path.exists():
        return None

    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#+"):
            continue
        if ":" not in line:
            continue
        key, value = line[2:].split(":", 1)
        fields[key.strip().lower()] = value.strip()

    abs_url = fields.get("source", f"http://arxiv.org/abs/{arxiv_id}")
    version_id = abs_url.split("/abs/")[-1]
    return {
        "arxiv_id": arxiv_id,
        "version_id": version_id,
        "title": fields.get("subtitle") or fields.get("title") or arxiv_id,
        "abstract": "",
        "authors": split_authors(fields.get("authors", "")),
        "categories": [],
        "primary_category": None,
        "published": "",
        "updated": "",
        "abs_url": abs_url,
        "pdf_url": abs_url.replace("/abs/", "/pdf/"),
        "priority_keyword": "Agent",
        "keyword_rank": 0,
        "query_total": 0,
        "institution_matches": [],
        "lab_matches": [],
        "score": 0.0,
        "reasons": ["local-org-artifact"],
        "metadata_source": "local-org-artifact",
        "metadata_status": "partial",
    }


def split_authors(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]
