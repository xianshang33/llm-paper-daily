import unittest
from unittest.mock import patch

from skill.paper_daily_import import add_paper_daily_path


add_paper_daily_path()

from paper_daily.agent_reach_fallback import AgentReachFallback, parse_arxiv_ids_from_text
from paper_daily.arxiv_client import ArxivClient
from paper_daily.models import PaperCandidate


EXA_OUTPUT = """
Title: A Practical Multi-Agent LLM Benchmark
URL: https://arxiv.org/abs/2605.12345v2
Published: 2026-05-26T00:00:00.000Z

Title: Duplicate PDF Link
URL: https://arxiv.org/pdf/2605.12345v2

Title: Another Agent Paper
URL: https://arxiv.org/abs/2605.23456
"""


class AgentReachFallbackTest(unittest.TestCase):
    def test_parse_arxiv_ids_from_exa_text(self):
        self.assertEqual(parse_arxiv_ids_from_text(EXA_OUTPUT), ["2605.12345", "2605.23456"])

    @patch("paper_daily.agent_reach_fallback.subprocess.run")
    def test_search_returns_partial_candidates_from_exa_results(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = EXA_OUTPUT
        run.return_value.stderr = ""

        fallback = AgentReachFallback(timeout_seconds=5)
        candidates = fallback.search(
            keywords=["Agent", "LLM"],
            date="2026-05-26",
            categories=["cs.AI"],
            max_results=10,
        )

        self.assertEqual([candidate.arxiv_id for candidate in candidates], ["2605.12345", "2605.23456"])
        self.assertEqual(candidates[0].metadata_source, "agent-reach-exa")
        self.assertEqual(candidates[0].metadata_status, "partial")
        self.assertIn("site:arxiv.org", " ".join(run.call_args.args[0]))

    def test_combined_search_uses_agent_reach_when_api_returns_zero(self):
        fallback_candidate = self.make_candidate("2605.34567", "Fallback Agent Paper")

        class FakeClient(ArxivClient):
            def _fetch(self, params):
                return self._empty_feed()

            def _search_keywords_combined_from_listing(self, *, keywords, date, categories, max_results):
                return [], 0

            def _search_keywords_combined_from_agent_reach(self, *, keywords, date, categories, max_results):
                return [fallback_candidate], 1

            def _empty_feed(self):
                import xml.etree.ElementTree as ET

                return ET.fromstring(
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <feed xmlns="http://www.w3.org/2005/Atom"
                          xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
                      <opensearch:totalResults>0</opensearch:totalResults>
                    </feed>"""
                )

        candidates, total = FakeClient(enable_agent_reach_fallback=True).search_keywords_combined(
            keywords=["Agent", "LLM"],
            date="2026-05-26",
            categories=["cs.AI"],
            max_results=5,
        )

        self.assertEqual(total, 1)
        self.assertEqual([candidate.arxiv_id for candidate in candidates], ["2605.34567"])

    def test_agent_reach_results_must_match_submitted_date_after_hydration(self):
        stale = self.make_candidate("2605.00001", "Stale Agent Paper")
        stale.published = "2026-05-25T23:00:00Z"
        fresh = self.make_candidate("2605.00002", "Fresh Agent Paper")

        class FakeClient(ArxivClient):
            def _fetch(self, params):
                raise RuntimeError("api failed")

            def _search_keywords_combined_from_listing(self, *, keywords, date, categories, max_results):
                return [], 0

            def hydrate_candidate_from_abs(self, candidate):
                if candidate.arxiv_id == "2605.00001":
                    return stale
                return fresh

        with patch("paper_daily.agent_reach_fallback.AgentReachFallback.search", return_value=[stale, fresh]):
            candidates, total = FakeClient(enable_agent_reach_fallback=True).search_keywords_combined(
                keywords=["Agent", "LLM"],
                date="2026-05-26",
                categories=["cs.AI"],
                max_results=5,
            )

        self.assertEqual(total, 1)
        self.assertEqual([candidate.arxiv_id for candidate in candidates], ["2605.00002"])

    def test_api_failure_with_empty_fallbacks_returns_empty_listing_result(self):
        class FakeClient(ArxivClient):
            def _fetch(self, params):
                raise RuntimeError("api failed")

            def _search_keywords_combined_from_listing(self, *, keywords, date, categories, max_results):
                return [], 12

            def _search_keywords_combined_from_agent_reach(self, *, keywords, date, categories, max_results):
                return [], 0

        candidates, total = FakeClient(enable_agent_reach_fallback=True).search_keywords_combined(
            keywords=["Agent", "LLM"],
            date="2026-05-26",
            categories=["cs.AI"],
            max_results=5,
        )

        self.assertEqual(candidates, [])
        self.assertEqual(total, 0)

    def test_disable_agent_reach_fallback_leaves_zero_result_unchanged(self):
        class FakeClient(ArxivClient):
            def _fetch(self, params):
                import xml.etree.ElementTree as ET

                return ET.fromstring(
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <feed xmlns="http://www.w3.org/2005/Atom"
                          xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
                      <opensearch:totalResults>0</opensearch:totalResults>
                    </feed>"""
                )

        with patch("paper_daily.agent_reach_fallback.AgentReachFallback.search") as search:
            candidates, total = FakeClient(enable_agent_reach_fallback=False).search_keywords_combined(
                keywords=["Agent", "LLM"],
                date="2026-05-26",
                categories=["cs.AI"],
                max_results=5,
            )

        search.assert_not_called()
        self.assertEqual(total, 0)
        self.assertEqual(candidates, [])

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
