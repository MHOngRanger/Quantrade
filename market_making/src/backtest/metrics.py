"""Market-making performance metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def summary(sim: pd.DataFrame) -> dict:
    if sim.empty or "mark_to_market" not in sim:
        return {"total_pnl": 0.0, "max_drawdown": 0.0, "max_abs_inventory": 0.0, "fills": 0}

    mtm = sim["mark_to_market"].dropna()
    pnl = mtm.diff().dropna()
    drawdown = mtm - mtm.cummax()
    fills = int(sim.get("bid_fill", pd.Series(dtype=int)).sum() + sim.get("ask_fill", pd.Series(dtype=int)).sum())
    return {
        "total_pnl": round(float(mtm.iloc[-1] - mtm.iloc[0]), 4) if len(mtm) else 0.0,
        "mean_step_pnl": round(float(pnl.mean()), 6) if len(pnl) else 0.0,
        "step_sharpe": round(float(pnl.mean() / pnl.std() * np.sqrt(len(pnl))), 2) if len(pnl) and pnl.std() else 0.0,
        "max_drawdown": round(float(drawdown.min()), 4) if len(drawdown) else 0.0,
        "max_abs_inventory": round(float(sim["inventory"].abs().max()), 4) if "inventory" in sim else 0.0,
        "fills": fills,
    }


def print_summary(sim: pd.DataFrame) -> None:
    s = summary(sim)
    print(
        f"total_pnl={s['total_pnl']:+.4f} "
        f"step_sharpe={s['step_sharpe']:.2f} "
        f"max_dd={s['max_drawdown']:.4f} "
        f"max_abs_inv={s['max_abs_inventory']:.2f} fills={s['fills']}"
    )

