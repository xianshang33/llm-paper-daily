from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .arxiv_client import ArxivClient, normalize_arxiv_id
from .defaults import DEFAULT_DAILY_SELECT
from .filters import DEFAULT_CATEGORIES, DEFAULT_KEYWORDS, dedupe_by_priority, keep_candidate
from .institutions import InstitutionCatalog
from .models import PaperCandidate
from .ranker import rank_candidates


def discover_ranked(
    *,
    client: ArxivClient,
    catalog: InstitutionCatalog,
    date: str,
    keywords: list[str] | None = None,
    categories: list[str] | None = None,
    max_results_per_keyword: int = 50,
) -> dict:
    keywords = keywords or list(DEFAULT_KEYWORDS)
    categories = categories or list(DEFAULT_CATEGORIES)

    raw_candidates = []
    query_totals: dict[str, int | str] = {}
    query_key = f"combined:{','.join(keywords)}"
    try:
        candidates, total = client.search_keywords_combined(
            keywords=keywords,
            date=date,
            categories=categories,
            max_results=max_results_per_keyword * len(keywords),
        )
        raw_candidates.extend(candidates)
        query_totals[query_key] = total
    except Exception as exc:
        query_totals[query_key] = f"ERROR:{type(exc).__name__}:{exc}"

    deduped = dedupe_by_priority(raw_candidates)
    filtered = [candidate for candidate in deduped if keep_candidate(candidate)]
    ranked = rank_candidates(filtered, catalog)
    return {
        "date": date,
        "keywords": keywords,
        "categories": categories,
        "query_totals": query_totals,
        "counts": {
            "raw": len(raw_candidates),
            "deduped": len(deduped),
            "filtered": len(filtered),
        },
        "ranked": ranked,
    }


def find_next_discovery(
    *,
    client: ArxivClient,
    catalog: InstitutionCatalog,
    preferred_date: str,
    analyzed_dates: set[str] | None = None,
    max_lookback_days: int = 7,
    keywords: list[str] | None = None,
    categories: list[str] | None = None,
    max_results_per_keyword: int = 50,
) -> dict:
    analyzed_dates = analyzed_dates or set()
    attempted_dates: list[str] = []
    skipped_analyzed_dates: list[str] = []
    discovery_errors: list[str] = []
    start_date = datetime.strptime(preferred_date, "%Y-%m-%d").date()
    stage_limits = backfill_stage_limits(max_lookback_days)

    for stage_limit in stage_limits:
        stage_result = scan_discovery_window(
            client=client,
            catalog=catalog,
            start_date=start_date,
            stage_limit=stage_limit,
            attempted_dates=attempted_dates,
            skipped_analyzed_dates=skipped_analyzed_dates,
            discovery_errors=discovery_errors,
            analyzed_dates=analyzed_dates,
            keywords=keywords,
            categories=categories,
            max_results_per_keyword=max_results_per_keyword,
        )
        if stage_result:
            candidate_date, discovered = stage_result
            return {
                "preferred_date": preferred_date,
                "selected_date": candidate_date,
                "attempted_dates": attempted_dates,
                "skipped_analyzed_dates": skipped_analyzed_dates,
                "discovery_errors": discovery_errors,
                "used_backfill": candidate_date != preferred_date,
                "selected_stage_limit": stage_limit,
                "discovered": discovered,
            }
        if discovery_errors:
            break

    return {
        "preferred_date": preferred_date,
        "selected_date": None,
        "attempted_dates": attempted_dates,
        "skipped_analyzed_dates": skipped_analyzed_dates,
        "discovery_errors": discovery_errors,
        "used_backfill": False,
        "selected_stage_limit": None,
        "discovered": None,
    }


def load_discovery_artifact(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "date": payload["date"],
        "keywords": payload.get("keywords", list(DEFAULT_KEYWORDS)),
        "categories": payload.get("categories", list(DEFAULT_CATEGORIES)),
        "query_totals": payload.get("query_totals", {}),
        "counts": payload.get("counts", {}),
        "selected": [paper_candidate_from_dict(candidate) for candidate in payload.get("selected", [])],
        "ranked": [paper_candidate_from_dict(candidate) for candidate in payload.get("ranked", [])],
    }


def load_cached_discovery_for_date(repo_root: str | Path, date: str) -> dict | None:
    path = Path(repo_root) / "skill" / "paper-daily" / "output" / f"discovered-{date}.json"
    if not path.exists():
        return None
    return load_discovery_artifact(path)


