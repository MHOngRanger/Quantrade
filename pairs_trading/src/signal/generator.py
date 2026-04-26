"""Cointegration and z-score signal generation for pair trading."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint


@dataclass(frozen=True)
class PairCandidate:
    ticker_a: str
    ticker_b: str
    hedge_ratio: float
    intercept: float
    pvalue: float


def estimate_hedge_ratio(series_a: pd.Series, series_b: pd.Series) -> tuple[float, float]:
    """Estimate A = intercept + beta * B using OLS."""
    aligned = pd.concat([series_a, series_b], axis=1).dropna()
    if len(aligned) < 30:
        raise ValueError("not enough observations to estimate hedge ratio")

    y = aligned.iloc[:, 0]
    x = sm.add_constant(aligned.iloc[:, 1])
    model = sm.OLS(y, x).fit()
    return float(model.params.iloc[1]), float(model.params.iloc[0])


def find_cointegrated_pairs(
    log_prices: pd.DataFrame,
    *,
    significance: float = 0.05,
) -> list[PairCandidate]:
    """Run Engle-Granger tests for every pair in the price panel."""
    candidates: list[PairCandidate] = []
    for ticker_a, ticker_b in combinations(log_prices.columns, 2):
        pair = log_prices[[ticker_a, ticker_b]].dropna()
        if len(pair) < 60:
            continue

        _, pvalue, _ = coint(pair[ticker_a], pair[ticker_b])
        if pvalue > significance:
            continue

        hedge_ratio, intercept = estimate_hedge_ratio(pair[ticker_a], pair[ticker_b])
        candidates.append(
            PairCandidate(
                ticker_a=ticker_a,
                ticker_b=ticker_b,
                hedge_ratio=hedge_ratio,
                intercept=intercept,
                pvalue=float(pvalue),
            )
        )

    return sorted(candidates, key=lambda item: item.pvalue)


def pair_spread(log_prices: pd.DataFrame, candidate: PairCandidate) -> pd.Series:
    """Build the stationary spread A - intercept - beta * B."""
    return (
        log_prices[candidate.ticker_a]
        - candidate.intercept
        - candidate.hedge_ratio * log_prices[candidate.ticker_b]
    ).dropna()


def zscore(series: pd.Series, lookback: int = 60) -> pd.Series:
    """Rolling z-score."""
    mean = series.rolling(lookback).mean()
    std = series.rolling(lookback).std()
    return (series - mean) / std.replace(0, np.nan)

