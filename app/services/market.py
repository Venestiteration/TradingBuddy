"""真实行情服务：股票清单、腾讯实时快照、腾讯/新浪/AkShare 历史日线与技术指标。

迁移自个人项目 A-Share-Data-Visualization 的 MarketCollector 与
SingleStockService._normalize_history / technical_indicators，并增加
超时控制、有限重试、TTL 缓存与最近有效数据降级。
"""
from __future__ import annotations

import math
import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable

import numpy as np
import pandas as pd
import requests

from ..config import settings
from .. import database as db

UNIVERSE_TTL = 24 * 3600
SNAPSHOT_TTL = 60
HISTORY_TTL = 30 * 60

# 进程内 TTL 缓存：key -> (expires_at, value)
_memory_cache: dict[str, tuple[float, Any]] = {}

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "Chrome/124 Safari/537.36"
)


class MarketDataError(RuntimeError):
    """外部行情数据请求最终失败。"""

    def __init__(self, message: str, source: str = ""):
        super().__init__(message)
        self.source = source


def retry_call(call: Callable, attempts: int = 3, label: str = "") -> Any:
    error: Exception | None = None
    for index in range(attempts):
        try:
            return call()
        except Exception as exc:  # 外部数据源可能瞬时失败
            error = exc
            if index < attempts - 1:
                time.sleep(0.8 * (index + 1))
    raise MarketDataError(f"{label or '数据请求'}连续失败: {error}", source=label) from error


def normalize_code(raw: str) -> str:
    code = re.sub(r"\D", "", str(raw))
    if len(code) == 6 and code.startswith(("0", "3", "6")):
        return code
    raise ValueError("仅支持沪深交易所代码以 0、3 或 6 开头的六位 A 股代码")


def market_code(code: str) -> str:
    return ("sh" if code.startswith("6") else "sz") + code


def clean_number(value: Any, digits: int | None = None) -> float | None:
    try:
        text = str(value).replace("%", "").replace(",", "")
        number = float(text)
        if not math.isfinite(number):
            return None
        return round(number, digits) if digits is not None else number
    except (TypeError, ValueError):
        return None


def _cache_get(key: str, ttl: float) -> tuple[Any | None, Any | None]:
    """返回 (有效缓存, 最近缓存)；最近缓存用于失败降级。"""
    entry = _memory_cache.get(key)
    if entry:
        expires_at, value = entry
        if expires_at > time.time():
            return value, value
    stored = db.kv_get_stale(f"cache:{key}")
    value = stored.get("value") if stored else None
    if value is not None and stored and _kv_age_seconds(stored) < ttl:
        return value, value
    return None, value


def _kv_age_seconds(stored: dict) -> float:
    try:
        fetched = datetime.fromisoformat(stored["fetched_at"])
        return (datetime.now().astimezone() - fetched).total_seconds()
    except (KeyError, ValueError, TypeError):
        return 0.0


def _cache_set(key: str, value: Any, ttl: float) -> None:
    _memory_cache[key] = (time.time() + ttl, value)
    try:
        db.kv_set(f"cache:{key}", {"value": value})
    except Exception:
        pass  # 缓存写库失败不影响主流程


