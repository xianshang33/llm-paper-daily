import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skill.paper_daily_import import add_paper_daily_path


add_paper_daily_path()

from paper_daily.metadata import normalize_metadata_payload, write_metadata_payload
from paper_daily.run_state import record_candidate_run
from prepare_missing_summary_requests import main as missing_summary_main


class MissingSummaryRequestsTest(unittest.TestCase):
    def test_prepares_only_missing_summary_requests_from_run_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            candidate = {
                "arxiv_id": "2605.00001",
                "version_id": "2605.00001v1",
                "title": "Agent Paper",
                "abstract": "An LLM agent paper.",
                "authors": ["A"],
                "categories": ["cs.AI"],
                "primary_category": "cs.AI",
                "published": "2026-05-26T00:00:00Z",
                "updated": "2026-05-26T00:00:00Z",
                "abs_url": "https://arxiv.org/abs/2605.00001v1",
                "pdf_url": "https://arxiv.org/pdf/2605.00001v1",
                "priority_keyword": "Agent",
                "keyword_rank": 1,
                "query_total": 10,
            }
            record_candidate_run(
                repo_root,
                date="2026-05-26",
                selected=[candidate],
                preferred_date="2026-05-26",
                attempted_dates=["2026-05-26"],
            )
            write_metadata_payload(
                repo_root / "data" / "paper-daily" / "metadata-cache",
                normalize_metadata_payload(candidate, source="arxiv-api", status="complete"),
            )

            argv = ["prepare_missing_summary_requests.py", "--repo-root", str(repo_root), "--date", "2026-05-26"]
            stdout = io.StringIO()
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
                exit_code = missing_summary_main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertEqual(payload["missing_summary_ids"], ["2605.00001"])
            self.assertEqual(payload["requests"][0]["paper"]["title"], "Agent Paper")

    def test_blocks_summary_request_when_metadata_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            candidate = {
                "arxiv_id": "2605.00002",
                "version_id": "2605.00002v1",
                "title": "Agent Paper",
                "abstract": "An LLM agent paper.",
                "authors": ["A"],
                "categories": ["cs.AI"],
                "primary_category": "cs.AI",
                "published": "2026-05-26T00:00:00Z",
                "updated": "2026-05-26T00:00:00Z",
                "abs_url": "https://arxiv.org/abs/2605.00002v1",
                "pdf_url": "https://arxiv.org/pdf/2605.00002v1",
                "priority_keyword": "Agent",
                "keyword_rank": 1,
                "query_total": 10,
            }
            record_candidate_run(
                repo_root,
                date="2026-05-26",
                selected=[candidate],
                preferred_date="2026-05-26",
                attempted_dates=["2026-05-26"],
            )

            argv = ["prepare_missing_summary_requests.py", "--repo-root", str(repo_root), "--date", "2026-05-26"]
            stdout = io.StringIO()
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
                exit_code = missing_summary_main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["blocked_metadata_ids"], ["2605.00002"])
            self.assertEqual(payload["requests"], [])


if __name__ == "__main__":
    unittest.main()
