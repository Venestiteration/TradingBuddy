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
    def __init__(self, page):
        self.page = page

    def get(self, url, **kwargs):
        if url.endswith("szse_stock.json"):
            return FakeResponse({"stockList": [{"code": "600519", "orgId": "gssh0600519"}]})
        raise AssertionError(url)

    def post(self, url, **kwargs):
        return FakeResponse(self.page)


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
        result = CninfoAnnouncementAdapter(FakeHttpClient(self.cninfo)).fetch(
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


if __name__ == "__main__":
    unittest.main()
