"""Run the cross-sectional momentum backtest."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.engine import run
from src.backtest.metrics import print_summary
from src.data.yahoo import load_monthly_prices


DEFAULT_UNIVERSE = [
    "SPY", "QQQ", "IWM", "EFA", "EEM",
    "XLK", "XLF", "XLE", "XLV", "XLY",
    "XLP", "XLI", "XLU", "XLB", "VNQ",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-sectional momentum backtest")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--lookback", type=int, default=12)
    parser.add_argument("--skip", type=int, default=1)
    parser.add_argument("--quantile", type=float, default=0.2)
    parser.add_argument("--long-only", action="store_true")
    args = parser.parse_args()

    prices = load_monthly_prices(DEFAULT_UNIVERSE, start=args.start, end=args.end)
    if prices.empty:
        raise SystemExit("No price data loaded")

    returns, turnover = run(
        prices,
        lookback_months=args.lookback,
        skip_months=args.skip,
        quantile=args.quantile,
        long_short=not args.long_only,
    )
    print_summary(returns, label="momentum")
    print(f"Average turnover: {turnover['turnover'].mean():.2f}")


if __name__ == "__main__":
    main()

