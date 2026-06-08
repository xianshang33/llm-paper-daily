import unittest
from dataclasses import replace

from skill.paper_learning_import import add_paper_learning_path


add_paper_learning_path()

from paper_learning.config import NotionConfig
from paper_learning.models import DeepNote, DailyPaperRecord, SelectedPaper
from paper_learning.notion_client import (
    NotionClient,
    _normalize_arxiv_url,
    markdown_to_blocks,
    selected_paper_from_page,
)


class NormalizeArxivUrlTest(unittest.TestCase):
    def test_http_versioned_and_https_bare_collapse_to_same_key(self):
        # The two producer paths historically emitted these two forms; dedup must
        # treat them as the same paper to avoid duplicate Notion pages.
        a = _normalize_arxiv_url("http://arxiv.org/abs/2606.05037v1")
        b = _normalize_arxiv_url("https://arxiv.org/abs/2606.05037")
        self.assertEqual(a, b)
        self.assertEqual(a, "https://arxiv.org/abs/2606.05037")

    def test_empty_url_passthrough(self):
        self.assertEqual(_normalize_arxiv_url(""), "")


def sample_record() -> DailyPaperRecord:
    return DailyPaperRecord(
        paper_id="arxiv:2605.00001",
        source="arXiv",
        title="Agentic RL",
        authors=["A. Author"],
        institutions="Example AI Lab",
        abstract="Abstract",
        digest_summary="Digest",
        summary_cn="中文摘要",
        summary_en="English summary",
        published_date="2026-05-20",
        run_date="2026-05-20",
        url="https://arxiv.org/abs/2605.00001",
        pdf_url="https://arxiv.org/pdf/2605.00001",
        topic="Agent",
        score=8.5,
        signals={},
        provenance={},
    )


