from backend.signals import (
    classify_market_phase,
    enrich_klines,
    moving_average,
    review_statistics,
    stop_loss_status,
    support_resistance,
    trend_label,
)


def test_moving_average_preserves_length_and_warmup():
    assert moving_average([1, 2, 3, 4], 3) == [None, None, 2.0, 3.0]


def test_enrichment_trend_and_levels():
    rows = [
        {
            "date": f"2026-01-{index + 1:02d}",
            "open": float(index + 1),
            "close": float(index + 1),
            "high": float(index + 2),
            "low": float(index),
            "volume": 1000.0,
        }
        for index in range(65)
    ]
    enriched = enrich_klines(rows)
    assert enriched[-1]["ma5"] == 63.0
    assert enriched[-1]["ma60"] == 35.5
    assert trend_label(enriched) == "up"
    assert support_resistance(enriched, 20) == (45.0, 66.0)


def test_market_phase_boundaries():
    assert classify_market_phase(-1.1, 0.6)["code"] == "winter"
    assert classify_market_phase(1.2, 0.7, 1.2, 30, 2)["code"] == "summer"
    assert classify_market_phase(0.2, 0.5, 1.5, 5, 2)["code"] == "autumn"
    assert classify_market_phase(0.2, 0.55)["code"] == "spring"


def test_stop_loss_status_explains_hard_stop_and_ma60():
    status = stop_loss_status(8.8, 9.0, 9.2)
    assert status["triggered"] is True
    assert status["hard_stop"] is True
    assert status["below_ma60"] is True
    assert len(status["reasons"]) == 2


def test_review_statistics():
    trades = [
        {"side": "buy", "realized_pnl": None, "traded_at": "2026-01-01", "violated": 0},
        {"side": "sell", "realized_pnl": 200, "traded_at": "2026-01-02", "violated": 0},
        {"side": "sell", "realized_pnl": -100, "traded_at": "2026-02-02", "violated": 1},
    ]
    stats = review_statistics(trades)
    assert stats["win_rate"] == 0.5
    assert stats["profit_loss_ratio"] == 2.0
    assert stats["realized_pnl"] == 100.0
    assert stats["violations"] == 1
    assert stats["monthly_pnl"] == [
        {"month": "2026-01", "pnl": 200.0},
        {"month": "2026-02", "pnl": -100.0},
    ]
