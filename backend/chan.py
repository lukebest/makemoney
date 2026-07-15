"""Simplified Chan-theory (缠论) structure detectors as pure functions.

Scope is deliberately limited to the parts that can be defined objectively
and backtested: K-line inclusion merging, fractals (分型), stroke endpoints
(笔), pivots (中枢) and third-type buy points (三买). This is not a full
recursive Chan engine; it is a testable structure layer on daily bars.

All functions take normalized K-line rows: mappings with at least
"date", "open", "close", "high", "low".
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def merge_inclusion(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Merge bars with inclusion relationships (包含关系).

    Returns merged bars of {"high", "low", "index"} where index points at the
    original bar carrying the merged extreme, so downstream signals can be
    mapped back to real dates.
    """
    merged: list[dict[str, Any]] = []
    direction = 1  # assumed up until the first non-inclusive bar says otherwise
    for position, row in enumerate(rows):
        high = float(row["high"])
        low = float(row["low"])
        if not merged:
            merged.append({"high": high, "low": low, "index": position})
            continue
        last = merged[-1]
        contains = last["high"] >= high and last["low"] <= low
        contained = last["high"] <= high and last["low"] >= low
        if contains or contained:
            if direction >= 0:
                keep_new = high > last["high"]
                last["high"] = max(last["high"], high)
                last["low"] = max(last["low"], low)
            else:
                keep_new = low < last["low"]
                last["high"] = min(last["high"], high)
                last["low"] = min(last["low"], low)
            if keep_new:
                last["index"] = position
            continue
        direction = 1 if high > last["high"] else -1
        merged.append({"high": high, "low": low, "index": position})
    return merged


def find_fractals(merged: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Detect top/bottom fractals (顶/底分型) on inclusion-merged bars.

    confirm_index is the original index of the right-hand bar: the earliest
    moment the fractal is actually knowable, which backtests must respect.
    """
    fractals: list[dict[str, Any]] = []
    for position in range(1, len(merged) - 1):
        left, mid, right = merged[position - 1], merged[position], merged[position + 1]
        if mid["high"] > left["high"] and mid["high"] > right["high"]:
            kind = "top"
            price = float(mid["high"])
        elif mid["low"] < left["low"] and mid["low"] < right["low"]:
            kind = "bottom"
            price = float(mid["low"])
        else:
            continue
        fractals.append(
            {
                "kind": kind,
                "index": mid["index"],
                "confirm_index": right["index"],
                "price": price,
            }
        )
    return fractals


def stroke_points(
    fractals: Sequence[Mapping[str, Any]], min_gap: int = 4
) -> list[dict[str, Any]]:
    """Reduce fractals to alternating stroke endpoints (笔的端点).

    Consecutive same-kind fractals keep the more extreme one; an opposite
    fractal starts a new stroke only when it is at least min_gap bars away
    and beyond the previous endpoint's price.
    """
    points: list[dict[str, Any]] = []
    for fractal in fractals:
        if not points:
            points.append(dict(fractal))
            continue
        last = points[-1]
        if fractal["kind"] == last["kind"]:
            more_extreme = (
                fractal["price"] >= last["price"]
                if fractal["kind"] == "top"
                else fractal["price"] <= last["price"]
            )
            if more_extreme:
                points[-1] = dict(fractal)
            continue
        far_enough = fractal["index"] - last["index"] >= min_gap
        valid_swing = (
            fractal["price"] > last["price"]
            if fractal["kind"] == "top"
            else fractal["price"] < last["price"]
        )
        if far_enough and valid_swing:
            points.append(dict(fractal))
    return points


def find_pivots(points: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Detect pivots (中枢): the price overlap of three consecutive strokes.

    ZG is the lowest stroke high, ZD the highest stroke low of the first
    three strokes; the pivot extends while later strokes keep overlapping
    the [ZD, ZG] range.
    """
    pivots: list[dict[str, Any]] = []
    index = 0
    while index + 3 < len(points):
        window = points[index : index + 4]
        ranges = [
            (
                min(window[k]["price"], window[k + 1]["price"]),
                max(window[k]["price"], window[k + 1]["price"]),
            )
            for k in range(3)
        ]
        zg = min(top for _, top in ranges)
        zd = max(bottom for bottom, _ in ranges)
        if zg <= zd:
            index += 1
            continue
        end = index + 3
        while end + 1 < len(points):
            low = min(points[end]["price"], points[end + 1]["price"])
            high = max(points[end]["price"], points[end + 1]["price"])
            if low > zg or high < zd:
                break
            end += 1
        pivots.append(
            {
                "start_index": int(points[index]["index"]),
                "end_index": int(points[end]["index"]),
                "zg": round(zg, 4),
                "zd": round(zd, 4),
            }
        )
        index = end
    return pivots


def latest_structure(
    rows: Sequence[Mapping[str, Any]], recent: int = 10
) -> dict[str, Any]:
    """Summarize the latest pivot and any fresh third-buy for the UI.

    Backtested on 60 liquid A-shares x 500 daily bars (2026-07): third-buy
    entries beat unconditional entries on 5/10/20-day horizons, which is why
    this is exposed in the diagnosis page.
    """
    pivots = find_pivots(stroke_points(find_fractals(merge_inclusion(rows))))
    pivot = None
    if pivots:
        last = pivots[-1]
        pivot = {
            "zg": last["zg"],
            "zd": last["zd"],
            "start_date": str(rows[last["start_index"]]["date"]),
            "end_date": str(rows[last["end_index"]]["date"]),
        }
    signals = third_buy_signals(rows)
    third_buy = None
    if signals and signals[-1]["index"] >= len(rows) - recent:
        latest = signals[-1]
        third_buy = {
            "date": latest["date"],
            "price": latest["price"],
            "pullback_low": latest["pullback_low"],
            "zg": latest["pivot"]["zg"],
        }
    return {"pivot": pivot, "third_buy": third_buy}


def third_buy_signals(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Find third-type buy points (三买) on daily bars.

    Definition used: after a pivot completes, price closes above ZG
    (leaving the pivot upward); the first pullback bottom fractal after the
    breakout holds above ZG. To stay causal for backtesting, the pullback is
    taken from raw confirmed fractals (not stroke endpoints, which later
    bars can revise) and the signal fires at the fractal's confirming bar.
    """
    merged = merge_inclusion(rows)
    fractals = find_fractals(merged)
    pivots = find_pivots(stroke_points(fractals))
    signals: list[dict[str, Any]] = []
    for pivot in pivots:
        breakout = next(
            (
                position
                for position in range(pivot["end_index"] + 1, len(rows))
                if float(rows[position]["close"]) > pivot["zg"]
            ),
            None,
        )
        if breakout is None:
            continue
        pullback = next(
            (
                fractal
                for fractal in fractals
                if fractal["kind"] == "bottom" and fractal["index"] > breakout
            ),
            None,
        )
        if pullback is None or pullback["price"] <= pivot["zg"]:
            continue
        confirm = pullback["confirm_index"]
        if confirm >= len(rows):
            continue
        signals.append(
            {
                "index": confirm,
                "date": str(rows[confirm]["date"]),
                "price": float(rows[confirm]["close"]),
                "pivot": pivot,
                "pullback_low": float(pullback["price"]),
            }
        )
    return signals
