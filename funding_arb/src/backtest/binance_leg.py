"""
Binance 永续腿回测。

该模块只评估 Binance funding leg：按资金费率符号持有收款方向，
收益包含资金费收入和永续下单手续费，不包含 IBKR 对冲腿成本。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .costs import CostModel, DEFAULT
from .metrics import summary


def _clean_panel(wide: pd.DataFrame) -> pd.DataFrame:
    if wide.empty:
        return wide.copy()

    panel = wide.sort_index().copy()
    panel = panel.loc[~panel.index.duplicated(keep="last")]
    panel = panel.apply(pd.to_numeric, errors="coerce")
    return panel.loc[panel.notna().any(axis=1)]


def _period_hours(index: pd.Index, i: int) -> float:
    if i == 0 or len(index) < 2:
        return 8.0

    prev_ts = pd.Timestamp(index[i - 1])
    curr_ts = pd.Timestamp(index[i])
    delta = (curr_ts - prev_ts).total_seconds() / 3600
    return 8.0 if delta <= 0 else float(delta)


def run_binance_leg(
    wide: pd.DataFrame,
    *,
    cost: CostModel = DEFAULT,
    threshold: float = 0.0001,
    max_leverage: float = 5.0,
    cooldown_periods: int | None = None,
    initial_equity: float = 1.0,
) -> tuple[pd.Series, pd.DataFrame]:
    """
    回测 Binance 永续资金费腿。

    Args:
        wide:             宽表，列=合约代码，行=资金结算时间戳，值=资金费率
        cost:             成本模型；使用 futures_fee 拆分为开/平各半
        threshold:        入场绝对值阈值
        max_leverage:     Binance 保证金杠杆
        cooldown_periods: 平仓后的冷却周期，默认使用 CostModel 配置
        initial_equity:   初始权益

    Returns:
        (equity, trade_log)
    """
    panel = _clean_panel(wide)
    if panel.empty:
        return pd.Series(dtype=float, name="binance_equity"), pd.DataFrame()

    cooldown_periods = cost.cooldown_periods if cooldown_periods is None else cooldown_periods
    fee_per_order = cost.futures_fee / 2

    equity_value = float(initial_equity)
    equity_points: list[float] = []
    cooldown: dict[str, int] = {col: 0 for col in panel.columns}
    prev_pos: dict[str, dict[str, float | int]] = {}
    trade_log: list[dict] = []

    for i, (ts, row) in enumerate(panel.iterrows()):
        period_hours = _period_hours(panel.index, i)
        active_row = row.dropna()
        raw_signals = active_row[active_row.abs() > threshold]

        signals: dict[str, float] = {}
        for sym, rate in raw_signals.items():
            if cooldown[sym] > 0 and sym not in prev_pos:
                cooldown[sym] -= 1
                continue
            signals[sym] = float(rate)

        for sym in panel.columns:
            if sym not in raw_signals.index and cooldown[sym] > 0:
                cooldown[sym] -= 1

        pnl = 0.0

        # 平掉信号消失的仓位。
        for sym in list(prev_pos):
            if sym not in signals:
                notional = float(prev_pos[sym]["notional"])
                pnl -= fee_per_order * notional
                cooldown[sym] = cooldown_periods
                trade_log.append(
                    {
                        "ts": ts,
                        "symbol": sym,
                        "event": "close",
                        "direction": int(prev_pos[sym]["direction"]),
                        "rate_ann": np.nan,
                        "notional": round(notional, 4),
                        "fee": round(fee_per_order * notional, 6),
                    }
                )
                prev_pos.pop(sym, None)

        if signals:
            total_abs = sum(abs(v) for v in signals.values())
            capital = equity_value

            for sym, rate in signals.items():
                direction = int(np.sign(rate))
                weight = abs(rate) / total_abs
                notional = capital * weight * max_leverage

                pnl += abs(rate) * notional * (period_hours / 8.0)

                previous = prev_pos.get(sym)
                previous_direction = int(previous["direction"]) if previous else 0
                if direction != previous_direction:
                    turnover = notional
                    event = "open"
                    if previous:
                        turnover += float(previous["notional"])
                        event = "flip"
                    fee = fee_per_order * turnover
                    pnl -= fee
                    trade_log.append(
                        {
                            "ts": ts,
                            "symbol": sym,
                            "event": event,
                            "direction": direction,
                            "rate_ann": round(rate * 3 * 365 * 100, 2),
                            "notional": round(notional, 4),
                            "fee": round(fee, 6),
                        }
                    )

                prev_pos[sym] = {"direction": direction, "notional": float(notional)}

        equity_value = max(equity_value + pnl, 0.001)
        equity_points.append(equity_value)

    equity_series = pd.Series(equity_points, index=panel.index, name="binance_equity")
    trade_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
    return equity_series, trade_df


def sensitivity_binance_leg(
    wide: pd.DataFrame,
    thresholds: list[float] | None = None,
    leverages: list[float] | None = None,
    cost: CostModel = DEFAULT,
    **kwargs,
) -> pd.DataFrame:
    """Binance 永续腿阈值 × 杠杆敏感性分析。"""
    thresholds = thresholds or [0.00003, 0.00005, 0.0001, 0.00015, 0.0002]
    leverages = leverages or [3.0, 4.0, 5.0]
    rows = []

    for lev in leverages:
        for thr in thresholds:
            eq, _ = run_binance_leg(wide, cost=cost, threshold=thr, max_leverage=lev, **kwargs)
            s = summary(eq)
            rows.append(
                {
                    "leverage": lev,
                    "threshold_%/period": round(thr * 100, 4),
                    "ann_ret_%": s["ann_ret"],
                    "sharpe": s["sharpe"],
                    "max_dd_%": s["max_dd"],
                }
            )

    return pd.DataFrame(rows)
