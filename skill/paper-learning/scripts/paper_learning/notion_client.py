from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import NotionConfig
from .models import DailyPaperRecord, DeepNote, OperationResult, ReportModel, SelectedPaper
from .report import render_markdown_report

# markdown→block rendering and page→model deserialization live in dedicated
# modules; re-exported here so the historical import surface stays stable.
from .notion_blocks import markdown_to_blocks  # noqa: F401
from .notion_pages import selected_paper_from_page  # noqa: F401


class NotionClient:
    def __init__(self, config: NotionConfig):
        self.config = config

    def create_database(self, *, parent_page_id: str, title: str, properties: dict) -> OperationResult:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title[:2000]}}],
            "properties": properties,
        }
        if self.config.dry_run:
            return OperationResult(True, "dry_run", "database creation skipped in dry-run", payload)

        data = self._request("POST", "/databases", payload)
        return OperationResult(True, "created", "database created", data)

    def update_database(self, database_id: str, properties: dict) -> OperationResult:
        payload = {"properties": properties}
        if self.config.dry_run:
            return OperationResult(True, "dry_run", "database update skipped in dry-run", {"database_id": database_id, **payload})

        data = self._request("PATCH", f"/databases/{database_id}", payload)
        return OperationResult(True, "updated", "database updated", data)

    def find_database_in_parent(self, *, parent_page_id: str, title: str) -> dict | None:
        if self.config.dry_run:
            return None

        payload = {
            "query": title,
            "filter": {"property": "object", "value": "database"},
            "page_size": 50,
        }
        data = self._request("POST", "/search", payload)
        for result in data.get("results", []):
            if result.get("object") != "database":
                continue
            if result.get("parent", {}).get("page_id") != parent_page_id:
                continue
            titles = result.get("title", [])
            found = "".join(part.get("plain_text", "") for part in titles)
            if found == title:
                return result
        return None

    def build_paper_properties(self, record: DailyPaperRecord, *, include_workflow_defaults: bool = True) -> dict:
        properties = {
            "Title": _title(record.title),
            "Digest Summary": _rich_text(_normalize_digest_summary(record.digest_summary)),
            "Institutions": _rich_text(record.institutions),
            "Published Date": {"date": {"start": record.published_date}},
            "URL": {"url": record.url or None},
            "Source": {"select": {"name": record.source}},
        }
        if include_workflow_defaults:
            properties["Status"] = {"status": {"name": "New"}}
            properties["Error"] = {"rich_text": []}
        return properties

    def upsert_paper(self, record: DailyPaperRecord) -> OperationResult:
        if self.config.dry_run:
            return OperationResult(
                ok=True,
                status="dry_run",
                message="paper upsert skipped in dry-run",
                data={"paper_id": record.paper_id, "properties": self.build_paper_properties(record)},
            )

        existing_page_id = self._find_page_by_url(record.url)
        if existing_page_id:
            properties = self.build_paper_properties(record, include_workflow_defaults=False)
            data = self._request("PATCH", f"/pages/{existing_page_id}", {"properties": properties})
            return OperationResult(True, "updated", "paper updated", data)

        payload = {
            "parent": {"database_id": self.config.paper_inbox_database_id},
            "properties": self.build_paper_properties(record),
        }
        data = self._request("POST", "/pages", payload)
        return OperationResult(True, "created", "paper created", data)

    def create_daily_report(self, report: ReportModel, inbox_links: dict[str, str] | None = None) -> OperationResult:
        markdown = render_markdown_report(report, inbox_links=inbox_links or {})
        if self.config.dry_run:
            return OperationResult(True, "dry_run", "daily report skipped in dry-run", {"markdown": markdown})

        self._delete_existing_daily_report(report.date)

        all_blocks = markdown_to_blocks(markdown)

        payload = {
            "parent": {"page_id": self.config.daily_report_parent_page_id},
            "properties": {"title": [{"text": {"content": report.title[:2000]}}]},
            "children": all_blocks[:100],
        }
        data = self._request("POST", "/pages", payload)
        page_id = data.get("id")

        for i in range(100, len(all_blocks), 100):
            if page_id:
                self._request("PATCH", f"/blocks/{page_id}/children", {"children": all_blocks[i:i + 100]})

        return OperationResult(True, "created", "daily report created", data)

    def _delete_existing_daily_report(self, date: str) -> None:
        """删除该日期的所有旧 daily report"""
        data = self._request("GET", f"/blocks/{self.config.daily_report_parent_page_id}/children")
        for block in data.get("results", []):
            if block.get("type") == "child_page":
                page_id = block.get("id")
                title = block.get("child_page", {}).get("title", "")
                if date in title and "Daily Paper Report" in title:
                    self._request("PATCH", f"/pages/{page_id}", {"archived": True})

    def query_selected_papers(self) -> list[SelectedPaper]:
        if self.config.dry_run:
            return []

        payload = {"filter": {"property": "Status", "status": {"equals": "Selected"}}}
        data = self._request("POST", f"/databases/{self.config.paper_inbox_database_id}/query", payload)
        return [selected_paper_from_page(page) for page in data.get("results", [])]

    def get_papers_by_page_ids(self, page_ids: list[str]) -> list[SelectedPaper]:
        if self.config.dry_run:
            return []

        papers: list[SelectedPaper] = []
        for page_id in page_ids:
            data = self._request("GET", f"/pages/{page_id}")
            papers.append(selected_paper_from_page(data))
        return papers

    def find_papers_by_urls(self, urls: list[str]) -> list[SelectedPaper]:
        if self.config.dry_run:
            return []

        papers: list[SelectedPaper] = []
        for url in urls:
            page_id = self._find_page_by_url(url)
            if not page_id:
                continue
            data = self._request("GET", f"/pages/{page_id}")
            papers.append(selected_paper_from_page(data))
        return papers

    def create_deep_note(self, paper: SelectedPaper, note: DeepNote, area_ids: list[str]) -> OperationResult:
        properties = self._build_deep_note_properties(paper, note, area_ids)
        children = markdown_to_blocks(note.markdown)
        if self.config.dry_run:
            status = "dry_run_update" if paper.existing_deep_note_id else "dry_run_create"
            return OperationResult(True, status, "deep note skipped in dry-run", {
                "paper_id": paper.record.paper_id,
                "page_id": paper.existing_deep_note_id,
                "properties": properties,
                "children": children,
            })

        if paper.existing_deep_note_id:
            data = self._update_deep_note(paper.existing_deep_note_id, properties, children)
            return OperationResult(True, "updated", "deep note updated", data)

        payload = {
            "parent": {"database_id": self.config.deep_notes_database_id},
            "properties": properties,
            "children": children,
        }
        data = self._request("POST", "/pages", payload)
        return OperationResult(True, "created", "deep note created", data)

    def _build_deep_note_properties(
        self, paper: SelectedPaper, note: DeepNote, area_ids: list[str]
    ) -> dict:
        properties: dict = {
            "Title": _title(note.title),
            "Paper": {"relation": [{"id": paper.notion_page_id}]},
            "Research Areas": {"relation": [{"id": area_id} for area_id in area_ids]},
            "Reading Focus": _rich_text(note.reading_focus),
            "Contribution Type": {"select": {"name": note.contribution_type}},
            "Method Tags": {"multi_select": [{"name": tag} for tag in note.method_tags]},
            "Review Status": {"select": {"name": "Draft"}},
        }
        return properties

    def update_paper_status(self, page_id: str, properties: dict) -> OperationResult:
        if self.config.dry_run:
            return OperationResult(
                True,
                "dry_run",
                "paper status skipped in dry-run",
                {"page_id": page_id, "properties": properties},
            )

        data = self._request("PATCH", f"/pages/{page_id}", {"properties": properties})
        return OperationResult(True, "updated", "paper status updated", data)

    def _update_deep_note(self, page_id: str, properties: dict, children: list[dict]) -> dict:
        data = self._request("PATCH", f"/pages/{page_id}", {"properties": properties})
        existing_block_ids = self._list_block_children(page_id)
        for block_id in existing_block_ids:
            self._request("PATCH", f"/blocks/{block_id}", {"archived": True})
        if children:
            self._request("PATCH", f"/blocks/{page_id}/children", {"children": children})
        return data

    def _list_block_children(self, block_id: str) -> list[str]:
        child_ids: list[str] = []
        cursor: str | None = None
        while True:
            path = f"/blocks/{block_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            data = self._request("GET", path)
            child_ids.extend(result["id"] for result in data.get("results", []))
            if not data.get("has_more"):
                return child_ids
            cursor = data.get("next_cursor")

    def _find_page_by_url(self, url: str) -> str | None:
        if not url:
            return None
        payload = {"filter": {"property": "URL", "url": {"equals": url}}}
        data = self._request("POST", f"/databases/{self.config.paper_inbox_database_id}/query", payload)
        results = data.get("results", [])
        if not results:
            return None
        return results[0]["id"]

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.config.api_base.rstrip("/") + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Notion-Version": self.config.api_version,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Notion API {exc.code} {exc.reason}: {details}") from exc


def _title(value: str) -> dict:
    return {"title": [{"text": {"content": value[:2000]}}]}


def _rich_text(value: str) -> dict:
    return {"rich_text": [{"text": {"content": value[:2000]}}]}


def _normalize_digest_summary(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    for prefix in ("机构:", "机构：", "Institution:", "Institution："):
        if text.startswith(prefix):
            parts = text.split("<br>", 1)
            if len(parts) == 2:
                return parts[1].lstrip()
    return text
