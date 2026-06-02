import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from skill.paper_daily_import import add_paper_daily_path


add_paper_daily_path()

from paper_daily.local_metadata import load_local_candidate_payload
from run_daily import resolve_manual_candidates


class LocalMetadataFallbackTest(unittest.TestCase):
    def test_load_local_candidate_payload_reads_cached_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            output_dir = repo_root / "skill" / "paper-daily" / "output"
            output_dir.mkdir(parents=True)
            payload = {
                "date": "2026-05-19",
                "ranked": [
                    {
                        "arxiv_id": "2605.12345",
                        "version_id": "2605.12345v1",
                        "title": "Cached Candidate",
                        "abstract": "From discovery cache.",
                        "authors": ["A Author"],
                        "categories": ["cs.AI"],
                        "primary_category": "cs.AI",
                        "published": "2026-05-19T00:00:00Z",
                        "updated": "2026-05-19T00:00:00Z",
                        "abs_url": "http://arxiv.org/abs/2605.12345v1",
                        "pdf_url": "https://arxiv.org/pdf/2605.12345v1",
                        "priority_keyword": "Agent",
                        "keyword_rank": 1,
                        "query_total": 1,
                        "institution_matches": [],
                        "lab_matches": [],
                        "score": 9.0,
                        "reasons": ["cached"],
                    }
                ],
            }
            (output_dir / "discovered-2026-05-19.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            candidate = load_local_candidate_payload(repo_root, "2605.12345")

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["title"], "Cached Candidate")
        self.assertEqual(candidate["abstract"], "From discovery cache.")

    def test_resolve_manual_candidates_falls_back_to_org_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            org_dir = repo_root / "data" / "paper-learning" / "deep-reading-org"
            org_dir.mkdir(parents=True)
            (org_dir / "arxiv_2605.54321.org").write_text(
                "\n".join([
                    "#+title: note title",
                    "#+subtitle: Actual Paper Title",
                    "#+authors: Alice, Bob",
                    "#+source: http://arxiv.org/abs/2605.54321v1",
                ]),
                encoding="utf-8",
            )

            client = Mock()
            client.get_by_arxiv_ids.side_effect = RuntimeError("arxiv unavailable")

            candidates = resolve_manual_candidates(
                client=client,
                repo_root=repo_root,
                arxiv_ids=["2605.54321"],
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "Actual Paper Title")
        self.assertEqual(candidates[0].authors, ["Alice", "Bob"])
        self.assertEqual(candidates[0].abs_url, "http://arxiv.org/abs/2605.54321v1")


if __name__ == "__main__":
    unittest.main()
