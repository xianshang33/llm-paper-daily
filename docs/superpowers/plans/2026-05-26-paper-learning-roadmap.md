# Paper Learning Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the confirmed roadmap into a skill-first, pluggable, diagnosable paper-learning workflow while keeping Feishu robot notifications as a documented future module.

**Architecture:** Keep `paper-learning` as the product entrypoint and keep Python scripts as execution primitives. Introduce a deep-reading provider interface with the current `ljg-paper` Org flow as the default provider, add local stage manifests for status/readiness, revise Hugging Face recall so it is supplemental and non-blocking, and document Feishu notification events without implementing the notification client.

**Tech Stack:** Python 3 standard library, existing `paper-learning` modules, existing `paper-daily` adapters, Notion/Feishu dry-run adapters, `unittest`, Markdown specs and skill docs.

---

## Scope Check

This plan is one coherent implementation slice: make the personal learning loop easier to operate and easier to evolve. It includes provider abstraction, status/readiness, Hugging Face recall cleanup, and Feishu notification research because they all support that loop.

This plan does not implement a Feishu notification module, dashboard, public subscription product, or knowledge graph.

## File Structure

Create these files:

- `skill/paper-learning/scripts/paper_learning/deep_reading_providers.py`: provider protocol, default provider registry, and `LjgPaperOrgProvider`.
- `skill/paper-learning/scripts/paper_learning/manifest.py`: manifest dataclass helpers for per-date status and next-action reporting.
- `skill/paper-learning/scripts/paper_learning/source_merge.py`: source normalization helpers for deduping arXiv and Hugging Face records.
- `skill/paper-learning/references/feishu_notification_research.md`: local research note for future Feishu robot notifications.
- `tests/paper_learning/test_deep_reading_providers.py`: provider registry and `ljg-paper` provider tests.
- `tests/paper_learning/test_manifest.py`: manifest read/write and next-action tests.
- `tests/paper_learning/test_source_merge.py`: Hugging Face/arXiv dedupe tests.

Modify these files:

- `skill/paper-learning/SKILL.md`: make the skill-first operating model and provider selection explicit.
- `skill/paper-learning/templates/config.example.json`: add `deep_reading.provider`.
- `skill/paper-learning/scripts/paper_learning/config.py`: parse `deep_reading.provider`.
- `skill/paper-learning/scripts/paper_learning/deep_reading.py`: delegate compatibility functions to providers.
- `skill/paper-learning/scripts/paper_learning/huggingface_client.py`: normalize after filtering valid items and add safe fetch behavior.
- `skill/paper-learning/scripts/run_daily_learning.py`: use non-blocking Hugging Face fetch and source dedupe.
- `skill/paper-learning/scripts/check_pipeline_readiness.py`: use provider readiness.
- `skill/paper-learning/scripts/process_notion_queue.py`: use provider-generated deep reader.
- `skill/paper-learning/scripts/rehearse_pipeline.py`: update manifest during rehearsal.
- `tests/paper_learning/test_deep_reading.py`: preserve compatibility tests for existing public functions.
- `tests/paper_learning/test_huggingface_client.py`: add invalid item, failure, and limit tests.
- `tests/paper_learning/test_process_notion_queue_script.py`: assert provider mode is wired for queue execution.
- `tests/paper_learning/test_skill_contract.py`: assert skill doc mentions skill-first and provider replacement.

## Task 1: Document Skill-First Operation and Provider Configuration

**Files:**
- Modify: `skill/paper-learning/SKILL.md`
- Modify: `skill/paper-learning/templates/config.example.json`
- Test: `tests/paper_learning/test_skill_contract.py`

- [ ] **Step 1: Write failing skill contract assertions**

Edit `tests/paper_learning/test_skill_contract.py` and add this test:

```python
def test_skill_doc_declares_skill_first_and_pluggable_deep_reading():
    text = SKILL.read_text(encoding="utf-8")
    assert "skill-first" in text
    assert "DeepReadingProvider" in text
    assert "ljg-paper" in text
    assert "replace" in text or "替换" in text
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.paper_learning.test_skill_contract -v
```

Expected: fail because `SKILL.md` does not yet mention `skill-first` or `DeepReadingProvider`.

- [ ] **Step 3: Update the skill doc**

Add this section to `skill/paper-learning/SKILL.md` after `## Operating Model`:

