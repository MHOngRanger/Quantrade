"""
OKX 美股永续合约资金费率数据层（备用数据源）
"""
from __future__ import annotations

import time
import requests
import pandas as pd

OKX_EQUITY_SYMBOLS = [
    "TSLA-USDT-SWAP", "AAPL-USDT-SWAP", "NVDA-USDT-SWAP",
    "MSFT-USDT-SWAP",  "GOOGL-USDT-SWAP", "META-USDT-SWAP",
    "AMZN-USDT-SWAP",  "SPY-USDT-SWAP",   "QQQ-USDT-SWAP",
    "TSM-USDT-SWAP",
]

_BASE = "https://www.okx.com/api/v5/public"


def fetch_funding_history(inst_id: str, max_pages: int = 50) -> pd.Series:
    """
    分页拉取 OKX 永续合约历史资金费率（每8小时一次）。

    Returns:
        pd.Series, index=UTC timestamp, name=inst_id
    """
    all_data: list[dict] = []
    after: str | None = None

    for _ in range(max_pages):
        params: dict = {"instId": inst_id, "limit": 100}
        if after:
            params["after"] = after
        try:
            resp = requests.get(f"{_BASE}/funding-rate-history", params=params, timeout=10)
            batch = resp.json().get("data", [])
        except Exception as e:
            print(f"[warn] {inst_id}: {e}")
            break
        if not batch:
            break
        all_data.extend(batch)
        after = batch[-1]["fundingTime"]
        if len(batch) < 100:
            break
        time.sleep(0.05)

    if not all_data:
        return pd.Series(dtype=float, name=inst_id)

    df = pd.DataFrame(all_data)
    df["ts"]   = pd.to_datetime(df["fundingTime"].astype(int), unit="ms", utc=True)
    df["rate"] = df["fundingRate"].astype(float)
    return df.set_index("ts")["rate"].rename(inst_id).sort_index()


def fetch_current_rates(symbols: list[str] | None = None) -> pd.DataFrame:
    """
    获取 OKX 当前实时费率。
    """
    syms = symbols or OKX_EQUITY_SYMBOLS
    rows = []
    for sym in syms:
        try:
            r = requests.get(f"{_BASE}/funding-rate", params={"instId": sym}, timeout=8)
            d = r.json().get("data", [{}])[0]
            cur = float(d.get("fundingRate", 0) or 0)
            nxt = float(d.get("nextFundingRate", 0) or 0)
            rows.append({
                "symbol":      sym,
                "current_rate": cur,
                "next_rate":   nxt,
                "current_ann": cur * 3 * 365 * 100,
                "next_ann":    nxt * 3 * 365 * 100,
            })
        except Exception as e:
            print(f"[warn] {sym}: {e}")
    return pd.DataFrame(rows).set_index("symbol")


def load_all(symbols: list[str] | None = None) -> pd.DataFrame:
    syms = symbols or OKX_EQUITY_SYMBOLS
    series = [fetch_funding_history(s) for s in syms]
    series = [s for s in series if len(s)]
    if not series:
        return pd.DataFrame()
    return pd.concat(series, axis=1).sort_index().fillna(0)
