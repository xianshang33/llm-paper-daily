from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from .models import PaperCandidate

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

FALLBACK_SIGNAL_RE = re.compile(
    r"\b(agent|agents|multi-agent|agentic|llm|llms|large language model|language model|tool[- ]?use|planning|autonomous|workflow|coding)\b",
    re.IGNORECASE,
)


class ArxivClient:
    def __init__(
        self,
        base_url: str = "https://export.arxiv.org/api/query",
        user_agent: str = "llm-paper-daily-skill/0.1",
        delay_seconds: float = 3.1,
        timeout_seconds: float = 60.0,
        retries: int = 2,
        budget_seconds: float | None = None,
        api_search_budget_seconds: float | None = 30.0,
    ) -> None:
        self.base_url = base_url
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.deadline_monotonic = time.monotonic() + budget_seconds if budget_seconds and budget_seconds > 0 else None
        self.api_search_budget_seconds = api_search_budget_seconds if api_search_budget_seconds and api_search_budget_seconds > 0 else None
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
        api_error = None
        original_deadline = self.deadline_monotonic
        try:
            self._cap_deadline(self.api_search_budget_seconds)
            root = self._fetch(params)
        except RuntimeError as exc:
            api_error = exc
        finally:
            self.deadline_monotonic = original_deadline

        if api_error is not None:
            try:
                return self._search_keywords_combined_from_listing(
                    keywords=keywords,
                    date=date,
                    categories=categories,
                    max_results=max_results,
                )
            except RuntimeError as fallback_error:
                raise RuntimeError(f"arXiv API failed ({api_error}); listing fallback failed ({fallback_error})") from fallback_error

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

    def hydrate_candidate_from_abs(self, candidate: PaperCandidate) -> PaperCandidate:
        text = self._fetch_url(candidate.abs_url, min_delay=0.5).decode("utf-8", "ignore")
        abstract = parse_abs_abstract(text)
        authors = parse_abs_authors(text) or candidate.authors
        categories, primary_category = parse_abs_categories(text, fallback=candidate.categories)
        version_id = parse_abs_version_id(text) or candidate.version_id
        published, updated = parse_abs_submission_dates(text, fallback_published=candidate.published, fallback_updated=candidate.updated)
        enriched = PaperCandidate(
            arxiv_id=candidate.arxiv_id,
            version_id=version_id,
            title=candidate.title,
            abstract=abstract or candidate.abstract,
            authors=authors,
            categories=categories,
            primary_category=primary_category or candidate.primary_category,
            published=published,
            updated=updated,
            abs_url=candidate.abs_url,
            pdf_url=build_pdf_url(version_id or candidate.version_id or candidate.arxiv_id),
            priority_keyword=candidate.priority_keyword,
            keyword_rank=candidate.keyword_rank,
            query_total=candidate.query_total,
            metadata_source="abs-html",
            metadata_status="complete",
        )
        return enriched

    def _fetch(self, params: dict) -> ET.Element:
        url = self.base_url + "?" + urllib.parse.urlencode(params)
        data = self._fetch_url(url, min_delay=self.delay_seconds)
        try:
            return ET.fromstring(data)
        except ET.ParseError as exc:
            raise RuntimeError(f"arXiv API returned invalid XML: {exc}") from exc

    def _search_keywords_combined_from_listing(
        self,
        *,
        keywords: list[str],
        date: str,
        categories: list[str],
        max_results: int,
    ) -> tuple[list[PaperCandidate], int]:
        discovered: dict[str, PaperCandidate] = {}
        for category in categories:
            try:
                category_candidates = self._fetch_listing_candidates(date=date, category=category)
            except RuntimeError:
                if discovered:
                    break
                raise
            for candidate in category_candidates:
                existing = discovered.get(candidate.arxiv_id)
                if existing is None or len(candidate.categories) > len(existing.categories):
                    discovered[candidate.arxiv_id] = candidate

        listing_candidates = list(discovered.values())
        shortlisted = [
            candidate
            for candidate in listing_candidates
            if listing_candidate_matches(candidate, keywords)
        ]
        shortlisted.sort(key=lambda candidate: listing_prefilter_score(candidate, keywords), reverse=True)
        target_count = min(max_results, 40)
        fetch_limit = min(len(shortlisted), max(target_count * 2, 60))
        enriched = []
        rejected = set()
        for candidate in shortlisted[:fetch_limit]:
            try:
                enriched_candidate = self._enrich_listing_candidate(candidate, keywords=keywords, query_total=len(listing_candidates))
            except RuntimeError:
                break
            if candidate_submitted_on(enriched_candidate, date):
                enriched.append(enriched_candidate)
                if len(enriched) >= target_count:
                    break
            else:
                rejected.add(candidate.arxiv_id)
        if len(enriched) < target_count:
            seen = {candidate.arxiv_id for candidate in enriched} | rejected
            for candidate in shortlisted:
                if candidate.arxiv_id in seen:
                    continue
                listing_candidate = self._prepare_listing_candidate(candidate, keywords=keywords, query_total=len(listing_candidates))
                enriched.append(listing_candidate)
                seen.add(candidate.arxiv_id)
                if len(enriched) >= target_count:
                    break
        return enriched, len(listing_candidates)

    def _fetch_listing_candidates(self, *, date: str, category: str) -> list[PaperCandidate]:
        url = f"https://arxiv.org/list/{category}/pastweek?show=2000"
        text = self._fetch_url(url, min_delay=0.5).decode("utf-8", "ignore")
        return parse_listing_candidates(text, date=date, category=category)

    def _enrich_listing_candidate(
        self,
        candidate: PaperCandidate,
        *,
        keywords: list[str],
        query_total: int,
    ) -> PaperCandidate:
        enriched = self.hydrate_candidate_from_abs(candidate)
        enriched.query_total = query_total
        keyword, keyword_rank = infer_priority_keyword(enriched, keywords)
        enriched.priority_keyword = keyword
        enriched.keyword_rank = keyword_rank
        return enriched

    def _prepare_listing_candidate(
        self,
        candidate: PaperCandidate,
        *,
        keywords: list[str],
        query_total: int,
    ) -> PaperCandidate:
        keyword, keyword_rank = infer_priority_keyword(candidate, keywords)
        candidate.priority_keyword = keyword
        candidate.keyword_rank = keyword_rank
        candidate.query_total = query_total
        candidate.metadata_source = "arxiv-listing"
        candidate.metadata_status = "partial"
        return candidate

    def _fetch_url(self, url: str, *, min_delay: float) -> bytes:
        self._respect_delay(min_delay)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._ensure_budget()
            self._last_request = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self._request_timeout()) as response:
                    return response.read()
            except Exception as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                self._sleep_with_budget(self._retry_delay(exc, attempt))
        raise RuntimeError(f"arXiv query failed after {self.retries + 1} attempts: {last_error}")

    def _respect_delay(self, minimum_delay: float) -> None:
        wait = minimum_delay - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleep_with_budget(wait)

    def _retry_delay(self, exc: Exception, attempt: int) -> float:
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
            retry_after = exc.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(float(retry_after), self.delay_seconds)
                except ValueError:
                    pass
            return max(30.0 * (attempt + 1), self.delay_seconds)
        return max(min(2**attempt, 8), self.delay_seconds)

    def _request_timeout(self) -> float:
        remaining = self._remaining_budget()
        if remaining is None:
            return self.timeout_seconds
        if remaining <= 0:
            raise RuntimeError("arXiv discovery budget exhausted")
        return max(0.1, min(self.timeout_seconds, remaining))

    def _sleep_with_budget(self, seconds: float) -> None:
        remaining = self._remaining_budget()
        if remaining is None:
            time.sleep(seconds)
            return
        if remaining <= 0 or seconds >= remaining:
            raise RuntimeError("arXiv discovery budget exhausted")
        time.sleep(seconds)

    def _ensure_budget(self) -> None:
        remaining = self._remaining_budget()
        if remaining is not None and remaining <= 0:
            raise RuntimeError("arXiv discovery budget exhausted")

    def _remaining_budget(self) -> float | None:
        if self.deadline_monotonic is None:
            return None
        return self.deadline_monotonic - time.monotonic()

    def _cap_deadline(self, budget_seconds: float | None) -> None:
        if budget_seconds is None:
            return
        deadline = time.monotonic() + budget_seconds
        if self.deadline_monotonic is None:
            self.deadline_monotonic = deadline
        else:
            self.deadline_monotonic = min(self.deadline_monotonic, deadline)


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


