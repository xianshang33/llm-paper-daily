import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skill" / "paper-learning" / "scripts" / "process_notion_queue.py"


class ProcessNotionQueueScriptTest(unittest.TestCase):
    def test_process_queue_uses_configured_deep_reading_provider(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("get_deep_reading_provider", text)
        self.assertIn("provider.read", text)

    def test_selected_papers_json_requires_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            selected_path = root / "selected-papers.json"
            selected_path.write_text(json.dumps({"selected_papers": []}), encoding="utf-8")

            result = subprocess.run(
                ["python3", str(SCRIPT), "--config", str(config_path), "--selected-papers-json", str(selected_path)],
                capture_output=True,
                text=True,
                cwd=ROOT,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["message"], "--selected-papers-json is rehearsal-only and requires --dry-run.")

    def test_unconfirmed_deep_reading_request_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            request_path = root / "deep-reading-request.json"
            request_path.write_text(json.dumps({
                "date": "2026-05-20",
                "selector_type": "notion_selected_set",
                "candidate_source": "notion_selected",
                "resolved_paper_ids": ["arxiv:2605.00001"],
                "human_instruction": "Focus on evals",
                "trigger_source": "chat_manual",
                "requires_confirmation": True,
                "confirmed": False,
                "selected_papers": [
                    {
                        "notion_page_id": "page-1",
                        "record": {
                            "paper_id": "arxiv:2605.00001",
                            "source": "arXiv",
                            "title": "Paper 1",
                            "authors": [],
                            "institutions": "",
                            "abstract": "",
                            "digest_summary": "Digest",
                            "summary_cn": "",
                            "summary_en": "",
                            "published_date": "2026-05-20",
                            "run_date": "2026-05-20",
                            "url": "https://arxiv.org/abs/2605.00001",
                            "pdf_url": None,
                            "topic": "",
                            "score": 0.0,
                            "signals": {},
                            "provenance": {},
                        },
                        "human_instruction": "Focus on evals",
                        "existing_research_area_ids": [],
                        "existing_deep_note_id": None,
                    }
                ],
            }), encoding="utf-8")

            result = subprocess.run(
                ["python3", str(SCRIPT), "--config", str(config_path), "--deep-reading-request-json", str(request_path)],
                capture_output=True,
                text=True,
                cwd=ROOT,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["message"], "deep-reading request requires confirmation before execution")
        self.assertEqual(payload["data"]["candidates"][0]["paper_id"], "arxiv:2605.00001")

    def test_existing_deep_note_does_not_require_org_artifact_when_not_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            request_path = root / "deep-reading-request.json"
            request_path.write_text(json.dumps({
                "date": "2026-05-20",
                "selector_type": "explicit_paper_ids",
                "candidate_source": "chat_explicit",
                "resolved_paper_ids": ["arxiv:2605.00001"],
                "human_instruction": "",
                "trigger_source": "chat_manual",
                "requires_confirmation": False,
                "confirmed": False,
                "selected_papers": [
                    {
                        "notion_page_id": "page-1",
                        "record": {
                            "paper_id": "arxiv:2605.00001",
                            "source": "arXiv",
                            "title": "Paper 1",
                            "authors": [],
                            "institutions": "",
                            "abstract": "",
                            "digest_summary": "Digest",
                            "summary_cn": "",
                            "summary_en": "",
                            "published_date": "2026-05-20",
                            "run_date": "2026-05-20",
                            "url": "https://arxiv.org/abs/2605.00001",
                            "pdf_url": None,
                            "topic": "",
                            "score": 0.0,
                            "signals": {},
                            "provenance": {},
                        },
                        "human_instruction": "",
                        "existing_research_area_ids": [],
                        "existing_deep_note_id": "note-1",
                    }
                ],
            }), encoding="utf-8")

            result = subprocess.run(
                ["python3", str(SCRIPT), "--config", str(config_path), "--deep-reading-request-json", str(request_path), "--dry-run"],
                capture_output=True,
                text=True,
                cwd=ROOT,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["data"]["processed"], [{"paper_id": "arxiv:2605.00001", "status": "skipped_existing_deep_note"}])

    def test_deep_reading_request_date_is_used_when_live_record_lacks_run_date(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("request.date", text)
        self.assertIn("date=_queue_date(selected, fallback=request_date)", text)


def _write_config(root: Path) -> Path:
    config_path = root / "config.json"
    config_path.write_text(json.dumps({
        "paper_daily": {"repo_root": str(ROOT)},
        "notion": {"dry_run": True},
        "feishu": {"dry_run": True},
        "runtime": {"artifact_dir": str(root / "runs"), "dry_run": True},
        "deep_reading": {"mode": "org_artifact", "org_artifact_dir": str(root / "org")},
        "classification": {"default_research_areas_path": str(ROOT / "skill" / "paper-learning" / "references" / "research_areas.example.json")},
    }), encoding="utf-8")
    return config_path


if __name__ == "__main__":
    unittest.main()
