import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from skill.paper_learning_import import add_paper_learning_path


add_paper_learning_path()

from paper_learning.config import PaperDailyConfig
from paper_learning.paper_daily_adapter import (
    _assert_discovery_succeeded,
    _bilingual_digest,
    _condense_subprocess_error,
    load_discovered_records,
    load_paper_daily_records,
    run_paper_daily,
    prepare_paper_daily_summary_requests,
)


ROOT = Path(__file__).resolve().parents[2]


class PaperDailyAdapterTest(unittest.TestCase):
    def test_load_paper_daily_records_merges_canonical_and_discovery_signals(self):
        records = load_paper_daily_records(
            canonical_path=ROOT / "tests/paper_learning/fixtures/canonical-papers.json",
            discovered_path=ROOT / "tests/paper_learning/fixtures/discovered-papers.json",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].paper_id, "arxiv:2605.00001")
        self.assertEqual(records[0].source, "arXiv")
        self.assertEqual(records[0].institutions, "Example AI Lab")
        self.assertEqual(records[0].score, 8.5)
        self.assertEqual(records[0].signals["priority_keyword"], "Agent")

    def test_load_paper_daily_records_digest_summary_is_bilingual(self):
        records = load_paper_daily_records(
            canonical_path=ROOT / "tests/paper_learning/fixtures/canonical-papers.json",
        )

        digest = records[0].digest_summary
        self.assertIn("这是一篇关于 Agent RL 的论文", digest)
        self.assertIn("This paper studies Agent RL", digest)

    def test_bilingual_digest_strips_institution_prefix_from_each_part(self):
        cn = "机构: Example Lab<br>这是中文摘要。"
        en = "Institution: Example Lab<br>This is the English summary."
        result = _bilingual_digest(cn, en)
        self.assertNotIn("机构:", result)
        self.assertNotIn("Institution:", result)
        self.assertIn("这是中文摘要", result)
        self.assertIn("This is the English summary", result)

    def test_bilingual_digest_handles_missing_en(self):
        result = _bilingual_digest("只有中文。", "")
        self.assertEqual(result, "只有中文。")

    def test_bilingual_digest_handles_missing_cn(self):
        result = _bilingual_digest("", "English only.")
        self.assertEqual(result, "English only.")

    def test_load_discovered_records_supports_summary_free_pipeline(self):
        records = load_discovered_records(
            ROOT / "tests/paper_learning/fixtures/discovered-papers.json",
            run_date="2026-05-19",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].paper_id, "arxiv:2605.00001")
        self.assertEqual(records[0].source, "arXiv")
        self.assertEqual(records[0].digest_summary, records[0].abstract)
        self.assertEqual(records[0].summary_cn, "")
        self.assertEqual(records[0].provenance["summary"], "not_generated")

    def test_discovery_error_artifact_fails_before_fallback_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "discovered.json"
            path.write_text(json.dumps({
                "query_totals": {"combined:Agent,Agents,LLM": "ERROR:RuntimeError:network"},
                "selected": [],
            }), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "paper-daily discovery failed"):
                _assert_discovery_succeeded(path)

    def test_prepare_paper_daily_summary_requests_writes_run_artifact_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            expected = repo_root / "data" / "paper-learning" / "runs" / "2026-05-19" / "paper-daily-summary-requests.json"
            expected.parent.mkdir(parents=True, exist_ok=True)
            expected.write_text(json.dumps({"mode": "paper-daily-summary-artifact", "requests": []}), encoding="utf-8")

            cfg = PaperDailyConfig(repo_root=repo_root)
            with patch("paper_learning.paper_daily_adapter._run_command") as mocked:
                path = prepare_paper_daily_summary_requests("2026-05-19", cfg, select_override=3)

            self.assertEqual(path, expected)
            mocked.assert_called_once()
            self.assertIn("--select", mocked.call_args.args[0])
            self.assertIn("3", mocked.call_args.args[0])

    def test_condense_subprocess_error_prefers_terminal_exception_line(self):
        detail = "\n".join([
            "Traceback (most recent call last):",
            "  File \"x.py\", line 1, in <module>",
            "FileNotFoundError: Missing summary artifact for 2605.19932",
        ])
        self.assertEqual(
            _condense_subprocess_error(detail),
            "FileNotFoundError: Missing summary artifact for 2605.19932",
        )

    def test_run_paper_daily_passes_discovered_json_to_generate_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            discovered = repo_root / "data" / "paper-learning" / "runs" / "2026-05-19" / "discovered-papers.json"
            discovered.parent.mkdir(parents=True, exist_ok=True)
            discovered.write_text(json.dumps({
                "date": "2026-05-19",
                "query_totals": {"combined:Agent,Agents,LLM": 1},
                "selected": [],
                "ranked": [],
            }), encoding="utf-8")
            cfg = PaperDailyConfig(repo_root=repo_root)
            with patch("paper_learning.paper_daily_adapter._run_command") as mocked:
                run_paper_daily("2026-05-19", cfg, select_override=3)

            self.assertEqual(mocked.call_count, 2)
            second_call_args = mocked.call_args_list[1].args[0]
            self.assertIn("--discovered-json", second_call_args)
            self.assertIn(str(discovered), second_call_args)


if __name__ == "__main__":
    unittest.main()
