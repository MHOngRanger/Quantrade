"""Run calendar seasonality analysis."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.yahoo import load_daily_prices
from src.research.effects import all_effects, prepare_returns


def main() -> None:
    parser = argparse.ArgumentParser(description="Calendar seasonality analysis")
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--start", default="1993-01-01")
    parser.add_argument("--end", default="2024-12-31")
    args = parser.parse_args()

    prices = load_daily_prices(args.ticker, start=args.start, end=args.end)
    if prices.empty:
        raise SystemExit("No price data loaded")

    df = prepare_returns(prices)
    print(f"{args.ticker}: {df.index.min().date()} -> {df.index.max().date()}, rows={len(df)}")

    for name, table in all_effects(df).items():
        print(f"\n{name}")
        print(table.round(4).to_string())


if __name__ == "__main__":
    main()

