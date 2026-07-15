from backend.chan import (
    find_fractals,
    find_pivots,
    latest_structure,
    merge_inclusion,
    stroke_points,
    third_buy_signals,
)


def bars(closes: list[float], spread: float = 0.2) -> list[dict]:
    return [
        {
            "date": f"2025-01-{index + 1:02d}",
            "open": close,
            "close": close,
            "high": round(close + spread, 4),
            "low": round(close - spread, 4),
        }
        for index, close in enumerate(closes)
    ]


# One pivot oscillating roughly in [10.2, 12.0], an upward breakout,
# then a pullback that holds above the pivot high -> third buy.
THIRD_BUY_CLOSES = [
    13, 12.25, 11.5, 10.75, 10,          # down to bottom fractal @4
    10.5, 11, 11.4, 11.8, 12,            # up to top @9
    11.6, 11.2, 10.9, 10.6, 10.4,        # down to bottom @14
    10.8, 11.1, 11.4, 11.6, 11.8,        # up to top @19
    11.4, 11.1, 10.9, 10.7, 10.6,        # down to bottom @24
    11.2, 11.9, 12.5, 13.0, 13.5,        # breakout leg, top @29
    13.4, 13.1, 12.8, 12.6, 12.5,        # pullback bottom @34 stays above ZG
    12.6, 12.9, 13.2, 13.5,              # turn up confirms the fractal
]


def test_merge_inclusion_absorbs_contained_bars():
    rows = bars([10, 11, 12]) + [
        {"date": "2025-01-04", "open": 12, "close": 12, "high": 12.1, "low": 11.9}
    ]
    merged = merge_inclusion(rows)
    # The last bar sits inside the previous one and must be absorbed upward.
    assert len(merged) == 3
    assert merged[-1]["high"] == 12.2
    assert merged[-1]["low"] == 11.9


def test_fractals_and_strokes_alternate():
    rows = bars(THIRD_BUY_CLOSES)
    points = stroke_points(find_fractals(merge_inclusion(rows)))
    assert [point["kind"] for point in points] == [
        "bottom", "top", "bottom", "top", "bottom", "top", "bottom",
    ]
    assert [point["index"] for point in points] == [4, 9, 14, 19, 24, 29, 34]


def test_pivot_is_stroke_overlap():
    rows = bars(THIRD_BUY_CLOSES)
    points = stroke_points(find_fractals(merge_inclusion(rows)))
    pivots = find_pivots(points)
    assert len(pivots) == 1
    pivot = pivots[0]
    assert pivot["zg"] == 12.0
    assert pivot["zd"] == 10.2
    assert pivot["start_index"] == 4


def test_third_buy_signal_fires_on_held_pullback():
    signals = third_buy_signals(bars(THIRD_BUY_CLOSES))
    assert len(signals) == 1
    signal = signals[0]
    assert signal["index"] == 35
    assert signal["pivot"]["zg"] == 12.0
    assert signal["pullback_low"] > signal["pivot"]["zg"]


def test_no_third_buy_when_pullback_reenters_pivot():
    closes = THIRD_BUY_CLOSES[:30] + [13.0, 12.6, 12.2, 11.9, 11.7, 12.0, 12.4, 12.8, 13.2]
    assert third_buy_signals(bars(closes)) == []


def test_latest_structure_reports_fresh_signal_only():
    rows = bars(THIRD_BUY_CLOSES)
    structure = latest_structure(rows, recent=10)
    assert structure["pivot"]["zg"] == 12.0
    assert structure["third_buy"]["zg"] == 12.0
    # The same signal is stale once enough new bars pile up after it.
    stale = latest_structure(rows, recent=2)
    assert stale["third_buy"] is None
    assert latest_structure(rows[:5], recent=10) == {"pivot": None, "third_buy": None}
