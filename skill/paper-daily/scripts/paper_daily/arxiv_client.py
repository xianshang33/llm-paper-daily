from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .models import PaperCandidate

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
RATE_LIMIT_RETRY_DELAYS = [120.0, 300.0, 900.0]


class ArxivClient:
    def __init__(
        self,
        base_url: str = "https://export.arxiv.org/api/query",
        user_agent: str = "llm-paper-daily-skill/0.1",
        delay_seconds: float = 3.1,
        timeout_seconds: float = 60.0,
        retries: int = 2,
    ) -> None:
        self.base_url = base_url
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self._last_request = 0.0

    def search_keyword(
        self,
        *,
        keyword: str,
        keyword_rank: int,
        date: str,
        categories: list[str],
        max_results: int,
    ) -> tuple[list[PaperCandidate], int]:
        query = build_query(keyword=keyword, date=date, categories=categories)
        params = {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        root = self._fetch(params)
        total = int(root.findtext("opensearch:totalResults", default="0", namespaces=ATOM_NS))
        candidates = [
            parse_entry(entry, keyword=keyword, keyword_rank=keyword_rank, query_total=total)
            for entry in root.findall("atom:entry", ATOM_NS)
        ]
        return candidates, total

    def search_keywords_combined(
        self,
        *,
        keywords: list[str],
        date: str,
        categories: list[str],
        max_results: int,
    ) -> tuple[list[PaperCandidate], int]:
        query = build_combined_query(keywords=keywords, date=date, categories=categories)
        params = {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        root = self._fetch(params)
        total = int(root.findtext("opensearch:totalResults", default="0", namespaces=ATOM_NS))
        candidates = []
        for entry in root.findall("atom:entry", ATOM_NS):
            candidate = parse_entry(entry, keyword=keywords[0], keyword_rank=1, query_total=total)
            keyword, keyword_rank = infer_priority_keyword(candidate, keywords)
            candidate.priority_keyword = keyword
            candidate.keyword_rank = keyword_rank
            candidates.append(candidate)
        return candidates, total

    def get_by_arxiv_ids(self, arxiv_ids: list[str]) -> list[PaperCandidate]:
        normalized_ids = [normalize_arxiv_id(arxiv_id) for arxiv_id in arxiv_ids]
        params = {
            "id_list": ",".join(normalized_ids),
            "max_results": len(normalized_ids),
        }
        root = self._fetch(params)
        candidates = [
            parse_entry(entry, keyword="manual-arxiv-id", keyword_rank=0, query_total=len(normalized_ids))
            for entry in root.findall("atom:entry", ATOM_NS)
        ]
        by_id = {candidate.arxiv_id: candidate for candidate in candidates}
        missing = [arxiv_id for arxiv_id in normalized_ids if arxiv_id not in by_id]
        if missing:
            raise RuntimeError(f"arXiv id not found: {', '.join(missing)}")
        return [by_id[arxiv_id] for arxiv_id in normalized_ids]

    def _fetch(self, params: dict) -> ET.Element:
        wait = self.delay_seconds - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

        url = self.base_url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            self._last_request = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                    data = response.read()
                return ET.fromstring(data)
            except Exception as exc:  # network APIs fail in several urllib-specific shapes
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(self._retry_delay(exc, attempt))

        raise RuntimeError(f"arXiv query failed after {self.retries + 1} attempts: {last_error}")

    def _retry_delay(self, exc: Exception, attempt: int) -> float:
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
            default_delay = RATE_LIMIT_RETRY_DELAYS[min(attempt, len(RATE_LIMIT_RETRY_DELAYS) - 1)]
            retry_after = exc.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(float(retry_after), default_delay, self.delay_seconds)
                except ValueError:
                    pass
            return max(default_delay, self.delay_seconds)
        return max(min(2**attempt, 8), self.delay_seconds)


def build_query(*, keyword: str, date: str, categories: list[str]) -> str:
    start = date.replace("-", "") + "0000"
    end = date.replace("-", "") + "2359"
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    return f"({category_query}) AND (all:{keyword}) AND submittedDate:[{start} TO {end}]"


def build_combined_query(*, keywords: list[str], date: str, categories: list[str]) -> str:
    start = date.replace("-", "") + "0000"
    end = date.replace("-", "") + "2359"
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    keyword_query = " OR ".join(f"all:{keyword}" for keyword in keywords)
    return f"({category_query}) AND ({keyword_query}) AND submittedDate:[{start} TO {end}]"


def normalize_arxiv_id(raw: str) -> str:
    raw = raw.split("/abs/")[-1].strip()
    return re.sub(r"v\d+$", "", raw)


def infer_priority_keyword(candidate: PaperCandidate, keywords: list[str]) -> tuple[str, int]:
    text = f"{candidate.title} {candidate.abstract}".lower()
    for rank, keyword in enumerate(keywords, start=1):
        if keyword.lower() in text:
            return keyword, rank
    return keywords[0], 1


def parse_entry(entry: ET.Element, *, keyword: str, keyword_rank: int, query_total: int) -> PaperCandidate:
    abs_url = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
    version_id = abs_url.split("/abs/")[-1] if "/abs/" in abs_url else abs_url
    arxiv_id = normalize_arxiv_id(version_id)
    title = clean_text(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
    abstract = clean_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
    authors = [
        clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
        for author in entry.findall("atom:author", ATOM_NS)
    ]
    categories = [node.attrib.get("term", "") for node in entry.findall("atom:category", ATOM_NS)]
    primary_node = entry.find("arxiv:primary_category", ATOM_NS)
    primary_category = primary_node.attrib.get("term") if primary_node is not None else None
    pdf_url = None
    for link in entry.findall("atom:link", ATOM_NS):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href")
            break

    return PaperCandidate(
        arxiv_id=arxiv_id,
        version_id=version_id,
        title=title,
        abstract=abstract,
        authors=authors,
        categories=categories,
        primary_category=primary_category,
        published=entry.findtext("atom:published", default="", namespaces=ATOM_NS),
        updated=entry.findtext("atom:updated", default="", namespaces=ATOM_NS),
        abs_url=abs_url,
        pdf_url=pdf_url,
        priority_keyword=keyword,
        keyword_rank=keyword_rank,
        query_total=query_total,
    )


def clean_text(value: str) -> str:
    return " ".join(value.split())
