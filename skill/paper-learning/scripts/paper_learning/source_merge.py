from __future__ import annotations

from dataclasses import replace

from .models import DailyPaperRecord


def merge_supplemental_records(
    primary: list[DailyPaperRecord],
    supplemental: list[DailyPaperRecord],
) -> list[DailyPaperRecord]:
    merged = list(primary)
    by_arxiv_id = {
        normalized: index
        for index, record in enumerate(merged)
        if (normalized := _normalized_arxiv_id(record.paper_id))
    }

    for record in supplemental:
        normalized = _normalized_arxiv_id(record.paper_id)
        if normalized and normalized in by_arxiv_id:
            index = by_arxiv_id[normalized]
            original = merged[index]
            merged[index] = replace(
                original,
                signals={
                    **original.signals,
                    "hf_duplicate": True,
                    **{key: value for key, value in record.signals.items() if key.startswith("hf_")},
                },
                provenance={
                    **original.provenance,
                    "hf_url": record.url,
                    "hf_source": record.provenance.get("source", "huggingface_daily_papers"),
                },
            )
            continue

        merged.append(record)

    return merged


def _normalized_arxiv_id(paper_id: str) -> str:
    raw = paper_id.split(":", 1)[1] if ":" in paper_id else paper_id
    if raw[:4].isdigit() and "." in raw:
        return raw.split("v", 1)[0]
    return ""