```markdown
## Skill-First Operation

This skill is the product entrypoint. Prefer using the skill to resolve intent, date, stage, provider, confirmation, and recovery path before calling low-level scripts.

Scripts are execution primitives. They should stay narrow and repeatable; they should not become the only way the user can operate the workflow.

Deep reading is provider-based. The default provider is `ljg-paper`, but the queue must work through a `DeepReadingProvider` boundary so another deep-reading skill can replace it later without rewriting queue orchestration.
```

Add this section near the existing deep-reading guidance:

```markdown
## Deep Reading Providers

Use the configured `deep_reading.provider` when preparing, checking, or executing deep reading.

Supported provider in this phase:

- `ljg-paper-org`: uses the `ljg-paper` skill to write Org artifacts, validates those artifacts, and converts them into `Deep Notes`.

Provider requirements:

- expose readiness for selected papers
- produce or locate provider artifacts
- convert one selected paper into one `DeepNote`
- surface provider errors without hiding the paper id
- record enough provider metadata for later review

Do not hard-code queue behavior to `ljg-paper`. Treat `ljg-paper-org` as the default provider, not the permanent architecture.
```

- [ ] **Step 4: Add provider config**

Edit `skill/paper-learning/templates/config.example.json` so the `deep_reading` object is:

```json
"deep_reading": {
  "provider": "ljg-paper-org",
  "mode": "org_artifact",
  "org_artifact_dir": "data/paper-learning/deep-reading-org"
}
```

- [ ] **Step 5: Run the skill contract test and commit**

Run:

```bash
python3 -m unittest tests.paper_learning.test_skill_contract -v
```

Expected: pass.

Commit:

```bash
git add skill/paper-learning/SKILL.md skill/paper-learning/templates/config.example.json tests/paper_learning/test_skill_contract.py
git commit -m "docs: clarify paper learning skill operation"
```

## Task 2: Add the Deep Reading Provider Interface

**Files:**
- Create: `skill/paper-learning/scripts/paper_learning/deep_reading_providers.py`
- Modify: `skill/paper-learning/scripts/paper_learning/config.py`
- Modify: `skill/paper-learning/scripts/paper_learning/deep_reading.py`
- Test: `tests/paper_learning/test_deep_reading_providers.py`
- Test: `tests/paper_learning/test_deep_reading.py`

- [ ] **Step 1: Write failing provider tests**

Create `tests/paper_learning/test_deep_reading_providers.py`:

```python
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
        provider = get_deep_reading_provider(DeepReadingConfig(provider="ljg-paper-org", mode="org_artifact", org_artifact_dir=Path("data/org")))

        self.assertEqual(provider.name, "ljg-paper-org")

    def test_ljg_provider_reports_missing_artifact(self):
        paper = SelectedPaper(notion_page_id="page-1", record=_sample_record(), human_instruction="")
        provider = get_deep_reading_provider(DeepReadingConfig(provider="ljg-paper-org", mode="org_artifact", org_artifact_dir=Path("missing")))

        result = provider.check_ready([paper])[0]

        self.assertFalse(result["ok"])
        self.assertEqual(result["paper_id"], "arxiv:2605.00001")
        self.assertIn("missing", result["path"])

    def test_ljg_provider_reads_artifact(self):
        paper = SelectedPaper(notion_page_id="page-1", record=_sample_record(), human_instruction="Focus")
        with tempfile.TemporaryDirectory() as tmp:
            cfg = DeepReadingConfig(provider="ljg-paper-org", mode="org_artifact", org_artifact_dir=Path(tmp))
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
            get_deep_reading_provider(DeepReadingConfig(provider="unknown", mode="org_artifact", org_artifact_dir=Path("data/org")))


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
```

- [ ] **Step 2: Run the provider tests and verify they fail**

Run:

```bash
python3 -m unittest tests.paper_learning.test_deep_reading_providers -v
```

Expected: fail with `ModuleNotFoundError: No module named 'paper_learning.deep_reading_providers'`.

- [ ] **Step 3: Add provider config field**

Edit `skill/paper-learning/scripts/paper_learning/config.py`.

Change `DeepReadingConfig` to:

```python
@dataclass(frozen=True)
class DeepReadingConfig:
    provider: str = "ljg-paper-org"
    mode: str = "org_artifact"
    org_artifact_dir: Path = Path("data/paper-learning/deep-reading-org")
```

