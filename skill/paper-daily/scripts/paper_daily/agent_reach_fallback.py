from __future__ import annotations

import re
import subprocess

from .arxiv_parse import build_pdf_url, normalize_arxiv_id
from .arxiv_query import infer_priority_keyword
from .models import PaperCandidate


ARXIV_URL_RE = re.compile(r"https?://arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?")


def parse_arxiv_ids_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    arxiv_ids: list[str] = []
    for match in ARXIV_URL_RE.finditer(text):
        arxiv_id = normalize_arxiv_id(match.group(1))
        if arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        arxiv_ids.append(arxiv_id)
    return arxiv_ids


class AgentReachFallback:
    """Optional Exa-backed arXiv URL recall via Agent Reach's mcporter route."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    def search(
        self,
        *,
        keywords: list[str],
        date: str,
        categories: list[str],
        max_results: int,
    ) -> list[PaperCandidate]:
        query = build_exa_query(keywords=keywords, date=date, categories=categories)
        selector = f'exa.web_search_exa(query: "{_escape_selector_string(query)}", numResults: {max(1, min(max_results, 25))})'
        try:
            result = subprocess.run(
                ["mcporter", "call", selector],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        arxiv_ids = parse_arxiv_ids_from_text(result.stdout)
        return [
            self._candidate_from_arxiv_id(
                arxiv_id,
                keywords=keywords,
                categories=categories,
                query_total=len(arxiv_ids),
            )
            for arxiv_id in arxiv_ids[:max_results]
        ]

    def _candidate_from_arxiv_id(
        self,
        arxiv_id: str,
        *,
        keywords: list[str],
        categories: list[str],
        query_total: int,
    ) -> PaperCandidate:
        keyword, keyword_rank = infer_priority_keyword(
            PaperCandidate(
                arxiv_id=arxiv_id,
                version_id=arxiv_id,
                title=arxiv_id,
                abstract="",
                authors=[],
                categories=categories,
                primary_category=categories[0] if categories else None,
                published="",
                updated="",
                abs_url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=build_pdf_url(arxiv_id),
                priority_keyword=keywords[0],
                keyword_rank=1,
                query_total=query_total,
            ),
            keywords,
        )
        return PaperCandidate(
            arxiv_id=arxiv_id,
            version_id=arxiv_id,
            title=arxiv_id,
            abstract="",
            authors=[],
            categories=categories,
            primary_category=categories[0] if categories else None,
            published="",
            updated="",
            abs_url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=build_pdf_url(arxiv_id),
            priority_keyword=keyword,
            keyword_rank=keyword_rank,
            query_total=query_total,
            metadata_source="agent-reach-exa",
            metadata_status="partial",
        )


def build_exa_query(*, keywords: list[str], date: str, categories: list[str]) -> str:
    keyword_query = " OR ".join(f'"{keyword}"' for keyword in keywords)
    category_hint = " OR ".join(categories)
    # Exa understands natural language/date hints better than arXiv category
    # filters. Keep arXiv IDs as the source of truth after retrieval.
    return f"site:arxiv.org/abs ({keyword_query}) ({category_hint}) submitted {date}"


def _escape_selector_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
