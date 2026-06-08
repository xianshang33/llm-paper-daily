import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from skill.paper_daily_import import add_paper_daily_path

add_paper_daily_path()

from paper_daily.notify import FeishuNotifier, build_card


class FakePaper:
    def __init__(self, paper_id, title, abs_url):
        self.paper_id = paper_id
        self.title = title
        self.links = {"abs": abs_url, "pdf": None}


class BuildCardTests(unittest.TestCase):
    def test_card_lists_papers_with_links(self):
        papers = [FakePaper("2606.00001", "A Great Paper", "https://arxiv.org/abs/2606.00001")]
        card = build_card("2026-06-07", papers)
        content = card["elements"][0]["text"]["content"]
        self.assertIn("2026-06-07", content)
        self.assertIn("1 篇", content)
        self.assertIn("[A Great Paper](https://arxiv.org/abs/2606.00001)", content)

    def test_card_truncates_and_notes_overflow(self):
        papers = [FakePaper(f"id{i}", f"T{i}", f"https://arxiv.org/abs/id{i}") for i in range(25)]
        content = build_card("2026-06-07", papers)["elements"][0]["text"]["content"]
        self.assertIn("另外 5 篇", content)

    def test_falls_back_to_arxiv_url_when_links_missing(self):
        papers = [{"paper_id": "2606.00009", "title": "No Links"}]
        content = build_card("2026-06-07", papers)["elements"][0]["text"]["content"]
        self.assertIn("https://arxiv.org/abs/2606.00009", content)


class NotifierTests(unittest.TestCase):
    def test_unconfigured_is_skipped_not_failed(self):
        notifier = FeishuNotifier(webhook_url="")
        result = notifier.notify_finalized("2026-06-07", [])
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "skipped")

    def test_dry_run_builds_payload_without_sending(self):
        notifier = FeishuNotifier(webhook_url="https://example.com/hook", dry_run=True)
        result = notifier.notify_finalized("2026-06-07", [FakePaper("2606.1", "X", "u")])
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.data["payload"]["msg_type"], "interactive")

    def test_send_success_posts_signed_payload(self):
        sent = {}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"code": 0, "msg": "success"}).encode("utf-8")

        def fake_urlopen(request, timeout=0):
            sent["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResp()

        notifier = FeishuNotifier(webhook_url="https://example.com/hook", secret="topsecret")
        with patch("paper_daily.notify.urlopen", fake_urlopen):
            result = notifier.notify_finalized("2026-06-07", [FakePaper("2606.1", "X", "u")])

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "sent")
        body = sent["body"]
        self.assertIn("sign", body)
        self.assertIn("timestamp", body)
        expected = base64.b64encode(
            hmac.new(f"{body['timestamp']}\ntopsecret".encode(), b"", hashlib.sha256).digest()
        ).decode()
        self.assertEqual(body["sign"], expected)

    def test_network_error_is_failed_not_raised(self):
        def boom(request, timeout=0):
            raise OSError("connection refused")

        notifier = FeishuNotifier(webhook_url="https://example.com/hook")
        with patch("paper_daily.notify.urlopen", boom):
            result = notifier.notify_finalized("2026-06-07", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")

    def test_nonzero_code_is_failed(self):
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"code": 19021, "msg": "sign match fail"}).encode("utf-8")

        notifier = FeishuNotifier(webhook_url="https://example.com/hook")
        with patch("paper_daily.notify.urlopen", lambda request, timeout=0: FakeResp()):
            result = notifier.notify_finalized("2026-06-07", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")


if __name__ == "__main__":
    unittest.main()
