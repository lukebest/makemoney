"""Backtest the simplified Chan third-buy signal on real daily history.

Usage:
    PYTHONPATH=. .venv/bin/python -m backend.backtest_chan [--stocks 60] [--days 500]

For a universe of liquid A-shares (top by turnover) it detects historical
third-buy points and measures forward returns over 5/10/20 trading days,
compared against the unconditional baseline of holding the same stocks over
random entry days. This is the evidence gate before wiring the signal into
the product UI.
"""

from __future__ import annotations

import argparse
import statistics
import time

from .chan import third_buy_signals
from .market import MarketService

HORIZONS = (5, 10, 20)


def forward_returns(closes: list[float], index: int) -> dict[int, float] | None:
    result: dict[int, float] = {}
    for horizon in HORIZONS:
        if index + horizon >= len(closes):
            return None
        result[horizon] = closes[index + horizon] / closes[index] - 1
    return result


def summarize(label: str, samples: list[dict[int, float]]) -> None:
    print(f"\n{label}  (n={len(samples)})")
    if not samples:
        print("  no samples")
        return
    for horizon in HORIZONS:
        values = [sample[horizon] for sample in samples]
        wins = sum(value > 0 for value in values) / len(values)
        print(
            f"  {horizon:>2}d: win {wins:6.1%}  mean {statistics.mean(values):+7.2%}"
            f"  median {statistics.median(values):+7.2%}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stocks", type=int, default=60)
    parser.add_argument("--days", type=int, default=500)
    args = parser.parse_args()

    service = MarketService()
    spot = service._load_spot()
    if spot["source"] != "akshare":
        raise SystemExit(f"live spot unavailable: {spot['fallback_reason']}")
    universe = [
        item
        for item in sorted(
            spot["items"], key=lambda item: float(item["amount"]), reverse=True
        )
        if "ST" not in str(item["name"]).upper()
        and "退" not in str(item["name"])
        and float(item["price"]) >= 2
    ][: args.stocks]
    print(f"universe: {len(universe)} most-traded A-shares, {args.days} daily bars")

    signal_samples: list[dict[int, float]] = []
    baseline_samples: list[dict[int, float]] = []
    fetched = 0
    failed: list[str] = []
    for item in universe:
        code = item["code"]
        try:
            rows = service._fetch_daily_rows(code, args.days)
        except Exception as exc:
            failed.append(f"{code}: {exc}")
            continue
        fetched += 1
        closes = [float(row["close"]) for row in rows]
        for signal in third_buy_signals(rows):
            returns = forward_returns(closes, signal["index"])
            if returns is not None:
                signal_samples.append(returns)
        # Unconditional baseline: every 5th bar to keep sample size sane.
        for index in range(60, len(closes) - max(HORIZONS), 5):
            returns = forward_returns(closes, index)
            if returns is not None:
                baseline_samples.append(returns)
        time.sleep(0.15)

    print(f"fetched {fetched}/{len(universe)} stocks; {len(failed)} failed")
    summarize("third-buy signal", signal_samples)
    summarize("baseline (unconditional entries)", baseline_samples)


if __name__ == "__main__":
    main()
