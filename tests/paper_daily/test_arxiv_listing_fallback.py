import unittest
from unittest.mock import patch

from skill.paper_daily_import import add_paper_daily_path


add_paper_daily_path()

from paper_daily.arxiv_client import (
    ArxivClient,
    candidate_submitted_on,
    format_listing_header,
    parse_abs_abstract,
    parse_abs_categories,
    parse_abs_version_id,
    listing_prefilter_score,
    parse_listing_candidates,
)
from paper_daily.models import PaperCandidate


LISTING_HTML = """
<dl id='articles'>
<h3>Tue, 26 May 2026 (showing 1 of 1 entries )</h3>
<dt>
  <a href ="/abs/2605.12345v1" title="Abstract" id="2605.12345">arXiv:2605.12345</a>
</dt>
<dd>
  <div class='meta'>
    <div class='list-title mathjax'><span class='descriptor'>Title:</span>
      Example Agent Paper
    </div>
    <div class='list-authors'><a href="/search">Alice</a>, <a href="/search">Bob</a></div>
    <div class='list-subjects'><span class='descriptor'>Subjects:</span>
      <span class="primary-subject">Artificial Intelligence (cs.AI)</span>; Computation and Language (cs.CL)
    </div>
  </div>
</dd>
</dl>
"""

ABS_HTML = """
<html>
  <body>
    <div>arXiv:2605.12345v1</div>
    <blockquote class="abstract mathjax">
      <span class="descriptor">Abstract:</span>
      This is an abstract about an LLM agent system.
    </blockquote>
    <td class="tablecell subjects">
      <span class="primary-subject">Artificial Intelligence</span> (cs.AI); Computation and Language (cs.CL)
    </td>
  </body>
</html>
"""


class ArxivListingFallbackTest(unittest.TestCase):
    def test_format_listing_header(self):
        self.assertEqual(format_listing_header("2026-05-26"), "Tue, 26 May 2026")

    def test_parse_listing_candidates(self):
        candidates = parse_listing_candidates(LISTING_HTML, date="2026-05-26", category="cs.AI")
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.arxiv_id, "2605.12345")
        self.assertEqual(candidate.title, "Example Agent Paper")
        self.assertEqual(candidate.authors, ["Alice", "Bob"])
        self.assertEqual(candidate.categories, ["cs.AI", "cs.CL"])

    def test_parse_abs_helpers(self):
        self.assertEqual(parse_abs_version_id(ABS_HTML), "2605.12345v1")
        self.assertEqual(parse_abs_abstract(ABS_HTML), "This is an abstract about an LLM agent system.")
        self.assertEqual(parse_abs_categories(ABS_HTML, fallback=["cs.AI"]), (["cs.AI", "cs.CL"], "cs.AI"))

    def test_candidate_submitted_on_uses_actual_published_date(self):
        candidates = parse_listing_candidates(LISTING_HTML, date="2026-05-26", category="cs.AI")
        candidate = candidates[0]
        candidate.published = "2026-05-25T23:59:59Z"
        self.assertFalse(candidate_submitted_on(candidate, "2026-05-26"))
        candidate.published = "2026-05-26T00:00:00Z"
        self.assertTrue(candidate_submitted_on(candidate, "2026-05-26"))

    def test_listing_fallback_filters_by_hydrated_submission_date(self):
        stale = self.make_candidate("2605.00001", "Stale Agent Paper")
        fresh = self.make_candidate("2605.00002", "Fresh Agent Paper")

        class FakeClient(ArxivClient):
            def _fetch_listing_candidates(self, *, date, category):
                return [stale, fresh]

            def hydrate_candidate_from_abs(self, candidate):
                if candidate.arxiv_id == "2605.00001":
                    candidate.published = "2026-05-25T23:00:00Z"
                return candidate

        candidates, _ = FakeClient()._search_keywords_combined_from_listing(
            keywords=["Agent"],
            date="2026-05-26",
            categories=["cs.AI"],
            max_results=5,
        )
        self.assertEqual([candidate.arxiv_id for candidate in candidates], ["2605.00002"])

    def test_retry_sleep_is_capped_by_global_budget(self):
        client = ArxivClient(budget_seconds=1, retries=1)

        with patch("time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                client._sleep_with_budget(30)

        sleep.assert_not_called()

    def test_request_timeout_is_capped_by_global_budget(self):
        client = ArxivClient(timeout_seconds=60, budget_seconds=10)
        self.assertLessEqual(client._request_timeout(), 10)

    def test_combined_search_preserves_budget_for_listing_fallback(self):
        fallback_candidate = self.make_candidate("2605.00003", "Fallback Agent Paper")

        class FakeClient(ArxivClient):
            def _fetch(self, params):
                raise RuntimeError("api exhausted")

            def _search_keywords_combined_from_listing(self, *, keywords, date, categories, max_results):
                return [fallback_candidate], 1

        candidates, total = FakeClient(budget_seconds=90, api_search_budget_seconds=1).search_keywords_combined(
            keywords=["Agent"],
            date="2026-05-26",
            categories=["cs.AI"],
            max_results=5,
        )
        self.assertEqual(total, 1)
        self.assertEqual([candidate.arxiv_id for candidate in candidates], ["2605.00003"])

    def test_listing_fallback_returns_partial_candidates_when_abs_hydration_exhausts_budget(self):
        candidates = [
            self.make_candidate(f"2605.{index:05d}", f"Agent LLM Benchmark Paper {index}")
            for index in range(1, 31)
        ]

        class FakeClient(ArxivClient):
            def _fetch_listing_candidates(self, *, date, category):
                return candidates

            def hydrate_candidate_from_abs(self, candidate):
                raise RuntimeError("budget exhausted")

        selected, _ = FakeClient()._search_keywords_combined_from_listing(
            keywords=["Agent", "Agents", "LLM"],
            date="2026-05-26",
            categories=["cs.AI"],
            max_results=60,
        )
        self.assertEqual(len(selected), 30)
        self.assertEqual(selected[0].metadata_source, "arxiv-listing")
        self.assertEqual(selected[0].metadata_status, "partial")

    def test_listing_prefilter_prioritizes_agent_llm_titles(self):
        agent = self.make_candidate("2605.00004", "Privacy Benchmark for Multi-Agent LLM Systems")
        generic = self.make_candidate("2605.00005", "A General Optimization Method")

        self.assertGreater(
            listing_prefilter_score(agent, ["Agent", "Agents", "LLM"]),
            listing_prefilter_score(generic, ["Agent", "Agents", "LLM"]),
        )

    def make_candidate(self, paper_id: str, title: str) -> PaperCandidate:
        return PaperCandidate(
            arxiv_id=paper_id,
            version_id=f"{paper_id}v1",
            title=title,
            abstract="",
            authors=[],
            categories=["cs.AI"],
            primary_category="cs.AI",
            published="2026-05-26T00:00:00Z",
            updated="2026-05-26T00:00:00Z",
            abs_url=f"https://arxiv.org/abs/{paper_id}v1",
            pdf_url=f"https://arxiv.org/pdf/{paper_id}v1",
            priority_keyword="Agent",
            keyword_rank=1,
            query_total=0,
        )


if __name__ == "__main__":
    unittest.main()
