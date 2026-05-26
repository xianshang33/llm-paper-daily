import json
import unittest
from pathlib import Path
from urllib.error import URLError

from skill.paper_learning_import import add_paper_learning_path


add_paper_learning_path()

from paper_learning.config import HuggingFaceConfig
from paper_learning.huggingface_client import fetch_hf_daily_papers_safe
from paper_learning.huggingface_client import normalize_hf_daily_papers


ROOT = Path(__file__).resolve().parents[2]


class HuggingFaceClientTest(unittest.TestCase):
    def test_normalize_hf_daily_papers(self):
        raw = json.loads((ROOT / "tests/paper_learning/fixtures/hf-daily-papers.json").read_text(encoding="utf-8"))

        records = normalize_hf_daily_papers(raw, run_date="2026-05-20")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].paper_id, "hf:2605.00002")
        self.assertEqual(records[0].source, "HuggingFace")
        self.assertEqual(records[0].url, "https://huggingface.co/papers/2605.00002")
        self.assertEqual(records[0].authors, ["C. Author"])

    def test_normalize_hf_daily_papers_skips_invalid_before_limit(self):
        raw = [
            {"paper": {"id": "", "title": "invalid"}},
            {"paper": {"id": "2605.00002", "title": "valid", "summary": "summary", "authors": []}},
        ]

        records = normalize_hf_daily_papers(raw, run_date="2026-05-20", limit=1)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].paper_id, "hf:2605.00002")

    def test_fetch_hf_daily_papers_safe_returns_warning_on_failure(self):
        def failing_fetch(date, cfg):
            raise URLError("network blocked")

        records, warnings = fetch_hf_daily_papers_safe("2026-05-20", HuggingFaceConfig(), fetcher=failing_fetch)

        self.assertEqual(records, [])
        self.assertEqual(warnings, ["Hugging Face daily papers unavailable: <urlopen error network blocked>"])


if __name__ == "__main__":
    unittest.main()
