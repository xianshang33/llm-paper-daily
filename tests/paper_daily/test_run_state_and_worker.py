import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from skill.paper_daily_import import add_paper_daily_path


add_paper_daily_path()

from paper_daily.metadata import load_metadata_payload
from paper_daily.models import PaperCandidate
from paper_daily.run_state import (
    assess_run_state,
    enqueue_metadata_tasks,
    load_pending_metadata,
    record_candidate_run,
)
from enrich_metadata import run_worker


def candidate_payload(paper_id: str = "2605.00001") -> dict:
    return {
        "arxiv_id": paper_id,
        "version_id": paper_id,
        "title": "Candidate",
        "abstract": "Candidate abstract",
        "authors": ["A"],
        "categories": ["cs.AI"],
        "primary_category": "cs.AI",
        "published": "2026-05-26T00:00:00Z",
        "updated": "2026-05-26T00:00:00Z",
        "abs_url": f"https://arxiv.org/abs/{paper_id}",
        "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
        "priority_keyword": "Agent",
        "keyword_rank": 1,
        "query_total": 1,
    }


def write_summary_artifact(repo_root: Path, paper_id: str) -> None:
    path = repo_root / "data" / "paper-daily" / "summary-artifacts" / f"{paper_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "institution": None,
        "github": None,
        "blog": None,
        "summary_cn_markdown": "#### 总结\n\n中文总结。",
        "summary_en_markdown": "#### Summary\n\nEnglish summary.",
        "provider": "test",
        "model": "test",
    }, ensure_ascii=False), encoding="utf-8")


