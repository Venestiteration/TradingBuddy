import json
import unittest
from datetime import datetime
from pathlib import Path

from app.services.public_dynamics_sources import (
    CninfoAnnouncementAdapter,
    EastmoneyNewsAdapter,
    EastmoneyNoticeAdapter,
)

FIXTURES = Path(__file__).parent / "fixtures" / "public_dynamics"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, page, stock_list=None):
        self.pages = page if isinstance(page, list) else [page]
        self.stock_list = stock_list or [{"code": "600519", "orgId": "gssh0600519"}]
        self.post_calls = []

    def get(self, url, **kwargs):
        if url.endswith("szse_stock.json"):
            return FakeResponse({"stockList": self.stock_list})
        raise AssertionError(url)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return FakeResponse(self.pages[len(self.post_calls) - 1])


class RaisingResponse:
    def __init__(self, exc):
        self.exc = exc

    def raise_for_status(self):
        raise self.exc


class FailingHttpClient(FakeHttpClient):
    def __init__(self, page, response):
        super().__init__(page)
        self.response = response

    def post(self, url, **kwargs):
        return self.response


class InvalidJsonResponse:
    def raise_for_status(self):
        return None

    def json(self):
        raise ValueError("invalid json")


class InvalidJsonHttpClient(FakeHttpClient):
    def post(self, url, **kwargs):
        return InvalidJsonResponse()


class FakeAk:
    def __init__(self, notices, news):
        self.notices = notices
        self.news = news

    def stock_individual_notice_report(self, **kwargs):
        import pandas as pd
        return pd.DataFrame(self.notices)

    def stock_news_em(self, **kwargs):
        import pandas as pd
        return pd.DataFrame(self.news)


class PublicDynamicsSourcesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cninfo = json.loads((FIXTURES / "cninfo_page.json").read_text())
        cls.notices = json.loads((FIXTURES / "eastmoney_notices.json").read_text())
        cls.news = json.loads((FIXTURES / "eastmoney_news.json").read_text())
        cls.start = datetime(2026, 6, 17)
        cls.end = datetime(2026, 9, 15, 9, 32)

    def test_cninfo_preserves_pdf_and_primary_source(self):
        client = FakeHttpClient(self.cninfo)
        result = CninfoAnnouncementAdapter(client).fetch(
            "600519", self.start, self.end, "2026-09-15T09:32:00+08:00"
        )
        self.assertEqual(result.status, "success")
        item = result.items[0]
        self.assertEqual(item.provider_item_id, "1212345678")
        self.assertEqual(item.source_level, "primary")
        self.assertEqual(
            item.document_url,
            "https://static.cninfo.com.cn/finalpage/2026-09-15/1212345678.PDF",
        )
        self.assertEqual(client.post_calls[0][1]["data"]["column"], "sse")
        self.assertEqual(client.post_calls[0][1]["data"]["stock"], "600519,gssh0600519")
        self.assertEqual(item.published_at, "2026-09-14T16:41:00+00:00")

    def test_eastmoney_adapters_preserve_category_and_original_publisher(self):
        fake = FakeAk(self.notices, self.news)
        notices = EastmoneyNoticeAdapter(fake).fetch(
            "600519", self.start, self.end, "2026-09-15T09:32:00+08:00"
        )
        news = EastmoneyNewsAdapter(fake).fetch(
            "600519", self.start, self.end, "2026-09-15T09:32:00+08:00"
        )
        self.assertEqual(notices.items[0].category, "风险提示")
        self.assertEqual(news.items[0].publisher, "证券时报")
        self.assertEqual(news.items[0].kind, "news")
        self.assertEqual(news.items[0].published_at, "2026-09-15T07:58:00+00:00")

    def test_cninfo_fetches_all_pages_with_exchange_specific_parameters(self):
        second_page = {**self.cninfo, "totalAnnouncement": 31}
        first_page = {**self.cninfo, "totalAnnouncement": 31}
        client = FakeHttpClient([first_page, second_page])

        result = CninfoAnnouncementAdapter(client).fetch(
            "600519", self.start, self.end, "2026-09-15T09:32:00+08:00"
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.items), 2)
        self.assertEqual(
            [call[1]["data"]["pageNum"] for call in client.post_calls], [1, 2]
        )
        self.assertTrue(
            all(call[1]["data"]["column"] == "sse" for call in client.post_calls)
        )

    def test_cninfo_http_error_returns_failed_provider_result(self):
        result = CninfoAnnouncementAdapter(
            FailingHttpClient(self.cninfo, RaisingResponse(RuntimeError("server error")))
        ).fetch("600519", self.start, self.end, "attempted-at")

        self._assert_failed_result(result, "cninfo", "RuntimeError", "attempted-at")

    def test_cninfo_json_parse_error_returns_failed_provider_result(self):
        result = CninfoAnnouncementAdapter(InvalidJsonHttpClient(self.cninfo)).fetch(
            "600519", self.start, self.end, "attempted-at"
        )

        self._assert_failed_result(result, "cninfo", "ValueError", "attempted-at")

    def test_cninfo_missing_required_field_returns_failed_provider_result(self):
        incomplete = {"totalAnnouncement": 1, "announcements": [{"announcementId": "1"}]}
        result = CninfoAnnouncementAdapter(FakeHttpClient(incomplete)).fetch(
            "600519", self.start, self.end, "attempted-at"
        )

        self._assert_failed_result(result, "cninfo", "KeyError", "attempted-at")

    def _assert_failed_result(self, result, provider, error_code, attempted_at):
        self.assertEqual(result.provider, provider)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.items, ())
        self.assertEqual(result.error_code, error_code)
        self.assertEqual(result.attempted_at, attempted_at)


if __name__ == "__main__":
    unittest.main()
