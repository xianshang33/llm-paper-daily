from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class PaperCandidate:
    arxiv_id: str
    version_id: str
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    primary_category: str | None
    published: str
    updated: str
    abs_url: str
    pdf_url: str | None
    priority_keyword: str
    keyword_rank: int
    query_total: int
    institution_matches: list[str] = field(default_factory=list)
    lab_matches: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    metadata_source: str = ""
    metadata_status: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CanonicalPaper:
    schema_version: str
    paper_id: str
    date: str
    title: str
    authors: list[str]
    abstract: str
    links: dict[str, str | None]
    institution: str | None
    category_key: str
    category_alias: str
    category_display: dict[str, str]
    summary_cn: str
    summary_en: str
    render_excerpt: str
    render_excerpt_en: str
    source_discovery: dict[str, str]
    source_summary: dict[str, str]
    provenance: dict[str, str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FeedItem:
    id: str
    date: str
    title: str
    topic: str
    language: list[str]
    authors: list[str]
    institution: str | None
    summary: dict[str, str]
    links: dict[str, str | None]
    artifacts: dict[str, str | None]
    signals: dict[str, str | float | int]
    provenance: dict[str, str]

    def to_dict(self) -> dict:
        return asdict(self)
