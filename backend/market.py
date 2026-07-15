"""AKShare-backed A-share market data with TTL caching and safe fallbacks."""

from __future__ import annotations

import math
import random
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from .signals import (
    classify_market_phase,
    enrich_klines,
    preferred_stock_analysis,
    stock_checklist,
    support_resistance,
    trend_label,
)


INDEXES = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
}


class TTLCache:
    """Minimal lock-protected in-memory TTL cache."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get_or_load(self, key: str, ttl: float, loader: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            cached = self._items.get(key)
            if cached and cached[0] > now:
                return cached[1]
        value = loader()
        with self._lock:
            self._items[key] = (time.monotonic() + ttl, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class MarketService:
    def __init__(self, cache: TTLCache | None = None) -> None:
        self.cache = cache or TTLCache()

    def overview(self) -> dict[str, Any]:
        return self.cache.get_or_load("market:overview", 60, self._load_overview)

    def quotes(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        normalized = [normalize_code(code) for code in codes]
        spot = self.cache.get_or_load("market:spot", 45, self._load_spot)
        by_code = {item["code"]: item for item in spot["items"]}
        result: dict[str, dict[str, Any]] = {}
        for code in normalized:
            item = by_code.get(code)
            if item is None:
                item = self._sample_quote(code)
            result[code] = item
        return result

    def stock_daily(self, code: str, days: int = 120) -> dict[str, Any]:
        code = normalize_code(code)
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("stock code must contain exactly 6 digits")
        days = max(60, min(days, 500))
        key = f"daily:{code}:{days}"
        return self.cache.get_or_load(
            key, 900, lambda: self._load_stock_daily(code, days)
        )

    def preferred_stocks(
        self, limit: int = 8, candidate_count: int = 12
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 20))
        candidate_count = max(limit, min(candidate_count, 30))
        key = f"market:preferred:{limit}:{candidate_count}"
        return self.cache.get_or_load(
            key,
            900,
            lambda: self._load_preferred_stocks(limit, candidate_count),
        )

    def _load_preferred_stocks(
        self, limit: int, candidate_count: int
    ) -> dict[str, Any]:
        spot = self.cache.get_or_load("market:spot", 45, self._load_spot)
        if spot["source"] == "sample":
            return {
                "items": [],
                "source": "sample",
                "fallback_reason": spot.get("fallback_reason"),
                "analyzed_count": 0,
                "updated_at": _now(),
            }

        candidates = self._prefilter_candidates(spot["items"], candidate_count)
        results: list[dict[str, Any]] = []
        failures: list[str] = []
        for quote in candidates:
            daily = self.stock_daily(quote["code"], 120)
            if daily["source"] != "akshare":
                failures.append(f"{quote['code']}: {daily.get('fallback_reason', 'unavailable')}")
                continue
            analysis = preferred_stock_analysis(daily["klines"])
            results.append(
                {
                    "code": quote["code"],
                    "name": quote["name"],
                    "price": quote["price"],
                    "change_pct": quote["change_pct"],
                    "amount": quote["amount"],
                    **analysis,
                }
            )

        results.sort(
            key=lambda item: (
                float(item["score"]),
                float(item["change_pct"]),
                float(item["amount"]),
            ),
            reverse=True,
        )
        return {
            "items": results[:limit],
            "source": "akshare",
            "fallback_reason": "; ".join(failures)[:240] or None,
            "analyzed_count": len(candidates),
            "updated_at": _now(),
        }

    @staticmethod
    def _prefilter_candidates(
        items: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        eligible = [
            item
            for item in items
            if 1.5 <= float(item.get("change_pct", 0)) <= 20.5
            and float(item.get("amount", 0)) > 0
            and "ST" not in str(item.get("name", "")).upper()
            and "退" not in str(item.get("name", ""))
        ]
        half = max(1, (limit + 1) // 2)
        by_change = sorted(
            eligible,
            key=lambda item: (
                float(item.get("change_pct", 0)),
                float(item.get("amount", 0)),
            ),
            reverse=True,
        )
        by_amount = sorted(
            eligible,
            key=lambda item: float(item.get("amount", 0)),
            reverse=True,
        )
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in by_change[:half] + by_amount:
            code = str(item["code"])
            if code in seen:
                continue
            selected.append(item)
            seen.add(code)
            if len(selected) >= limit:
                break
        return selected

    def _load_overview(self) -> dict[str, Any]:
        fallback_reason: str | None = None
        try:
            indexes = self._real_indexes()
            if len(indexes) < len(INDEXES):
                raise RuntimeError("AKShare returned incomplete index data")
        except Exception as exc:  # network and provider schemas are outside our control
            indexes = self._sample_indexes()
            fallback_reason = _safe_reason(exc)

        try:
            spot = self.cache.get_or_load("market:spot", 45, self._load_spot)
            items = spot["items"]
            breadth = self._breadth(items)
            if spot["source"] == "sample":
                fallback_reason = fallback_reason or spot.get("fallback_reason")
        except Exception as exc:
            breadth = self._sample_breadth()
            fallback_reason = fallback_reason or _safe_reason(exc)

        main_change = next(
            (float(item["change_pct"]) for item in indexes if item["code"] == "000001"),
            0.0,
        )
        phase = classify_market_phase(
            main_change,
            breadth["advance_ratio"],
            breadth["volume_ratio"],
            breadth["limit_up"],
            breadth["limit_down"],
        )
        return {
            "indexes": indexes,
            "breadth": breadth,
            "phase": phase,
            "source": "sample" if fallback_reason else "akshare",
            "fallback_reason": fallback_reason,
            "updated_at": _now(),
        }

    def _load_spot(self) -> dict[str, Any]:
        errors: list[str] = []
        # Prefer Sina: East Money full-market spot often aborts mid-pagination.
        for loader in (self._spot_from_sina, self._spot_from_em):
            try:
                items = loader()
                if items:
                    return {"items": items, "source": "akshare", "fallback_reason": None}
                errors.append(f"{loader.__name__}: empty")
            except Exception as exc:
                errors.append(f"{loader.__name__}: {_safe_reason(exc)}")
        sample_codes = ["600519", "000001", "300750", "601318", "000858"]
        return {
            "items": [self._sample_quote(code) for code in sample_codes],
            "source": "sample",
            "fallback_reason": "; ".join(errors)[:240] or "spot providers unavailable",
        }

    def _spot_from_sina(self) -> list[dict[str, Any]]:
        ak = _import_akshare()
        return self._parse_spot_rows(_records(ak.stock_zh_a_spot()))

    def _spot_from_em(self) -> list[dict[str, Any]]:
        ak = _import_akshare()
        return self._parse_spot_rows(_records(ak.stock_zh_a_spot_em()))

    @staticmethod
    def _parse_spot_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items = []
        for row in records:
            code = normalize_code(_pick(row, "代码", "code", default=""))
            price = _number(_pick(row, "最新价", "price"))
            if not re.fullmatch(r"\d{6}", code) or price <= 0:
                continue
            items.append(
                {
                    "code": code,
                    "name": str(_pick(row, "名称", "name", default=code)),
                    "price": price,
                    "change": _number(_pick(row, "涨跌额", "change")),
                    "change_pct": _number(_pick(row, "涨跌幅", "change_pct")),
                    "open": _number(_pick(row, "今开", "open")),
                    "high": _number(_pick(row, "最高", "high")),
                    "low": _number(_pick(row, "最低", "low")),
                    "previous_close": _number(_pick(row, "昨收", "previous_close")),
                    "volume": _number(_pick(row, "成交量", "volume")),
                    "amount": _number(_pick(row, "成交额", "amount")),
                    "source": "akshare",
                }
            )
        return items

    def _real_indexes(self) -> list[dict[str, Any]]:
        ak = _import_akshare()
        frame = ak.stock_zh_index_spot_sina()
        records = _records(frame)
        result: list[dict[str, Any]] = []
        for target_code, default_name in INDEXES.items():
            row = next(
                (
                    candidate
                    for candidate in records
                    if normalize_code(_pick(candidate, "代码", "code", default=""))
                    == target_code
                ),
                None,
            )
            if not row:
                continue
            price = _number(_pick(row, "最新价", "price"))
            if price <= 0:
                continue
            result.append(
                {
                    "code": target_code,
                    "name": str(_pick(row, "名称", "name", default=default_name)),
                    "price": price,
                    "change": _number(_pick(row, "涨跌额", "change")),
                    "change_pct": _number(_pick(row, "涨跌幅", "change_pct")),
                    "open": _number(_pick(row, "今开", "open")),
                    "high": _number(_pick(row, "最高", "high")),
                    "low": _number(_pick(row, "最低", "low")),
                    "previous_close": _number(_pick(row, "昨收", "previous_close")),
                    "volume": _number(_pick(row, "成交量", "volume")),
                    "amount": _number(_pick(row, "成交额", "amount")),
                }
            )
        return result

    def _load_stock_daily(self, code: str, days: int) -> dict[str, Any]:
        fallback_reason: str | None = None
        try:
            rows = self._fetch_daily_rows(code, days)
            if len(rows) < 20:
                raise RuntimeError("AKShare returned insufficient daily history")
            source = "akshare"
        except Exception as exc:
            rows = self._sample_klines(code, days)
            source = "sample"
            fallback_reason = _safe_reason(exc)

        enriched = enrich_klines(rows)
        support, resistance = support_resistance(enriched)
        quote = self.quotes([code])[code]
        trend = trend_label(enriched)
        trend_summaries = {
            "up": "均线呈多头结构，价格处于趋势上方；顺势观察，回调时仍需验证承接。",
            "down": "均线呈空头结构，当前以控制风险和等待企稳为主。",
            "sideways": "均线相互缠绕，方向尚未确认；看不懂的时候先看戏。",
            "insufficient": "历史数据不足，暂时无法形成可靠趋势判断。",
        }
        return {
            "code": code,
            "name": quote["name"],
            "price": quote["price"],
            "change_pct": quote["change_pct"],
            "klines": enriched,
            "trend": trend,
            "summary": trend_summaries[trend],
            "support": support,
            "resistance": resistance,
            "checklist": stock_checklist(enriched),
            "source": source,
            "fallback_reason": fallback_reason,
            "updated_at": _now(),
        }

    def _fetch_daily_rows(self, code: str, days: int) -> list[dict[str, Any]]:
        ak = _import_akshare()
        end = date.today()
        start = end - timedelta(days=max(days * 2, 180))
        start_s = start.strftime("%Y%m%d")
        end_s = end.strftime("%Y%m%d")
        errors: list[str] = []

        # Sina first — East Money hist frequently drops the connection.
        try:
            frame = ak.stock_zh_a_daily(
                symbol=to_sina_symbol(code),
                start_date=start_s,
                end_date=end_s,
                adjust="qfq",
            )
            rows = self._normalize_klines(_records(frame))[-days:]
            if len(rows) >= 20:
                return rows
            errors.append("sina: insufficient rows")
        except Exception as exc:
            errors.append(f"sina: {_safe_reason(exc)}")

        try:
            frame = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_s,
                end_date=end_s,
                adjust="qfq",
                timeout=10,
            )
            rows = self._normalize_klines(_records(frame))[-days:]
            if len(rows) >= 20:
                return rows
            errors.append("em: insufficient rows")
        except Exception as exc:
            errors.append(f"em: {_safe_reason(exc)}")

        raise RuntimeError("; ".join(errors) or "daily history unavailable")

    @staticmethod
    def _normalize_klines(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in records:
            close = _number(_pick(row, "收盘", "close"))
            if close <= 0:
                continue
            raw_date = _pick(row, "日期", "date", default="")
            date_value = raw_date.isoformat() if hasattr(raw_date, "isoformat") else str(raw_date)
            turnover = _number(_pick(row, "换手率", "turnover_rate", "turnover"))
            # Sina daily returns turnover as a ratio (e.g. 0.0049); EM uses percent.
            if 0 < turnover < 1:
                turnover *= 100
            rows.append(
                {
                    "date": date_value[:10],
                    "open": _number(_pick(row, "开盘", "open")),
                    "close": close,
                    "high": _number(_pick(row, "最高", "high")),
                    "low": _number(_pick(row, "最低", "low")),
                    "volume": _number(_pick(row, "成交量", "volume")),
                    "amount": _number(_pick(row, "成交额", "amount")),
                    "change_pct": _number(_pick(row, "涨跌幅", "change_pct")),
                    "turnover_rate": round(turnover, 4),
                }
            )
        rows.sort(key=lambda item: item["date"])
        previous = None
        for item in rows:
            if item["change_pct"] == 0.0 and previous and previous > 0:
                item["change_pct"] = round((item["close"] / previous - 1) * 100, 3)
            previous = item["close"]
        return rows

    @staticmethod
    def _breadth(items: list[dict[str, Any]]) -> dict[str, Any]:
        valid = [item for item in items if item["price"] > 0]
        up = sum(item["change_pct"] > 0 for item in valid)
        down = sum(item["change_pct"] < 0 for item in valid)
        flat = len(valid) - up - down
        return {
            "up": up,
            "down": down,
            "flat": flat,
            "advance_ratio": round(up / len(valid), 4) if valid else 0.5,
            "limit_up": sum(item["change_pct"] >= 9.5 for item in valid),
            "limit_down": sum(item["change_pct"] <= -9.5 for item in valid),
            "amount": round(sum(item["amount"] for item in valid), 2),
            "volume_ratio": 1.0,
        }

    @staticmethod
    def _sample_indexes() -> list[dict[str, Any]]:
        values = [
            ("000001", "上证指数", 3216.84, 10.52, 0.33),
            ("399001", "深证成指", 10288.31, -12.40, -0.12),
            ("399006", "创业板指", 2098.76, 8.91, 0.43),
        ]
        return [
            {
                "code": code,
                "name": name,
                "price": price,
                "change": change,
                "change_pct": change_pct,
                "open": round(price - change * 0.4, 2),
                "high": round(price + abs(change) * 0.8, 2),
                "low": round(price - abs(change) * 0.8, 2),
                "previous_close": round(price - change, 2),
                "volume": 0.0,
                "amount": 0.0,
            }
            for code, name, price, change, change_pct in values
        ]

    @staticmethod
    def _sample_breadth() -> dict[str, Any]:
        return {
            "up": 2678,
            "down": 2214,
            "flat": 286,
            "advance_ratio": 0.5172,
            "limit_up": 47,
            "limit_down": 9,
            "amount": 786_500_000_000.0,
            "volume_ratio": 0.96,
        }

    @staticmethod
    def _sample_quote(code: str) -> dict[str, Any]:
        names = {
            "600519": "贵州茅台",
            "000001": "平安银行",
            "300750": "宁德时代",
            "601318": "中国平安",
            "000858": "五粮液",
        }
        seed = int(code) if code.isdigit() else sum(ord(char) for char in code)
        price = round(8 + (seed % 24000) / 100, 2)
        change_pct = round(((seed % 401) - 200) / 100, 2)
        previous = price / (1 + change_pct / 100) if change_pct != -100 else price
        change = price - previous
        return {
            "code": code,
            "name": names.get(code, f"示例股票{code}"),
            "price": price,
            "change": round(change, 2),
            "change_pct": change_pct,
            "open": round(previous * 1.002, 2),
            "high": round(max(price, previous) * 1.008, 2),
            "low": round(min(price, previous) * 0.992, 2),
            "previous_close": round(previous, 2),
            "volume": float(5_000_000 + seed % 20_000_000),
            "amount": round(price * (5_000_000 + seed % 20_000_000), 2),
            "source": "sample",
        }

    @staticmethod
    def _sample_klines(code: str, days: int) -> list[dict[str, Any]]:
        seed = int(code)
        rng = random.Random(seed)
        current = date.today()
        dates: list[date] = []
        while len(dates) < days:
            if current.weekday() < 5:
                dates.append(current)
            current -= timedelta(days=1)
        dates.reverse()
        price = 10 + (seed % 18000) / 100
        rows: list[dict[str, Any]] = []
        previous = price
        for index, day in enumerate(dates):
            drift = 0.0007 + math.sin(index / 11 + seed % 7) * 0.002
            move = drift + rng.uniform(-0.018, 0.018)
            close = max(1.0, previous * (1 + move))
            open_price = previous * (1 + rng.uniform(-0.008, 0.008))
            high = max(open_price, close) * (1 + rng.uniform(0.002, 0.012))
            low = min(open_price, close) * (1 - rng.uniform(0.002, 0.012))
            volume = float(2_000_000 + rng.randint(0, 12_000_000))
            rows.append(
                {
                    "date": day.isoformat(),
                    "open": round(open_price, 3),
                    "close": round(close, 3),
                    "high": round(high, 3),
                    "low": round(low, 3),
                    "volume": volume,
                    "amount": round(volume * close, 2),
                    "change_pct": round((close / previous - 1) * 100, 3),
                    "turnover_rate": round(rng.uniform(0.3, 4.5), 3),
                }
            )
            previous = close
        return rows


def normalize_code(value: Any) -> str:
    code = str(value or "").strip().lower()
    code = re.sub(r"^(sh|sz|bj)", "", code)
    digits = re.sub(r"\D", "", code)
    return digits.zfill(6) if digits and len(digits) <= 6 else digits


def to_sina_symbol(code: str) -> str:
    """Map a 6-digit A-share code to Sina's sh/sz/bj prefix form."""
    code = normalize_code(code)
    if code.startswith(("60", "68", "90")):
        return f"sh{code}"
    if code.startswith(("00", "30", "20")):
        return f"sz{code}"
    if code.startswith(("43", "83", "87", "92")):
        return f"bj{code}"
    if code.startswith(("5", "6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _import_akshare() -> Any:
    try:
        import akshare  # type: ignore

        return akshare
    except ImportError as exc:
        raise RuntimeError("AKShare is not installed") from exc


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", False):
        return []
    return list(frame.to_dict(orient="records"))


def _pick(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


def _number(value: Any) -> float:
    try:
        result = float(value)
        return round(result, 4) if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _safe_reason(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:240]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
