"""Monthly cross-sectional momentum backtest."""
from __future__ import annotations

import pandas as pd

from ..signal.generator import momentum_signal, quantile_weights


def run(
    prices: pd.DataFrame,
    *,
    lookback_months: int = 12,
    skip_months: int = 1,
    quantile: float = 0.2,
    long_short: bool = True,
    fee_bps: float = 5.0,
) -> tuple[pd.Series, pd.DataFrame]:
    """Run a monthly-rebalanced momentum strategy."""
    prices = prices.sort_index().apply(pd.to_numeric, errors="coerce")
    asset_returns = prices.pct_change().replace([float("inf"), -float("inf")], pd.NA)
    signals = momentum_signal(prices, lookback_months=lookback_months, skip_months=skip_months)

    weights = []
    prev = pd.Series(0.0, index=prices.columns)
    turnovers: list[dict] = []
    for ts, row in signals.iterrows():
        weight = quantile_weights(row, quantile=quantile, long_short=long_short)
        turnover = float((weight - prev).abs().sum())
        turnovers.append({"ts": ts, "turnover": turnover, "active_names": int((weight != 0).sum())})
        weights.append(weight.rename(ts))
        prev = weight

    weight_panel = pd.DataFrame(weights)
    gross_returns = (weight_panel.shift(1) * asset_returns).sum(axis=1)
    costs = pd.Series([row["turnover"] for row in turnovers], index=weight_panel.index) * fee_bps / 10_000
    returns = (gross_returns - costs).dropna().rename("strategy_return")
    turnover_df = pd.DataFrame(turnovers)
    return returns, turnover_df

