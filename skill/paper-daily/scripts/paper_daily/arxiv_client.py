from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .models import PaperCandidate

# Parsing and query helpers live in dedicated modules; re-exported here so the
# historical ``paper_daily.arxiv_client`` import surface stays stable.
from .arxiv_parse import (  # noqa: F401
    ATOM_NS,
    build_pdf_url,
    candidate_submitted_on,
    clean_text,
    format_listing_header,
    normalize_arxiv_id,
    parse_abs_abstract,
    parse_abs_authors,
    parse_abs_categories,
    parse_abs_submission_dates,
    parse_abs_title,
    parse_abs_version_id,
    parse_arxiv_datetime,
    parse_descriptor_block,
    parse_entry,
    parse_listing_authors,
    parse_listing_candidates,
    parse_listing_categories,
    strip_html,
)
from .arxiv_query import (  # noqa: F401
    FALLBACK_SIGNAL_RE,
    build_combined_query,
    build_query,
    infer_priority_keyword,
    listing_candidate_matches,
    listing_prefilter_score,
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
        found = self.fetch_metadata_batch(normalized_ids)
        missing = [arxiv_id for arxiv_id in normalized_ids if arxiv_id not in found]
        if missing:
            raise RuntimeError(f"arXiv id not found: {', '.join(missing)}")
        return [found[arxiv_id] for arxiv_id in normalized_ids]

    def fetch_metadata_batch(self, arxiv_ids: list[str]) -> dict[str, PaperCandidate]:
        """Resolve many IDs in a single id_list request to avoid per-paper request
        amplification (the main arXiv 429 trigger). Returns {arxiv_id: candidate}
        for those found; missing IDs are simply absent rather than raising, so a
        caller can still process whatever resolved. Network/HTTP errors (e.g. 429,
        timeouts) propagate so the caller can back the whole batch off at once."""
        if not arxiv_ids:
            return {}
        normalized_ids = [normalize_arxiv_id(arxiv_id) for arxiv_id in arxiv_ids]
        params = {
            "id_list": ",".join(normalized_ids),
            "max_results": len(normalized_ids),
        }
        root = self._fetch(params)
        requested = set(normalized_ids)
        found: dict[str, PaperCandidate] = {}
        for entry in root.findall("atom:entry", ATOM_NS):
            candidate = parse_entry(entry, keyword="manual-arxiv-id", keyword_rank=0, query_total=len(normalized_ids))
            if candidate.arxiv_id in requested:
                found[candidate.arxiv_id] = candidate
        return found

    def hydrate_candidate_from_abs(self, candidate: PaperCandidate) -> PaperCandidate:
        text = self._fetch_url(candidate.abs_url, min_delay=0.5).decode("utf-8", "ignore")
        abstract = parse_abs_abstract(text)
        authors = parse_abs_authors(text) or candidate.authors
        categories, primary_category = parse_abs_categories(text, fallback=candidate.categories)
        version_id = parse_abs_version_id(text) or candidate.version_id
        published, updated = parse_abs_submission_dates(text, fallback_published=candidate.published, fallback_updated=candidate.updated)
        # Prefer the title parsed from the abs page. The incoming candidate.title
        # may be a placeholder (e.g. the bare arXiv id from the --arxiv-id path),
        # so trusting it blindly poisons the metadata cache with id-as-title.
        title = parse_abs_title(text) or candidate.title
        enriched = PaperCandidate(
            arxiv_id=candidate.arxiv_id,
            version_id=version_id,
            title=title,
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
