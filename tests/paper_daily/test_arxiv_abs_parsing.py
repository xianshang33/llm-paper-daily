import unittest

from skill.paper_daily_import import add_paper_daily_path


add_paper_daily_path()

from paper_daily.arxiv_client import parse_abs_authors, parse_abs_submission_dates


ABS_HTML = """
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