Change `_deep_reading()` to:

```python
def _deep_reading(raw: dict[str, Any]) -> DeepReadingConfig:
    return DeepReadingConfig(
        provider=raw.get("provider", "ljg-paper-org"),
        mode=raw.get("mode", "org_artifact"),
        org_artifact_dir=Path(raw.get("org_artifact_dir", "data/paper-learning/deep-reading-org")),
    )
```

- [ ] **Step 4: Implement provider module**

Create `skill/paper-learning/scripts/paper_learning/deep_reading_providers.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .config import DeepReadingConfig
from .deep_reading import (
    build_ljg_paper_runtime_request,
    deep_note_from_ljg_org,
    org_artifact_path,
)
from .models import DeepNote, SelectedPaper
from .org_converter import validate_ljg_paper_org


class DeepReadingProvider(Protocol):
    name: str

    def prepare_request(self, paper: SelectedPaper) -> dict:
        ...

    def check_ready(self, papers: list[SelectedPaper]) -> list[dict]:
        ...

    def read(self, paper: SelectedPaper) -> DeepNote:
        ...


class LjgPaperOrgProvider:
    name = "ljg-paper-org"

    def __init__(self, config: DeepReadingConfig):
        self.config = config

    def artifact_path(self, paper_id: str) -> Path:
        return org_artifact_path(self.config.org_artifact_dir, paper_id)

    def prepare_request(self, paper: SelectedPaper) -> dict:
        request = build_ljg_paper_runtime_request(paper, self.config)
        request["deep_reading_provider"] = self.name
        return request

    def check_ready(self, papers: list[SelectedPaper]) -> list[dict]:
        results: list[dict] = []
        for paper in papers:
            path = self.artifact_path(paper.record.paper_id)
            try:
                text = path.read_text(encoding="utf-8")
                validate_ljg_paper_org(text, fallback_metadata={
                    "subtitle": paper.record.title,
                    "authors": ", ".join(paper.record.authors),
                    "source": paper.record.url,
                })
                results.append({"paper_id": paper.record.paper_id, "ok": True, "path": str(path), "provider": self.name})
            except Exception as exc:
                results.append({"paper_id": paper.record.paper_id, "ok": False, "path": str(path), "provider": self.name, "error": str(exc)})
        return results

    def read(self, paper: SelectedPaper) -> DeepNote:
        path = self.artifact_path(paper.record.paper_id)
        note = deep_note_from_ljg_org(paper, path.read_text(encoding="utf-8"))
        return DeepNote(
            title=note.title,
            paper_id=note.paper_id,
            reading_focus=note.reading_focus,
            markdown=note.markdown,
            contribution_type=note.contribution_type,
            method_tags=note.method_tags,
            proposed_area=note.proposed_area,
            archive_confidence=note.archive_confidence,
            extra_properties={**note.extra_properties, "deep_reading_provider": self.name},
        )


def get_deep_reading_provider(config: DeepReadingConfig) -> DeepReadingProvider:
    if config.provider == "ljg-paper-org":
        return LjgPaperOrgProvider(config)
    raise ValueError(f"Unsupported deep reading provider: {config.provider}")
```

- [ ] **Step 5: Keep compatibility functions in `deep_reading.py`**

Edit `skill/paper-learning/scripts/paper_learning/deep_reading.py` so existing `generate_deep_note()` and `validate_org_artifacts()` keep passing current tests. Add this import inside functions to avoid a circular import:

```python
def generate_deep_note(paper: SelectedPaper, cfg: DeepReadingConfig) -> DeepNote:
    if cfg.mode == "fallback":
        raise ValueError(
            "deep_reading.mode='fallback' is no longer supported. "
            "Use the ljg-paper skill to write an Org artifact and configure deep_reading.mode='org_artifact'."
        )
    from .deep_reading_providers import get_deep_reading_provider

    return get_deep_reading_provider(cfg).read(paper)
```

Change `validate_org_artifacts()` to:

```python
def validate_org_artifacts(papers: list[SelectedPaper], cfg: DeepReadingConfig) -> list[dict]:
    from .deep_reading_providers import get_deep_reading_provider

    return get_deep_reading_provider(cfg).check_ready(papers)
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
python3 -m unittest tests.paper_learning.test_deep_reading_providers tests.paper_learning.test_deep_reading -v
```

