"""Pairs trading backtest engine."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..signal.generator import PairCandidate, pair_spread, zscore


def backtest_pair(
    log_prices: pd.DataFrame,
    candidate: PairCandidate,
    *,
    lookback: int = 60,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    fee_bps: float = 2.0,
) -> tuple[pd.Series, pd.DataFrame]:
    """Backtest one pair using spread z-score bands."""
    spread = pair_spread(log_prices, candidate)
    z = zscore(spread, lookback=lookback)
    spread_ret = spread.diff().fillna(0.0)

    position = 0
    positions: list[int] = []
    events: list[dict] = []
    fee = fee_bps / 10_000

    for ts, value in z.items():
        prev = position
        if np.isnan(value):
            positions.append(position)
            continue

        if position == 0:
            if value > entry_z:
                position = -1
                events.append({"ts": ts, "event": "enter_short_spread", "zscore": round(float(value), 3)})
            elif value < -entry_z:
                position = 1
                events.append({"ts": ts, "event": "enter_long_spread", "zscore": round(float(value), 3)})
        elif abs(value) < exit_z:
            events.append({"ts": ts, "event": "exit_mean_reversion", "zscore": round(float(value), 3)})
            position = 0
        elif abs(value) > stop_z:
            events.append({"ts": ts, "event": "stop_loss", "zscore": round(float(value), 3)})
            position = 0

        positions.append(position)
        if position != prev and ts in spread_ret.index:
            spread_ret.loc[ts] -= fee

    pos = pd.Series(positions, index=z.index, name="position").shift(1).fillna(0)
    returns = (pos * spread_ret.reindex(pos.index).fillna(0.0)).rename("strategy_return")
    trades = pd.DataFrame(events)
    return returns, trades


def backtest_candidates(
    log_prices: pd.DataFrame,
    candidates: list[PairCandidate],
    **kwargs,
) -> tuple[pd.Series, pd.DataFrame]:
    """Equal-weight all candidate pair strategies."""
    if not candidates:
        return pd.Series(dtype=float, name="portfolio_return"), pd.DataFrame()

    returns = []
    trade_logs = []
    for candidate in candidates:
        ret, trades = backtest_pair(log_prices, candidate, **kwargs)
        returns.append(ret.rename(f"{candidate.ticker_a}-{candidate.ticker_b}"))
        if not trades.empty:
            trades["pair"] = f"{candidate.ticker_a}-{candidate.ticker_b}"
            trade_logs.append(trades)

    panel = pd.concat(returns, axis=1).fillna(0.0)
    portfolio = panel.mean(axis=1).rename("portfolio_return")
    trade_df = pd.concat(trade_logs, ignore_index=True) if trade_logs else pd.DataFrame()
    return portfolio, trade_df

