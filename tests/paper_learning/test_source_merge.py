import unittest

from skill.paper_learning_import import add_paper_learning_path


add_paper_learning_path()

from paper_learning.models import DailyPaperRecord
from paper_learning.source_merge import merge_supplemental_records


class SourceMergeTest(unittest.TestCase):
    def test_hf_arxiv_duplicate_is_attached_as_signal(self):
        arxiv = _record("arxiv:2605.00001", source="arXiv")
        hf = _record("hf:2605.00001", source="HuggingFace")

        merged = merge_supplemental_records([arxiv], [hf])

        self.assertEqual([item.paper_id for item in merged], ["arxiv:2605.00001"])
        self.assertEqual(merged[0].signals["hf_duplicate"], True)
        self.assertEqual(merged[0].provenance["hf_url"], "https://huggingface.co/papers/2605.00001")

    def test_non_duplicate_hf_record_is_appended(self):
        arxiv = _record("arxiv:2605.00001", source="arXiv")
        hf = _record("hf:2605.00002", source="HuggingFace")

        merged = merge_supplemental_records([arxiv], [hf])

        self.assertEqual([item.paper_id for item in merged], ["arxiv:2605.00001", "hf:2605.00002"])


def _record(paper_id: str, source: str) -> DailyPaperRecord:
    clean = paper_id.split(":", 1)[1]
    return DailyPaperRecord(
        paper_id=paper_id,
        source=source,
        title=f"Paper {clean}",
        authors=[],
        institutions="",
        abstract="abstract",
        digest_summary="summary",
        summary_cn="",
        summary_en="summary",
        published_date="2026-05-20",
        run_date="2026-05-20",
        url=f"https://huggingface.co/papers/{clean}" if source == "HuggingFace" else f"https://arxiv.org/abs/{clean}",
        pdf_url=f"https://arxiv.org/pdf/{clean}",
        topic="Agent",
        score=1,
        signals={},
        provenance={},
    )


if __name__ == "__main__":
    unittest.main()
