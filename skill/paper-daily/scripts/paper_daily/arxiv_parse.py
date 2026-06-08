from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from .models import PaperCandidate

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def normalize_arxiv_id(raw: str) -> str:
    raw = raw.split("/abs/")[-1].strip()
    return re.sub(r"v\d+$", "", raw)


def parse_entry(entry: ET.Element, *, keyword: str, keyword_rank: int, query_total: int) -> PaperCandidate:
    abs_url = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
    version_id = abs_url.split("/abs/")[-1] if "/abs/" in abs_url else abs_url
    arxiv_id = normalize_arxiv_id(version_id)
    title = clean_text(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
    abstract = clean_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
    authors = [
        clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
        for author in entry.findall("atom:author", ATOM_NS)
    ]
    categories = [node.attrib.get("term", "") for node in entry.findall("atom:category", ATOM_NS)]
    primary_node = entry.find("arxiv:primary_category", ATOM_NS)
    primary_category = primary_node.attrib.get("term") if primary_node is not None else None
    pdf_url = None
    for link in entry.findall("atom:link", ATOM_NS):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href")
            break

    return PaperCandidate(
        arxiv_id=arxiv_id,
        version_id=version_id,
        title=title,
        abstract=abstract,
        authors=authors,
        categories=categories,
        primary_category=primary_category,
        published=entry.findtext("atom:published", default="", namespaces=ATOM_NS),
        updated=entry.findtext("atom:updated", default="", namespaces=ATOM_NS),
        abs_url=abs_url,
        pdf_url=pdf_url,
        priority_keyword=keyword,
        keyword_rank=keyword_rank,
        query_total=query_total,
    )


def clean_text(value: str) -> str:
    return " ".join(value.split())


def parse_listing_candidates(content: str, *, date: str, category: str) -> list[PaperCandidate]:
    header = format_listing_header(date)
    section_match = re.search(
        rf"<h3>\s*{re.escape(header)}.*?</h3>(.*?)(?:<h3>|</dl>)",
        content,
        re.S,
    )
    if not section_match:
        return []

    section = section_match.group(1)
    entries = re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", section, re.S)
    candidates = []
    for dt_html, dd_html in entries:
        arxiv_match = re.search(r'href\s*=\s*"/abs/([^"]+)"', dt_html)
        if not arxiv_match:
            continue
        version_id = arxiv_match.group(1).strip()
        arxiv_id = normalize_arxiv_id(version_id)
        title = parse_descriptor_block(dd_html, "Title:")
        authors = parse_listing_authors(dd_html)
        categories = parse_listing_categories(dd_html, fallback=[category])
        candidate = PaperCandidate(
            arxiv_id=arxiv_id,
            version_id=version_id,
            title=title,
            abstract="",
            authors=authors,
            categories=categories,
            primary_category=categories[0] if categories else category,
            published=f"{date}T00:00:00Z",
            updated=f"{date}T00:00:00Z",
            abs_url=f"https://arxiv.org/abs/{version_id}",
            pdf_url=build_pdf_url(version_id),
            priority_keyword="Agent",
            keyword_rank=1,
            query_total=0,
        )
        candidates.append(candidate)
    return candidates


def parse_abs_title(content: str) -> str:
    match = re.search(r'<h1[^>]*class="title[^"]*"[^>]*>(.*?)</h1>', content, re.S)
    if not match:
        return ""
    inner = re.sub(r'<span[^>]*class="descriptor"[^>]*>.*?</span>', "", match.group(1), flags=re.S)
    return clean_text(strip_html(html.unescape(inner)))


def parse_abs_abstract(content: str) -> str:
    match = re.search(r"Abstract:</span>(.*?)</blockquote>", content, re.S)
    if not match:
        return ""
    return clean_text(strip_html(match.group(1)))


def parse_abs_authors(content: str) -> list[str]:
    match = re.search(r'Authors:</span>(.*?)</div>', content, re.S)
    if not match:
        return []
    authors = re.findall(r">([^<]+)</a>", match.group(1))
    return [clean_text(html.unescape(author)) for author in authors]


def parse_abs_categories(content: str, *, fallback: list[str]) -> tuple[list[str], str | None]:
    subjects_match = re.search(r'<td class="tablecell subjects">(.*?)</td>', content, re.S)
    if not subjects_match:
        return fallback, fallback[0] if fallback else None
    categories = re.findall(r"\(([a-zA-Z.\-]+)\)", subjects_match.group(1))
    primary_match = re.search(r'<span class="primary-subject">.*?</span>\s*\(([a-zA-Z.\-]+)\)', subjects_match.group(1), re.S)
    primary = primary_match.group(1) if primary_match else (categories[0] if categories else None)
    return categories or fallback, primary


def parse_abs_version_id(content: str) -> str | None:
    match = re.search(r"arXiv:(\d{4}\.\d{4,5}(?:v\d+)?)", content)
    return match.group(1) if match else None


def parse_descriptor_block(content: str, descriptor: str) -> str:
    match = re.search(
        rf"<span class='descriptor'>{re.escape(descriptor)}</span>(.*?)</div>",
        content,
        re.S,
    )
    if not match:
        return ""
    return clean_text(strip_html(match.group(1)))


def parse_listing_authors(content: str) -> list[str]:
    match = re.search(r"<div class='list-authors'>(.*?)</div>", content, re.S)
    if not match:
        return []
    authors = re.findall(r">([^<]+)</a>", match.group(1))
    return [clean_text(html.unescape(author)) for author in authors]


def parse_listing_categories(content: str, *, fallback: list[str]) -> list[str]:
    match = re.search(r"<div class='list-subjects'>(.*?)</div>", content, re.S)
    if not match:
        return fallback
    categories = re.findall(r"\(([a-zA-Z.\-]+)\)", match.group(1))
    return categories or fallback


def parse_abs_submission_dates(content: str, *, fallback_published: str, fallback_updated: str) -> tuple[str, str]:
    history = re.findall(r"<strong>\[v\d+\]</strong>\s*([A-Za-z]{3}, \d{1,2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} UTC)", content)
    if not history:
        return fallback_published, fallback_updated
    timestamps = [parse_arxiv_datetime(value) for value in history]
    return timestamps[0], timestamps[-1]


def format_listing_header(date: str) -> str:
    return datetime.strptime(date, "%Y-%m-%d").strftime("%a, %d %b %Y").replace(" 0", " ")


def strip_html(content: str) -> str:
    content = re.sub(r"<[^>]+>", " ", content)
    return html.unescape(content)


def build_pdf_url(version_id: str) -> str:
    return f"https://arxiv.org/pdf/{version_id}"


def parse_arxiv_datetime(raw: str) -> str:
    return datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def candidate_submitted_on(candidate: PaperCandidate, date: str) -> bool:
    return candidate.published.startswith(f"{date}T")
