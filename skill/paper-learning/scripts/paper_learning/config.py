from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DAILY_SELECT = 20
DEFAULT_MAX_RESULTS_PER_KEYWORD = 50
DEFAULT_SCORE_THRESHOLD = 6.0


@dataclass(frozen=True)
class PaperDailyConfig:
    repo_root: Path
    python: str = "python3"
    generate_feed_script: str = "skill/paper-daily/scripts/generate_feed.py"
    discover_script: str = "skill/paper-daily/scripts/discover.py"
    prepare_summary_requests_script: str = "skill/paper-daily/scripts/prepare_summary_requests.py"
    select: int = DEFAULT_DAILY_SELECT
    max_results_per_keyword: int = DEFAULT_MAX_RESULTS_PER_KEYWORD
    score_threshold: float = DEFAULT_SCORE_THRESHOLD


@dataclass(frozen=True)
class HuggingFaceConfig:
    enabled: bool = True
    endpoint: str = "https://huggingface.co/api/daily_papers"
    limit: int = 20


@dataclass(frozen=True)
class NotionConfig:
    enabled: bool = True
    dry_run: bool = True
    api_base: str = "https://api.notion.com/v1"
    api_version: str = "2022-06-28"
    token_env: str = "NOTION_TOKEN"
    token: str = ""
    paper_inbox_database_id: str = ""
    deep_notes_database_id: str = ""
    research_areas_database_id: str = ""
    daily_report_parent_page_id: str = ""


@dataclass(frozen=True)
class FeishuConfig:
    enabled: bool = True
    dry_run: bool = True
    webhook_url_env: str = "FEISHU_WEBHOOK_URL"
    webhook_url: str = ""


@dataclass(frozen=True)
class DeepReadingConfig:
    provider: str = "ljg-paper-org"
    mode: str = "org_artifact"
    org_artifact_dir: Path = Path("data/paper-learning/deep-reading-org")


@dataclass(frozen=True)
class ClassificationConfig:
    confidence_threshold: float = 0.72
    default_research_areas_path: Path = Path("skill/paper-learning/references/research_areas.example.json")


@dataclass(frozen=True)
class RuntimeConfig:
    artifact_dir: Path = Path("data/paper-learning/runs")
    timeout_seconds: int = 60
    dry_run: bool = True


@dataclass(frozen=True)
class AppConfig:
    paper_daily: PaperDailyConfig
    huggingface: HuggingFaceConfig
    notion: NotionConfig
    feishu: FeishuConfig
    deep_reading: DeepReadingConfig
    classification: ClassificationConfig
    runtime: RuntimeConfig


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return AppConfig(
        paper_daily=_paper_daily(raw.get("paper_daily", {})),
        huggingface=_huggingface(raw.get("huggingface", {})),
        notion=_notion(raw.get("notion", {})),
        feishu=_feishu(raw.get("feishu", {})),
        deep_reading=_deep_reading(raw.get("deep_reading", {})),
        classification=_classification(raw.get("classification", {})),
        runtime=_runtime(raw.get("runtime", {})),
    )


def _paper_daily(raw: dict[str, Any]) -> PaperDailyConfig:
    return PaperDailyConfig(
        repo_root=Path(raw.get("repo_root", ".")),
        python=raw.get("python", "python3"),
        generate_feed_script=raw.get("generate_feed_script", "skill/paper-daily/scripts/generate_feed.py"),
        discover_script=raw.get("discover_script", "skill/paper-daily/scripts/discover.py"),
        prepare_summary_requests_script=raw.get("prepare_summary_requests_script", "skill/paper-daily/scripts/prepare_summary_requests.py"),
        select=int(raw.get("select", DEFAULT_DAILY_SELECT)),
        max_results_per_keyword=int(raw.get("max_results_per_keyword", DEFAULT_MAX_RESULTS_PER_KEYWORD)),
        score_threshold=float(raw.get("score_threshold", DEFAULT_SCORE_THRESHOLD)),
    )


def _huggingface(raw: dict[str, Any]) -> HuggingFaceConfig:
    return HuggingFaceConfig(
        enabled=bool(raw.get("enabled", True)),
        endpoint=raw.get("endpoint", "https://huggingface.co/api/daily_papers"),
        limit=int(raw.get("limit", 20)),
    )


def _notion(raw: dict[str, Any]) -> NotionConfig:
    token_env = raw.get("token_env", "NOTION_TOKEN")
    return NotionConfig(
        enabled=bool(raw.get("enabled", True)),
        dry_run=bool(raw.get("dry_run", True)),
        api_base=raw.get("api_base", "https://api.notion.com/v1"),
        api_version=raw.get("api_version", "2022-06-28"),
        token_env=token_env,
        token=os.environ.get(token_env, ""),
        paper_inbox_database_id=raw.get("paper_inbox_database_id", ""),
        deep_notes_database_id=raw.get("deep_notes_database_id", ""),
        research_areas_database_id=raw.get("research_areas_database_id", ""),
        daily_report_parent_page_id=raw.get("daily_report_parent_page_id", ""),
    )


def _feishu(raw: dict[str, Any]) -> FeishuConfig:
    webhook_url_env = raw.get("webhook_url_env", "FEISHU_WEBHOOK_URL")
    return FeishuConfig(
        enabled=bool(raw.get("enabled", True)),
        dry_run=bool(raw.get("dry_run", True)),
        webhook_url_env=webhook_url_env,
        webhook_url=os.environ.get(webhook_url_env, ""),
    )


def _deep_reading(raw: dict[str, Any]) -> DeepReadingConfig:
    return DeepReadingConfig(
        provider=raw.get("provider", "ljg-paper-org"),
        mode=raw.get("mode", "org_artifact"),
        org_artifact_dir=Path(raw.get("org_artifact_dir", "data/paper-learning/deep-reading-org")),
    )


def _classification(raw: dict[str, Any]) -> ClassificationConfig:
    return ClassificationConfig(
        confidence_threshold=float(raw.get("confidence_threshold", 0.72)),
        default_research_areas_path=Path(raw.get("default_research_areas_path", "skill/paper-learning/references/research_areas.example.json")),
    )


def _runtime(raw: dict[str, Any]) -> RuntimeConfig:
    return RuntimeConfig(
        artifact_dir=Path(raw.get("artifact_dir", "data/paper-learning/runs")),
        timeout_seconds=int(raw.get("timeout_seconds", 60)),
        dry_run=bool(raw.get("dry_run", True)),
    )