def parse_listing_candidates(content: str, *, date: str, category: str) -> list[PaperCandidate]:
    header = format_listing_header(date)
    section_match = re.search(
        rf"<h3>\s*{re.escape(header)}.*?</h3>(.*?)(?:<h3>|</dl>)",
        content,
        re.S,
    )
    if not section_match:
        return []

    section = section_match.group(1)
    entries = re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", section, re.S)
    candidates = []
    for dt_html, dd_html in entries:
        arxiv_match = re.search(r'href\s*=\s*"/abs/([^"]+)"', dt_html)
        if not arxiv_match:
            continue
        version_id = arxiv_match.group(1).strip()
        arxiv_id = normalize_arxiv_id(version_id)
        title = parse_descriptor_block(dd_html, "Title:")
        authors = parse_listing_authors(dd_html)
        categories = parse_listing_categories(dd_html, fallback=[category])
        candidate = PaperCandidate(
            arxiv_id=arxiv_id,
            version_id=version_id,
            title=title,
            abstract="",
            authors=authors,
            categories=categories,
            primary_category=categories[0] if categories else category,
            published=f"{date}T00:00:00Z",
            updated=f"{date}T00:00:00Z",
            abs_url=f"https://arxiv.org/abs/{version_id}",
            pdf_url=build_pdf_url(version_id),
            priority_keyword="Agent",
            keyword_rank=1,
            query_total=0,
        )
        candidates.append(candidate)
    return candidates


