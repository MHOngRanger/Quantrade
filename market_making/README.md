# market_making

Market-making simulation framework based on `notebooks/05_market_making.ipynb`.

```text
scripts/run_simulation.py
  -> src/data/yahoo.py
  -> src/model/avellaneda_stoikov.py
  -> src/backtest/simulator.py
  -> src/backtest/metrics.py
```

## Usage

```bash
cd market_making
uv sync
uv run python scripts/run_simulation.py
```

## Model Outline

- estimate rolling volatility from intraday or daily mid prices
- compute reservation price and optimal spread
- simulate bid/ask fills using a simple arrival-probability model
- track inventory, cash, mark-to-market value, and PnL

