"""Yahoo Finance data access for seasonality research."""
from __future__ import annotations

import pandas as pd
import yfinance as yf


def load_daily_prices(
    ticker: str = "SPY",
    *,
    start: str = "1993-01-01",
    end: str = "2024-12-31",
) -> pd.DataFrame:
    """Download daily adjusted OHLCV data."""
    raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs(ticker, axis=1, level=1, drop_level=True)

    out = raw.copy()
    out.columns = [str(col).lower().replace(" ", "_") for col in out.columns]
    return out.apply(pd.to_numeric, errors="coerce").dropna(how="all")

