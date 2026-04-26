"""Yahoo Finance data access for momentum strategies."""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import yfinance as yf


def load_monthly_prices(
    tickers: Iterable[str],
    *,
    start: str = "2010-01-01",
    end: str = "2024-12-31",
) -> pd.DataFrame:
    """Download monthly adjusted close prices."""
    symbols = sorted(set(tickers))
    if not symbols:
        return pd.DataFrame()

    raw = yf.download(
        symbols,
        start=start,
        end=end,
        interval="1mo",
        auto_adjust=True,
        progress=False,
    )
    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"]
    else:
        prices = raw[["Close"]].rename(columns={"Close": symbols[0]})

    prices = prices.apply(pd.to_numeric, errors="coerce").dropna(how="all")
    return prices.ffill()

