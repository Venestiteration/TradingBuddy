import json
import unittest
from datetime import datetime, timezone
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


class FakeEastmoneyNoticeHttpClient:
    def __init__(self, pages, total_hits=None):
        self.pages = pages
        self.total_hits = total_hits if total_hits is not None else sum(
            len(page) for page in pages
        )
        self.get_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        page_index = kwargs["params"]["page_index"]
        page = self.pages[min(page_index - 1, len(self.pages) - 1)]
        return FakeResponse({"data": {"list": page, "total_hits": self.total_hits}})


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
        self.notice_params = kwargs
        return pd.DataFrame(self.notices)

    def stock_news_em(self, **kwargs):
        import pandas as pd
        return pd.DataFrame(self.news)


class FailingAk(FakeAk):
    def stock_news_em(self, **kwargs):
        raise ConnectionError("eastmoney unavailable")


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
        self.assertIn("announcementTime=2026-09-15", item.source_url)

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
        self.assertEqual(news.items[0].published_at, "2026-09-14T23:58:00+00:00")
        self.assertEqual(notices.items[0].published_at, "2026-09-14T16:00:00+00:00")

    def test_eastmoney_notice_direct_endpoint_parses_nested_provider_schema(self):
        client = FakeEastmoneyNoticeHttpClient([
            [{
                "art_code": "AN456",
                "title": "关于签署重大合同的公告",
                "notice_date": "2026-09-15 00:00:00",
                "codes": [{"stock_code": "600519", "short_name": "贵州茅台"}],
                "columns": [{"column_name": "重大合同"}],
            }]
        ])
        result = EastmoneyNoticeAdapter(FakeAk([], []), client).fetch(
            "600519", self.start, self.end, "attempt"
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.provider_item_id, "AN456")
        self.assertEqual(item.category, "重大合同")
        self.assertEqual(item.source_level, "primary")
        self.assertEqual(item.published_at, "2026-09-14T16:00:00+00:00")
        self.assertIn("/600519/AN456.html", item.source_url)
        self.assertEqual(client.get_calls[0][1]["params"]["stock_list"], "600519")

    def test_source_queries_use_shanghai_business_date_across_utc_midnight(self):
        start = datetime(2026, 9, 14, 17, tzinfo=timezone.utc)
        end = datetime(2026, 9, 15, 1, tzinfo=timezone.utc)
        client = FakeHttpClient(self.cninfo)
        CninfoAnnouncementAdapter(client).fetch("600519", start, end, "attempt")
        self.assertEqual(client.post_calls[0][1]["data"]["seDate"], "2026-09-15~2026-09-15")
        fake = FakeAk(self.notices, self.news)
        EastmoneyNoticeAdapter(fake).fetch("600519", start, end, "attempt")
        self.assertEqual(fake.notice_params["begin_date"], "20260915")
        self.assertEqual(fake.notice_params["end_date"], "20260915")
        result = EastmoneyNewsAdapter(fake).fetch("600519", start, end, "attempt")
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].published_at, "2026-09-14T23:58:00+00:00")

    def test_source_queries_span_two_business_dates_at_shanghai_midnight(self):
        start = datetime(2026, 9, 15, 15, 59, tzinfo=timezone.utc)
        end = datetime(2026, 9, 15, 16, 1, tzinfo=timezone.utc)
        client = FakeHttpClient(self.cninfo)

        CninfoAnnouncementAdapter(client).fetch("600519", start, end, "attempt")
        fake = FakeAk(self.notices, self.news)
        EastmoneyNoticeAdapter(fake).fetch("600519", start, end, "attempt")

        self.assertEqual(
            client.post_calls[0][1]["data"]["seDate"],
            "2026-09-15~2026-09-16",
        )
        self.assertEqual(fake.notice_params["begin_date"], "20260915")
        self.assertEqual(fake.notice_params["end_date"], "20260916")

    def test_busy_day_fixed_page_is_reported_as_limited_not_complete(self):
        # Simulate a provider with 15 matching rows, while AKShare exposes 10.
        rows = [
            dict(self.news[0], 新闻链接=f"https://example.test/news/{i}")
            for i in range(15)
        ]
        fake = FakeAk([], rows[:10])
        result = EastmoneyNewsAdapter(fake).fetch(
            "600519", self.start, self.end, "attempt"
        )
        self.assertEqual(len(result.items), 10)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "coverage_limited")

    def test_empty_fixed_page_cannot_certify_90_day_coverage(self):
        result = EastmoneyNewsAdapter(FakeAk([], [])).fetch(
            "600519", self.start, self.end, "attempt"
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "coverage_limited")

    def test_eastmoney_news_error_returns_failed_provider_result(self):
        result = EastmoneyNewsAdapter(FailingAk(self.notices, self.news)).fetch(
            "600519", self.start, self.end, "attempted-at"
        )

        self._assert_failed_result(
            result, "eastmoney_news", "ConnectionError", "attempted-at"
        )

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
