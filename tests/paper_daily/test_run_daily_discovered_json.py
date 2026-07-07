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

from run_daily import main as run_daily_main


class RunDailyDiscoveredJsonTest(unittest.TestCase):
    def test_run_daily_consumes_discovered_json_without_manual_context_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            discovered_path = repo_root / "discovered.json"
            discovered_path.write_text(json.dumps({
                "date": "2026-05-26",
                "ranked": [{
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
                    "score": 10.0,
                    "reasons": ["keyword:Agent"],
                }],
            }), encoding="utf-8")

            argv = [
                "run_daily.py",
                "--repo-root", str(repo_root),
                "--date", "2026-05-26",
                "--discovered-json", str(discovered_path),
                "--view-only",
            ]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                exit_code = run_daily_main()

            self.assertEqual(exit_code, 0)
            state = json.loads((repo_root / "data" / "paper-daily" / "runs" / "2026-05-26.json").read_text(encoding="utf-8"))
            self.assertEqual(state["selected"][0]["priority_keyword"], "Agent")
            self.assertEqual(state["attempted_dates"], ["2026-05-26"])

    def test_discovered_json_partial_candidates_are_pool_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            discovered_path = repo_root / "discovered.json"
            discovered_path.write_text(json.dumps({
                "date": "2026-05-26",
                "candidate_pool": [{
                    "arxiv_id": "2605.00002",
                    "version_id": "2605.00002v1",
                    "title": "Agent Listing Paper",
                    "abstract": "",
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
                    "score": 10.0,
                    "metadata_source": "arxiv-listing",
                    "metadata_status": "partial",
                }],
            }), encoding="utf-8")

            argv = [
                "run_daily.py",
                "--repo-root", str(repo_root),
                "--date", "2026-05-26",
                "--discovered-json", str(discovered_path),
                "--view-only",
            ]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                exit_code = run_daily_main()

            self.assertEqual(exit_code, 0)
            state = json.loads((repo_root / "data" / "paper-daily" / "runs" / "2026-05-26.json").read_text(encoding="utf-8"))
            self.assertEqual(state["selected"], [])
            self.assertEqual(state["candidate_pool"][0]["arxiv_id"], "2605.00002")
            queue = json.loads((repo_root / "data" / "paper-daily" / "pending-metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(queue["tasks"][0]["paper_id"], "2605.00002")

    def test_complete_discovered_json_candidates_seed_metadata_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            metadata_dir = repo_root / "fresh-metadata"
            discovered_path = repo_root / "discovered.json"
            discovered_path.write_text(json.dumps({
                "date": "2026-05-26",
                "ranked": [{
                    "arxiv_id": "2605.00003",
                    "version_id": "2605.00003v1",
                    "title": "Fresh Agent Paper",
                    "abstract": "A complete LLM agent paper.",
                    "authors": ["A"],
                    "categories": ["cs.AI"],
                    "primary_category": "cs.AI",
                    "published": "2026-05-26T00:00:00Z",
                    "updated": "2026-05-26T00:00:00Z",
                    "abs_url": "https://arxiv.org/abs/2605.00003v1",
                    "pdf_url": "https://arxiv.org/pdf/2605.00003v1",
                    "priority_keyword": "Agent",
                    "keyword_rank": 1,
                    "query_total": 10,
                    "score": 10.0,
                    "reasons": ["keyword:Agent"],
                }],
            }), encoding="utf-8")

            argv = [
                "run_daily.py",
                "--repo-root", str(repo_root),
                "--date", "2026-05-26",
                "--discovered-json", str(discovered_path),
                "--metadata-artifact-dir", str(metadata_dir),
                "--view-only",
            ]
            stdout = io.StringIO()
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
                exit_code = run_daily_main()

            self.assertEqual(exit_code, 0)
            self.assertTrue((metadata_dir / "2605.00003.json").exists())
            self.assertNotIn("blocking_metadata=2605.00003", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
