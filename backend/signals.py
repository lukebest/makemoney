"""Pure technical-signal and review-statistics helpers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence


def moving_average(values: Sequence[float], window: int) -> list[float | None]:
    """Return a same-length simple moving average series."""
    if window <= 0:
        raise ValueError("window must be positive")
    result: list[float | None] = []
    running = 0.0
    for index, value in enumerate(values):
        running += float(value)
        if index >= window:
            running -= float(values[index - window])
        result.append(round(running / window, 4) if index + 1 >= window else None)
    return result


def enrich_klines(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Add MA5/10/20/60 values to normalized K-line rows."""
    closes = [float(row["close"]) for row in rows]
    averages = {window: moving_average(closes, window) for window in (5, 10, 20, 60)}
    enriched: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        item = dict(row)
        for window, values in averages.items():
            item[f"ma{window}"] = values[index]
        enriched.append(item)
    return enriched


def trend_label(rows: Sequence[Mapping[str, Any]]) -> str:
    """Classify the current moving-average trend."""
    if len(rows) < 20:
        return "insufficient"
    last = rows[-1]
    close = float(last["close"])
    ma5 = last.get("ma5")
    ma10 = last.get("ma10")
    ma20 = last.get("ma20")
    if None in (ma5, ma10, ma20):
        return "insufficient"
    if close > float(ma5) > float(ma10) > float(ma20):
        return "up"
    if close < float(ma5) < float(ma10) < float(ma20):
        return "down"
    return "sideways"


def support_resistance(
    rows: Sequence[Mapping[str, Any]], lookback: int = 20
) -> tuple[float | None, float | None]:
    """Estimate support and resistance from recent lows and highs."""
    if not rows or lookback <= 0:
        return None, None
    recent = rows[-lookback:]
    support = min(float(row["low"]) for row in recent)
    resistance = max(float(row["high"]) for row in recent)
    return round(support, 3), round(resistance, 3)


def stock_checklist(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build an explainable trend-following checklist."""
    if not rows:
        return []
    last = rows[-1]
    previous = rows[-6] if len(rows) >= 6 else rows[0]
    avg_volume = (
        sum(float(row.get("volume", 0)) for row in rows[-20:]) / min(len(rows), 20)
    )
    checks = [
        ("price_above_ma20", "收盘价站上20日线", _greater(last.get("close"), last.get("ma20"))),
        ("ma5_above_ma10", "5日线高于10日线", _greater(last.get("ma5"), last.get("ma10"))),
        ("ma10_above_ma20", "10日线高于20日线", _greater(last.get("ma10"), last.get("ma20"))),
        (
            "ma20_rising",
            "20日线持续抬升",
            _greater(last.get("ma20"), previous.get("ma20")),
        ),
        (
            "volume_confirmed",
            "成交量不低于20日均量",
            float(last.get("volume", 0)) >= avg_volume if avg_volume else False,
        ),
    ]
    return [{"key": key, "label": label, "passed": passed} for key, label, passed in checks]


def stop_loss_status(
    live_price: float,
    stop_loss: float,
    ma60: float | None = None,
) -> dict[str, Any]:
    """Return an explainable mechanical stop-loss status."""
    hard_stop = float(live_price) <= float(stop_loss)
    below_ma60 = ma60 is not None and float(live_price) < float(ma60)
    reasons: list[str] = []
    if hard_stop:
        reasons.append("现价已触及或跌破预设止损线")
    if below_ma60:
        reasons.append("现价已跌破60日均线")
    return {
        "triggered": hard_stop or below_ma60,
        "hard_stop": hard_stop,
        "below_ma60": below_ma60,
        "distance_pct": round((float(live_price) / float(stop_loss) - 1) * 100, 2),
        "reasons": reasons,
    }


def classify_market_phase(
    index_change_pct: float,
    advance_ratio: float,
    volume_ratio: float = 1.0,
    limit_up_count: int = 0,
    limit_down_count: int = 0,
) -> dict[str, str]:
    """Map market breadth and momentum to the spring/summer/autumn/winter cycle."""
    if (
        index_change_pct <= -1.0
        or advance_ratio < 0.35
        or limit_down_count > max(5, limit_up_count)
    ):
        return {"code": "winter", "name": "冬藏期", "strategy": "空仓休息，等待风险释放"}
    if (
        index_change_pct >= 1.0
        and advance_ratio >= 0.65
        and volume_ratio >= 1.05
        and limit_up_count >= limit_down_count
    ):
        return {"code": "summer", "name": "夏长期", "strategy": "顺势参与，仍需保留预备资金"}
    if volume_ratio >= 1.35 and advance_ratio < 0.55:
        return {"code": "autumn", "name": "秋收期", "strategy": "逐步减仓，锁定已有利润"}
    return {"code": "spring", "name": "春播期", "strategy": "观察待机，小仓验证市场方向"}


def review_statistics(trades: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate realized performance and discipline statistics."""
    rows = list(trades)
    closed = [
        row
        for row in rows
        if str(row.get("side", "")).lower() == "sell"
        and row.get("realized_pnl") is not None
    ]
    profits = [float(row["realized_pnl"]) for row in closed if float(row["realized_pnl"]) > 0]
    losses = [float(row["realized_pnl"]) for row in closed if float(row["realized_pnl"]) < 0]
    monthly: dict[str, float] = defaultdict(float)
    for row in closed:
        month = str(row.get("traded_at", ""))[:7] or "unknown"
        monthly[month] += float(row["realized_pnl"])
    win_rate = len(profits) / len(closed) if closed else 0.0
    average_profit = sum(profits) / len(profits) if profits else 0.0
    average_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    pnl_ratio = average_profit / average_loss if average_loss else None
    return {
        "total_trades": len(rows),
        "closed_trades": len(closed),
        "wins": len(profits),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "profit_loss_ratio": round(pnl_ratio, 4) if pnl_ratio is not None else None,
        "realized_pnl": round(sum(float(row["realized_pnl"]) for row in closed), 2),
        "monthly_pnl": [
            {"month": month, "pnl": round(value, 2)}
            for month, value in sorted(monthly.items())
        ],
        "violations": sum(bool(row.get("violated", False)) for row in rows),
    }


def _greater(left: Any, right: Any) -> bool:
    return left is not None and right is not None and float(left) > float(right)
