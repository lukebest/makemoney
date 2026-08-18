from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.market import (
    MarketService,
    is_after_a_share_close,
    last_completed_session,
    next_session_date,
    normalize_code,
    session_status,
    tape_is_closed,
    to_sina_symbol,
)


def test_close_session_helpers():
    assert next_session_date(date(2026, 7, 16)) == date(2026, 7, 17)
    assert next_session_date(date(2026, 7, 17)) == date(2026, 7, 20)
    shanghai = ZoneInfo("Asia/Shanghai")
    assert is_after_a_share_close(datetime(2026, 7, 16, 14, 59, tzinfo=shanghai)) is False
    assert is_after_a_share_close(datetime(2026, 7, 16, 15, 0, tzinfo=shanghai)) is True
    assert is_after_a_share_close(datetime(2026, 7, 18, 10, 0, tzinfo=shanghai)) is True
    assert last_completed_session(
        datetime(2026, 7, 16, 14, 59, tzinfo=shanghai)
    ) == date(2026, 7, 15)
    assert last_completed_session(
        datetime(2026, 7, 16, 15, 0, tzinfo=shanghai)
    ) == date(2026, 7, 16)
    assert last_completed_session(
        datetime(2026, 7, 18, 10, 0, tzinfo=shanghai)
    ) == date(2026, 7, 17)
    morning = session_status(datetime(2026, 7, 16, 9, 10, tzinfo=shanghai))
    assert morning["code"] == "preopen"
    assert morning["for_date"] == "2026-07-16"
    midnight = session_status(datetime(2026, 7, 17, 0, 7, tzinfo=shanghai))
    assert midnight["code"] == "preopen"
    assert midnight["as_of_date"] == "2026-07-16"
    assert midnight["for_date"] == "2026-07-17"
    assert tape_is_closed(datetime(2026, 7, 17, 0, 7, tzinfo=shanghai)) is True
    assert tape_is_closed(datetime(2026, 7, 16, 10, 0, tzinfo=shanghai)) is False
    closed = session_status(datetime(2026, 7, 16, 15, 5, tzinfo=shanghai))
    assert closed["code"] == "after_close"
    assert closed["for_date"] == "2026-07-17"


def test_normalize_and_sina_symbol():
    assert normalize_code("sh600519") == "600519"
    assert normalize_code("sz000001") == "000001"
    assert normalize_code("bj920000") == "920000"
    assert normalize_code("00700") == "00700"
    assert normalize_code("hk700") == "00700"
    assert to_sina_symbol("600519") == "sh600519"
    assert to_sina_symbol("000001") == "sz000001"
    assert to_sina_symbol("300750") == "sz300750"
    assert to_sina_symbol("688981") == "sh688981"
    assert to_sina_symbol("920000") == "bj920000"


def test_parse_spot_rows_accepts_prefixed_codes():
    rows = MarketService._parse_spot_rows(
        [
            {
                "代码": "sh600519",
                "名称": "贵州茅台",
                "最新价": 1500.0,
                "涨跌额": 10.0,
                "涨跌幅": 0.67,
                "今开": 1490.0,
                "最高": 1510.0,
                "最低": 1488.0,
                "昨收": 1490.0,
                "成交量": 1000,
                "成交额": 1_500_000,
            }
        ]
    )
    assert rows[0]["code"] == "600519"
    assert rows[0]["price"] == 1500.0
    assert rows[0]["source"] == "akshare"


def test_parse_hong_kong_spot_rows():
    rows = MarketService._parse_spot_rows(
        [
            {
                "代码": "00700",
                "中文名称": "腾讯控股",
                "最新价": 472.4,
                "涨跌额": 16.2,
                "涨跌幅": 3.55,
                "昨收": 456.2,
                "今开": 467.6,
                "最高": 475.8,
                "最低": 455.4,
                "成交量": 18_000_000,
                "成交额": 8_600_000_000,
            }
        ]
    )
    assert rows[0]["code"] == "00700"
    assert rows[0]["name"] == "腾讯控股"
    assert rows[0]["market"] == "HK"
    assert rows[0]["currency"] == "HKD"


def test_normalize_klines_fills_change_and_turnover():
    rows = MarketService._normalize_klines(
        [
            {
                "date": "2026-07-13",
                "open": 10,
                "high": 11,
                "low": 9.5,
                "close": 10,
                "volume": 100,
                "amount": 1000,
                "turnover": 0.005,
            },
            {
                "date": "2026-07-14",
                "open": 10,
                "high": 11,
                "low": 9.5,
                "close": 11,
                "volume": 100,
                "amount": 1100,
                "turnover": 0.006,
            },
        ]
    )
    assert rows[0]["turnover_rate"] == 0.5
    assert rows[1]["change_pct"] == 10.0


def test_prefilter_balances_momentum_and_liquidity():
    items = [
        {"code": "000001", "name": "高涨幅", "change_pct": 9.8, "amount": 100},
        {"code": "000002", "name": "高成交", "change_pct": 2.0, "amount": 10_000},
        {"code": "000003", "name": "次高涨幅", "change_pct": 8.0, "amount": 200},
        {"code": "000004", "name": "普通", "change_pct": 3.0, "amount": 1000},
        {"code": "000005", "name": "ST风险", "change_pct": 10.0, "amount": 20_000},
        {"code": "000006", "name": "下跌股", "change_pct": -2.0, "amount": 30_000},
    ]

    selected = MarketService._prefilter_candidates(items, 3)

    assert [item["code"] for item in selected] == ["000001", "000003", "000002"]