def parse_abs_abstract(content: str) -> str:
    match = re.search(r"Abstract:</span>(.*?)</blockquote>", content, re.S)
    if not match:
        return ""
    return clean_text(strip_html(match.group(1)))


def parse_abs_authors(content: str) -> list[str]:
    match = re.search(r'Authors:</span>(.*?)</div>', content, re.S)
    if not match:
        return []
    authors = re.findall(r">([^<]+)</a>", match.group(1))
    return [clean_text(html.unescape(author)) for author in authors]


def parse_abs_categories(content: str, *, fallback: list[str]) -> tuple[list[str], str | None]:
    subjects_match = re.search(r'<td class="tablecell subjects">(.*?)</td>', content, re.S)
    if not subjects_match:
        return fallback, fallback[0] if fallback else None
    categories = re.findall(r"\(([a-zA-Z.\-]+)\)", subjects_match.group(1))
    primary_match = re.search(r'<span class="primary-subject">.*?</span>\s*\(([a-zA-Z.\-]+)\)', subjects_match.group(1), re.S)
    primary = primary_match.group(1) if primary_match else (categories[0] if categories else None)
    return categories or fallback, primary


def parse_abs_version_id(content: str) -> str | None:
    match = re.search(r"arXiv:(\d{4}\.\d{4,5}(?:v\d+)?)", content)
    return match.group(1) if match else None


def parse_descriptor_block(content: str, descriptor: str) -> str:
    match = re.search(
        rf"<span class='descriptor'>{re.escape(descriptor)}</span>(.*?)</div>",
        content,
        re.S,
    )
    if not match:
        return ""
    return clean_text(strip_html(match.group(1)))


def parse_listing_authors(content: str) -> list[str]:
    match = re.search(r"<div class='list-authors'>(.*?)</div>", content, re.S)
    if not match:
        return []
    authors = re.findall(r">([^<]+)</a>", match.group(1))
    return [clean_text(html.unescape(author)) for author in authors]


def parse_listing_categories(content: str, *, fallback: list[str]) -> list[str]:
    match = re.search(r"<div class='list-subjects'>(.*?)</div>", content, re.S)
    if not match:
        return fallback
    categories = re.findall(r"\(([a-zA-Z.\-]+)\)", match.group(1))
    return categories or fallback


def listing_candidate_matches(candidate: PaperCandidate, keywords: list[str]) -> bool:
    text = f"{candidate.title} {' '.join(candidate.categories)}"
    return FALLBACK_SIGNAL_RE.search(text) is not None or any(keyword.lower() in text.lower() for keyword in keywords)


def listing_prefilter_score(candidate: PaperCandidate, keywords: list[str]) -> float:
    text = f"{candidate.title} {' '.join(candidate.categories)}".lower()
    score = 0.0
    for rank, keyword in enumerate(keywords, start=1):
        if keyword.lower() in text:
            score += max(0.5, 4.0 - rank)
    if re.search(r"\bagents?\b|multi-agent|agentic", text):
        score += 6.0
    if re.search(r"\bllms?\b|large language model|language model", text):
        score += 4.0
    if re.search(r"\b(reasoning|benchmark|evaluation|skill|distillation|reinforcement|privacy|safety|memory|tool)\b", text):
        score += 2.0
    if any(category in candidate.categories for category in ("cs.AI", "cs.CL", "cs.LG", "stat.ML")):
        score += 1.0
    return score


def parse_abs_submission_dates(content: str, *, fallback_published: str, fallback_updated: str) -> tuple[str, str]:
    history = re.findall(r"<strong>\[v\d+\]</strong>\s*([A-Za-z]{3}, \d{1,2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} UTC)", content)
    if not history:
        return fallback_published, fallback_updated
    timestamps = [parse_arxiv_datetime(value) for value in history]
    return timestamps[0], timestamps[-1]


def format_listing_header(date: str) -> str:
    return datetime.strptime(date, "%Y-%m-%d").strftime("%a, %d %b %Y").replace(" 0", " ")


def strip_html(content: str) -> str:
    content = re.sub(r"<[^>]+>", " ", content)
    return html.unescape(content)


def build_pdf_url(version_id: str) -> str:
    return f"https://arxiv.org/pdf/{version_id}"


def parse_arxiv_datetime(raw: str) -> str:
    return datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def candidate_submitted_on(candidate: PaperCandidate, date: str) -> bool:
    return candidate.published.startswith(f"{date}T")
