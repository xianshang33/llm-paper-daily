from __future__ import annotations

import re

_IMAGE_LINE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$")
_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_INLINE_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
_RICH_TEXT_LIMIT = 2000
_PARAGRAPH_LIMIT = 1900  # leave headroom for safe segmentation


def markdown_to_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            language = line[3:].strip() or "plain text"
            if language == "text":
                language = "plain text"
            buffer: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buffer.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # consume closing ```
            blocks.append(_code_block("\n".join(buffer), language))
            continue
        if line.startswith("# "):
            blocks.append(_block("heading_1", line[2:]))
        elif line.startswith("## "):
            blocks.append(_block("heading_2", line[3:]))
        elif line.startswith("### "):
            blocks.append(_block("heading_3", line[4:]))
        elif line.startswith("- "):
            blocks.append(_rich_block("bulleted_list_item", line[2:]))
        else:
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            image_match = _IMAGE_LINE_RE.match(stripped)
            if image_match:
                blocks.append(_image_block(image_match.group(2)))
            else:
                blocks.extend(_paragraph_blocks(line))
        i += 1
    return blocks


def _block(block_type: str, content: str) -> dict:
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": [{"type": "text", "text": {"content": content[:2000]}}]},
    }


def _rich_block(block_type: str, content: str) -> dict:
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": _rich_text_runs(content)},
    }


def _code_block(content: str, language: str = "plain text") -> dict:
    safe = content[:_RICH_TEXT_LIMIT]
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": safe}}],
            "language": language,
        },
    }


def _image_block(url: str) -> dict:
    return {
        "object": "block",
        "type": "image",
        "image": {"type": "external", "external": {"url": url}},
    }


def _paragraph_blocks(line: str) -> list[dict]:
    chunks = _split_long_text(line, _PARAGRAPH_LIMIT)
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text_runs(chunk)},
        }
        for chunk in chunks
    ]


def _split_long_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("。", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(". ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[: cut + 1].rstrip())
        remaining = remaining[cut + 1 :].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _rich_text_runs(text: str) -> list[dict]:
    """Tokenize markdown inline (links, **bold**) into Notion rich_text runs."""
    runs: list[dict] = []
    cursor = 0
    matches: list[tuple[int, int, dict]] = []
    for match in _INLINE_LINK_RE.finditer(text):
        matches.append((match.start(), match.end(), {
            "kind": "link",
            "label": match.group(1),
            "url": match.group(2),
        }))
    for match in _INLINE_BOLD_RE.finditer(text):
        # Skip bold spans that fall inside a link span we already captured.
        if any(start <= match.start() and match.end() <= end for start, end, _ in matches):
            continue
        matches.append((match.start(), match.end(), {
            "kind": "bold",
            "label": match.group(1),
        }))
    matches.sort(key=lambda item: item[0])

    for start, end, payload in matches:
        if start < cursor:
            continue
        if start > cursor:
            runs.append(_text_run(text[cursor:start]))
        if payload["kind"] == "link":
            runs.append(_text_run(payload["label"], link=payload["url"]))
        else:
            runs.append(_text_run(payload["label"], bold=True))
        cursor = end
    if cursor < len(text):
        runs.append(_text_run(text[cursor:]))
    if not runs:
        runs.append(_text_run(text))
    return runs


def _text_run(content: str, *, bold: bool = False, link: str | None = None) -> dict:
    run: dict = {
        "type": "text",
        "text": {"content": content[:_RICH_TEXT_LIMIT]},
    }
    if link:
        run["text"]["link"] = {"url": link}
    if bold:
        run["annotations"] = {"bold": True}
    return run
