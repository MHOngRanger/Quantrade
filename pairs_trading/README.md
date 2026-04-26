# pairs_trading

Statistical arbitrage framework for equity/ETF pair trading.

This module is based on `notebooks/01_pairs_trading.ipynb` and turns the notebook
workflow into reusable code:

```text
scripts/run_backtest.py
  -> src/data/yahoo.py
  -> src/signal/generator.py
  -> src/backtest/engine.py
  -> src/backtest/metrics.py
```

## Usage

```bash
cd pairs_trading
uv sync
uv run python scripts/run_backtest.py
```

## Strategy Outline

- download adjusted close prices
- test candidate pairs with Engle-Granger cointegration
- estimate hedge ratio with OLS
- trade mean reversion in the pair spread using z-score bands
- report returns, Sharpe ratio, max drawdown, and trade events