def load_cached_candidate(repo_root: str | Path, arxiv_id: str) -> PaperCandidate | None:
    output_dir = Path(repo_root) / "skill" / "paper-daily" / "output"
    if not output_dir.exists():
        return None

    candidate_key = normalize_arxiv_id(arxiv_id)
    latest_date = ""
    latest_candidate = None
    for path in sorted(output_dir.glob("discovered-*.json")):
        match = re.match(r"discovered-(\d{4}-\d{2}-\d{2})\.json$", path.name)
        if not match:
            continue
        discovered = load_discovery_artifact(path)
        for candidate in discovered["ranked"]:
            if candidate.arxiv_id != candidate_key:
                continue
            artifact_date = match.group(1)
            if artifact_date >= latest_date:
                latest_date = artifact_date
                latest_candidate = candidate
    return latest_candidate


def select_ranked_candidates(
    ranked_candidates: list,
    *,
    min_select: int = 3,
    max_select: int = DEFAULT_DAILY_SELECT,
    score_threshold: float = 6.0,
) -> list:
    if not ranked_candidates or max_select <= 0:
        return []

    max_select = max(max_select, 1)
    min_select = max(0, min(min_select, max_select))

    threshold_hits = [candidate for candidate in ranked_candidates if candidate.score >= score_threshold]
    if len(threshold_hits) >= min_select:
        return threshold_hits[:max_select]

    fallback_count = min(len(ranked_candidates), max_select)
    if min_select > 0 and len(ranked_candidates) >= min_select:
        fallback_count = max(min_select, min(fallback_count, max_select))
    return ranked_candidates[:fallback_count]


def backfill_stage_limits(max_lookback_days: int) -> list[int]:
    if max_lookback_days <= 0:
        return []
    if max_lookback_days <= 3:
        return [max_lookback_days]
    return [3, max_lookback_days]


def scan_discovery_window(
    *,
    client: ArxivClient,
    catalog: InstitutionCatalog,
    start_date,
    stage_limit: int,
    attempted_dates: list[str],
    skipped_analyzed_dates: list[str],
    discovery_errors: list[str],
    analyzed_dates: set[str],
    keywords: list[str] | None,
    categories: list[str] | None,
    max_results_per_keyword: int,
) -> tuple[str, dict] | None:
    for offset in range(stage_limit):
        candidate_date = (start_date - timedelta(days=offset)).strftime("%Y-%m-%d")
        if candidate_date in attempted_dates:
            continue
        attempted_dates.append(candidate_date)
        if candidate_date in analyzed_dates:
            skipped_analyzed_dates.append(candidate_date)
            continue
        discovered = discover_ranked(
            client=client,
            catalog=catalog,
            date=candidate_date,
            keywords=keywords,
            categories=categories,
            max_results_per_keyword=max_results_per_keyword,
        )
        errors = [
            f"{candidate_date}:{keyword}:{total}"
            for keyword, total in discovered["query_totals"].items()
            if isinstance(total, str) and total.startswith("ERROR:")
        ]
        discovery_errors.extend(errors)
        if errors and len(errors) == len(discovered["query_totals"]):
            return None
        if discovered["ranked"]:
            return candidate_date, discovered
    return None


def paper_candidate_from_dict(payload: dict) -> PaperCandidate:
    return PaperCandidate(
        arxiv_id=payload["arxiv_id"],
        version_id=payload.get("version_id", payload["arxiv_id"]),
        title=payload["title"],
        abstract=payload.get("abstract", ""),
        authors=payload.get("authors", []),
        categories=payload.get("categories", []),
        primary_category=payload.get("primary_category"),
        published=payload.get("published", ""),
        updated=payload.get("updated", ""),
        abs_url=payload.get("abs_url", ""),
        pdf_url=payload.get("pdf_url"),
        priority_keyword=payload.get("priority_keyword", "Agent"),
        keyword_rank=payload.get("keyword_rank", 0),
        query_total=payload.get("query_total", 0),
        institution_matches=payload.get("institution_matches", []),
        lab_matches=payload.get("lab_matches", []),
        score=payload.get("score", 0.0),
        reasons=payload.get("reasons", []),
        metadata_source=payload.get("metadata_source", ""),
        metadata_status=payload.get("metadata_status", ""),
    )
