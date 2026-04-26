# Quantrade

Quantrade is a quantitative trading research workspace. The main implemented
subproject is `funding_arb`, a Binance TradFi USDT perpetual funding-rate
arbitrage system with backtesting, live signal scanning, paper state tracking,
and optional execution hooks for Binance Futures and IBKR synthetic option
hedges.

> Note: this repository contains trading code. Treat all live execution paths as
> high risk, test with dry-run/paper accounts first, and review exchange/account
> configuration before enabling real orders.

## Repository Layout

```text
Quantrade/
├── main.py                         # Placeholder root entry
├── notebooks/                      # General strategy research notebooks
├── pyproject.toml                  # Root Python project config
├── pairs_trading/                  # Statistical arbitrage subproject
├── momentum/                       # Cross-sectional momentum subproject
├── seasonality/                    # Calendar-effect research subproject
├── market_making/                  # Avellaneda-Stoikov simulation subproject
└── funding_arb/                    # Funding-rate arbitrage subproject
    ├── scripts/                    # Runnable command-line entry points
    ├── src/                        # Core source code
    ├── notebooks/                  # Funding-arb research notebooks
    ├── data/                       # Local caches and runtime state
    ├── pyproject.toml              # Subproject dependencies
    └── bluemap.md                  # Longer-term production architecture plan
```

## Strategy Subprojects

The root notebooks are now mirrored by standalone subproject directories:

```text
pairs_trading/
    Statistical arbitrage framework: data download, cointegration screening,
    z-score signals, and pair backtesting.

momentum/
    Cross-sectional momentum framework: monthly data, 12-1 momentum signals,
    quantile portfolios, and monthly rebalancing.

seasonality/
    Calendar-effect research framework: month-of-year, day-of-week,
    turn-of-month, and sell-in-May summaries.

funding_arb/
    Binance TradFi funding-rate arbitrage framework with backtesting,
    monitoring, paper state, and optional execution.

market_making/
    Avellaneda-Stoikov market-making framework: quote model, fill simulation,
    inventory tracking, and PnL metrics.
```

## Core Subproject: `funding_arb`

The strategy targets Binance TradFi USDT perpetual contracts. It scans funding
rates every 8 hours and, when a rate is large enough, takes the funding-earning
side on Binance. For stock/ETF contracts that have a configured IBKR mapping,
the intended hedge is an IBKR synthetic option position:

- positive funding: short Binance perpetual + synthetic long via IBKR options
- negative funding: long Binance perpetual + synthetic short via IBKR options

The current implementation has two main workflows.

### 1. Backtesting

Entry point:

```bash
cd funding_arb
uv run python scripts/run_backtest.py
```

Main modules:

```text
scripts/run_backtest.py
  -> src/data/binance.py
  -> src/backtest/engine.py or src/backtest/binance_leg.py
  -> src/backtest/costs.py
  -> src/backtest/metrics.py
```

What it does:

- loads historical Binance funding-rate data
- builds a wide time-series panel by symbol
- runs either the full two-leg model or Binance-only funding leg
- reports total return, annualized return, Sharpe ratio, max drawdown, and trade
  events
- optionally runs threshold/leverage sensitivity analysis

Useful commands:

```bash
uv run python scripts/run_backtest.py
uv run python scripts/run_backtest.py --refresh
uv run python scripts/run_backtest.py --threshold 0.00015 --leverage 4
uv run python scripts/run_backtest.py --binance-only
uv run python scripts/run_backtest.py --skip-sensitivity
```

### 2. Live Signal Monitoring and Optional Execution

Entry point:

```bash
cd funding_arb
uv run python scripts/monitor_loop.py --once
```

Main modules:

```text
scripts/monitor_loop.py
  -> src/monitor/scanner.py
  -> src/data/binance.py
  -> src/signal/generator.py
  -> src/execution/paper.py
  -> src/execution/binance_executor.py
  -> src/execution/ibkr.py
  -> src/execution/orchestrator.py
```

What it does:

- fetches current Binance funding data
- generates threshold-based signals
- compares the new signal snapshot with the previous snapshot
- reads local position state from `funding_arb/data/paper_positions.json`
- plans `open`, `close`, or `skip` actions
- optionally executes Binance-only or Binance + IBKR dual-leg actions

Execution modes:

```bash
# Scan once and print signals/plans only. No execution.
uv run python scripts/monitor_loop.py --once

# Enter execution flow, but default dry-run remains enabled. No real orders.
uv run python scripts/monitor_loop.py --once --execute

# Real order path. Use only after reviewing environment, API keys, and account mode.
uv run python scripts/monitor_loop.py --once --execute --no-dry-run

# Execute only the Binance leg.
uv run python scripts/monitor_loop.py --once --execute --binance-only

# Continuous monitor loop. Default interval is 8 hours.
uv run python scripts/monitor_loop.py
```

Environment pairing rules enforced by the monitor:

- Binance Testnet must pair with IBKR Paper
- Binance Production must pair with IBKR Live
- mixed environments are rejected

## Important Source Modules

```text
funding_arb/src/data/binance.py
    Binance TradFi symbol universe, historical funding fetch, current rate fetch,
    and Parquet cache handling.

funding_arb/src/signal/generator.py
    Threshold filtering, direction mapping, and signal weight allocation.

funding_arb/src/backtest/engine.py
    Full two-leg backtest loop with funding income, costs, cooldowns, and
    tracking error.

funding_arb/src/backtest/binance_leg.py
    Binance-only funding-leg backtest.

funding_arb/src/execution/paper.py
    Local position state, cooldown state, and planned action generation.

funding_arb/src/execution/binance_executor.py
    Binance USD-M Futures REST executor using signed requests.

funding_arb/src/execution/ibkr.py
    IBKR synthetic option executor using ib_insync.

funding_arb/src/execution/orchestrator.py
    Dual-leg open/close orchestration.
```

## Setup

This workspace uses `uv` for Python dependency management.

```bash
cd funding_arb
uv sync
```

For live/paper execution, create `funding_arb/.env`:

```text
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
BINANCE_TESTNET=true
```

IBKR execution requires TWS or IB Gateway to be running locally and reachable on
the configured port. The monitor defaults to paper mode unless `--live` is used.

## Current Maturity

The codebase is organized into data, signal, backtest, monitor, and execution
layers. Backtesting and dry-run workflows are the safest paths for exploration.

The execution layer is currently synchronous and sequential. It is suitable for
paper testing and careful small-scale validation, but it is not yet the full
async, production-grade architecture described in `funding_arb/bluemap.md`.
