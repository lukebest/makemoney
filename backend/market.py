"""AKShare-backed A-share market data with TTL caching and safe fallbacks."""

from __future__ import annotations

import math
import os
import random
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .chan import latest_structure
from .signals import (
    classify_market_phase,
    enrich_klines,
    market_structure_analysis,
    preferred_stock_analysis,
    preferred_stock_fail_fast,
    stock_checklist,
    support_resistance,
    trend_label,
)

CHINA_TZ = ZoneInfo("Asia/Shanghai")


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
        by_code: dict[str, dict[str, Any]] = {}
        if any(is_a_share_code(code) for code in normalized):
            spot = self.cache.get_or_load("market:spot", 45, self._load_spot)
            by_code.update({item["code"]: item for item in spot["items"]})
        if any(is_hk_code(code) for code in normalized):
            hk_spot = self.cache.get_or_load("market:hk:spot", 45, self._load_hk_spot)
            by_code.update({item["code"]: item for item in hk_spot["items"]})
        result: dict[str, dict[str, Any]] = {}
        for code in normalized:
            item = by_code.get(code)
            if item is None:
                item = self._sample_quote(code)
            result[code] = item
        return result

    def stock_daily(self, code: str, days: int = 120) -> dict[str, Any]:
        code = normalize_code(code)
        if not (is_a_share_code(code) or is_hk_code(code)):
            raise ValueError("stock code must contain 5 Hong Kong or 6 A-share digits")
        days = max(60, min(days, 500))
        key = f"daily:{code}:{days}"
        return self.cache.get_or_load(
            key, 900, lambda: self._load_stock_daily(code, days)
        )

    def cny_rate(self, code: str) -> float:
        if is_hk_code(normalize_code(code)):
            return self.cache.get_or_load(
                "fx:hkd-cny", 3600, self._load_hkd_cny_rate
            )
        return 1.0

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

    def close_screen(self, max_candidates: int | None = None) -> dict[str, Any]:
        """Scan active-sector constituents as of the latest completed session.

        After 15:00 China time, that session is today; otherwise the previous
        trading day is used so the screen never depends on an unfinished bar.
        """
        after_close = is_after_a_share_close()
        as_of_date = last_completed_session()
        session_kind = "today_close" if after_close and as_of_date == china_today() else "previous_close"

        spot = self.cache.get_or_load("market:spot", 45, self._load_spot)
        if spot["source"] == "sample":
            return {
                "items": [],
                "source": "sample",
                "fallback_reason": spot.get("fallback_reason"),
                "analyzed_count": 0,
                "universe_count": 0,
                "match_count": 0,
                "rejected_by": {},
                "active_sectors": [],
                "as_of_date": as_of_date.isoformat(),
                "for_date": next_session_date(as_of_date).isoformat(),
                "after_close": after_close,
                "session_kind": session_kind,
                "updated_at": _now(),
            }

        mainline = self.mainline_as_of(as_of_date)
        active_sectors = (
            list(mainline.get("active_sectors") or [])
            if mainline.get("source") == "akshare"
            else []
        )
        if not active_sectors:
            return {
                "items": [],
                "source": "akshare",
                "fallback_reason": "热点主线不可用，无法做五项全过收盘筛选",
                "analyzed_count": 0,
                "universe_count": 0,
                "match_count": 0,
                "rejected_by": {"active_sector": 0},
                "active_sectors": [],
                "as_of_date": as_of_date.isoformat(),
                "for_date": next_session_date(as_of_date).isoformat(),
                "after_close": after_close,
                "session_kind": session_kind,
                "updated_at": _now(),
            }

        sector_by_code = self._load_active_sector_universe(
            active_sectors, mainline.get("stock_sectors") or {}
        )
        spot_by_code = {str(item["code"]): item for item in spot["items"]}
        # Spot names/amounts help when available; before close, unfinished turnover
        # is ignored as a hard gate and replaced by the as-of daily bar later.
        candidates: list[dict[str, Any]] = []
        rejected: Counter[str] = Counter()
        for code, sector in sector_by_code.items():
            quote = spot_by_code.get(code) or {
                "code": code,
                "name": code,
                "price": 0.0,
                "change_pct": 0.0,
                "amount": 0.0,
            }
            name = str(quote.get("name", ""))
            if "ST" in name.upper() or "退" in name:
                rejected["st"] += 1
                continue
            amount = float(quote.get("amount", 0))
            if after_close and amount and amount < 30_000_000:
                rejected["liquidity"] += 1
                continue
            candidates.append({**quote, "sector": sector})

        candidates.sort(
            key=lambda item: (
                float(item.get("amount", 0)),
                float(item.get("change_pct", 0)),
            ),
            reverse=True,
        )
        if max_candidates is not None:
            candidates = candidates[: max(1, min(int(max_candidates), 2000))]

        matches: list[dict[str, Any]] = []
        workers = min(8, max(1, len(candidates)))
        if candidates:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(
                        self._close_screen_one,
                        quote,
                        str(quote["sector"]),
                        active_sectors,
                        as_of_date,
                    )
                    for quote in candidates
                ]
                for future in as_completed(futures):
                    item, stage = future.result()
                    if item is None:
                        rejected[stage] += 1
                        continue
                    matches.append(item)

        matches.sort(
            key=lambda item: (
                float(item["score"]),
                float(item["change_pct"]),
                float(item["amount"]),
            ),
            reverse=True,
        )
        return {
            "items": matches,
            "source": "akshare",
            "fallback_reason": None,
            "analyzed_count": len(candidates),
            "universe_count": len(sector_by_code),
            "match_count": len(matches),
            "rejected_by": dict(rejected),
            "active_sectors": active_sectors,
            "as_of_date": as_of_date.isoformat(),
            "for_date": next_session_date(as_of_date).isoformat(),
            "after_close": after_close,
            "session_kind": session_kind,
            "updated_at": _now(),
        }

    def _close_screen_one(
        self,
        quote: Mapping[str, Any],
        sector: str,
        active_sectors: Sequence[str],
        as_of_date: date,
    ) -> tuple[dict[str, Any] | None, str]:
        code = str(quote["code"])
        as_of = as_of_date.isoformat()
        try:
            rows = self.cache.get_or_load(
                f"close-klines:{code}:120:{as_of}",
                1800,
                lambda: self._daily_rows_as_of(code, 120, as_of_date),
            )
        except Exception:
            return None, "kline"
        if len(rows) < 40:
            return None, "history"
        last = rows[-1]
        amount = float(last.get("amount") or 0)
        if amount and amount < 30_000_000:
            return None, "liquidity"
        analysis, stage = preferred_stock_fail_fast(rows, sector, active_sectors)
        if analysis is None:
            return None, stage
        return (
            {
                "code": code,
                "name": quote["name"],
                "price": float(last["close"]),
                "change_pct": float(last.get("change_pct") or quote.get("change_pct") or 0),
                "amount": amount or float(quote.get("amount") or 0),
                "sector": sector,
                "in_mainline": True,
                **analysis,
            },
            "passed",
        )

    def _daily_rows_as_of(
        self, code: str, days: int, as_of_date: date
    ) -> list[dict[str, Any]]:
        rows = self._fetch_daily_rows(code, days + 5)
        as_of = as_of_date.isoformat()
        clipped = [row for row in rows if str(row.get("date", ""))[:10] <= as_of]
        if not clipped:
            raise RuntimeError(f"no daily bars on or before {as_of}")
        return clipped[-days:]

    def _load_active_sector_universe(
        self,
        active_sectors: Sequence[str],
        mainline_sectors: Mapping[str, str],
    ) -> dict[str, str]:
        """Map code → sector for every stock in today's hot industries."""
        key = "market:active-sector-universe:" + ",".join(active_sectors)
        return self.cache.get_or_load(
            key,
            1800,
            lambda: self._fetch_active_sector_universe(
                active_sectors, mainline_sectors
            ),
        )

    def _fetch_active_sector_universe(
        self,
        active_sectors: Sequence[str],
        mainline_sectors: Mapping[str, str],
    ) -> dict[str, str]:
        universe: dict[str, str] = {
            normalize_code(code): sector
            for code, sector in mainline_sectors.items()
            if sector in active_sectors and is_a_share_code(normalize_code(code))
        }
        try:
            ak = _import_akshare()
        except Exception:
            return universe

        for sector in active_sectors:
            try:
                records = _records(ak.stock_board_industry_cons_em(symbol=sector))
            except Exception:
                continue
            for row in records:
                code = normalize_code(_pick(row, "代码", "code", default=""))
                if not is_a_share_code(code):
                    continue
                name = str(_pick(row, "名称", "name", default=""))
                if "ST" in name.upper() or "退" in name:
                    continue
                universe[code] = sector
        return universe

    def mainline(self) -> dict[str, Any]:
        """Return today's hot sectors and consecutive-board leader ladder."""
        return self.cache.get_or_load(
            "market:mainline", 180, self._load_mainline
        )

    def mainline_as_of(self, as_of: date) -> dict[str, Any]:
        """Limit-up mainline anchored on a completed session date."""
        key = f"market:mainline:{as_of.isoformat()}"
        return self.cache.get_or_load(
            key, 1800, lambda: self._load_mainline_from(as_of)
        )

    def _load_preferred_stocks(
        self, limit: int, candidate_count: int
    ) -> dict[str, Any]:
        scanned = self._scan_preferred_candidates(candidate_count)
        if scanned["source"] == "sample":
            return {
                "items": [],
                "source": "sample",
                "fallback_reason": scanned.get("fallback_reason"),
                "analyzed_count": 0,
                "updated_at": _now(),
            }
        return {
            "items": scanned["items"][:limit],
            "source": scanned["source"],
            "fallback_reason": scanned.get("fallback_reason"),
            "analyzed_count": scanned["analyzed_count"],
            "active_sectors": scanned.get("active_sectors") or [],
            "updated_at": _now(),
        }

    def _scan_preferred_candidates(self, candidate_count: int) -> dict[str, Any]:
        spot = self.cache.get_or_load("market:spot", 45, self._load_spot)
        if spot["source"] == "sample":
            return {
                "items": [],
                "source": "sample",
                "fallback_reason": spot.get("fallback_reason"),
                "analyzed_count": 0,
                "active_sectors": [],
                "board_date": None,
            }

        mainline = self.mainline()
        sector_map = mainline.get("stock_sectors", {})
        active_sectors = (
            mainline.get("active_sectors")
            if mainline.get("source") == "akshare"
            else None
        )
        candidates = self._prefilter_candidates(
            spot["items"],
            candidate_count,
            set(mainline.get("limit_up_codes", [])),
        )
        results: list[dict[str, Any]] = []
        failures: list[str] = []
        for quote in candidates:
            daily = self.stock_daily(quote["code"], 120)
            if daily["source"] != "akshare":
                failures.append(
                    f"{quote['code']}: {daily.get('fallback_reason', 'unavailable')}"
                )
                continue
            sector = sector_map.get(quote["code"])
            analysis = preferred_stock_analysis(
                daily["klines"], sector, active_sectors
            )
            results.append(
                {
                    "code": quote["code"],
                    "name": quote["name"],
                    "price": quote["price"],
                    "change_pct": quote["change_pct"],
                    "amount": quote["amount"],
                    "sector": sector,
                    "in_mainline": bool(sector and sector in (active_sectors or [])),
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
            "items": results,
            "source": "akshare",
            "fallback_reason": "; ".join(failures)[:240] or None,
            "analyzed_count": len(candidates),
            "active_sectors": active_sectors or [],
            "board_date": mainline.get("date"),
        }

    @staticmethod
    def _prefilter_candidates(
        items: list[dict[str, Any]],
        limit: int,
        mainline_codes: set[str] | None = None,
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
        mainline_codes = mainline_codes or set()
        by_mainline = sorted(
            (item for item in eligible if str(item["code"]) in mainline_codes),
            key=lambda item: (
                float(item.get("change_pct", 0)),
                float(item.get("amount", 0)),
            ),
            reverse=True,
        )
        for item in by_mainline + by_change[:half] + by_amount:
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
            else:
                boards = self.cache.get_or_load(
                    "market:boards", 120, self._load_board_pool
                )
                if boards.get("available"):
                    breadth["limit_up"] = boards["limit_up"]
                    breadth["limit_down"] = boards["limit_down"]
                    breadth["fried"] = boards["fried"]
                    breadth["board_date"] = boards["date"]
                breadth["volume_ratio"] = self.cache.get_or_load(
                    "market:volume-ratio", 900, self._load_volume_ratio
                )
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
            breadth.get("fried", 0),
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

    def _load_hk_spot(self) -> dict[str, Any]:
        errors: list[str] = []
        ak = _import_akshare()
        for name in ("stock_hk_spot", "stock_hk_spot_em"):
            try:
                items = self._parse_spot_rows(_records(getattr(ak, name)()))
                if items:
                    return {
                        "items": items,
                        "source": "akshare",
                        "fallback_reason": None,
                    }
                errors.append(f"{name}: empty")
            except Exception as exc:
                errors.append(f"{name}: {_safe_reason(exc)}")
        return {
            "items": [],
            "source": "sample",
            "fallback_reason": "; ".join(errors)[:240] or "HK quote providers unavailable",
        }

    def _load_mainline(self) -> dict[str, Any]:
        """Load detailed limit-up records and derive sectors/leader ladders."""
        return self._load_mainline_from(date.today())

    def _load_mainline_from(self, as_of: date) -> dict[str, Any]:
        """Load the newest non-empty limit-up pool on or before as_of."""
        try:
            ak = _import_akshare()
        except Exception as exc:
            return self._empty_mainline(_safe_reason(exc))
        errors: list[str] = []
        for back in range(8):
            stamp = (as_of - timedelta(days=back)).strftime("%Y%m%d")
            try:
                records = _records(ak.stock_zt_pool_em(date=stamp))
            except Exception as exc:
                errors.append(f"{stamp}: {_safe_reason(exc)}")
                continue
            if records:
                return self._analyze_limit_up_pool(records, stamp)
        return self._empty_mainline(
            "; ".join(errors)[:240] or "recent limit-up pools are empty"
        )

    @staticmethod
    def _analyze_limit_up_pool(
        records: list[dict[str, Any]], stamp: str
    ) -> dict[str, Any]:
        stocks: list[dict[str, Any]] = []
        sectors: dict[str, list[dict[str, Any]]] = {}
        for row in records:
            code = normalize_code(_pick(row, "代码", default=""))
            name = str(_pick(row, "名称", default=code))
            sector = str(_pick(row, "所属行业", default="未知行业")).strip() or "未知行业"
            board_count = max(1, int(_number(_pick(row, "连板数", default=1))))
            if "ST" in name.upper() or "退" in name:
                continue
            stock = {
                "code": code,
                "name": name,
                "sector": sector,
                "board_count": board_count,
                "change_pct": _number(_pick(row, "涨跌幅")),
                "price": _number(_pick(row, "最新价")),
                "amount": _number(_pick(row, "成交额")),
                "sealed_amount": _number(_pick(row, "封板资金")),
                "break_count": int(_number(_pick(row, "炸板次数"))),
                "limit_up_stats": str(_pick(row, "涨停统计", default="")),
                "first_sealed_at": str(_pick(row, "首次封板时间", default="")),
            }
            if not is_a_share_code(code):
                continue
            stocks.append(stock)
            sectors.setdefault(sector, []).append(stock)

        sector_rows: list[dict[str, Any]] = []
        for name, members in sectors.items():
            ranked = sorted(
                members,
                key=lambda item: (
                    int(item["board_count"]),
                    float(item["sealed_amount"]),
                    float(item["amount"]),
                ),
                reverse=True,
            )
            sector_rows.append(
                {
                    "name": name,
                    "limit_up_count": len(members),
                    "first_board_count": sum(
                        int(item["board_count"]) == 1 for item in members
                    ),
                    "second_plus_count": sum(
                        int(item["board_count"]) >= 2 for item in members
                    ),
                    "max_board": max(int(item["board_count"]) for item in members),
                    "leader": ranked[0],
                }
            )
        # "一板定热点": first-board breadth comes first. Total breadth and
        # board height break ties, so one isolated high board cannot define a
        # whole sector as the main line by itself.
        sector_rows.sort(
            key=lambda item: (
                int(item["first_board_count"]),
                int(item["limit_up_count"]),
                int(item["max_board"]),
            ),
            reverse=True,
        )
        active = [
            item["name"]
            for item in sector_rows
            if int(item["limit_up_count"]) >= 2
        ][:3]
        if not active:
            active = [item["name"] for item in sector_rows[:3]]

        ladder_groups: dict[int, list[dict[str, Any]]] = {}
        for stock in stocks:
            if int(stock["board_count"]) >= 2:
                ladder_groups.setdefault(int(stock["board_count"]), []).append(stock)
        ladders = [
            {
                "board_count": board_count,
                "stocks": sorted(
                    members,
                    key=lambda item: (
                        float(item["sealed_amount"]),
                        float(item["amount"]),
                    ),
                    reverse=True,
                ),
            }
            for board_count, members in sorted(ladder_groups.items(), reverse=True)
        ]
        leaders = [
            stock
            for group in ladders
            for stock in group["stocks"]
        ][:8]
        formatted_date = (
            f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
            if len(stamp) == 8
            else stamp
        )
        return {
            "source": "akshare",
            "date": formatted_date,
            "main_sector": active[0] if active else None,
            "active_sectors": active,
            "sectors": sector_rows[:8],
            "ladders": ladders,
            "leaders": leaders,
            "stock_sectors": {stock["code"]: stock["sector"] for stock in stocks},
            "limit_up_codes": [stock["code"] for stock in stocks],
            "total_count": len(stocks),
            "fallback_reason": None,
            "updated_at": _now(),
        }

    @staticmethod
    def _empty_mainline(reason: str) -> dict[str, Any]:
        return {
            "source": "unavailable",
            "date": None,
            "main_sector": None,
            "active_sectors": [],
            "sectors": [],
            "ladders": [],
            "leaders": [],
            "stock_sectors": {},
            "limit_up_codes": [],
            "total_count": 0,
            "fallback_reason": reason,
            "updated_at": _now(),
        }

    def _load_board_pool(self) -> dict[str, Any]:
        """Count limit-up, limit-down and broken (炸板) boards.

        Uses the Legu market-activity summary plus the East Money broken-board
        pool; both answer in a couple of seconds, unlike the full limit-up pool
        which paginates per stock. Failures are returned (and thus cached)
        instead of raised so a broken provider does not push the whole
        overview into sample mode.
        """
        try:
            ak = _import_akshare()
            rows = _records(ak.stock_market_activity_legu())
            stats = {str(row.get("item")): row.get("value") for row in rows}
            limit_up = int(_number(stats.get("涨停")))
            limit_down = int(_number(stats.get("跌停")))
            board_date = str(stats.get("统计日期", ""))[:10]
            if limit_up <= 0 and limit_down <= 0:
                raise RuntimeError("legu market activity returned no board counts")
        except Exception as exc:
            return {"available": False, "reason": _safe_reason(exc)}
        fried = 0
        try:
            stamp = (board_date or date.today().isoformat()).replace("-", "")
            fried = len(_records(ak.stock_zt_pool_zbgc_em(date=stamp)))
        except Exception:
            pass
        return {
            "available": True,
            "date": board_date or date.today().isoformat(),
            "limit_up": limit_up,
            "fried": fried,
            "limit_down": limit_down,
        }

    def _load_volume_ratio(self) -> float:
        """Shanghai index volume of the last completed day vs its 5-day average."""
        try:
            ak = _import_akshare()
            records = _records(ak.stock_zh_index_daily(symbol="sh000001"))
            today_s = date.today().isoformat()
            volumes = [
                _number(row.get("volume"))
                for row in records
                # Skip today's bar: intraday volume is partial and would
                # wrongly read as shrinking volume.
                if str(row.get("date"))[:10] != today_s
            ]
            volumes = [volume for volume in volumes if volume > 0][-6:]
            if len(volumes) == 6:
                base = sum(volumes[:-1]) / 5
                if base > 0:
                    return round(volumes[-1] / base, 4)
        except Exception:
            pass
        return 1.0

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
            if not (is_a_share_code(code) or is_hk_code(code)) or price <= 0:
                continue
            hk = is_hk_code(code)
            items.append(
                {
                    "code": code,
                    "name": str(_pick(row, "名称", "中文名称", "name", default=code)),
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
                    "market": "HK" if hk else "A",
                    "currency": "HKD" if hk else "CNY",
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
        rows: list[dict[str, Any]] = []
        source = "akshare"
        try:
            rows = self._fetch_daily_rows(code, days)
        except Exception as exc:
            fallback_reason = _safe_reason(exc)

        quote = self.quotes([code])[code]
        if not rows:
            # New listings often have a live quote before daily history APIs catch up.
            # Prefer a single real session bar over inventing multi-day sample candles.
            if quote.get("source") == "akshare" and float(quote.get("price", 0)) > 0:
                rows = [self._quote_as_kline(quote)]
                source = "partial"
                fallback_reason = (
                    "日线历史暂不可用（常见于新股），仅展示当日行情"
                    + (f"；上游：{fallback_reason}" if fallback_reason else "")
                )
            else:
                rows = self._sample_klines(code, days)
                source = "sample"
                fallback_reason = fallback_reason or "daily history unavailable"

        enriched = enrich_klines(rows)
        support, resistance = support_resistance(enriched)
        if quote["source"] == "sample" and source == "akshare" and enriched:
            quote = {
                **quote,
                "price": enriched[-1]["close"],
                "change_pct": enriched[-1]["change_pct"],
            }
            source = "partial"
            fallback_reason = "live quote unavailable; using latest historical close"
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
            "market": quote.get("market", "HK" if is_hk_code(code) else "A"),
            "currency": quote.get("currency", "HKD" if is_hk_code(code) else "CNY"),
            "cny_rate": self.cny_rate(code),
            "klines": enriched,
            "trend": trend,
            "summary": trend_summaries[trend],
            "support": support,
            "resistance": resistance,
            "checklist": stock_checklist(enriched),
            "chan": latest_structure(enriched),
            "structure": market_structure_analysis(enriched),
            "source": source,
            "fallback_reason": fallback_reason,
            "updated_at": _now(),
        }

    def _fetch_daily_rows(self, code: str, days: int) -> list[dict[str, Any]]:
        ak = _import_akshare()
        if is_hk_code(code):
            try:
                rows = self._normalize_klines(
                    _records(ak.stock_hk_daily(symbol=code, adjust="qfq"))
                )[-days:]
                if rows:
                    return rows
            except Exception as exc:
                raise RuntimeError(f"sina HK: {_safe_reason(exc)}") from exc
            raise RuntimeError("sina HK: empty daily history")

        end = date.today()
        start = end - timedelta(days=max(days * 2, 180))
        start_s = start.strftime("%Y%m%d")
        end_s = end.strftime("%Y%m%d")
        errors: list[str] = []
        best: list[dict[str, Any]] = []

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
            if len(rows) > len(best):
                best = rows
            if not rows:
                errors.append("sina: empty")
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
            if len(rows) > len(best):
                best = rows
            if not rows:
                errors.append("em: empty")
        except Exception as exc:
            errors.append(f"em: {_safe_reason(exc)}")

        # IPO / recent listings may only have a few real bars — keep them.
        if best:
            return best
        raise RuntimeError("; ".join(errors) or "daily history unavailable")

    @staticmethod
    def _quote_as_kline(quote: Mapping[str, Any]) -> dict[str, Any]:
        price = float(quote.get("price") or 0)
        open_price = float(quote.get("open") or price)
        high = float(quote.get("high") or max(open_price, price))
        low = float(quote.get("low") or min(open_price, price))
        return {
            "date": china_today().isoformat(),
            "open": open_price,
            "close": price,
            "high": high,
            "low": low,
            "volume": float(quote.get("volume") or 0),
            "amount": float(quote.get("amount") or 0),
            "change_pct": float(quote.get("change_pct") or 0),
            "turnover_rate": 0.0,
        }
    @staticmethod
    def _load_hkd_cny_rate() -> float:
        fallback = float(os.getenv("HKD_CNY_RATE", "0.87"))
        try:
            ak = _import_akshare()
            end = date.today()
            start = end - timedelta(days=14)
            frame = ak.currency_boc_sina(
                symbol="港币",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            records = _records(frame)
            for row in reversed(records):
                rate = _number(_pick(row, "中行折算价", "央行中间价"))
                if rate > 0:
                    return round(rate / 100, 6)
        except Exception:
            pass
        return fallback

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
            "fried": 0,
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
            "fried": 12,
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
            "00700": "腾讯控股",
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
            "market": "HK" if is_hk_code(code) else "A",
            "currency": "HKD" if is_hk_code(code) else "CNY",
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


def china_today() -> date:
    return datetime.now(CHINA_TZ).date()


def is_after_a_share_close(now: datetime | None = None) -> bool:
    """True after 15:00 Asia/Shanghai on weekdays, or any time on weekends."""
    current = now.astimezone(CHINA_TZ) if now else datetime.now(CHINA_TZ)
    if current.weekday() >= 5:
        return True
    return (current.hour, current.minute) >= (15, 0)


def last_completed_session(now: datetime | None = None) -> date:
    """Latest A-share session whose daily bar should be treated as final.

    Weekday after 15:00 → today; otherwise walk back to the previous weekday.
    """
    current = now.astimezone(CHINA_TZ) if now else datetime.now(CHINA_TZ)
    day = current.date()
    if current.weekday() < 5 and (current.hour, current.minute) >= (15, 0):
        return day
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def next_session_date(as_of: date) -> date:
    """Next weekday after as_of (ignores statutory holidays)."""
    nxt = as_of + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def normalize_code(value: Any) -> str:
    code = str(value or "").strip().lower()
    prefix = re.match(r"^(sh|sz|bj|hk)", code)
    code = re.sub(r"^(sh|sz|bj|hk)", "", code)
    digits = re.sub(r"\D", "", code)
    if not digits:
        return digits
    if prefix and prefix.group(1) == "hk":
        return digits.zfill(5)
    if len(digits) == 5:
        return digits
    return digits.zfill(6) if len(digits) <= 6 else digits


def is_hk_code(code: str) -> bool:
    return bool(re.fullmatch(r"\d{5}", code))


def is_a_share_code(code: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", code))


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
