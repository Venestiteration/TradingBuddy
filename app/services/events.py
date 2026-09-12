"""事件服务：个股新闻与巨潮公告 → 证据 → 确定性去重与排序。

排序规则（MVP 采用确定性规则，不交给模型）：
1. 按规范化标题与链接去重；
2. 公司公告高于新闻；
3. 财报、业绩、风险提示等关键词加权；
4. 发布时间越近排序越高；
5. 行情明显变化但没有高质量事件时，生成一条只描述行情事实的事件。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .. import database as db
from .evidence import make_evidence, save_evidence

NEWS_TTL = 10 * 60

HIGH_RELEVANCE_KEYWORDS = (
    "财报", "业绩", "预告", "快报", "年报", "半年报", "季报", "分红", "派息", "回购",
    "增减持", "增持", "减持", "风险提示", "警示", "处罚", "立案", "问询", "监管",
    "重组", "收购", "中标", "重大合同", "停牌", "复牌", "退市", "股东", "募集", "定增",
)

MAJOR_SOURCES = (
    "财联社", "证券时报", "上海证券报", "中国证券报", "证券日报", "每日经济新闻",
    "第一财经", "新浪财经", "东方财富", "界面新闻", "21世纪经济报道",
)


def _normalize_title(title: str) -> str:
    return re.sub(r"[\s：:，,。.!！?？\"'（）()\[\]【】]+", "", str(title)).lower()


def _parse_datetime(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 4].strip(), fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    match = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", text)
    if match:
        try:
            return datetime(*map(int, match.groups())).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return None


def _fetch_news(code: str) -> list[dict]:
    import akshare as ak

    frame = ak.stock_news_em(symbol=code)
    if frame is None or frame.empty:
        return []
    items = []
    for _, row in frame.iterrows():
        title = str(row.get("新闻标题") or "").strip()
        if not title:
            continue
        content = str(row.get("新闻内容") or "").strip()
        published = _parse_datetime(row.get("发布时间"))
        items.append(make_evidence(
            stock_code=code,
            source_type="news",
            source_level="secondary",
            title=title,
            excerpt=content,
            published_at=published,
            source_url=str(row.get("新闻链接") or "").strip() or None,
            content_status="excerpt" if len(content) > 40 else ("title_only" if not content else "excerpt"),
            raw={"publisher": str(row.get("文章来源") or "").strip()},
        ))
    return items


def _announcement_columns(frame) -> tuple[str, str, str]:
    """返回 (标题列, 日期列, 链接列)。"""
    columns = list(frame.columns)
    title_col = next((c for c in columns if "标题" in str(c)), None)
    date_col = next((c for c in columns if "日期" in str(c) or "时间" in str(c)), None)
    url_col = next(
        (c for c in columns if "链接" in str(c) or "网址" in str(c) or "url" in str(c).lower()),
        None,
    )
    return title_col, date_col, url_col


def _fetch_announcements(code: str) -> list[dict]:
    import akshare as ak

    start = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    frame = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=code, market="沪深京", start_date=start, end_date=end
    )
    if frame is None or frame.empty:
        return []
    title_col, date_col, url_col = _announcement_columns(frame)
    if not title_col:
        return []
    items = []
    for _, row in frame.iterrows():
        title = str(row.get(title_col) or "").strip()
        if not title:
            continue
        published = _parse_datetime(row.get(date_col)) if date_col else None
        url = str(row.get(url_col) or "").strip() if url_col else ""
        if url and not url.startswith("http"):
            url = ""
        items.append(make_evidence(
            stock_code=code,
            source_type="announcement",
            source_level="primary",
            title=title,
            excerpt=title,
            published_at=published,
            source_url=url or None,
            content_status="title_only",
            raw={"publisher": "巨潮资讯网（公司公告）"},
        ))
    return items


def _score_event(evidence: dict) -> int:
    score = 0
    title = evidence["title"]
    if evidence["source_type"] == "announcement":
        score += 30
    if any(keyword in title for keyword in HIGH_RELEVANCE_KEYWORDS):
        score += 20
    published = evidence.get("published_at")
    if published:
        try:
            age = datetime.now() - datetime.fromisoformat(published)
            if age <= timedelta(days=1):
                score += 25
            elif age <= timedelta(days=3):
                score += 15
            elif age <= timedelta(days=7):
                score += 8
        except ValueError:
            pass
    publisher = str((evidence.get("raw") or {}).get("publisher") or "")
    if any(source in publisher for source in MAJOR_SOURCES):
        score += 5
    return score


def _market_fact_event(code: str, name: str, snapshot: dict, history: dict) -> dict | None:
    """行情明显变化但没有高质量事件时，生成一条只描述行情事实的事件。"""
    price = snapshot.get("price")
    change_pct = snapshot.get("change_pct")
    if price is None or change_pct is None:
        return None
    rows = history.get("rows") or []
    volume_note = ""
    significant_volume = False
    if len(rows) >= 21:
        volumes = [row.get("volume") or 0 for row in rows[-21:-1]]
        latest_volume = rows[-1].get("volume") or 0
        average = sum(volumes) / len(volumes) if volumes else 0
        if average > 0 and latest_volume / average >= 1.5:
            significant_volume = True
            volume_note = f"，成交量较前 20 日均值放大 {latest_volume / average:.1f} 倍"
    significant_move = abs(change_pct) >= 2
    if not (significant_move or significant_volume):
        return None
    date = rows[-1]["date"] if rows else (snapshot.get("price_time") or "")[:10]
    change_text = f"{change_pct:+.2f}%" if change_pct is not None else "未知"
    title = f"{name}行情变动：{date}收盘 {price} 元（{change_text}）"
    excerpt = (
        f"腾讯行情显示，{name}在 {date} 收报 {price} 元，当日涨跌幅 {change_text}{volume_note}。"
        f"以上仅为行情事实，未包含任何原因解释。"
    )
    return make_evidence(
        stock_code=code,
        source_type="market",
        source_level="primary",
        title=title,
        excerpt=excerpt,
        published_at=snapshot.get("price_time") or db.utcnow(),
        source_url=None,
        content_status="full",
        raw={"publisher": "腾讯行情（站内结构化数据）"},
    )


def collect_events(code: str, name: str, snapshot: dict, history: dict, use_cache: bool = True) -> dict:
    """抓取并整理事件列表。返回 {events, errors, fetched_at}。"""
    key = f"events:{code}"
    if use_cache:
        cached = db.kv_get(f"cache:{key}", NEWS_TTL)
        if cached:
            return cached

    errors: list[str] = []
    evidence_items: list[dict] = []
    try:
        evidence_items.extend(_fetch_announcements(code))
    except Exception as exc:
        errors.append(f"公告获取失败: {exc.__class__.__name__}")
    try:
        evidence_items.extend(_fetch_news(code))
    except Exception as exc:
        errors.append(f"新闻获取失败: {exc.__class__.__name__}")

    # 去重：规范化标题 + 链接
    unique: dict[str, dict] = {}
    for item in evidence_items:
        dedup_key = _normalize_title(item["title"])[:120] + "|" + (item["source_url"] or "")
        if dedup_key not in unique:
            unique[dedup_key] = item
    items = list(unique.values())

    # 行情事实事件：仅在缺少高质量事件时补充
    has_high_quality = any(
        item["source_type"] == "announcement"
        or _score_event(item) >= 40
        for item in items
    )
    if not has_high_quality:
        market_event = _market_fact_event(code, name, snapshot, history)
        if market_event:
            items.append(market_event)

    scored = []
    for item in items:
        save_evidence(item)
        scored.append({
            "event_id": item["evidence_id"],
            "evidence_id": item["evidence_id"],
            "title": item["title"],
            "excerpt": item["excerpt"],
            "published_at": item["published_at"],
            "source_type": item["source_type"],
            "source_level": item["source_level"],
            "source_url": item["source_url"],
            "content_status": item["content_status"],
            "publisher": str((item.get("raw") or {}).get("publisher") or ""),
            "priority": _score_event(item),
        })

    type_rank = {"announcement": 0, "market": 1, "news": 2}
    scored.sort(key=lambda event: (-event["priority"], type_rank[event["source_type"]],
                                   event["published_at"] or ""), )
    # 每类来源限额，避免公告把时效性新闻完全挤出首屏
    quota = {"announcement": 10, "news": 12, "market": 2}
    counts: dict[str, int] = {}
    selected: list[dict] = []
    overflow: list[dict] = []
    for event in scored:
        kind = event["source_type"]
        if counts.get(kind, 0) < quota.get(kind, 10):
            counts[kind] = counts.get(kind, 0) + 1
            selected.append(event)
        else:
            overflow.append(event)
    payload = {
        "events": (selected + overflow)[:20],
        "errors": errors,
        "fetched_at": db.utcnow(),
    }
    try:
        db.kv_set(f"cache:{key}", payload)
    except Exception:
        pass
    return payload