class RunStateAndWorkerTest(unittest.TestCase):
    def test_assess_blocks_until_summary_and_metadata_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            candidate = candidate_payload()
            record_candidate_run(
                repo_root,
                date="2026-05-26",
                selected=[candidate],
                preferred_date="2026-05-26",
                attempted_dates=["2026-05-26"],
            )

            state = assess_run_state(repo_root, date="2026-05-26")
            self.assertEqual(state["status"], "finalize_blocked")
            self.assertFalse(state["finalize_ready"])
            self.assertEqual({block["kind"] for block in state["blocking"]}, {"summary", "metadata"})

    def test_worker_retries_api_before_html_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            metadata_dir = repo_root / "data" / "paper-daily" / "metadata-cache"
            candidate = candidate_payload()
            record_candidate_run(
                repo_root,
                date="2026-05-26",
                selected=[candidate],
                preferred_date="2026-05-26",
                attempted_dates=["2026-05-26"],
            )
            enqueue_metadata_tasks(repo_root, date="2026-05-26", candidates=[candidate])

            client = Mock()
            # 429 hits the batch fast-path too, so the worker falls through to the
            # per-task path under test.
            client.fetch_metadata_batch.side_effect = RuntimeError("HTTP Error 429")
            client.get_by_arxiv_ids.side_effect = RuntimeError("HTTP Error 429")
            run_worker(
                repo_root=repo_root,
                date="2026-05-26",
                client=client,
                metadata_artifact_dir=metadata_dir,
                pending_path="data/paper-daily/pending-metadata.json",
                budget_seconds=60,
                max_papers=5,
                api_retry_limit=3,
                fallback="html",
                fallback_backoff_seconds=3600,
                force_due=False,
                run_state_dir="data/paper-daily/runs",
            )

            queue = load_pending_metadata(repo_root)
            task = queue["tasks"][0]
            self.assertEqual(task["status"], "api_retrying")
            self.assertEqual(task["retry_count"], 1)
            self.assertFalse((metadata_dir / "2605.00001.json").exists())
            client.hydrate_candidate_from_abs.assert_not_called()

    def test_worker_uses_html_after_retry_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            metadata_dir = repo_root / "data" / "paper-daily" / "metadata-cache"
            candidate = candidate_payload()
            record_candidate_run(
                repo_root,
                date="2026-05-26",
                selected=[candidate],
                preferred_date="2026-05-26",
                attempted_dates=["2026-05-26"],
            )
            queue = enqueue_metadata_tasks(repo_root, date="2026-05-26", candidates=[candidate])
            queue["tasks"][0]["retry_count"] = 2
            queue["tasks"][0]["next_retry_at"] = "2020-01-01T00:00:00+00:00"
            (repo_root / "data" / "paper-daily").mkdir(parents=True, exist_ok=True)
            (repo_root / "data" / "paper-daily" / "pending-metadata.json").write_text(
                json.dumps(queue),
                encoding="utf-8",
            )

            client = Mock()
            # Batch and single-id API both throttled -> per-task HTML fallback.
            client.fetch_metadata_batch.side_effect = RuntimeError("HTTP Error 429")
            client.get_by_arxiv_ids.side_effect = RuntimeError("HTTP Error 429")
            client.hydrate_candidate_from_abs.return_value = PaperCandidate(
                **candidate,
                metadata_source="abs-html",
                metadata_status="complete",
            )
            run_worker(
                repo_root=repo_root,
                date="2026-05-26",
                client=client,
                metadata_artifact_dir=metadata_dir,
                pending_path="data/paper-daily/pending-metadata.json",
                budget_seconds=60,
                max_papers=5,
                api_retry_limit=3,
                fallback="html",
                fallback_backoff_seconds=3600,
                force_due=False,
                run_state_dir="data/paper-daily/runs",
            )

            queue = load_pending_metadata(repo_root)
            task = queue["tasks"][0]
            self.assertEqual(task["status"], "html_complete")
            payload = load_metadata_payload(metadata_dir, "2605.00001")
            self.assertEqual(payload["metadata_source"], "abs-html")

    def test_worker_force_due_ignores_future_retry_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            metadata_dir = repo_root / "data" / "paper-daily" / "metadata-cache"
            candidate = candidate_payload()
            record_candidate_run(
                repo_root,
                date="2026-05-26",
                selected=[candidate],
                preferred_date="2026-05-26",
                attempted_dates=["2026-05-26"],
            )
            queue = enqueue_metadata_tasks(repo_root, date="2026-05-26", candidates=[candidate])
            queue["tasks"][0]["next_retry_at"] = "2999-01-01T00:00:00+00:00"
            (repo_root / "data" / "paper-daily").mkdir(parents=True, exist_ok=True)
            (repo_root / "data" / "paper-daily" / "pending-metadata.json").write_text(json.dumps(queue), encoding="utf-8")

            client = Mock()
            # Force the per-task path (batch unavailable) to assert force_due still
            # services a task whose next_retry_at is in the future.
            client.fetch_metadata_batch.side_effect = RuntimeError("HTTP Error 429")
            client.get_by_arxiv_ids.return_value = [PaperCandidate(**candidate)]
            result = run_worker(
                repo_root=repo_root,
                date="2026-05-26",
                client=client,
                metadata_artifact_dir=metadata_dir,
                pending_path="data/paper-daily/pending-metadata.json",
                budget_seconds=60,
                max_papers=5,
                api_retry_limit=3,
                fallback="html",
                fallback_backoff_seconds=3600,
                force_due=True,
                run_state_dir="data/paper-daily/runs",
            )

            self.assertEqual(result["processed_count"], 1)
            client.get_by_arxiv_ids.assert_called_once()

    def test_worker_prioritizes_selected_over_unselected_pool(self):
        # The pending queue holds the full discovery pool, sorted by paper_id.
        # A bounded worker (max_papers=1) must still service the selected pack
        # first, even when unselected candidates sort ahead of it by id.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            metadata_dir = repo_root / "data" / "paper-daily" / "metadata-cache"
            selected = candidate_payload("2605.09999")  # sorts to the back by id
            pool = [
                candidate_payload("2605.00001"),  # unselected, sorts to front
                candidate_payload("2605.00002"),  # unselected, sorts to front
                selected,
            ]
            record_candidate_run(
                repo_root,
                date="2026-05-26",
                selected=[selected],
                preferred_date="2026-05-26",
                attempted_dates=["2026-05-26"],
            )
            enqueue_metadata_tasks(repo_root, date="2026-05-26", candidates=pool)

            client = Mock()
            client.fetch_metadata_batch.side_effect = (
                lambda ids: {i: PaperCandidate(**candidate_payload(i)) for i in ids}
            )
            run_worker(
                repo_root=repo_root,
                date="2026-05-26",
                client=client,
                metadata_artifact_dir=metadata_dir,
                pending_path="data/paper-daily/pending-metadata.json",
                budget_seconds=60,
                max_papers=1,
                api_retry_limit=3,
                fallback="html",
                fallback_backoff_seconds=3600,
                force_due=False,
                run_state_dir="data/paper-daily/runs",
            )

            # The single processed slot (and the only fetched id) must be the
            # selected paper, not the lower-id unselected candidates.
            self.assertTrue((metadata_dir / "2605.09999.json").exists())
            self.assertFalse((metadata_dir / "2605.00001.json").exists())
            client.fetch_metadata_batch.assert_called_once_with(["2605.09999"])

    def test_worker_batches_metadata_in_single_request(self):
        # The arXiv 429 mitigation: many eligible papers must be resolved in ONE
        # id_list request, not one HTTP call per paper.
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            metadata_dir = repo_root / "data" / "paper-daily" / "metadata-cache"
            pool = [candidate_payload(f"2605.0000{n}") for n in range(1, 4)]
            record_candidate_run(
                repo_root,
                date="2026-05-26",
                selected=pool,
                preferred_date="2026-05-26",
                attempted_dates=["2026-05-26"],
            )
            enqueue_metadata_tasks(repo_root, date="2026-05-26", candidates=pool)

            client = Mock()
            client.fetch_metadata_batch.side_effect = (
                lambda ids: {i: PaperCandidate(**candidate_payload(i)) for i in ids}
            )
            result = run_worker(
                repo_root=repo_root,
                date="2026-05-26",
                client=client,
                metadata_artifact_dir=metadata_dir,
                pending_path="data/paper-daily/pending-metadata.json",
                budget_seconds=60,
                max_papers=20,
                api_retry_limit=3,
                fallback="html",
                fallback_backoff_seconds=3600,
                force_due=False,
                run_state_dir="data/paper-daily/runs",
            )

            self.assertEqual(result["processed_count"], 3)
            # One batch call for all three; no per-paper amplification.
            client.fetch_metadata_batch.assert_called_once_with(
                ["2605.00001", "2605.00002", "2605.00003"]
            )
            client.get_by_arxiv_ids.assert_not_called()
            for n in range(1, 4):
                self.assertTrue((metadata_dir / f"2605.0000{n}.json").exists())

    def test_status_becomes_final_ready_when_requirements_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            metadata_dir = repo_root / "data" / "paper-daily" / "metadata-cache"
            candidate = candidate_payload()
            record_candidate_run(
                repo_root,
                date="2026-05-26",
                selected=[candidate],
                preferred_date="2026-05-26",
                attempted_dates=["2026-05-26"],
            )
            write_summary_artifact(repo_root, "2605.00001")
            enqueue_metadata_tasks(repo_root, date="2026-05-26", candidates=[candidate])
            client = Mock()
            client.fetch_metadata_batch.return_value = {"2605.00001": PaperCandidate(**candidate)}
            run_worker(
                repo_root=repo_root,
                date="2026-05-26",
                client=client,
                metadata_artifact_dir=metadata_dir,
                pending_path="data/paper-daily/pending-metadata.json",
                budget_seconds=60,
                max_papers=5,
                api_retry_limit=3,
                fallback="html",
                fallback_backoff_seconds=3600,
                force_due=False,
                run_state_dir="data/paper-daily/runs",
            )

            state = assess_run_state(repo_root, date="2026-05-26")
            self.assertTrue(state["finalize_ready"])
            self.assertEqual(state["status"], "final_ready")


if __name__ == "__main__":
    unittest.main()
