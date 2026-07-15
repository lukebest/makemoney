from backend.signals import (
    classify_market_phase,
    enrich_klines,
    moving_average,
    preferred_stock_analysis,
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


def test_market_phase_uses_fried_boards():
    # Sellers keep breaking limit-up boards on shrinking volume -> winter.
    assert classify_market_phase(0.2, 0.5, 0.9, 10, 0, fried_count=20)["code"] == "winter"
    # Heavy volume with half the boards breaking -> distribution, autumn.
    assert classify_market_phase(0.5, 0.6, 1.2, 15, 0, fried_count=18)["code"] == "autumn"
    # Strong day stays summer when boards mostly hold.
    assert classify_market_phase(1.2, 0.7, 1.2, 30, 2, fried_count=5)["code"] == "summer"
    # Too few boards in total: fried ratio is noise and must not flip the phase.
    assert classify_market_phase(0.2, 0.55, 1.0, 3, 0, fried_count=5)["code"] == "spring"


def test_preferred_stock_analysis_is_explainable():
    closes = [90 + index * 0.8 for index in range(30)]
    closes.extend([115, 114, 113, 112, 111, 114, 116, 118, 119, 121])
    rows = []
    for index, close in enumerate(closes):
        volume = 1000.0 if index < 30 else 1300.0
        if index in (35, 39):
            volume = 1800.0
        rows.append(
            {
                "date": f"2026-01-{index + 1:02d}",
                "open": close - 0.3,
                "close": close,
                "high": 120.0 if index == 30 else close + 0.5,
                "low": 110.0 if index == 34 else close - 0.5,
                "volume": volume,
            }
        )

    result = preferred_stock_analysis(enrich_klines(rows))

    assert result["score"] == 100
    assert result["setup"] == "重点观察"
    assert result["washout_days"] == 4
    assert result["pullback_pct"] == 8.33
    assert result["stop_loss"] == 110.0
    assert result["checks"][-1]["status"] == "manual"


def test_preferred_stock_analysis_rejects_short_history():
    result = preferred_stock_analysis([])
    assert result["score"] == 0
    assert result["setup"] == "数据不足"


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
