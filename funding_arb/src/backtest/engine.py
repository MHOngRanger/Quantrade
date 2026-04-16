"""
核心回测引擎：多标的双向资金费率套利。

改进点：
- 跳过缺失值，不再把未上市/无数据当成 0 费率
- 无信号平仓时正确触发冷却期
- 资金费收益直接按 `abs(rate)` 计入，更清晰地表达“持有收款方向”
- 支持按真实时间间隔折算运行成本
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .costs import CostModel, DEFAULT
from .metrics import summary


def _period_hours(index: pd.Index, i: int) -> float:
    if i == 0 or len(index) < 2:
        return 8.0

    prev_ts = pd.Timestamp(index[i - 1])
    curr_ts = pd.Timestamp(index[i])
    delta = (curr_ts - prev_ts).total_seconds() / 3600
    return 8.0 if delta <= 0 else float(delta)


def _clean_panel(wide: pd.DataFrame) -> pd.DataFrame:
    if wide.empty:
        return wide.copy()

    panel = wide.sort_index().copy()
    panel = panel.loc[~panel.index.duplicated(keep="last")]
    panel = panel.apply(pd.to_numeric, errors="coerce")
    return panel.loc[panel.notna().any(axis=1)]


def run(
    wide: pd.DataFrame,
    cost: CostModel = DEFAULT,
    threshold: float = 0.0001,
    max_leverage: float = 5.0,
    ibkr_margin: float = 0.12,
    track_err_std: float = 0.001,
    seed: int = 42,
    stress_cutoff: str | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """
    多标的动态双向资金费率套利回测。

    Args:
        wide:          宽表，列=合约代码，行=资金结算时间戳，值=资金费率
        cost:          成本模型实例
        threshold:     入场绝对值阈值（默认 0.01%/周期）
        max_leverage:  Binance 永续最大杠杆倍数
        ibkr_margin:   IBKR PM 合成期权保证金率
        track_err_std: Delta追踪误差标准差（名义本金的小数）
        seed:          随机数种子（追踪误差）
        stress_cutoff: 高波动期分界日期（str），高波动期追踪误差 × 1.5

    Returns:
        (equity, trade_log)
    """
    panel = _clean_panel(wide)
    if panel.empty:
        return pd.Series(dtype=float, name="equity"), pd.DataFrame()

    np.random.seed(seed)
    total_margin = 1 / max_leverage + ibkr_margin
    cutoff_ts = pd.Timestamp(stress_cutoff or cost.stress_cutoff, tz="UTC")

    equity_value = 1.0
    equity_points: list[float] = []
    cooldown: dict[str, int] = {col: 0 for col in panel.columns}
    prev_pos: dict[str, int] = {col: 0 for col in panel.columns}
    trade_log: list[dict] = []

    for i, (ts, row) in enumerate(panel.iterrows()):
        is_stress = ts >= cutoff_ts
        period_hours = _period_hours(panel.index, i)
        active_row = row.dropna()

        raw_signals = active_row[active_row.abs() > threshold]
        signals: dict[str, float] = {}
        for sym, rate in raw_signals.items():
            if cooldown[sym] > 0:
                cooldown[sym] -= 1
                continue
            signals[sym] = float(rate)

        # 衰减未参与本期决策的冷却计数。
        for sym in panel.columns:
            if sym not in raw_signals.index and cooldown[sym] > 0:
                cooldown[sym] -= 1

        # 先处理平仓，让“无信号 → 冷却”真正生效。
        for sym, prev_direction in list(prev_pos.items()):
            if prev_direction != 0 and sym not in signals:
                cooldown[sym] = cost.cooldown_periods
                prev_pos[sym] = 0

        pnl = 0.0
        if signals:
            total_abs = sum(abs(v) for v in signals.values())
            capital = equity_value

            for sym, rate in signals.items():
                direction = int(np.sign(rate))
                weight = abs(rate) / total_abs
                notional = capital * weight / total_margin

                pnl += abs(rate) * notional
                pnl -= cost.running_cost(hours=period_hours) * notional

                vol_multiplier = 1.5 if is_stress else 1.0
                pnl += np.random.normal(0, track_err_std * vol_multiplier) * notional

                previous_direction = prev_pos.get(sym, 0)
                if direction != previous_direction:
                    open_cost = cost.open_cost(is_stress=is_stress)
                    pnl -= open_cost * notional
                    trade_log.append(
                        {
                            "ts": ts,
                            "symbol": sym,
                            "event": "open" if previous_direction == 0 else "flip",
                            "direction": direction,
                            "rate_ann": round(rate * 3 * 365 * 100, 2),
                            "notional": round(notional, 4),
                            "open_cost": round(open_cost * notional, 6),
                            "is_stress": is_stress,
                        }
                    )

                prev_pos[sym] = direction

        equity_value = max(equity_value + pnl, 0.001)
        equity_points.append(equity_value)

    equity_series = pd.Series(equity_points, index=panel.index, name="equity")
    trade_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
    return equity_series, trade_df


def sensitivity(
    wide: pd.DataFrame,
    thresholds: list[float] | None = None,
    leverages: list[float] | None = None,
    cost: CostModel = DEFAULT,
    **kwargs,
) -> pd.DataFrame:
    """
    阈值 × 杠杆 敏感性分析，返回汇总表。
    """
    thresholds = thresholds or [0.00003, 0.00005, 0.0001, 0.00015, 0.0002]
    leverages = leverages or [3.0, 4.0, 5.0]
    rows = []

    for lev in leverages:
        for thr in thresholds:
            eq, _ = run(wide, cost=cost, threshold=thr, max_leverage=lev, **kwargs)
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
