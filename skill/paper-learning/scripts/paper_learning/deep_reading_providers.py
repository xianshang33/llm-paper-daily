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
                validate_ljg_paper_org(
                    text,
                    fallback_metadata={
                        "subtitle": paper.record.title,
                        "authors": ", ".join(paper.record.authors),
                        "source": paper.record.url,
                    },
                )
                results.append({
                    "paper_id": paper.record.paper_id,
                    "ok": True,
                    "path": str(path),
                    "provider": self.name,
                })
            except Exception as exc:
                results.append({
                    "paper_id": paper.record.paper_id,
                    "ok": False,
                    "path": str(path),
                    "provider": self.name,
                    "error": str(exc),
                })
        return results

    def read(self, paper: SelectedPaper) -> DeepNote:
        path = self.artifact_path(paper.record.paper_id)
        if not path.exists():
            raise FileNotFoundError(
                f"Missing ljg-paper Org artifact for {paper.record.paper_id}: {path}. "
                "Run the agent runtime with the ljg-paper skill and write the resulting Org document there."
            )
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
