from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import DailyPaperRecord, SelectedPaper


def selected_paper_from_page(page: dict) -> SelectedPaper:
    props = page.get("properties", {})
    url = props.get("URL", {}).get("url") or ""
    paper_id = _plain_rich_text(props.get("Paper ID", {})) or _paper_id_from_url(url)
    record = DailyPaperRecord(
        paper_id=paper_id,
        source=_select_name(props.get("Source", {})),
        title=_plain_title(props.get("Title", {})),
        authors=[],
        institutions=_plain_rich_text(props.get("Institutions", {})),
        abstract="",
        digest_summary=_plain_rich_text(props.get("Digest Summary", {})),
        summary_cn="",
        summary_en="",
        published_date=_date_start(props.get("Published Date", {})),
        run_date=_date_start(props.get("Run Date", {})),
        url=url,
        pdf_url=None,
        topic="",
        score=0,
        signals={},
        provenance={"source": "notion"},
    )
    return SelectedPaper(
        notion_page_id=page["id"],
        record=record,
        human_instruction=_plain_rich_text(props.get("Human Instruction", {})),
        existing_research_area_ids=[item["id"] for item in props.get("Research Areas", {}).get("relation", [])],
        existing_deep_note_id=_first_relation_id(props.get("Deep Note", {})),
    )


def _plain_title(prop: dict) -> str:
    return "".join(part.get("plain_text", "") for part in prop.get("title", []))


def _plain_rich_text(prop: dict) -> str:
    return "".join(part.get("plain_text", "") for part in prop.get("rich_text", []))


def _select_name(prop: dict) -> str:
    select = prop.get("select")
    return select.get("name", "") if select else ""


def _date_start(prop: dict) -> str:
    date = prop.get("date")
    return date.get("start", "") if date else ""


def _first_relation_id(prop: dict) -> str | None:
    relation = prop.get("relation", [])
    return relation[0]["id"] if relation else None


def _paper_id_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.endswith("arxiv.org") and len(parts) >= 2 and parts[0] in {"abs", "pdf"}:
        arxiv_id = re.sub(r"v\d+$", "", parts[1].removesuffix(".pdf"))
        return f"arxiv:{arxiv_id}"
    if parsed.netloc == "huggingface.co" and len(parts) >= 2 and parts[0] == "papers":
        return f"hf:{parts[1]}"
    return url