def test_mainline_uses_first_boards_for_sector_and_second_boards_for_leaders():
    result = MarketService._analyze_limit_up_pool(
        [
            {"代码": "000001", "名称": "医药甲", "所属行业": "医疗器械", "连板数": 1, "封板资金": 10},
            {"代码": "000002", "名称": "医药乙", "所属行业": "医疗器械", "连板数": 1, "封板资金": 20},
            {"代码": "000003", "名称": "医药龙", "所属行业": "医疗器械", "连板数": 2, "封板资金": 30},
            {"代码": "600001", "名称": "电网龙", "所属行业": "电网设备", "连板数": 3, "封板资金": 50},
            {"代码": "600002", "名称": "电网乙", "所属行业": "电网设备", "连板数": 1, "封板资金": 10},
        ],
        "20260715",
    )

    assert result["main_sector"] == "医疗器械"
    assert result["active_sectors"] == ["医疗器械", "电网设备"]
    assert result["sectors"][0]["first_board_count"] == 2
    assert result["ladders"][0]["board_count"] == 3
    assert result["ladders"][0]["stocks"][0]["name"] == "电网龙"
    assert result["stock_sectors"]["000003"] == "医疗器械"


def test_prefilter_puts_mainline_limit_up_stocks_first():
    items = [
        {"code": "000001", "name": "普通高涨", "change_pct": 9.9, "amount": 10_000},
        {"code": "000002", "name": "主线股", "change_pct": 2.0, "amount": 100},
        {"code": "000003", "name": "普通高量", "change_pct": 3.0, "amount": 20_000},
    ]
    selected = MarketService._prefilter_candidates(items, 2, {"000002"})
    assert [item["code"] for item in selected] == ["000002", "000001"]


def test_quote_as_kline_builds_single_session_bar():
    bar = MarketService._quote_as_kline(
        {
            "code": "688825",
            "name": "N长鑫",
            "price": 54.65,
            "open": 49.5,
            "high": 55.03,
            "low": 38.11,
            "volume": 1000,
            "amount": 2e9,
            "change_pct": 531.0,
            "source": "akshare",
        }
    )
    assert bar["close"] == 54.65
    assert bar["open"] == 49.5
    assert bar["high"] == 55.03
    assert bar["low"] == 38.11


def test_stock_daily_uses_live_quote_instead_of_sample_for_ipo(monkeypatch):
    service = MarketService()

    def boom(code, days):
        raise RuntimeError("sina: empty; em: empty")

    monkeypatch.setattr(service, "_fetch_daily_rows", boom)
    monkeypatch.setattr(
        service,
        "quotes",
        lambda codes: {
            "688825": {
                "code": "688825",
                "name": "N长鑫",
                "price": 54.65,
                "open": 49.5,
                "high": 55.03,
                "low": 38.11,
                "volume": 1000,
                "amount": 2e9,
                "change_pct": 531.0,
                "source": "akshare",
                "market": "A",
                "currency": "CNY",
            }
        },
    )
    monkeypatch.setattr(service, "cny_rate", lambda code: 1.0)

    result = service._load_stock_daily("688825", 120)
    assert result["source"] == "partial"
    assert len(result["klines"]) == 1
    assert result["klines"][0]["close"] == 54.65
    assert "新股" in (result["fallback_reason"] or "")


def test_stock_daily_skips_spot_when_tape_closed(monkeypatch):
    service = MarketService()

    def fail_quotes(codes):
        raise AssertionError("should not load the spot tape")

    monkeypatch.setattr(
        service,
        "_fetch_daily_rows",
        lambda code, days: [
            {
                "date": "2026-08-17",
                "open": 10,
                "close": 11,
                "high": 12,
                "low": 9,
                "volume": 1,
                "change_pct": 10.0,
            }
        ],
    )
    monkeypatch.setattr(service, "quotes", fail_quotes)
    monkeypatch.setattr(service, "cny_rate", lambda code: 1.0)
    monkeypatch.setattr(
        "backend.market.session_status",
        lambda now=None: {
            "code": "preopen",
            "as_of_date": "2026-08-17",
            "for_date": "2026-08-18",
        },
    )
    result = service._load_stock_daily("600519", 120)
    assert result["price"] == 11
    assert result["source"] == "akshare"


def test_close_screen_skips_spot_when_tape_closed(monkeypatch):
    service = MarketService()

    def fail_spot():
        raise AssertionError("should not load the spot tape")

    monkeypatch.setattr(service, "_load_spot", fail_spot)
    monkeypatch.setattr("backend.market.tape_is_closed", lambda now=None: True)
    monkeypatch.setattr(
        service,
        "mainline_as_of",
        lambda as_of: {
            "source": "akshare",
            "active_sectors": ["电子"],
            "stock_sectors": {"600519": "电子"},
        },
    )
    monkeypatch.setattr(
        service,
        "_load_active_sector_universe",
        lambda sectors, mapping: {"600519": "电子"},
    )
    monkeypatch.setattr(
        service,
        "_close_screen_one",
        lambda quote, sector, active, as_of: (
            {
                "code": "600519",
                "name": "贵州茅台",
                "score": 100,
                "change_pct": 1.0,
                "amount": 1e9,
            },
            "",
        ),
    )
    result = service.close_screen(max_candidates=1)
    assert result["source"] == "akshare"
    assert result["items"][0]["code"] == "600519"


def test_mainline_uses_last_close_when_tape_closed(monkeypatch):
    service = MarketService()
    seen: list[date] = []
    monkeypatch.setattr("backend.market.tape_is_closed", lambda now=None: True)
    monkeypatch.setattr(
        "backend.market.last_completed_session",
        lambda now=None: date(2026, 8, 17),
    )
    monkeypatch.setattr(
        service,
        "_load_mainline_from",
        lambda as_of: seen.append(as_of) or {"source": "akshare"},
    )
    service._load_mainline()
    assert seen == [date(2026, 8, 17)]
