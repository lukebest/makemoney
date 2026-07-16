from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.market import (
    MarketService,
    is_after_a_share_close,
    next_session_date,
    normalize_code,
    to_sina_symbol,
)


def test_close_session_helpers():
    assert next_session_date(date(2026, 7, 16)) == date(2026, 7, 17)
    assert next_session_date(date(2026, 7, 17)) == date(2026, 7, 20)
    shanghai = ZoneInfo("Asia/Shanghai")
    assert is_after_a_share_close(datetime(2026, 7, 16, 14, 59, tzinfo=shanghai)) is False
    assert is_after_a_share_close(datetime(2026, 7, 16, 15, 0, tzinfo=shanghai)) is True
    assert is_after_a_share_close(datetime(2026, 7, 18, 10, 0, tzinfo=shanghai)) is True


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
