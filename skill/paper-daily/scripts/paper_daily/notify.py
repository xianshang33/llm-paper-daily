"""Feishu (Lark) custom-bot notification for the paper-daily producer.

Self-contained on purpose: paper-daily is the foundational layer, so this module
depends only on the standard library and the local ``CanonicalPaper`` shape. It is
a *reminder* notifier (a lightweight card with the published paper list), not the
full-report delivery that ``paper_learning.feishu_client`` performs.

Configuration is environment-driven and fully optional:

- ``FEISHU_WEBHOOK_URL``    custom-bot webhook; when unset the notifier is a no-op.
- ``FEISHU_WEBHOOK_SECRET`` optional signing secret (Feishu "签名校验").

Network/credential failures never raise to the caller — finalize must stay green
even if the chat is unreachable; the failure is reported in the returned result.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

WEBHOOK_URL_ENV = "FEISHU_WEBHOOK_URL"
WEBHOOK_SECRET_ENV = "FEISHU_WEBHOOK_SECRET"
DEFAULT_HEADER = "📚 今日 LLM/Agent 日报已发布"
MAX_LISTED_PAPERS = 20


@dataclass(frozen=True)
class NotifyResult:
    ok: bool
    status: str  # sent | skipped | failed
    message: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "status": self.status, "message": self.message, "data": self.data}


def _abs_url(paper: Any) -> str:
    """Best-effort abstract URL for a canonical paper (or a bare dict)."""
    links = getattr(paper, "links", None)
    if links is None and isinstance(paper, dict):
        links = paper.get("links")
    if isinstance(links, dict):
        for key in ("abs", "html", "pdf"):
            if links.get(key):
                return str(links[key])
    paper_id = getattr(paper, "paper_id", None) or (paper.get("paper_id") if isinstance(paper, dict) else None)
    return f"https://arxiv.org/abs/{paper_id}" if paper_id else ""


def _title(paper: Any) -> str:
    title = getattr(paper, "title", None)
    if title is None and isinstance(paper, dict):
        title = paper.get("title")
    return str(title or "(untitled)").strip()


def build_card(date: str, papers: Sequence[Any], *, header: str = DEFAULT_HEADER) -> dict[str, Any]:
    """Build a Feishu interactive card summarising the finalized daily report."""
    count = len(papers)
    lines = [f"**日期 (UTC submittedDate):** {date}", f"**入选论文:** {count} 篇", ""]
    for idx, paper in enumerate(papers[:MAX_LISTED_PAPERS], start=1):
        url = _abs_url(paper)
        title = _title(paper).replace("\n", " ")
        lines.append(f"{idx}. [{title}]({url})" if url else f"{idx}. {title}")
    if count > MAX_LISTED_PAPERS:
        lines.append(f"\n… 以及另外 {count - MAX_LISTED_PAPERS} 篇，详见 README / feed。")
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": header}},
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}],
    }


def _sign(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class FeishuNotifier:
    def __init__(
        self,
        *,
        webhook_url: str | None = None,
        secret: str | None = None,
        dry_run: bool = False,
        timeout: int = 15,
    ) -> None:
        self.webhook_url = webhook_url if webhook_url is not None else os.environ.get(WEBHOOK_URL_ENV, "")
        self.secret = secret if secret is not None else os.environ.get(WEBHOOK_SECRET_ENV, "")
        self.dry_run = dry_run
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.webhook_url)

    def notify_finalized(self, date: str, papers: Sequence[Any], *, header: str = DEFAULT_HEADER) -> NotifyResult:
        card = build_card(date, papers, header=header)
        payload: dict[str, Any] = {"msg_type": "interactive", "card": card}

        if not self.configured:
            return NotifyResult(True, "skipped", f"no webhook ({WEBHOOK_URL_ENV} unset); notification skipped", {})
        if self.dry_run:
            return NotifyResult(True, "skipped", "dry-run; notification not sent", {"payload": payload})

        if self.secret:
            timestamp = int(time.time())
            payload["timestamp"] = str(timestamp)
            payload["sign"] = _sign(timestamp, self.secret)

        request = Request(
            self.webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            return NotifyResult(False, "failed", f"feishu request error: {exc}", {})

        # Feishu returns {"code":0,...} or {"StatusCode":0,...} on success.
        code = body.get("code", body.get("StatusCode", 0))
        if code in (0, "0"):
            return NotifyResult(True, "sent", "feishu reminder sent", body)
        return NotifyResult(False, "failed", f"feishu rejected payload: {body}", body)