Expected: pass.

Commit:

```bash
git add skill/paper-learning/scripts/paper_learning/config.py skill/paper-learning/scripts/paper_learning/deep_reading.py skill/paper-learning/scripts/paper_learning/deep_reading_providers.py tests/paper_learning/test_deep_reading.py tests/paper_learning/test_deep_reading_providers.py
git commit -m "feat: add deep reading provider interface"
```

## Task 3: Wire Providers Into Readiness and Queue Execution

**Files:**
- Modify: `skill/paper-learning/scripts/check_pipeline_readiness.py`
- Modify: `skill/paper-learning/scripts/process_notion_queue.py`
- Test: `tests/paper_learning/test_process_notion_queue_script.py`

- [ ] **Step 1: Add script-level provider assertion**

Edit `tests/paper_learning/test_process_notion_queue_script.py` and add:

```python
def test_process_queue_uses_configured_deep_reading_provider(self):
    text = (ROOT / "skill/paper-learning/scripts/process_notion_queue.py").read_text(encoding="utf-8")
    self.assertIn("get_deep_reading_provider", text)
    self.assertIn("provider.read", text)
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.paper_learning.test_process_notion_queue_script -v
```

Expected: fail because the script still calls `generate_deep_note` directly.

- [ ] **Step 3: Update queue script**

Edit `skill/paper-learning/scripts/process_notion_queue.py`.

Replace the import:

```python
from paper_learning.deep_reading import generate_deep_note, validate_org_artifacts
```

with:

```python
from paper_learning.deep_reading_providers import get_deep_reading_provider
```

After config loading and selected-paper resolution, create the provider:

```python
provider = get_deep_reading_provider(cfg.deep_reading)
```

Replace readiness validation with:

```python
readiness = provider.check_ready(selected)
missing = [item for item in readiness if not item["ok"]]
```

Replace queue execution deep reader with:

```python
deep_reader=provider.read,
```

- [ ] **Step 4: Update readiness script**

Edit `skill/paper-learning/scripts/check_pipeline_readiness.py`.

Replace:

```python
from paper_learning.deep_reading import validate_org_artifacts
```

with:

```python
from paper_learning.deep_reading_providers import get_deep_reading_provider
```

Replace queue-stage readiness:

```python
results = validate_org_artifacts(selected, cfg.deep_reading)
```

with:

```python
provider = get_deep_reading_provider(cfg.deep_reading)
results = provider.check_ready(selected)
```

- [ ] **Step 5: Run queue/readiness tests and commit**

Run:

```bash
python3 -m unittest tests.paper_learning.test_process_notion_queue_script tests.paper_learning.test_deep_reading_providers tests.paper_learning.test_deep_reading -v
```

Expected: pass.

Commit:

```bash
git add skill/paper-learning/scripts/check_pipeline_readiness.py skill/paper-learning/scripts/process_notion_queue.py tests/paper_learning/test_process_notion_queue_script.py
git commit -m "refactor: route queue through deep reading provider"
```

## Task 4: Add Stage Manifest Support

**Files:**
- Create: `skill/paper-learning/scripts/paper_learning/manifest.py`
- Modify: `skill/paper-learning/scripts/paper_learning/daily_pipeline.py`
- Modify: `skill/paper-learning/scripts/paper_learning/queue_pipeline.py`
- Test: `tests/paper_learning/test_manifest.py`

- [ ] **Step 1: Write failing manifest tests**

Create `tests/paper_learning/test_manifest.py`:

```python
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
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python3 -m unittest tests.paper_learning.test_manifest -v
```

Expected: fail with missing `paper_learning.manifest`.

- [ ] **Step 3: Implement manifest helpers**

