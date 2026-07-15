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
    """Detect top/bottom fractals (顶/底分型) on inclusion-merged bars."""
    fractals: list[dict[str, Any]] = []
    for position in range(1, len(merged) - 1):
        left, mid, right = merged[position - 1], merged[position], merged[position + 1]
        if mid["high"] > left["high"] and mid["high"] > right["high"]:
            fractals.append(
                {"kind": "top", "index": mid["index"], "price": float(mid["high"])}
            )
        elif mid["low"] < left["low"] and mid["low"] < right["low"]:
            fractals.append(
                {"kind": "bottom", "index": mid["index"], "price": float(mid["low"])}
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


def third_buy_signals(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Find third-type buy points (三买) on daily bars.

    Definition used: after a pivot completes, price closes above ZG
    (leaving the pivot upward); the following pullback bottoms out above ZG
    (a bottom fractal whose low stays above ZG). The signal fires at the bar
    confirming that bottom fractal.
    """
    merged = merge_inclusion(rows)
    points = stroke_points(find_fractals(merged))
    pivots = find_pivots(points)
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
                point
                for point in points
                if point["kind"] == "bottom" and point["index"] > breakout
            ),
            None,
        )
        if pullback is None or pullback["price"] <= pivot["zg"]:
            continue
        confirm = pullback["index"] + 1
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
