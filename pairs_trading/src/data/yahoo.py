"""Yahoo Finance data access for pairs trading."""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import yfinance as yf


def load_prices(
    tickers: Iterable[str],
    *,
    start: str = "2015-01-01",
    end: str = "2024-12-31",
    interval: str = "1d",
) -> pd.DataFrame:
    """Download adjusted close prices and return a clean wide table."""
    symbols = sorted(set(tickers))
    if not symbols:
        return pd.DataFrame()

    raw = yf.download(
        symbols,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=True,
        progress=False,
    )
    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"]
    else:
        prices = raw[["Close"]].rename(columns={"Close": symbols[0]})

    prices = prices.apply(pd.to_numeric, errors="coerce")
    prices = prices.dropna(how="all").ffill()
    return prices.loc[:, prices.notna().any()]

