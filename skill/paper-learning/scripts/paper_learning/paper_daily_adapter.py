from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import PaperDailyConfig
from .models import DailyPaperRecord


def run_paper_daily(date: str, cfg: PaperDailyConfig, *, select_override: int | None = None) -> None:
    repo_root = cfg.repo_root
    discover_out = repo_root / "data" / "paper-learning" / "runs" / date / "discovered-papers.json"
    discover_out.parent.mkdir(parents=True, exist_ok=True)
    select = select_override or cfg.select
    _run_command(
        [
            cfg.python,
            cfg.discover_script,
            "--date",
            date,
            "--json",
            "--out",
            str(discover_out),
            "--select",
            str(select),
            "--max-results-per-keyword",
            str(cfg.max_results_per_keyword),
        ],
        cwd=repo_root,
        context="paper-daily discovery",
    )
    _assert_discovery_succeeded(discover_out)
    try:
        _run_command(
            [
                cfg.python,
                cfg.generate_feed_script,
                "--repo-root",
                ".",
                "--discovered-json",
                str(discover_out),
                "--date",
                date,
                "--select",
                str(select),
                "--max-results-per-keyword",
                str(cfg.max_results_per_keyword),
                "--score-threshold",
                str(cfg.score_threshold),
            ],
            cwd=repo_root,
            context="paper-daily canonical feed generation",
        )
    except RuntimeError as exc:
        raise RuntimeError(
            f"{exc}\nPrepare summary artifacts first with "
            f"`python3 {cfg.prepare_summary_requests_script} --repo-root . --date {date}` "
            "and run those requests through the runtime skill before retrying."
        ) from exc


def prepare_paper_daily_summary_requests(date: str, cfg: PaperDailyConfig, *, select_override: int | None = None) -> Path:
    repo_root = cfg.repo_root
    requests_out = repo_root / "data" / "paper-learning" / "runs" / date / "paper-daily-summary-requests.json"
    requests_out.parent.mkdir(parents=True, exist_ok=True)
    select = select_override or cfg.select
    _run_command(
        [
            cfg.python,
            cfg.prepare_summary_requests_script,
            "--repo-root",
            ".",
            "--date",
            date,
            "--out",
            str(requests_out),
            "--select",
            str(select),
            "--max-results-per-keyword",
            str(cfg.max_results_per_keyword),
            "--score-threshold",
            str(cfg.score_threshold),
        ],
        cwd=repo_root,
        context="paper-daily summary request preparation",
    )
    return requests_out


def run_paper_daily_discovery(date: str, cfg: PaperDailyConfig, *, select_override: int | None = None) -> Path:
    repo_root = cfg.repo_root
    discover_out = repo_root / "data" / "paper-learning" / "runs" / date / "discovered-papers.json"
    discover_out.parent.mkdir(parents=True, exist_ok=True)
    select = select_override or cfg.select
    _run_command(
        [
            cfg.python,
            cfg.discover_script,
            "--date",
            date,
            "--json",
            "--out",
            str(discover_out),
            "--select",
            str(select),
            "--max-results-per-keyword",
            str(cfg.max_results_per_keyword),
        ],
        cwd=repo_root,
        context="paper-daily discovery",
    )
    _assert_discovery_succeeded(discover_out)
    return discover_out


def load_paper_daily_records(canonical_path: Path, discovered_path: Path | None = None) -> list[DailyPaperRecord]:
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    discovery_by_id = _load_discovery_by_id(discovered_path)
    records: list[DailyPaperRecord] = []
    for item in canonical.get("items", []):
        paper_id = item["paper_id"]
        discovery = discovery_by_id.get(paper_id, {})
        links = item.get("links", {})
        signals = {
            "priority_keyword": discovery.get("priority_keyword", item.get("category_alias", "")),
            "reasons": discovery.get("reasons", []),
        }
        records.append(DailyPaperRecord(
            paper_id=f"arxiv:{paper_id}",
            source="arXiv",
            title=item.get("title", ""),
            authors=list(item.get("authors", [])),
            institutions=item.get("institution") or "",
            abstract=item.get("abstract", ""),
            digest_summary=_bilingual_digest(item.get("render_excerpt", ""), item.get("render_excerpt_en", "")),
            summary_cn=item.get("summary_cn", ""),
            summary_en=item.get("summary_en", ""),
            published_date=item.get("date", canonical.get("run_date", "")),
            run_date=canonical.get("run_date", item.get("date", "")),
            url=links.get("abs") or "",
            pdf_url=links.get("pdf"),
            topic=item.get("category_key", ""),
            score=float(discovery.get("score", 0.0)),
            signals=signals,
            provenance=item.get("provenance", {}),
        ))
    return records


def load_discovered_records(discovered_path: Path, *, run_date: str) -> list[DailyPaperRecord]:
    payload = json.loads(discovered_path.read_text(encoding="utf-8"))
    records: list[DailyPaperRecord] = []
    for item in payload.get("selected", []):
        paper_id = str(item.get("arxiv_id", "")).split("v", 1)[0]
        if not paper_id:
            continue
        abstract = item.get("abstract", "")
        records.append(DailyPaperRecord(
            paper_id=f"arxiv:{paper_id}",
            source="arXiv",
            title=item.get("title", ""),
            authors=list(item.get("authors", [])),
            institutions=", ".join(item.get("institution_matches", []) + item.get("lab_matches", [])),
            abstract=abstract,
            digest_summary=abstract,
            summary_cn="",
            summary_en="",
            published_date=item.get("published", run_date)[:10],
            run_date=run_date,
            url=item.get("abs_url", ""),
            pdf_url=item.get("pdf_url"),
            topic=item.get("priority_keyword", ""),
            score=float(item.get("score", 0.0)),
            signals={
                "priority_keyword": item.get("priority_keyword", ""),
                "reasons": item.get("reasons", []),
            },
            provenance={
                "source": "paper-daily-discovery",
                "summary": "not_generated",
            },
        ))
    return records


def _bilingual_digest(cn: str, en: str) -> str:
    """Combine CN and EN excerpts, stripping the institution-header prefix from each.
    The institution is already stored in a dedicated Notion field, so the "机构:/Institution:"
    line in render_excerpt is redundant there."""
    parts = []
    for text in (cn, en):
        text = (text or "").strip()
        for prefix in ("机构:", "机构：", "Institution:", "Institution："):
            if text.startswith(prefix):
                _, _, rest = text.partition("<br>")
                text = rest.lstrip()
                break
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _load_discovery_by_id(path: Path | None) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict] = {}
    for item in payload.get("selected", []):
        arxiv_id = str(item.get("arxiv_id", "")).split("v", 1)[0]
        if arxiv_id:
            result[arxiv_id] = item
    return result


def _assert_discovery_succeeded(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    query_totals = payload.get("query_totals", {})
    errors = [str(value) for value in query_totals.values() if str(value).startswith("ERROR:")]
    if errors:
        raise RuntimeError(f"paper-daily discovery failed: {'; '.join(errors)}")


def _run_command(args: list[str], *, cwd: Path, context: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        if detail:
            raise RuntimeError(f"{context} failed: {_condense_subprocess_error(detail)}") from exc
        raise RuntimeError(f"{context} failed with exit code {exc.returncode}") from exc


def _condense_subprocess_error(detail: str) -> str:
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    for prefix in ("FileNotFoundError:", "RuntimeError:", "ValueError:"):
        for line in reversed(lines):
            if line.startswith(prefix):
                return line
    return lines[-1] if lines else detail
