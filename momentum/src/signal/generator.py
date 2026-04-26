"""Cross-sectional momentum signal generation."""
from __future__ import annotations

import pandas as pd


def momentum_signal(
    prices: pd.DataFrame,
    *,
    lookback_months: int = 12,
    skip_months: int = 1,
) -> pd.DataFrame:
    """Compute 12-1 style momentum: return from t-lookback to t-skip."""
    start_prices = prices.shift(lookback_months)
    end_prices = prices.shift(skip_months)
    return (end_prices / start_prices - 1).replace([float("inf"), -float("inf")], pd.NA)


def quantile_weights(
    signal_row: pd.Series,
    *,
    quantile: float = 0.2,
    long_short: bool = True,
) -> pd.Series:
    """Convert one cross-section of signals into equal-weight portfolio weights."""
    clean = signal_row.dropna().sort_values()
    weights = pd.Series(0.0, index=signal_row.index)
    if clean.empty:
        return weights

    n = max(1, int(len(clean) * quantile))
    longs = clean.tail(n).index
    weights.loc[longs] = 1.0 / len(longs)

    if long_short:
        shorts = clean.head(n).index
        weights.loc[shorts] = -1.0 / len(shorts)

    return weights