class MarketService:
    """行情、清单与指标计算。"""

    def __init__(self):
        self.timeout = settings.request_timeout_seconds

    # ---------- 股票清单 ----------

    def universe(self) -> list[dict]:
        cached, stale = _cache_get("universe", UNIVERSE_TTL)
        if cached:
            return cached
        try:
            import akshare as ak

            frame = retry_call(ak.stock_info_a_code_name, attempts=2, label="股票清单")
            frame = frame.rename(columns={"代码": "code", "名称": "name"})
            frame["code"] = frame["code"].astype(str).str.zfill(6)
            frame = frame[frame["code"].str.startswith(("0", "3", "6"))]
            frame = frame[~frame["name"].astype(str).str.contains("退", case=False, na=False)]
            data = (
                frame.drop_duplicates("code")[["code", "name"]]
                .astype(str)
                .to_dict("records")
            )
            if data:
                _cache_set("universe", data, UNIVERSE_TTL)
                return data
        except Exception:
            pass
        if stale:
            return stale
        raise MarketDataError("股票清单获取失败且无可用缓存", source="universe")

    def search(self, text: str, limit: int = 10) -> list[dict]:
        text = (text or "").strip()
        if not text:
            return []
        results: list[dict] = []
        if re.fullmatch(r"\d{6}", text):
            code = text
            name = self._name_for(code)
            if name:
                return [{"code": code, "name": name}]
            results.append({"code": code, "name": code})  # 允许直接输入六位代码
        keyword = text.lower()
        for item in self.universe():
            name = str(item.get("name", ""))
            code = str(item.get("code", ""))
            if keyword in name.lower() or keyword in code:
                results.append({"code": code, "name": name})
                if len(results) >= limit:
                    break
        return results

    def _name_for(self, code: str) -> str | None:
        try:
            for item in self.universe():
                if item.get("code") == code:
                    return str(item.get("name", code))
        except Exception:
            pass
        # 股票清单不可用时允许直接用代码建立本地资产；后续行情请求
        # 若成功，会在总览中返回真实名称和行情，避免添加动作被外部
        # 清单接口阻塞。
        return None

    def stock_name(self, code: str) -> str:
        return self._name_for(code) or code

    # ---------- 实时快照 ----------

    def snapshot(self, code: str, use_cache: bool = True) -> dict:
        key = f"snapshot:{code}"
        if use_cache:
            cached, stale = _cache_get(key, SNAPSHOT_TTL)
            if cached:
                cached = dict(cached)
                cached["stale"] = False
                return cached
        else:
            stale = _cache_get(key, SNAPSHOT_TTL)[1]
        try:
            data = self._fetch_snapshot(code)
            data["stale"] = False
            _cache_set(key, data, SNAPSHOT_TTL)
            return data
        except Exception:
            if stale:
                data = dict(stale)
                data["stale"] = True
                return data
            raise MarketDataError(f"实时行情获取失败 {code}", source="snapshot")

    def _fetch_snapshot(self, code: str) -> dict:
        mc = market_code(code)
        response = requests.get(
            f"https://qt.gtimg.cn/q={mc}",
            headers={"Referer": "https://finance.qq.com/", "User-Agent": _USER_AGENT},
            timeout=self.timeout,
        )
        response.raise_for_status()
        response.encoding = "gbk"
        match = re.search(r'="(.*)";', response.text)
        fields = match.group(1).split("~") if match else []
        if len(fields) < 40 or not fields[1]:
            raise MarketDataError("腾讯行情返回格式异常", source="snapshot")

        def number(index: int, digits: int | None = None) -> float | None:
            return clean_number(fields[index], digits) if len(fields) > index else None

        raw_time = fields[30] if len(fields) > 30 else ""
        price_time = None
        if re.fullmatch(r"\d{14}", raw_time):
            price_time = datetime.strptime(raw_time, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        price = number(3, 2)
        prev_close = number(4, 2)
        change_pct = number(32, 2)
        volume = number(6)          # 单位：手
        amount = number(37)         # 单位：万元
        if amount is not None:
            amount = amount * 1e4   # 统一为元
        return {
            "code": code,
            "name": fields[1],
            "market": "sh" if mc.startswith("sh") else "sz",
            "price": price,
            "prev_close": prev_close,
            "open": number(5, 2),
            "high": number(33, 2),
            "low": number(34, 2),
            "change_pct": change_pct,
            "volume": volume,          # 手
            "amount": amount,          # 元
            "pe_dynamic": number(39, 2),
            "pb": number(46, 2),
            "market_cap": number(45),  # 亿元
            "price_time": price_time,
            "fetched_at": db.utcnow(),
            "source": "腾讯行情",
        }

    # ---------- 历史日线 ----------

    def history(self, code: str, count: int = 320, use_cache: bool = True) -> dict:
        key = f"history:{code}:{count}"
        if use_cache:
            cached, stale = _cache_get(key, HISTORY_TTL)
            if cached:
                cached = dict(cached)
                cached["stale"] = False
                return cached
        else:
            stale = _cache_get(key, HISTORY_TTL)[1]
        try:
            data = self._fetch_history(code, count)
            data["stale"] = False
            _cache_set(key, data, HISTORY_TTL)
            return data
        except Exception:
            if stale:
                data = dict(stale)
                data["stale"] = True
                return data
            raise MarketDataError(f"历史行情获取失败 {code}", source="history")

    def _fetch_history(self, code: str, count: int) -> dict:
        frame = None
        try:
            frame = retry_call(
                lambda: self._tencent_or_sina_history(code, count), attempts=2, label="腾讯/新浪日线"
            )
        except Exception:
            pass
        if frame is None or frame.empty:
            frame = retry_call(lambda: self._akshare_history(code, count), attempts=2, label="AkShare 日线")
        normalized = self._normalize_history(frame).tail(count)
        if normalized.empty:
            raise MarketDataError(f"未获取到 {code} 的历史行情", source="history")
        enriched = self.technical_indicators(normalized)
        rows = self._history_records(enriched)
        return {
            "code": code,
            "rows": rows,
            "count": len(rows),
            "data_time": rows[-1]["date"] if rows else None,
            "fetched_at": db.utcnow(),
            "source": "腾讯前复权日线 / 新浪日线 / AkShare",
        }

    def _tencent_or_sina_history(self, code: str, count: int) -> pd.DataFrame:
        mc = market_code(code)
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mc},day,,,{count},qfq"
        response = requests.get(
            url, headers={"User-Agent": _USER_AGENT, "Referer": "https://gu.qq.com/"}, timeout=self.timeout
        )
        response.raise_for_status()
        payload = response.json().get("data", {}).get(mc, {})
        records = payload.get("qfqday") or payload.get("day")
        if records:
            return pd.DataFrame(
                [row[:6] for row in records],
                columns=["date", "open", "close", "high", "low", "volume"],
            )
        sina_url = (
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "CN_MarketData.getKLineData"
        )
        response = requests.get(
            sina_url,
            params={"symbol": mc, "scale": 240, "ma": 5, "datalen": count},
            headers={"User-Agent": _USER_AGENT},
            timeout=self.timeout,
        )
        response.raise_for_status()
        frame = pd.DataFrame(response.json())
        if "day" in frame.columns:
            frame = frame.rename(columns={"day": "date"})
        return frame

    def _akshare_history(self, code: str, count: int) -> pd.DataFrame:
        import akshare as ak

        start = (datetime.now() - timedelta(days=int(count * 1.7) + 40)).strftime("%Y%m%d")
        frame = ak.stock_zh_a_hist(
            symbol=code, period="daily", start_date=start,
            end_date=datetime.now().strftime("%Y%m%d"), adjust="qfq",
        )
        return frame.rename(
            columns={
                "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
                "收盘": "close", "成交量": "volume", "成交额": "amount",
            }
        )

    @staticmethod
    def _normalize_history(history: pd.DataFrame) -> pd.DataFrame:
        frame = history.copy()
        for column in ("open", "high", "low", "close", "volume"):
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if "amount" in frame:
            frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
        if "date" in frame:
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["date"]).sort_values("date").set_index("date")
        else:
            frame.index = pd.to_datetime(frame.index, errors="coerce")
            frame = frame[~frame.index.isna()].sort_index()
        return frame.dropna(subset=["open", "high", "low", "close"])

    @staticmethod
    def technical_indicators(history: pd.DataFrame) -> pd.DataFrame:
        frame = history.copy()
        close = frame["close"]
        for days in (5, 10, 20, 60):
            frame[f"MA{days}"] = close.rolling(days).mean()

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        frame["MACD_DIF"] = ema12 - ema26
        frame["MACD_DEA"] = frame["MACD_DIF"].ewm(span=9, adjust=False).mean()
        frame["MACD"] = 2 * (frame["MACD_DIF"] - frame["MACD_DEA"])

        low9 = frame["low"].rolling(9, min_periods=9).min()
        high9 = frame["high"].rolling(9, min_periods=9).max()
        rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100
        frame["KDJ_K"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
        frame["KDJ_D"] = frame["KDJ_K"].ewm(alpha=1 / 3, adjust=False).mean()
        frame["KDJ_J"] = 3 * frame["KDJ_K"] - 2 * frame["KDJ_D"]

        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False).mean()
        frame["RSI"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        frame.loc[(loss == 0) & (gain > 0), "RSI"] = 100

        frame["BOLL_MID"] = close.rolling(20).mean()
        boll_std = close.rolling(20).std(ddof=0)
        frame["BOLL_UPPER"] = frame["BOLL_MID"] + 2 * boll_std
        frame["BOLL_LOWER"] = frame["BOLL_MID"] - 2 * boll_std
        return frame

    @staticmethod
    def _history_records(frame: pd.DataFrame) -> list[dict]:
        rows: list[dict] = []
        for index, row in frame.iterrows():
            record: dict[str, Any] = {"date": index.strftime("%Y-%m-%d")}
            for field_name in (
                "open", "high", "low", "close", "volume", "amount",
                "MA5", "MA10", "MA20", "MA60",
                "MACD_DIF", "MACD_DEA", "MACD",
                "RSI", "KDJ_K", "KDJ_D", "KDJ_J",
                "BOLL_UPPER", "BOLL_MID", "BOLL_LOWER",
            ):
                if field_name not in row:
                    record[field_name] = None
                    continue
                value = row[field_name]
                if value is None or (isinstance(value, float) and not math.isfinite(value)):
                    record[field_name] = None
                elif field_name in ("volume", "amount"):
                    record[field_name] = float(value)
                else:
                    record[field_name] = round(float(value), 4)
            rows.append(record)
        return rows


market_service = MarketService()
