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


def preferred_stock_analysis(
    rows: Sequence[Mapping[str, Any]],
    sector: str | None = None,
    active_sectors: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Score the lecture's stock-selection conditions with explainable rules."""
    if len(rows) < 40:
        return {
            "score": 0,
            "setup": "数据不足",
            "checks": [],
            "stop_loss": None,
            "washout_days": None,
            "pullback_pct": None,
        }

    recent = list(rows[-40:])
    closes = [float(row["close"]) for row in recent]
    volumes = [float(row.get("volume", 0)) for row in recent]
    last = recent[-1]

    base_volume = _average(volumes[-30:-10])
    recent_volume = _average(volumes[-10:])
    volume_spikes = sum(
        volume >= base_volume * 1.5 for volume in volumes[-10:]
    ) if base_volume else 0
    volume_ratio = recent_volume / base_volume if base_volume else 0.0
    volume_pile = volume_ratio >= 1.15 and volume_spikes >= 2

    pattern = recent[-25:]
    peak_search = pattern[:-3]
    peak_index = max(
        range(len(peak_search)),
        key=lambda index: float(peak_search[index]["high"]),
    )
    peak_price = float(pattern[peak_index]["high"])
    after_peak = pattern[peak_index + 1:-1]
    trough_offset = (
        min(
            range(len(after_peak)),
            key=lambda index: float(after_peak[index]["low"]),
        )
        if after_peak
        else None
    )
    trough_index = peak_index + 1 + trough_offset if trough_offset is not None else None
    trough_price = (
        float(pattern[trough_index]["low"]) if trough_index is not None else peak_price
    )
    pullback_pct = (
        max(0.0, (peak_price - trough_price) / peak_price * 100)
        if peak_price
        else 0.0
    )
    washout_days = trough_index - peak_index if trough_index is not None else 0
    controlled_washout = (
        trough_index is not None
        and 1 <= washout_days <= 10
        and 0 < pullback_pct <= 12
        and float(last["close"]) > trough_price
    )

    prior_close = _average(closes[-10:-5])
    current_close = _average(closes[-5:])
    prior_volume = _average(volumes[-10:-5])
    current_volume = _average(volumes[-5:])
    price_volume_shift = (
        current_close > prior_close
        and current_volume >= prior_volume * 0.8
    )

    previous_high = max(float(row["high"]) for row in recent[-21:-1])
    average_volume = _average(volumes[-20:])
    ma5 = last.get("ma5")
    ma10 = last.get("ma10")
    ma20 = last.get("ma20")
    moving_averages_up = (
        ma5 is not None
        and ma10 is not None
        and ma20 is not None
        and float(ma5) > float(ma10) > float(ma20)
    )
    startup_signal = (
        float(last["close"]) >= previous_high * 0.98
        and float(last.get("volume", 0)) >= average_volume
        and moving_averages_up
    )
    active_sector = bool(
        active_sectors is not None and sector and sector in active_sectors
    )

    machine_checks = [
        (
            "volume_pile",
            "主力入场有量",
            volume_pile,
            f"近10日量能为前期的 {volume_ratio:.2f} 倍，显著放量 {volume_spikes} 天",
        ),
        (
            "controlled_washout",
            "洗盘短而可控",
            controlled_washout,
            f"高点后 {washout_days} 日见低，最大回撤 {pullback_pct:.1f}%",
        ),
        (
            "price_volume_shift",
            "洗盘后价量重心上移",
            price_volume_shift,
            f"近5日均价较前5日 {'抬升' if current_close > prior_close else '回落'}，量能比 {current_volume / prior_volume:.2f}" if prior_volume else "量能不足",
        ),
        (
            "startup_signal",
            "强势启动信号",
            startup_signal,
            "价格接近20日高点、均线多头且成交量确认",
        ),
    ]
    if active_sectors is not None:
        machine_checks.append(
            (
                "active_sector",
                "处在活跃板块",
                active_sector,
                f"{sector or '行业未知'}"
                + ("位于今日热点主线" if active_sector else "不在今日热点主线前三"),
            )
        )
    weight = 100 // len(machine_checks)
    score = sum(weight for _, _, passed, _ in machine_checks if passed)
    setup = "重点观察" if score >= 80 else "继续跟踪" if score >= 60 else "条件不足"
    stop_loss = round(min(float(row["low"]) for row in recent[-10:]), 3)
    checks = [
        {
            "key": key,
            "label": label,
            "status": "passed" if passed else "failed",
            "detail": detail,
        }
        for key, label, passed, detail in machine_checks
    ]
    if active_sectors is None:
        checks.append(
            {
                "key": "active_sector",
                "label": "处在活跃板块",
                "status": "manual",
                "detail": "涨停池暂不可用，本项不计入机器评分",
            }
        )
    return {
        "score": score,
        "setup": setup,
        "checks": checks,
        "stop_loss": stop_loss,
        "washout_days": washout_days,
        "pullback_pct": round(pullback_pct, 2),
    }


def market_structure_analysis(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Classify observable price-volume structure without claiming intent as fact.

    The names follow the lecture's accumulation/washout/markup/distribution
    vocabulary, but every result is deliberately prefixed with "疑似": OHLCV
    can describe behaviour, not prove who traded or why.
    """
    if len(rows) < 40:
        return {
            "phase": "insufficient",
            "label": "数据不足",
            "summary": "至少需要 40 个交易日才能判断量价阶段",
            "evidence": [],
            "acceptance": _acceptance_analysis(rows),
        }

    recent = list(rows[-40:])
    last = recent[-1]
    closes = [float(row["close"]) for row in recent]
    volumes = [float(row.get("volume", 0)) for row in recent]
    highs = [float(row["high"]) for row in recent]
    lows = [float(row["low"]) for row in recent]
    base_volume = _average(volumes[-25:-5])
    current_volume = _average(volumes[-5:])
    volume_ratio = current_volume / base_volume if base_volume else 0.0
    return_5 = closes[-1] / closes[-6] - 1
    return_20 = closes[-1] / closes[-21] - 1
    high_20 = max(highs[-20:])
    low_20 = min(lows[-20:])
    range_20 = (high_20 - low_20) / low_20 if low_20 else 0.0
    drawdown = closes[-1] / high_20 - 1 if high_20 else 0.0
    ma5, ma10, ma20 = last.get("ma5"), last.get("ma10"), last.get("ma20")
    uptrend = (
        None not in (ma5, ma10, ma20)
        and closes[-1] > float(ma5) > float(ma10) > float(ma20)
    )
    ma20_rising = (
        ma20 is not None
        and recent[-6].get("ma20") is not None
        and float(ma20) > float(recent[-6]["ma20"])
    )

    if (
        closes[-1] >= high_20 * 0.94
        and volume_ratio >= 1.25
        and return_5 <= 0.01
    ):
        phase = "distribution"
        label = "疑似出货"
        summary = "高位放量但价格推进有限，需防止分歧转弱"
        evidence = [
            f"近5日量能为前20日的 {volume_ratio:.2f} 倍",
            f"近5日涨跌 {return_5 * 100:.1f}%，收盘仍靠近20日高位",
        ]
    elif uptrend and ma20_rising and return_20 > 0.05 and drawdown >= -0.08:
        phase = "markup"
        label = "疑似拉升（主升）"
        summary = "均线多头且中期趋势抬升，价格保持在阶段高位附近"
        evidence = [
            "收盘价、MA5、MA10、MA20 呈多头排列",
            f"近20日上涨 {return_20 * 100:.1f}%，距20日高点 {abs(drawdown) * 100:.1f}%",
        ]
    elif (
        return_20 > 0.03
        and -0.12 <= drawdown <= -0.02
        and return_5 < 0
        and volume_ratio <= 0.9
    ):
        phase = "washout"
        label = "疑似洗盘"
        summary = "前期上涨后的缩量回调，回撤尚在可控范围"
        evidence = [
            f"近20日仍上涨 {return_20 * 100:.1f}%",
            f"距高点回撤 {abs(drawdown) * 100:.1f}%，近5日量比 {volume_ratio:.2f}",
        ]
    elif range_20 <= 0.16 and 0.9 <= volume_ratio <= 1.35:
        phase = "accumulation"
        label = "疑似建仓"
        summary = "价格在有限区间反复换手，量能保持但方向尚未突破"
        evidence = [
            f"近20日振幅 {range_20 * 100:.1f}%",
            f"近5日量能为前20日的 {volume_ratio:.2f} 倍",
        ]
    else:
        phase = "watch"
        label = "阶段待确认"
        summary = "当前量价组合不满足建仓、洗盘、拉升或出货的明确规则"
        evidence = [
            f"近20日涨跌 {return_20 * 100:.1f}%",
            f"近5日量比 {volume_ratio:.2f}",
        ]

    return {
        "phase": phase,
        "label": label,
        "summary": summary,
        "evidence": evidence,
        "metrics": {
            "return_20_pct": round(return_20 * 100, 2),
            "drawdown_pct": round(drawdown * 100, 2),
            "volume_ratio": round(volume_ratio, 2),
        },
        "acceptance": _acceptance_analysis(recent),
    }


def _acceptance_analysis(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Translate the lecture's price/volume table into observable acceptance."""
    if len(rows) < 10:
        return {
            "code": "insufficient",
            "label": "承接数据不足",
            "summary": "至少需要 10 个交易日",
        }
    recent = list(rows[-10:])
    closes = [float(row["close"]) for row in recent]
    volumes = [float(row.get("volume", 0)) for row in recent]
    base = _average(volumes[:-3])
    current = _average(volumes[-3:])
    volume_ratio = current / base if base else 0.0
    change = closes[-1] / closes[-4] - 1
    if change <= -0.02 and volume_ratio >= 1.05:
        code, label = "none", "下跌有量 · 无承接"
        summary = "卖压释放时成交放大，买方承接不足"
    elif abs(change) < 0.02 and volume_ratio >= 1.05:
        code, label = "absorbing", "横盘有量 · 有承接"
        summary = "分歧放大但价格守住区间，存在换手承接"
    elif change >= 0.02 and volume_ratio >= 1.05:
        code, label = "strong", "上涨有量 · 强承接"
        summary = "价格上涨同时成交活跃，买方承接占优"
    else:
        code, label = "weak", "量能不足 · 承接待确认"
        summary = "近三日量价没有给出明确的承接证据"
    return {
        "code": code,
        "label": label,
        "summary": summary,
        "change_3d_pct": round(change * 100, 2),
        "volume_ratio": round(volume_ratio, 2),
    }


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
    fried_count: int = 0,
) -> dict[str, str]:
    """Map market breadth and momentum to the spring/summer/autumn/winter cycle.

    fried_count is the number of broken limit-up boards (炸板). A high fried
    ratio means sellers are winning the limit-up battle, which the lecture
    treats as a cooling or topping signal.
    """
    boards = limit_up_count + fried_count
    fried_ratio = fried_count / boards if boards >= 10 else 0.0
    if (
        index_change_pct <= -1.0
        or advance_ratio < 0.35
        or limit_down_count > max(5, limit_up_count)
        or (fried_ratio >= 0.6 and volume_ratio < 0.95)
    ):
        return {"code": "winter", "name": "冬藏期", "strategy": "空仓休息，等待风险释放"}
    if (
        index_change_pct >= 1.0
        and advance_ratio >= 0.65
        and volume_ratio >= 1.05
        and limit_up_count >= limit_down_count
        and fried_ratio < 0.5
    ):
        return {"code": "summer", "name": "夏长期", "strategy": "顺势参与，仍需保留预备资金"}
    if (volume_ratio >= 1.35 and advance_ratio < 0.55) or (
        fried_ratio >= 0.5 and volume_ratio >= 1.15
    ):
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


def _average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
