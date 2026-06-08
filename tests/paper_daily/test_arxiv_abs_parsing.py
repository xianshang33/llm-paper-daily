import unittest

from skill.paper_daily_import import add_paper_daily_path


add_paper_daily_path()

from paper_daily.arxiv_client import ArxivClient, parse_abs_authors, parse_abs_submission_dates, parse_abs_title
from paper_daily.models import PaperCandidate


ABS_HTML = """
<h1 class="title mathjax"><span class="descriptor">Title:</span>UModel: An Agent-Ready Observability Method</h1>
<div class="authors"><span class="descriptor">Authors:</span><a>Alice</a>, <a>Bob</a></div>
<div class="submission-history">
  <h2>Submission history</h2>
  <strong>[v1]</strong> Tue, 26 May 2026 09:54:53 UTC<br/>
  <strong>[v2]</strong> Wed, 27 May 2026 10:00:00 UTC<br/>
</div>
"""


class ArxivAbsParsingTest(unittest.TestCase):
    def test_parse_abs_authors(self):
        self.assertEqual(parse_abs_authors(ABS_HTML), ["Alice", "Bob"])

    def test_parse_abs_title(self):
        self.assertEqual(parse_abs_title(ABS_HTML), "UModel: An Agent-Ready Observability Method")

    def test_parse_abs_title_missing_returns_empty(self):
        self.assertEqual(parse_abs_title("<div>no title here</div>"), "")

    def test_hydrate_prefers_parsed_title_over_placeholder(self):
        client = ArxivClient()
        client._fetch_url = lambda url, *, min_delay: ABS_HTML.encode("utf-8")
        placeholder = PaperCandidate(
            arxiv_id="2606.04799",
            version_id="2606.04799",
            title="2606.04799",  # bare-id placeholder from the --arxiv-id path
            abstract="",
            authors=[],
            categories=[],
            primary_category=None,
            published="",
            updated="",
            abs_url="https://arxiv.org/abs/2606.04799",
            pdf_url="https://arxiv.org/pdf/2606.04799",
            priority_keyword="Agent",
            keyword_rank=1,
            query_total=0,
        )
        enriched = client.hydrate_candidate_from_abs(placeholder)
        self.assertEqual(enriched.title, "UModel: An Agent-Ready Observability Method")

    def test_parse_abs_submission_dates(self):
        published, updated = parse_abs_submission_dates(
            ABS_HTML,
            fallback_published="",
            fallback_updated="",
        )
        self.assertEqual(published, "2026-05-26T09:54:53Z")
        self.assertEqual(updated, "2026-05-27T10:00:00Z")


if __name__ == "__main__":
    unittest.main()
