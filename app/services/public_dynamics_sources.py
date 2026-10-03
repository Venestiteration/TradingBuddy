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
        parsed = parsed.replace(tzinfo=CNINFO_BUSINESS_TZ)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="seconds")


def _business_time(value: datetime) -> datetime:
    return datetime.fromisoformat(_iso(value)).astimezone(CNINFO_BUSINESS_TZ)


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
                        "seDate": f"{_business_time(start):%Y-%m-%d}~{_business_time(end):%Y-%m-%d}",
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
    endpoint = "https://np-anotice-stock.eastmoney.com/api/security/ann"

    def __init__(self, ak_module, client: httpx.Client | None = None):
        self.ak = ak_module
        self.client = client

    def _fetch_direct(self, stock_code, start, end):
        """Read the structured Eastmoney endpoint instead of AKShare's fragile frame.

        AKShare's notice helper currently assumes every response contains a
        Chinese ``代码`` column. Eastmoney now returns nested ``codes`` and
        ``columns`` objects, so parsing the provider response here preserves
        the same evidence boundary without depending on that internal schema.
        """
        page_index = 1
        page_size = 100
        items = []
        start_date = _business_time(start).strftime("%Y%m%d")
        end_date = _business_time(end).strftime("%Y%m%d")
        while page_index <= 20:
            response = self.client.get(
                self.endpoint,
                params={
                    "sr": "-1",
                    "page_size": page_size,
                    "page_index": page_index,
                    "ann_type": "A",
                    "client_source": "web",
                    "f_node": "0",
                    "s_node": "0",
                    "stock_list": stock_code,
                    "begin_time": start_date,
                    "end_time": end_date,
                },
                headers={"Referer": "https://data.eastmoney.com/"},
                timeout=12.0,
            )
            response.raise_for_status()
            payload = response.json() or {}
            data = payload.get("data") or {}
            rows = data.get("list") or []
            for row in rows:
                codes = row.get("codes") or []
                matching_code = next(
                    (
                        code
                        for code in codes
                        if _string(code.get("stock_code")) == _string(stock_code)
                    ),
                    codes[0] if codes else {},
                )
                columns = row.get("columns") or []
                column = columns[0] if columns else {}
                article_code = _string(row.get("art_code"))
                title = _string(row.get("title") or row.get("title_ch"))
                if not title:
                    continue
                source_url = (
                    f"https://data.eastmoney.com/notices/detail/{stock_code}/"
                    f"{article_code}.html"
                    if article_code
                    else ""
                )
                published_value = row.get("notice_date") or row.get("display_time")
                if not published_value:
                    continue
                items.append(
                    RawDynamic(
                        provider=self.provider,
                        provider_item_id=article_code or source_url or title,
                        stock_code=stock_code,
                        kind="announcement",
                        category=_string(column.get("column_name")),
                        title=title,
                        excerpt="",
                        published_at=_iso(published_value),
                        publisher="东方财富公告",
                        source_url=source_url,
                        source_level="primary",
                        content_status="title_only",
                        raw_metadata={
                            "short_name": _string(matching_code.get("short_name")),
                            "direct_endpoint": self.endpoint,
                        },
                    )
                )
            total_hits = int(data.get("total_hits") or 0)
            if not rows or len(rows) < page_size or page_index * page_size >= total_hits:
                break
            page_index += 1
        return tuple(items)

    def fetch(self, stock_code, start, end, attempted_at):
        try:
            if self.client is not None:
                items = self._fetch_direct(stock_code, start, end)
            else:
                frame = self.ak.stock_individual_notice_report(
                    security=stock_code,
                    symbol="全部",
                    begin_date=_business_time(start).strftime("%Y%m%d"),
                    end_date=_business_time(end).strftime("%Y%m%d"),
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
                # AKShare exposes only a fixed first page, with no coverage or
                # exhaustion marker. Even an empty page cannot certify a window.
                "failed",
                result_items,
                attempted_at,
                error_code="coverage_limited",
                error_message="新闻接口仅提供固定首页，无法确认请求时间窗口的完整覆盖；已保留本页新闻。",
            )
        except Exception as exc:
            return _failed(self.provider, attempted_at, exc)