Create `skill/paper-learning/scripts/paper_learning/manifest.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def manifest_path(artifact_dir: Path, date: str) -> Path:
    return artifact_dir / date / "manifest.json"


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"date": path.parent.name, "stages": {}, "warnings": [], "latest_error": "", "next_action": ""}
    return json.loads(path.read_text(encoding="utf-8"))


def record_stage(
    *,
    artifact_dir: Path,
    date: str,
    stage: str,
    status: str,
    data: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    error: str = "",
) -> Path:
    path = manifest_path(artifact_dir, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_manifest(path)
    payload["date"] = date
    payload.setdefault("stages", {})
    payload.setdefault("warnings", [])
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["stages"][stage] = {
        "status": status,
        "updated_at": payload["updated_at"],
        "data": data or {},
        "error": error,
    }
    for warning in warnings or []:
        if warning not in payload["warnings"]:
            payload["warnings"].append(warning)
    if error:
        payload["latest_error"] = error
    else:
        payload.setdefault("latest_error", "")
    payload["next_action"] = _next_action(payload, stage, status)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _next_action(payload: dict[str, Any], stage: str, status: str) -> str:
    if status == "failed" and stage == "queue":
        return "run deep-check, prepare missing provider artifacts, then rerun deep-run"
    if status == "failed" and stage == "daily":
        return "run daily-check, resolve the reported missing dependency, then rerun daily-run"
    if stage == "daily" and status == "completed":
        return "review Notion Paper Inbox and select papers for deep reading"
    if stage == "queue" and status == "completed":
        return "review generated Deep Notes and archive review fields in Notion"
    return "run status for the date and inspect stage details"
```

- [ ] **Step 4: Record daily stage completion**

Edit `skill/paper-learning/scripts/paper_learning/daily_pipeline.py`.

Add import:

```python
from .manifest import record_stage
```

Before returning `OperationResult`, after writing the existing artifact, add:

```python
    record_stage(
        artifact_dir=artifact_dir,
        date=date,
        stage="daily",
        status="completed" if ok else "failed",
        data={
            "paper_count": len(records),
            "artifact_path": str(artifact_path),
            "notion_report_status": notion_report.status,
            "feishu_report_status": feishu_report.status,
        },
        error="" if ok else "daily pipeline completed with failures",
    )
```

- [ ] **Step 5: Record queue stage completion**

Edit `skill/paper-learning/scripts/paper_learning/queue_pipeline.py`.

Add optional parameters to `process_selected_papers()`:

```python
    artifact_dir=None,
    date: str = "",
```

Add import:

```python
from .manifest import record_stage
```

Before returning the final `OperationResult`, add:

```python
    if artifact_dir is not None and date:
        record_stage(
            artifact_dir=artifact_dir,
            date=date,
            stage="queue",
            status="completed" if ok else "failed",
            data={"processed": processed},
            error="" if ok else "queue processing completed with failures",
        )
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
python3 -m unittest tests.paper_learning.test_manifest tests.paper_learning.test_daily_pipeline tests.paper_learning.test_queue_pipeline -v
```

Expected: pass.

Commit:

```bash
git add skill/paper-learning/scripts/paper_learning/manifest.py skill/paper-learning/scripts/paper_learning/daily_pipeline.py skill/paper-learning/scripts/paper_learning/queue_pipeline.py tests/paper_learning/test_manifest.py
git commit -m "feat: record paper learning stage manifest"
```

## Task 5: Revise Hugging Face Recall as Supplemental Source

**Files:**
- Modify: `skill/paper-learning/scripts/paper_learning/huggingface_client.py`
- Create: `skill/paper-learning/scripts/paper_learning/source_merge.py`
- Modify: `skill/paper-learning/scripts/run_daily_learning.py`
- Test: `tests/paper_learning/test_huggingface_client.py`
- Test: `tests/paper_learning/test_source_merge.py`

- [ ] **Step 1: Add failing Hugging Face tests**

Edit `tests/paper_learning/test_huggingface_client.py` and add:

```python
from urllib.error import URLError
from paper_learning.config import HuggingFaceConfig
from paper_learning.huggingface_client import fetch_hf_daily_papers_safe


def test_normalize_hf_daily_papers_skips_invalid_before_limit(self):
    raw = [
        {"paper": {"id": "", "title": "invalid"}},
        {"paper": {"id": "2605.00002", "title": "valid", "summary": "summary", "authors": []}},
    ]

    records = normalize_hf_daily_papers(raw, run_date="2026-05-20", limit=1)

    assert len(records) == 1
    assert records[0].paper_id == "hf:2605.00002"


def test_fetch_hf_daily_papers_safe_returns_warning_on_failure():
    def failing_fetch(date, cfg):
        raise URLError("network blocked")

    records, warnings = fetch_hf_daily_papers_safe("2026-05-20", HuggingFaceConfig(), fetcher=failing_fetch)

    assert records == []
    assert warnings == ["Hugging Face daily papers unavailable: <urlopen error network blocked>"]
```

