import tempfile
import unittest
from pathlib import Path

from skill.paper_learning_import import add_paper_learning_path


add_paper_learning_path()

from paper_learning.config import DeepReadingConfig
from paper_learning.deep_reading_providers import get_deep_reading_provider
from paper_learning.models import DailyPaperRecord, SelectedPaper


class DeepReadingProviderTest(unittest.TestCase):
    def test_get_default_provider(self):
        provider = get_deep_reading_provider(
            DeepReadingConfig(
                provider="ljg-paper-org",
                mode="org_artifact",
                org_artifact_dir=Path("data/org"),
            )
        )

        self.assertEqual(provider.name, "ljg-paper-org")

    def test_ljg_provider_reports_missing_artifact(self):
        paper = SelectedPaper(notion_page_id="page-1", record=_sample_record(), human_instruction="")
        provider = get_deep_reading_provider(
            DeepReadingConfig(
                provider="ljg-paper-org",
                mode="org_artifact",
                org_artifact_dir=Path("missing"),
            )
        )

        result = provider.check_ready([paper])[0]

        self.assertFalse(result["ok"])
        self.assertEqual(result["paper_id"], "arxiv:2605.00001")
        self.assertIn("missing", result["path"])

    def test_ljg_provider_reads_artifact(self):
        paper = SelectedPaper(notion_page_id="page-1", record=_sample_record(), human_instruction="Focus")
        with tempfile.TemporaryDirectory() as tmp:
            cfg = DeepReadingConfig(
                provider="ljg-paper-org",
                mode="org_artifact",
                org_artifact_dir=Path(tmp),
            )
            provider = get_deep_reading_provider(cfg)
            path = provider.artifact_path(paper.record.paper_id)
            path.write_text(_sample_org(), encoding="utf-8")

            note = provider.read(paper)

        self.assertEqual(note.paper_id, "arxiv:2605.00001")
        self.assertEqual(note.reading_focus, "Focus")
        self.assertIn("## 问题", note.markdown)
        self.assertEqual(note.extra_properties["deep_reading_provider"], "ljg-paper-org")

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported deep reading provider"):
            get_deep_reading_provider(
                DeepReadingConfig(
                    provider="unknown",
                    mode="org_artifact",
                    org_artifact_dir=Path("data/org"),
                )
            )


def _sample_record() -> DailyPaperRecord:
    return DailyPaperRecord(
        paper_id="arxiv:2605.00001",
        source="arXiv",
        title="Agentic RL",
        authors=["Alice"],
        institutions="",
        abstract="Agentic RL paper",
        digest_summary="Digest",
        summary_cn="",
        summary_en="",
        published_date="2026-05-20",
        run_date="2026-05-20",
        url="https://arxiv.org/abs/2605.00001",
        pdf_url=None,
        topic="Agent RL",
        score=0,
        signals={},
        provenance={},
    )


def _sample_org() -> str:
    return (
        "#+title: Agentic RL\n\n"
        "* 问题\n\nbody\n\n"
        "* 翻译\n\nbody\n\n"
        "* 核心概念\n\nbody\n\n"
        "* 洞见\n\nbody\n\n"
        "* 博导审稿\n\nbody\n\n"
        "* 启发\n\nbody\n"
    )


if __name__ == "__main__":
    unittest.main()
