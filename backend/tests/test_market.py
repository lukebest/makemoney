from backend.market import MarketService, normalize_code, to_sina_symbol


def test_normalize_and_sina_symbol():
    assert normalize_code("sh600519") == "600519"
    assert normalize_code("sz000001") == "000001"
    assert normalize_code("bj920000") == "920000"
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