- [ ] **Step 2: Create failing dedupe tests**

Create `tests/paper_learning/test_source_merge.py`:

```python
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
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
python3 -m unittest tests.paper_learning.test_huggingface_client tests.paper_learning.test_source_merge -v
```

Expected: fail because `normalize_hf_daily_papers()` lacks `limit`, safe fetch is missing, and `source_merge.py` is missing.

- [ ] **Step 4: Update Hugging Face client**

Edit `skill/paper-learning/scripts/paper_learning/huggingface_client.py`.

Change `fetch_hf_daily_papers()` to:

```python
def fetch_hf_daily_papers(date: str, cfg: HuggingFaceConfig) -> list[DailyPaperRecord]:
    query = urlencode({"date": date})
    request = Request(f"{cfg.endpoint}?{query}", headers={"User-Agent": "llm-paper-daily/1.0"})
    with urlopen(request, timeout=30) as response:
        raw = json.loads(response.read().decode("utf-8"))
    return normalize_hf_daily_papers(raw, run_date=date, limit=cfg.limit)
```

Add:

```python
def fetch_hf_daily_papers_safe(date: str, cfg: HuggingFaceConfig, *, fetcher=fetch_hf_daily_papers) -> tuple[list[DailyPaperRecord], list[str]]:
    try:
        return fetcher(date, cfg), []
    except Exception as exc:
        return [], [f"Hugging Face daily papers unavailable: {exc}"]
```

Change `normalize_hf_daily_papers()` signature and loop:

```python
def normalize_hf_daily_papers(raw: list[dict], run_date: str, limit: int | None = None) -> list[DailyPaperRecord]:
    records: list[DailyPaperRecord] = []
    for rank, item in enumerate(raw, start=1):
        paper = item.get("paper", item)
        paper_id = str(paper.get("id") or paper.get("paperId") or "").strip()
        if not paper_id:
            continue
        title = paper.get("title", "")
        summary = paper.get("summary", "")
        published = _date_only(paper.get("publishedAt", run_date))
        authors = []
        for author in paper.get("authors", []):
            if isinstance(author, dict) and author.get("name"):
                authors.append(author["name"])
            elif isinstance(author, str):
                authors.append(author)
        records.append(DailyPaperRecord(
            paper_id=f"hf:{paper_id}",
            source="HuggingFace",
            title=title,
            authors=authors,
            institutions="",
            abstract=summary,
            digest_summary=summary,
            summary_cn="",
            summary_en=summary,
            published_date=published,
            run_date=run_date,
            url=f"https://huggingface.co/papers/{paper_id}",
            pdf_url=f"https://arxiv.org/pdf/{paper_id}" if paper_id[:4].isdigit() else None,
            topic="huggingface-daily",
            score=float(item.get("numComments", 0)),
            signals={"hf_num_comments": item.get("numComments", 0), "hf_rank": rank},
            provenance={"source": "huggingface_daily_papers", "hf_url": f"https://huggingface.co/papers/{paper_id}"},
        ))
        if limit is not None and len(records) >= limit:
            break
    return records
```

- [ ] **Step 5: Implement source merge**

Create `skill/paper-learning/scripts/paper_learning/source_merge.py`:

```python
from __future__ import annotations

from dataclasses import replace

from .models import DailyPaperRecord


def merge_supplemental_records(primary: list[DailyPaperRecord], supplemental: list[DailyPaperRecord]) -> list[DailyPaperRecord]:
    merged = list(primary)
    by_arxiv_id = {_normalized_arxiv_id(record.paper_id): index for index, record in enumerate(merged) if _normalized_arxiv_id(record.paper_id)}
    for record in supplemental:
        normalized = _normalized_arxiv_id(record.paper_id)
        if normalized and normalized in by_arxiv_id:
            index = by_arxiv_id[normalized]
            original = merged[index]
            merged[index] = replace(
                original,
                signals={**original.signals, "hf_duplicate": True, **{key: value for key, value in record.signals.items() if key.startswith("hf_")}},
                provenance={**original.provenance, "hf_url": record.url, "hf_source": record.provenance.get("source", "huggingface_daily_papers")},
            )
            continue
        merged.append(record)
    return merged


def _normalized_arxiv_id(paper_id: str) -> str:
    raw = paper_id.split(":", 1)[1] if ":" in paper_id else paper_id
    if raw[:4].isdigit() and "." in raw:
        return raw.split("v", 1)[0]
    return ""
```

