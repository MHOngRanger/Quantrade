"""Common performance metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1).min())


def summary(returns: pd.Series, *, label: str = "") -> dict:
    returns = returns.dropna()
    if returns.empty:
        return {"label": label, "total_ret": 0.0, "ann_ret": 0.0, "sharpe": 0.0, "max_dd": 0.0}

    periods = 12.0
    equity = (1 + returns).cumprod()
    ann_ret = float(equity.iloc[-1] ** (periods / len(returns)) - 1)
    vol = float(returns.std())
    sharpe = 0.0 if vol == 0 else float(returns.mean() / vol * np.sqrt(periods))
    return {
        "label": label,
        "total_ret": round((float(equity.iloc[-1]) - 1) * 100, 2),
        "ann_ret": round(ann_ret * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(max_drawdown(equity) * 100, 2),
    }


def print_summary(returns: pd.Series, *, label: str = "") -> None:
    s = summary(returns, label=label)
    print(
        f"{s['label']:18s} total={s['total_ret']:+7.2f}% "
        f"ann={s['ann_ret']:+7.2f}% sharpe={s['sharpe']:5.2f} "
        f"max_dd={s['max_dd']:6.2f}%"
    )

