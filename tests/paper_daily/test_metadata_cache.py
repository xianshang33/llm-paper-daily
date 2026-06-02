import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from skill.paper_daily_import import add_paper_daily_path


add_paper_daily_path()

from paper_daily.metadata import (
    complete_candidates_metadata,
    metadata_is_complete,
    metadata_missing_fields,
    normalize_metadata_payload,
)
from paper_daily.models import PaperCandidate


class MetadataCacheTest(unittest.TestCase):
    def test_metadata_completeness(self):
        payload = normalize_metadata_payload({
            "arxiv_id": "2605.00001",
            "version_id": "2605.00001v1",
            "title": "Example",
            "authors": ["A"],
            "abstract": "B",
            "published": "2026-05-26T00:00:00Z",
            "updated": "2026-05-26T00:00:00Z",
            "categories": ["cs.AI"],
            "primary_category": "cs.AI",
            "abs_url": "https://arxiv.org/abs/2605.00001v1",
            "pdf_url": "https://arxiv.org/pdf/2605.00001v1",
        }, source="arxiv-api", status="complete")
        self.assertTrue(metadata_is_complete(payload))
        self.assertEqual(metadata_missing_fields(payload), [])

    def test_complete_candidates_metadata_uses_api_then_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            client = Mock()
            client.get_by_arxiv_ids.return_value = [
                PaperCandidate(
                    arxiv_id="2605.00001",
                    version_id="2605.00001v1",
                    title="Example",
                    abstract="Abstract",
                    authors=["A"],
                    categories=["cs.AI"],
                    primary_category="cs.AI",
                    published="2026-05-26T00:00:00Z",
                    updated="2026-05-26T00:00:00Z",
                    abs_url="https://arxiv.org/abs/2605.00001v1",
                    pdf_url="https://arxiv.org/pdf/2605.00001v1",
                    priority_keyword="Agent",
                    keyword_rank=1,
                    query_total=1,
                )
            ]

            candidates = [{
                "arxiv_id": "2605.00001",
                "version_id": "2605.00001",
                "title": "stub",
                "abstract": "",
                "authors": [],
                "categories": [],
                "primary_category": None,
                "published": "",
                "updated": "",
                "abs_url": "https://arxiv.org/abs/2605.00001",
                "pdf_url": "https://arxiv.org/pdf/2605.00001",
                "priority_keyword": "Agent",
                "keyword_rank": 1,
                "query_total": 0,
            }]

            completed = complete_candidates_metadata(candidates, client=client, metadata_artifact_dir=artifact_dir)
            self.assertEqual(completed[0]["metadata_source"], "arxiv-api")
            self.assertTrue((artifact_dir / "2605.00001.json").exists())

            client.get_by_arxiv_ids.reset_mock()
            completed_again = complete_candidates_metadata(candidates, client=client, metadata_artifact_dir=artifact_dir)
            self.assertEqual(completed_again[0]["metadata_source"], "arxiv-api")
            client.get_by_arxiv_ids.assert_not_called()


if __name__ == "__main__":
    unittest.main()