class NotionClientTest(unittest.TestCase):
    def test_build_paper_properties(self):
        client = NotionClient(NotionConfig(dry_run=True, paper_inbox_database_id="db"))

        props = client.build_paper_properties(sample_record())

        self.assertEqual(props["Title"]["title"][0]["text"]["content"], "Agentic RL")
        self.assertEqual(props["Status"]["status"]["name"], "New")
        self.assertEqual(props["Institutions"]["rich_text"][0]["text"]["content"], "Example AI Lab")
        self.assertEqual(props["URL"]["url"], "https://arxiv.org/abs/2605.00001")
        self.assertNotIn("Paper ID", props)
        self.assertNotIn("PDF URL", props)
        self.assertNotIn("Authors", props)
        self.assertNotIn("Run Date", props)
        self.assertNotIn("Score", props)

    def test_build_paper_properties_passes_digest_summary_verbatim(self):
        # Institution-prefix stripping is done by the adapter (_bilingual_digest),
        # not here. The notion client writes whatever digest_summary it receives.
        client = NotionClient(NotionConfig(dry_run=True, paper_inbox_database_id="db"))
        record = replace(sample_record(), digest_summary="中文摘要\n\nEnglish summary")

        props = client.build_paper_properties(record)

        self.assertEqual(props["Digest Summary"]["rich_text"][0]["text"]["content"], "中文摘要\n\nEnglish summary")

    def test_build_paper_properties_can_omit_workflow_defaults_for_existing_pages(self):
        client = NotionClient(NotionConfig(dry_run=True, paper_inbox_database_id="db"))

        props = client.build_paper_properties(sample_record(), include_workflow_defaults=False)

        self.assertNotIn("Status", props)
        self.assertNotIn("Error", props)
        self.assertEqual(props["URL"]["url"], "https://arxiv.org/abs/2605.00001")

    def test_dry_run_upsert_returns_operation(self):
        client = NotionClient(NotionConfig(dry_run=True, paper_inbox_database_id="db"))

        result = client.upsert_paper(sample_record())

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.data["paper_id"], "arxiv:2605.00001")
        self.assertEqual(result.data["properties"]["URL"]["url"], "https://arxiv.org/abs/2605.00001")

    def test_markdown_to_blocks_maps_supported_lines(self):
        blocks = markdown_to_blocks("# Report\n\nOverview\n## Paper\n- Point")

        self.assertEqual([block["type"] for block in blocks], ["heading_1", "paragraph", "heading_2", "bulleted_list_item"])
        self.assertEqual(blocks[0]["heading_1"]["rich_text"][0]["text"]["content"], "Report")

    def test_markdown_to_blocks_handles_code_block(self):
        markdown = "Intro\n```text\n+----+\n| ab |\n+----+\n```\nAfter"

        blocks = markdown_to_blocks(markdown)

        types = [block["type"] for block in blocks]
        self.assertEqual(types, ["paragraph", "code", "paragraph"])
        code = blocks[1]["code"]
        self.assertEqual(code["rich_text"][0]["text"]["content"], "+----+\n| ab |\n+----+")
        self.assertEqual(code["language"], "plain text")

    def test_markdown_to_blocks_handles_h3_image_and_inline(self):
        markdown = "### Sub\n![](https://img.example/foo.png)\nText with **bold** and [link](https://x.example)"

        blocks = markdown_to_blocks(markdown)

        types = [block["type"] for block in blocks]
        self.assertEqual(types, ["heading_3", "image", "paragraph"])
        self.assertEqual(blocks[1]["image"]["external"]["url"], "https://img.example/foo.png")
        runs = blocks[2]["paragraph"]["rich_text"]
        self.assertEqual(runs[0]["text"]["content"], "Text with ")
        self.assertEqual(runs[1]["text"]["content"], "bold")
        self.assertTrue(runs[1]["annotations"]["bold"])
        self.assertEqual(runs[2]["text"]["content"], " and ")
        self.assertEqual(runs[3]["text"]["content"], "link")
        self.assertEqual(runs[3]["text"]["link"]["url"], "https://x.example")

    def test_create_deep_note_dry_run_ignores_metadata_extras(self):
        client = NotionClient(NotionConfig(dry_run=True, deep_notes_database_id="dn-db"))
        paper = SelectedPaper(notion_page_id="page-1", record=sample_record(), human_instruction="")
        note = DeepNote(
            title="学会反成枷锁",
            paper_id="arxiv:2605.00001",
            reading_focus="focus",
            markdown="## 问题\n\nbody",
            contribution_type="Method",
            method_tags=["Agent RL"],
            proposed_area="Agent RL",
            archive_confidence="High",
            extra_properties={
                "original_title": "Reinforcement Pre-Training",
                "authors": "A. Author",
                "venue": "arXiv 2026",
                "source_url": "https://arxiv.org/abs/2605.00001",
            },
        )

        result = client.create_deep_note(paper, note, ["area-1"])

        self.assertEqual(result.status, "dry_run_create")
        props = result.data["properties"]
        self.assertEqual(props["Title"]["title"][0]["text"]["content"], "学会反成枷锁")
        self.assertEqual(props["Method Tags"]["multi_select"], [{"name": "Agent RL"}])
        self.assertEqual(props["Research Areas"]["relation"], [{"id": "area-1"}])
        self.assertNotIn("Original Title", props)
        self.assertNotIn("Authors", props)
        self.assertNotIn("Venue", props)
        self.assertNotIn("Source URL", props)

    def test_create_deep_note_dry_run_omits_missing_extras(self):
        client = NotionClient(NotionConfig(dry_run=True, deep_notes_database_id="dn-db"))
        paper = SelectedPaper(notion_page_id="page-1", record=sample_record(), human_instruction="")
        note = DeepNote(
            title="t",
            paper_id="arxiv:2605.00001",
            reading_focus="",
            markdown="body",
            contribution_type="Method",
            method_tags=[],
            proposed_area="",
            archive_confidence="Medium",
        )

        result = client.create_deep_note(paper, note, [])

        props = result.data["properties"]
        self.assertNotIn("Original Title", props)
        self.assertNotIn("Authors", props)
        self.assertNotIn("Venue", props)
        self.assertNotIn("Source URL", props)

    def test_create_deep_note_dry_run_updates_existing_page(self):
        client = NotionClient(NotionConfig(dry_run=True, deep_notes_database_id="dn-db"))
        paper = SelectedPaper(
            notion_page_id="page-1",
            record=sample_record(),
            human_instruction="",
            existing_deep_note_id="note-123",
        )
        note = DeepNote(
            title="t",
            paper_id="arxiv:2605.00001",
            reading_focus="",
            markdown="## 问题\n\nbody",
            contribution_type="Method",
            method_tags=[],
            proposed_area="",
            archive_confidence="Medium",
        )

        result = client.create_deep_note(paper, note, [])

        self.assertEqual(result.status, "dry_run_update")
        self.assertEqual(result.data["page_id"], "note-123")
        self.assertEqual(result.data["children"][0]["type"], "heading_2")

    def test_selected_paper_from_page_parses_properties(self):
        page = {
            "id": "page-1",
            "properties": {
                "Title": {"title": [{"plain_text": "Agentic RL"}]},
                "Source": {"select": {"name": "arXiv"}},
                "Institutions": {"rich_text": [{"plain_text": "Example AI Lab"}]},
                "Digest Summary": {"rich_text": [{"plain_text": "Digest"}]},
                "Published Date": {"date": {"start": "2026-05-20"}},
                "URL": {"url": "https://arxiv.org/abs/2605.00001"},
                "Human Instruction": {"rich_text": [{"plain_text": "Focus on evals"}]},
                "Research Areas": {"relation": [{"id": "area-1"}]},
                "Deep Note": {"relation": [{"id": "note-1"}]},
            },
        }

        selected = selected_paper_from_page(page)

        self.assertEqual(selected.notion_page_id, "page-1")
        self.assertEqual(selected.record.paper_id, "arxiv:2605.00001")
        self.assertEqual(selected.record.authors, [])
        self.assertEqual(selected.human_instruction, "Focus on evals")
        self.assertEqual(selected.existing_research_area_ids, ["area-1"])
        self.assertEqual(selected.existing_deep_note_id, "note-1")

    def test_selected_paper_from_page_keeps_legacy_paper_id_when_present(self):
        page = {
            "id": "page-1",
            "properties": {
                "Title": {"title": [{"plain_text": "Agentic RL"}]},
                "Paper ID": {"rich_text": [{"plain_text": "legacy:id"}]},
                "Source": {"select": {"name": "arXiv"}},
                "URL": {"url": "https://arxiv.org/abs/2605.00001"},
            },
        }

        selected = selected_paper_from_page(page)

        self.assertEqual(selected.record.paper_id, "legacy:id")

    def test_selected_paper_from_page_normalizes_arxiv_version_from_url(self):
        page = {
            "id": "page-1",
            "properties": {
                "Title": {"title": [{"plain_text": "Agentic RL"}]},
                "Source": {"select": {"name": "arXiv"}},
                "URL": {"url": "http://arxiv.org/abs/2605.18747v1"},
            },
        }

        selected = selected_paper_from_page(page)

        self.assertEqual(selected.record.paper_id, "arxiv:2605.18747")


if __name__ == "__main__":
    unittest.main()
