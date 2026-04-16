"""
绩效指标计算。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _periods_per_year(index: pd.Index | None, fallback: float = 365 * 3) -> float:
    if index is None or len(index) < 2:
        return float(fallback)

    dt = pd.DatetimeIndex(index).to_series().diff().dropna()
    if dt.empty:
        return float(fallback)

    median_hours = dt.median().total_seconds() / 3600
    if median_hours <= 0:
        return float(fallback)
    return 24 * 365 / median_hours


def _returns_from_equity(equity: pd.Series, initial_equity: float = 1.0) -> pd.Series:
    if equity.empty:
        return pd.Series(dtype=float)

    prev = equity.shift(1)
    prev.iloc[0] = initial_equity
    return equity.div(prev).sub(1.0)


def _curve_with_initial(equity: pd.Series, initial_equity: float = 1.0) -> pd.Series:
    values = np.concatenate([[initial_equity], equity.to_numpy(dtype=float)])
    return pd.Series(values, dtype=float)


def sharpe(returns: pd.Series, periods_per_year: float = 365 * 3) -> float:
    """年化夏普比率。"""
    if returns.empty or returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series, initial_equity: float = 1.0) -> float:
    """最大回撤（负数，小数形式）。"""
    if equity.empty:
        return 0.0
    curve = _curve_with_initial(equity, initial_equity=initial_equity)
    return float((curve / curve.cummax() - 1).min())


def annualized_return(equity: pd.Series, initial_equity: float = 1.0) -> float:
    """年化收益率（小数）。"""
    if equity.empty:
        return 0.0

    periods_per_year = _periods_per_year(equity.index)
    years = len(equity) / periods_per_year
    if years <= 0:
        return 0.0

    total_multiple = float(equity.iloc[-1]) / initial_equity
    if total_multiple <= 0:
        return -1.0
    return float(total_multiple ** (1 / years) - 1)


def summary(equity: pd.Series, label: str = "", initial_equity: float = 1.0) -> dict:
    """一次性返回全部绩效指标。"""
    if equity.empty:
        return {
            "label": label,
            "total_ret": 0.0,
            "ann_ret": 0.0,
            "sharpe": 0.0,
            "max_dd": 0.0,
            "days": 0.0,
        }

    returns = _returns_from_equity(equity, initial_equity=initial_equity)
    periods_per_year = _periods_per_year(equity.index)
    days = len(equity) / (periods_per_year / 365) if periods_per_year else 0.0

    return {
        "label": label,
        "total_ret": round((float(equity.iloc[-1]) / initial_equity - 1) * 100, 2),
        "ann_ret": round(annualized_return(equity, initial_equity=initial_equity) * 100, 1),
        "sharpe": round(sharpe(returns, periods_per_year=periods_per_year), 2),
        "max_dd": round(max_drawdown(equity, initial_equity=initial_equity) * 100, 2),
        "days": round(days, 0),
    }


def print_summary(equity: pd.Series, label: str = "", initial_equity: float = 1.0) -> None:
    s = summary(equity, label, initial_equity=initial_equity)
    print(
        f"{s['label']:15s}  总收益={s['total_ret']:+7.2f}%  "
        f"年化={s['ann_ret']:+6.1f}%  夏普={s['sharpe']:5.2f}  "
        f"最大回撤={s['max_dd']:6.2f}%  ({s['days']:.0f}天)"
    )
