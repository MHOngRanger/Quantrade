"""Run the pairs trading research backtest."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.engine import backtest_candidates
from src.backtest.metrics import print_summary
from src.data.yahoo import load_prices
from src.signal.generator import find_cointegrated_pairs


DEFAULT_PAIRS = [
    ("SPY", "IVV"),
    ("QQQ", "XLK"),
    ("XLE", "CVX"),
    ("KO", "PEP"),
    ("MA", "V"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pairs trading backtest")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--entry-z", type=float, default=2.0)
    parser.add_argument("--exit-z", type=float, default=0.5)
    parser.add_argument("--lookback", type=int, default=60)
    args = parser.parse_args()

    tickers = sorted({ticker for pair in DEFAULT_PAIRS for ticker in pair})
    prices = load_prices(tickers, start=args.start, end=args.end)
    if prices.empty:
        raise SystemExit("No price data loaded")

    log_prices = np.log(prices)
    candidates = find_cointegrated_pairs(log_prices)
    print(f"Cointegrated pairs: {len(candidates)}")
    for candidate in candidates[:10]:
        print(
            f"  {candidate.ticker_a}-{candidate.ticker_b} "
            f"p={candidate.pvalue:.4f} beta={candidate.hedge_ratio:.3f}"
        )

    returns, trades = backtest_candidates(
        log_prices,
        candidates,
        lookback=args.lookback,
        entry_z=args.entry_z,
        exit_z=args.exit_z,
    )
    print_summary(returns, label="pairs")
    print(f"Trade events: {len(trades)}")


if __name__ == "__main__":
    main()

