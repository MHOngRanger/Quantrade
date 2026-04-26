"""Run the Avellaneda-Stoikov market-making simulation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.metrics import print_summary
from src.backtest.simulator import run_simulation
from src.data.yahoo import load_prices


def main() -> None:
    parser = argparse.ArgumentParser(description="Market-making simulation")
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--period", default="5d")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--gamma", type=float, default=0.1)
    parser.add_argument("--kappa", type=float, default=1.5)
    parser.add_argument("--max-inventory", type=float, default=10.0)
    args = parser.parse_args()

    prices = load_prices(args.ticker, period=args.period, interval=args.interval)
    if prices.empty or "close" not in prices:
        raise SystemExit("No price data loaded")

    sim = run_simulation(
        prices["close"],
        gamma=args.gamma,
        kappa=args.kappa,
        max_inventory=args.max_inventory,
    )
    print_summary(sim)
    print(sim.tail().round(4).to_string())


if __name__ == "__main__":
    main()

