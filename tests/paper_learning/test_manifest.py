import json
import tempfile
import unittest
from pathlib import Path

from skill.paper_learning_import import add_paper_learning_path


add_paper_learning_path()

from paper_learning.manifest import load_manifest, manifest_path, record_stage


class ManifestTest(unittest.TestCase):
    def test_record_stage_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = record_stage(
                artifact_dir=Path(tmp),
                date="2026-05-26",
                stage="daily",
                status="completed",
                data={"paper_count": 3},
                warnings=["hf unavailable"],
            )

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["date"], "2026-05-26")
        self.assertEqual(payload["stages"]["daily"]["status"], "completed")
        self.assertEqual(payload["stages"]["daily"]["data"]["paper_count"], 3)
        self.assertEqual(payload["warnings"], ["hf unavailable"])
        self.assertEqual(payload["next_action"], "review Notion Paper Inbox and select papers for deep reading")

    def test_failed_queue_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_stage(
                artifact_dir=Path(tmp),
                date="2026-05-26",
                stage="queue",
                status="failed",
                error="Missing Org artifact",
            )
            manifest = load_manifest(manifest_path(Path(tmp), "2026-05-26"))

        self.assertEqual(manifest["latest_error"], "Missing Org artifact")
        self.assertEqual(manifest["next_action"], "run deep-check, prepare missing provider artifacts, then rerun deep-run")


if __name__ == "__main__":
    unittest.main()