- [ ] **Step 6: Wire daily run to safe fetch and merge**

Edit `skill/paper-learning/scripts/run_daily_learning.py`.

Replace:

```python
from paper_learning.huggingface_client import fetch_hf_daily_papers
```

with:

```python
from paper_learning.huggingface_client import fetch_hf_daily_papers_safe
from paper_learning.source_merge import merge_supplemental_records
```

Replace the Hugging Face append block:

```python
        if cfg.huggingface.enabled and not limit_satisfied:
            records.extend(fetch_hf_daily_papers(args.date, cfg.huggingface))
```

with:

```python
        warnings = []
        if cfg.huggingface.enabled and not limit_satisfied:
            hf_records, warnings = fetch_hf_daily_papers_safe(args.date, cfg.huggingface)
            records = merge_supplemental_records(records, hf_records)
```

After `run_daily_pipeline(...)`, add warnings into the printed result:

```python
        output = result.to_dict()
        if warnings:
            output.setdefault("data", {})["warnings"] = warnings
        print(json.dumps(output, ensure_ascii=False, indent=2))
```

Remove the old direct `print(json.dumps(result.to_dict(), ...))`.

- [ ] **Step 7: Run tests and commit**

Run:

```bash
python3 -m unittest tests.paper_learning.test_huggingface_client tests.paper_learning.test_source_merge -v
```

Expected: pass.

Run:

```bash
python3 -m unittest discover tests.paper_learning -v
```

Expected: pass.

Commit:

```bash
git add skill/paper-learning/scripts/paper_learning/huggingface_client.py skill/paper-learning/scripts/paper_learning/source_merge.py skill/paper-learning/scripts/run_daily_learning.py tests/paper_learning/test_huggingface_client.py tests/paper_learning/test_source_merge.py
git commit -m "fix: make huggingface recall supplemental"
```

## Task 6: Add Feishu Notification Research Note

**Files:**
- Create: `skill/paper-learning/references/feishu_notification_research.md`
- Modify: `skill/paper-learning/SKILL.md`
- Test: `tests/paper_learning/test_skill_contract.py`

- [ ] **Step 1: Add failing documentation test**

Edit `tests/paper_learning/test_skill_contract.py` and add:

```python
FEISHU_RESEARCH = ROOT / "skill" / "paper-learning" / "references" / "feishu_notification_research.md"


def test_feishu_notification_research_doc_exists():
    text = FEISHU_RESEARCH.read_text(encoding="utf-8")
    assert "pipeline_failed" in text
    assert "FEISHU_WEBHOOK_SECRET" in text
    assert "Do not implement" in text
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python3 -m unittest tests.paper_learning.test_skill_contract -v
```

Expected: fail because `feishu_notification_research.md` is missing.

- [ ] **Step 3: Create Feishu research note**

Create `skill/paper-learning/references/feishu_notification_research.md`:

```markdown
# Feishu Robot Notification Research

Do not implement the notification module in the current roadmap slice. This note defines the future module boundary so implementation can happen later without mixing operational alerts into daily report delivery.

## Current State

- `FeishuClient.deliver_report()` sends the daily report through a webhook-style adapter.
- It does not model notification events.
- It does not support webhook signing.
- It does not distinguish reports from operational alerts.

## Future Module Boundary

Create a separate `FeishuNotificationClient` or `NotificationClient`.

Inputs:

- event type
- short title
- short body
- links
- stage
- date
- severity

Environment:

- `FEISHU_WEBHOOK_URL`
- `FEISHU_WEBHOOK_SECRET`

Events:

- `daily_ready`: daily report generated, with candidate count and Notion link.
- `deep_reading_confirmation_required`: selected papers resolved and waiting for confirmation.
- `deep_reading_done`: deep notes created, with count and links.
- `pipeline_failed`: stage failed, with error summary and recovery action.

## Message Format

Start with text messages. Use interactive cards only after the event model is stable.

Text payload shape:

```json
{
  "msg_type": "text",
  "content": {
    "text": "[paper-learning] daily_ready 2026-05-26\n候选论文: 20\n下一步: review Notion Paper Inbox"
  }
}
```

Signed webhook payloads should include `timestamp` and `sign` according to Feishu custom bot documentation.

## References

- Feishu custom bot: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
- Feishu message cards: https://open.feishu.cn/document/common-capabilities/message-card/getting-started/send-message-cards-with-a-custom-bot
```

