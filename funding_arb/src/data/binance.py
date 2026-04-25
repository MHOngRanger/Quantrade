"""
Binance TradFi 永续合约资金费率数据层。

改进点：
- 历史 funding 使用 Session + retry，减少瞬时网络失败
- `load_all()` 并发拉取，避免 TradFi 合约串行阻塞
- 缓存增量更新时保留重叠窗口，避免边界重复/漏数
- 实时费率通过一次 `premiumIndex` 批量请求完成
- 将毫秒抖动统一到整秒，并过滤到项目使用的 8h 结算栅格
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Binance USDⓈ-M 当前上线的全部 TradFi USDT 永续合约。
# 来源：/fapi/v1/exchangeInfo, contractType=TRADIFI_PERPETUAL, status=TRADING。
TRADFI_EQUITY_SYMBOLS = [
    "AAPLUSDT",
    "AMZNUSDT",
    "AVGOUSDT",
    "BABAUSDT",
    "COINUSDT",
    "CRCLUSDT",
    "EWJUSDT",
    "EWYUSDT",
    "GOOGLUSDT",
    "HOODUSDT",
    "INTCUSDT",
    "METAUSDT",
    "MSFTUSDT",
    "MSTRUSDT",
    "MUUSDT",
    "NVDAUSDT",
    "PAYPUSDT",
    "PLTRUSDT",
    "QQQUSDT",
    "SNDKUSDT",
    "SPYUSDT",
    "TSLAUSDT",
    "TSMUSDT",
]

TRADFI_COMMODITY_SYMBOLS = [
    "BZUSDT",
    "CLUSDT",
    "COPPERUSDT",
    "NATGASUSDT",
    "XAGUSDT",
    "XAUUSDT",
    "XPDUSDT",
    "XPTUSDT",
]

TRADFI_SYMBOLS = TRADFI_EQUITY_SYMBOLS + TRADFI_COMMODITY_SYMBOLS

# Backward-compatible equity-only alias. Signal pool uses TRADFI_SYMBOLS.
EQUITY_SYMBOLS = TRADFI_EQUITY_SYMBOLS

_BASE = "https://fapi.binance.com/fapi/v1"
_CACHE_DIR = Path(__file__).parent.parent.parent / "data"
_HISTORY_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SETTLEMENT_FREQ = "8h"
_CACHE_OVERLAP_ROWS = 3
_REQUEST_TIMEOUT = (5, 20)


def _build_session() -> requests.Session:
    retry = Retry(
        total=4,
        read=4,
        connect=4,
        backoff_factor=0.35,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=16,
        pool_maxsize=16,
    )

    session = requests.Session()
    session.headers.update({"User-Agent": "funding-arb/0.1"})
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _request_json(
    path: str,
    params: dict | None = None,
    session: requests.Session | None = None,
) -> list[dict] | dict:
    owns_session = session is None
    session = session or _build_session()
    try:
        resp = session.get(f"{_BASE}/{path}", params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    finally:
        if owns_session:
            session.close()

    if isinstance(payload, dict) and payload.get("code") not in (None, 200):
        raise RuntimeError(f"Binance API error: {payload}")
    return payload


def _normalize_index(index: pd.Index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    return idx.round("s")


def _canonicalize_history(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float, name=series.name)

    cleaned = series.copy()
    cleaned.index = _normalize_index(cleaned.index)
    cleaned = cleaned.sort_index()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]

    # 项目回测以 00:00 / 08:00 / 16:00 UTC 为结算周期。
    cleaned = cleaned[cleaned.index.hour % 8 == 0]
    cleaned.index.name = "ts"
    return cleaned.astype(float).rename(series.name)


def _read_cache(path: Path, symbol: str) -> pd.Series:
    cached = pd.read_parquet(path)
    if isinstance(cached, pd.DataFrame):
        if symbol in cached.columns:
            cached = cached[symbol]
        else:
            cached = cached.squeeze("columns")
    return _canonicalize_history(pd.Series(cached, name=symbol))


def _write_cache(path: Path, series: pd.Series) -> None:
    tmp_path = path.with_suffix(".tmp.parquet")
    series.to_frame(name=series.name).to_parquet(tmp_path)
    tmp_path.replace(path)


def _latest_expected_settlement(now: datetime | None = None) -> pd.Timestamp:
    current = pd.Timestamp(now or datetime.now(timezone.utc))
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")
    # 给 Binance API 一个很小的落地缓冲，避免整点刚过时误判缓存失效。
    return (current - pd.Timedelta(minutes=5)).floor(_SETTLEMENT_FREQ)


def _cache_path(symbol: str) -> Path:
    return _CACHE_DIR / f"{symbol}_funding.parquet"


def _records_to_series(records: list[dict], symbol: str) -> pd.Series:
    if not records:
        return pd.Series(dtype=float, name=symbol)

    df = pd.DataFrame(records)
    if df.empty or "fundingTime" not in df.columns or "fundingRate" not in df.columns:
        return pd.Series(dtype=float, name=symbol)

    df["ts"] = pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True)
    df["rate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    series = df.set_index("ts")["rate"].dropna().rename(symbol)
    return _canonicalize_history(series)


def fetch_funding_history(
    symbol: str,
    start_ms: int | None = None,
    session: requests.Session | None = None,
) -> pd.Series:
    """
    分页拉取 Binance 永续合约历史资金费率。

    Returns:
        pd.Series, index=UTC timestamp, name=symbol
    """
    owns_session = session is None
    session = session or _build_session()
    all_data: list[dict] = []
    cursor = start_ms or int(_HISTORY_START.timestamp() * 1000)

    try:
        while True:
            batch = _request_json(
                "fundingRate",
                params={"symbol": symbol, "limit": 1000, "startTime": cursor},
                session=session,
            )
            if not isinstance(batch, list) or not batch:
                break

            all_data.extend(batch)
            if len(batch) < 1000:
                break

            next_cursor = int(batch[-1]["fundingTime"]) + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            time.sleep(0.03)
    finally:
        if owns_session:
            session.close()

    return _records_to_series(all_data, symbol)


def fetch_current_rates(symbols: list[str] | None = None) -> pd.DataFrame:
    """
    批量获取当前实时费率和下期预测（调用 premiumIndex）。

    Returns:
        DataFrame with columns:
        symbol, mark_price, current_rate, next_rate, next_funding_time, current_ann, next_ann
    """
    syms = symbols or TRADFI_SYMBOLS
    wanted = set(syms)
    payload = _request_json("premiumIndex")

    rows = []
    if isinstance(payload, dict):
        payload = [payload]

    for item in payload:
        symbol = item.get("symbol")
        if symbol not in wanted:
            continue

        next_funding_raw = item.get("nextFundingTime")
        next_funding = (
            pd.to_datetime(int(next_funding_raw), unit="ms", utc=True)
            if next_funding_raw
            else pd.NaT
        )
        current_rate = float(item.get("lastFundingRate", 0) or 0)
        next_rate = float(item.get("nextFundingRate", 0) or 0)

        rows.append(
            {
                "symbol": symbol,
                "mark_price": float(item.get("markPrice", 0) or 0),
                "current_rate": current_rate,
                "next_rate": next_rate,
                "next_funding_time": next_funding,
                "current_ann": current_rate * 3 * 365 * 100,
                "next_ann": next_rate * 3 * 365 * 100,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "mark_price",
                "current_rate",
                "next_rate",
                "next_funding_time",
                "current_ann",
                "next_ann",
            ]
        )

    df = pd.DataFrame(rows).set_index("symbol")
    return df.reindex(syms)


def load_or_fetch(symbol: str, refresh: bool = False) -> pd.Series:
    """
    优先读取本地 Parquet 缓存，必要时做增量更新。

    Args:
        symbol:  合约代码，如 'SPYUSDT'
        refresh: 强制重新拉取全量数据

    Returns:
        pd.Series, index=UTC timestamp, name=symbol
    """
    _CACHE_DIR.mkdir(exist_ok=True)
    path = _cache_path(symbol)

    cached: pd.Series | None = None
    if path.exists() and not refresh:
        cached = _read_cache(path, symbol)
        if not cached.empty and cached.index.max() >= _latest_expected_settlement():
            return cached

    overlap_start_ms: int | None = None
    if cached is not None and not cached.empty and not refresh:
        overlap_start = cached.index[max(0, len(cached) - _CACHE_OVERLAP_ROWS)]
        overlap_start_ms = int(overlap_start.timestamp() * 1000)

    fresh = fetch_funding_history(symbol, start_ms=overlap_start_ms)
    if cached is not None and not refresh and not cached.empty:
        combined = pd.concat([cached, fresh]).sort_index()
        combined = _canonicalize_history(combined.rename(symbol))
    else:
        combined = fresh

    if not combined.empty:
        _write_cache(path, combined)
    return combined


def load_all(
    symbols: list[str] | None = None,
    refresh: bool = False,
    max_workers: int | None = None,
) -> pd.DataFrame:
    """
    加载全部合约费率到宽表（列=symbol，行=8h UTC 时间戳）。

    与旧实现不同：
    - 保留缺失值 NaN，避免把“未上市/无数据”伪造成费率 0
    - 通过并发加载缩短全量刷新时间
    """
    syms = symbols or TRADFI_SYMBOLS
    workers = max_workers or min(8, len(syms))
    series_map: dict[str, pd.Series] = {}

    def _load(symbol: str) -> tuple[str, pd.Series]:
        return symbol, load_or_fetch(symbol, refresh=refresh)

    if workers <= 1:
        for symbol in syms:
            try:
                name, series = _load(symbol)
                if not series.empty:
                    series_map[name] = series
            except Exception as exc:
                print(f"[warn] {symbol}: {exc}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_load, symbol): symbol for symbol in syms}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    name, series = future.result()
                    if not series.empty:
                        series_map[name] = series
                except Exception as exc:
                    print(f"[warn] {symbol}: {exc}")

    if not series_map:
        return pd.DataFrame()

    ordered = [series_map[s] for s in syms if s in series_map]
    wide = pd.concat(ordered, axis=1).sort_index()
    wide = wide.loc[~wide.index.duplicated(keep="last")]
    wide = wide.reindex(columns=syms)
    return wide.loc[wide.notna().any(axis=1)]
