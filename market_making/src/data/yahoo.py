"""Yahoo Finance data access for market-making simulations."""
from __future__ import annotations

import pandas as pd
import yfinance as yf


def load_prices(
    ticker: str = "SPY",
    *,
    period: str = "5d",
    interval: str = "1m",
) -> pd.DataFrame:
    """Download OHLCV data for a market-making simulation."""
    raw = yf.download(ticker, period=period, interval=interval, auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.xs(ticker, axis=1, level=1, drop_level=True)

    out = raw.copy()
    out.columns = [str(col).lower().replace(" ", "_") for col in out.columns]
    return out.apply(pd.to_numeric, errors="coerce").dropna(how="all")