- [ ] **Step 4: Link research note from skill doc**

Add this bullet under `## References` in `skill/paper-learning/SKILL.md`:

```markdown
- Feishu notification research: `references/feishu_notification_research.md`
```

- [ ] **Step 5: Run test and commit**

Run:

```bash
python3 -m unittest tests.paper_learning.test_skill_contract -v
```

Expected: pass.

Commit:

```bash
git add skill/paper-learning/SKILL.md skill/paper-learning/references/feishu_notification_research.md tests/paper_learning/test_skill_contract.py
git commit -m "docs: research feishu robot notifications"
```

## Task 7: Final Verification and Roadmap Status

**Files:**
- Modify: `docs/superpowers/specs/2026-05-26-paper-learning-roadmap-design.md`
- Test: full paper-learning test suite

- [ ] **Step 1: Run full tests**

Run:

```bash
python3 -m unittest discover tests.paper_learning -v
```

Expected: all tests pass.

- [ ] **Step 2: Run a summary-free daily dry-run**

Run:

```bash
python3 skill/paper-learning/scripts/run_daily_learning.py --config skill/paper-learning/templates/config.example.json --date 2026-05-20 --dry-run --skip-paper-daily --skip-summary --limit 1
```

Expected: JSON output with `"ok": true` or a clear failure explaining the missing local discovery artifact. If it fails due to missing local discovery, run:

```bash
python3 skill/paper-learning/scripts/run_daily_learning.py --config skill/paper-learning/templates/config.example.json --date 2026-05-20 --dry-run --skip-summary --limit 1
```

Expected: JSON output with dry-run Notion and Feishu data.

- [ ] **Step 3: Run queue readiness dry-run against a local selected-papers artifact**

Run:

```bash
python3 skill/paper-learning/scripts/prepare_selected_papers.py --config skill/paper-learning/templates/config.example.json --date 2026-05-20 --limit 1
python3 skill/paper-learning/scripts/check_pipeline_readiness.py --config skill/paper-learning/templates/config.example.json --date 2026-05-20 --stage queue --selected-papers-json data/paper-learning/runs/2026-05-20/selected-papers.json --limit 1
```

Expected: readiness JSON that includes `"stage": "queue"` and provider readiness results. Missing Org artifacts are acceptable at this step if the error includes the path and paper id.

- [ ] **Step 4: Add implementation status note to the spec**

Append this section to `docs/superpowers/specs/2026-05-26-paper-learning-roadmap-design.md`:

```markdown
## Implementation Status

- Skill-first operation documented.
- Deep reading provider interface implemented with `ljg-paper-org` as the default provider.
- Queue and readiness paths route through the provider interface.
- Stage manifests record daily and queue status.
- Hugging Face recall is supplemental, deduped against arXiv, and non-blocking by default.
- Feishu robot notification design is documented for a future module; notification sending is not implemented in this slice.
```

- [ ] **Step 5: Commit final status**

Commit:

```bash
git add docs/superpowers/specs/2026-05-26-paper-learning-roadmap-design.md
git commit -m "docs: mark paper learning roadmap status"
```

## Self-Review

Spec coverage:

- Skill-first operation: Task 1.
- Pluggable deep-reading provider: Tasks 1-3.
- Reliability and manifest: Task 4.
- Hugging Face recall review/fix: Task 5.
- Feishu robot notification research without implementation: Task 6.
- Verification and status: Task 7.

Placeholder scan:

- No unfinished markers or vague implementation steps are present.
- Feishu notification implementation is explicitly excluded and documented as research.

Type consistency:

- `DeepReadingConfig.provider` is introduced before provider usage.
- `DeepReadingProvider.read()` returns existing `DeepNote`.
- Queue still accepts a callable `deep_reader`, now supplied as `provider.read`.
- Manifest uses plain `dict` JSON to avoid changing external data contracts.
