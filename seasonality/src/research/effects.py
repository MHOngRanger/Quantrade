"""Calendar effect calculations."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def prepare_returns(prices: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
    """Add daily returns and calendar columns to a price table."""
    if price_col not in prices:
        raise KeyError(f"missing price column: {price_col}")

    df = prices.copy()
    df["ret"] = df[price_col].pct_change()
    idx = pd.DatetimeIndex(df.index)
    df["month"] = idx.month
    df["month_name"] = idx.month_name()
    df["day_of_week"] = idx.dayofweek
    df["day_name"] = idx.day_name()
    df["day"] = idx.day
    df["days_in_month"] = idx.days_in_month
    df["is_turn_of_month"] = (df["day"] >= df["days_in_month"] - 2) | (df["day"] <= 3)
    df["is_may_to_oct"] = df["month"].between(5, 10)
    return df.dropna(subset=["ret"])


def _summary(grouped: pd.core.groupby.SeriesGroupBy) -> pd.DataFrame:
    out = grouped.agg(["count", "mean", "std"])
    out["ann_ret"] = out["mean"] * 252
    out["ann_vol"] = out["std"] * np.sqrt(252)
    out["t_stat"] = grouped.apply(lambda s: stats.ttest_1samp(s.dropna(), 0.0).statistic)
    out["p_value"] = grouped.apply(lambda s: stats.ttest_1samp(s.dropna(), 0.0).pvalue)
    return out


def month_of_year(df: pd.DataFrame) -> pd.DataFrame:
    """Return return statistics by calendar month."""
    return _summary(df.groupby("month")["ret"])


def day_of_week(df: pd.DataFrame) -> pd.DataFrame:
    """Return return statistics by weekday."""
    return _summary(df.groupby("day_of_week")["ret"])


def turn_of_month(df: pd.DataFrame) -> pd.DataFrame:
    """Compare turn-of-month days with all other days."""
    return _summary(df.groupby("is_turn_of_month")["ret"])


def sell_in_may(df: pd.DataFrame) -> pd.DataFrame:
    """Compare May-Oct returns against Nov-Apr returns."""
    return _summary(df.groupby("is_may_to_oct")["ret"])


def all_effects(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Compute all supported calendar-effect summaries."""
    return {
        "month_of_year": month_of_year(df),
        "day_of_week": day_of_week(df),
        "turn_of_month": turn_of_month(df),
        "sell_in_may": sell_in_may(df),
    }

