from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from .public_dynamics_types import (
    PROVIDER_CNINFO,
    PROVIDER_EASTMONEY_NEWS,
    PROVIDER_EASTMONEY_NOTICES,
    ProviderResult,
    RawDynamic,
)

CNINFO_BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


class SourceAdapter(Protocol):
    provider: str

    def fetch(
        self, stock_code: str, start: datetime, end: datetime, attempted_at: str
    ) -> ProviderResult: ...


def _string(value) -> str:
    return "" if value is None else str(value).strip()


def _iso(value) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(_string(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="seconds")


def _failed(provider: str, attempted_at: str, exc: Exception) -> ProviderResult:
    return ProviderResult(
        provider=provider,
        status="failed",
        items=(),
        attempted_at=attempted_at,
        error_code=exc.__class__.__name__,
        error_message=str(exc)[:300],
    )


def _cninfo_exchange(stock_code: str) -> str:
    return "sse" if _string(stock_code).startswith(("5", "6", "9")) else "szse"


class CninfoAnnouncementAdapter:
    provider = PROVIDER_CNINFO

    def __init__(self, client: httpx.Client):
        self.client = client

    def fetch(self, stock_code, start, end, attempted_at):
        try:
            exchange = _cninfo_exchange(stock_code)
            stock_response = self.client.get(
                "https://www.cninfo.com.cn/new/data/szse_stock.json",
                timeout=12.0,
            )
            stock_response.raise_for_status()
            stock_map = {
                item["code"]: item["orgId"]
                for item in stock_response.json().get("stockList", [])
            }
            org_id = stock_map[stock_code]
            page_num = 1
            items = []
            while True:
                response = self.client.post(
                    "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                    data={
                        "pageNum": page_num,
                        "pageSize": 30,
                        "column": exchange,
                        "tabName": "fulltext",
                        "stock": f"{stock_code},{org_id}",
                        "seDate": f"{start:%Y-%m-%d}~{end:%Y-%m-%d}",
                        "isHLtitle": "true",
                    },
                    headers={"Referer": "https://www.cninfo.com.cn/"},
                    timeout=12.0,
                )
                response.raise_for_status()
                payload = response.json()
                announcements = payload.get("announcements") or []
                for row in announcements:
                    timestamp = datetime.fromtimestamp(
                        int(row["announcementTime"]) / 1000,
                        tz=timezone.utc,
                    )
                    business_timestamp = timestamp.astimezone(CNINFO_BUSINESS_TZ)
                    adjunct = _string(row.get("adjunctUrl")).lstrip("/")
                    announcement_id = _string(row.get("announcementId"))
                    items.append(
                        RawDynamic(
                            provider=self.provider,
                            provider_item_id=announcement_id,
                            stock_code=stock_code,
                            kind="announcement",
                            category="",
                            title=_string(row.get("announcementTitle")),
                            excerpt="",
                            published_at=timestamp.isoformat(timespec="seconds"),
                            publisher="巨潮资讯网",
                            source_url=(
                                "https://www.cninfo.com.cn/new/disclosure/detail?"
                                f"stockCode={stock_code}&announcementId={announcement_id}"
                                f"&orgId={org_id}"
                                f"&announcementTime={business_timestamp:%Y-%m-%d}"
                            ),
                            document_url=(
                                f"https://static.cninfo.com.cn/{adjunct}"
                                if adjunct
                                else None
                            ),
                            source_level="primary",
                            content_status="title_only",
                            raw_metadata={"org_id": org_id},
                        )
                    )
                total = int(payload.get("totalAnnouncement") or 0)
                if page_num * 30 >= total:
                    break
                page_num += 1
            return ProviderResult(
                self.provider,
                "success" if items else "empty",
                tuple(items),
                attempted_at,
            )
        except Exception as exc:
            return _failed(self.provider, attempted_at, exc)


class EastmoneyNoticeAdapter:
    provider = PROVIDER_EASTMONEY_NOTICES

    def __init__(self, ak_module):
        self.ak = ak_module

    def fetch(self, stock_code, start, end, attempted_at):
        try:
            frame = self.ak.stock_individual_notice_report(
                security=stock_code,
                symbol="全部",
                begin_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            items = tuple(
                RawDynamic(
                    provider=self.provider,
                    provider_item_id=_string(row.get("网址") or row.get("公告标题")),
                    stock_code=stock_code,
                    kind="announcement",
                    category=_string(row.get("公告类型")),
                    title=_string(row.get("公告标题")),
                    excerpt="",
                    published_at=_iso(row.get("公告日期")),
                    publisher="东方财富公告",
                    source_url=_string(row.get("网址")),
                    source_level="primary",
                    content_status="title_only",
                )
                for _, row in frame.iterrows()
                if _string(row.get("公告标题"))
            )
            return ProviderResult(
                self.provider, "success" if items else "empty", items, attempted_at
            )
        except Exception as exc:
            return _failed(self.provider, attempted_at, exc)


class EastmoneyNewsAdapter:
    provider = PROVIDER_EASTMONEY_NEWS

    def __init__(self, ak_module):
        self.ak = ak_module

    def fetch(self, stock_code, start, end, attempted_at):
        try:
            frame = self.ak.stock_news_em(symbol=stock_code)
            range_start = datetime.fromisoformat(_iso(start))
            range_end = datetime.fromisoformat(_iso(end))
            items = []
            for _, row in frame.iterrows():
                published_at = _iso(row.get("发布时间"))
                published = datetime.fromisoformat(published_at)
                if not range_start <= published <= range_end:
                    continue
                title = _string(row.get("新闻标题"))
                if not title:
                    continue
                excerpt = _string(row.get("新闻内容"))
                items.append(
                    RawDynamic(
                        provider=self.provider,
                        provider_item_id=_string(row.get("新闻链接") or title),
                        stock_code=stock_code,
                        kind="news",
                        category="媒体报道",
                        title=title,
                        excerpt=excerpt,
                        published_at=published_at,
                        publisher=_string(row.get("文章来源")) or "来源信息不完整",
                        source_url=_string(row.get("新闻链接")),
                        source_level="secondary",
                        content_status="excerpt" if excerpt else "title_only",
                    )
                )
            result_items = tuple(items)
            return ProviderResult(
                self.provider,
                "success" if result_items else "empty",
                result_items,
                attempted_at,
            )
        except Exception as exc:
            return _failed(self.provider, attempted_at, exc)
