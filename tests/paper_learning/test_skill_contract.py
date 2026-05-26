import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skill" / "paper-learning" / "SKILL.md"
CONFIG = ROOT / "skill" / "paper-learning" / "templates" / "config.example.json"
EVALS = ROOT / "skill" / "paper-learning" / "evals" / "evals.json"
FEISHU_RESEARCH = ROOT / "skill" / "paper-learning" / "references" / "feishu_notification_research.md"


class SkillContractTest(unittest.TestCase):
    def test_skill_doc_has_trigger_and_commands(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("name: paper-learning", text)
        self.assertIn("Notion", text)
        self.assertIn("Feishu", text)
        self.assertIn("run_daily_learning.py", text)
        self.assertIn("prepare_daily_learning_requests.py", text)
        self.assertIn("request_deep_reading.py", text)
        self.assertIn("confirm_deep_reading_request.py", text)
        self.assertIn("prepare_selected_papers.py", text)
        self.assertIn("prepare_queue_stage_requests.py", text)
        self.assertIn("check_pipeline_readiness.py", text)
        self.assertIn("rehearse_pipeline.py", text)
        self.assertIn("process_notion_queue.py", text)

    def test_config_and_evals_exist(self):
        self.assertTrue(CONFIG.exists())
        self.assertTrue(EVALS.exists())

    def test_skill_doc_declares_skill_first_and_pluggable_deep_reading(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("skill-first", text)
        self.assertIn("DeepReadingProvider", text)
        self.assertIn("ljg-paper", text)
        self.assertTrue("replace" in text or "替换" in text)

    def test_feishu_notification_research_doc_exists(self):
        text = FEISHU_RESEARCH.read_text(encoding="utf-8")
        self.assertIn("pipeline_failed", text)
        self.assertIn("FEISHU_WEBHOOK_SECRET", text)
        self.assertIn("Do not implement", text)


if __name__ == "__main__":
    unittest.main()
