# momentum

Cross-sectional momentum framework based on `notebooks/02_momentum.ipynb`.

```text
scripts/run_backtest.py
  -> src/data/yahoo.py
  -> src/signal/generator.py
  -> src/backtest/engine.py
  -> src/backtest/metrics.py
```

## Usage

```bash
cd momentum
uv sync
uv run python scripts/run_backtest.py
```

## Strategy Outline

- download monthly adjusted prices
- compute 12-1 momentum signals
- buy the top quantile and optionally short the bottom quantile
- rebalance monthly
- report portfolio performance and turnover

