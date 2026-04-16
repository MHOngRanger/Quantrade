"""
信号生成器：每8小时扫描，输出当前应建仓的标的和方向
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def generate(
    wide: pd.DataFrame,
    threshold: float = 0.0001,
    lookback: int = 21,           # 7日均值 = 21个8h周期
    use_rolling: bool = False,    # False: 用当期实时费率；True: 用滚动均值
) -> dict[str, tuple[int, float, float]]:
    """
    基于最新费率生成信号字典。

    Args:
        wide:        宽表（历史数据，最后一行为最新）
        threshold:   入场阈值（默认 0.01%/8h）
        lookback:    滚动均值回溯期
        use_rolling: 是否用滚动均值（更稳定但滞后）

    Returns:
        dict: {symbol: (direction, weight, rate_ann)}
            direction: +1 = 空永续+多现货; -1 = 多永续+空现货
            weight:    信号强度权重（0~1，全部信号权重之和=1）
            rate_ann:  当前年化费率（%）
    """
    if use_rolling:
        latest = wide.rolling(lookback).mean().iloc[-1]
    else:
        latest = wide.iloc[-1]

    active = latest[latest.abs() > threshold]
    if active.empty:
        return {}

    total_abs = active.abs().sum()
    signals: dict[str, tuple[int, float, float]] = {}
    for sym, rate in active.items():
        direction = int(np.sign(rate))
        weight    = abs(rate) / total_abs
        rate_ann  = round(rate * 3 * 365 * 100, 2)
        signals[sym] = (direction, round(weight, 4), rate_ann)

    return signals


def format_signals(signals: dict[str, tuple[int, float, float]]) -> str:
    """人类可读的信号输出"""
    if not signals:
        return "  ── 当前无信号 ──"
    lines = []
    for sym, (direction, weight, rate_ann) in sorted(
        signals.items(), key=lambda x: -abs(x[1][2])
    ):
        label    = sym.replace("USDT", "")
        dir_str  = "做多永续↑" if direction < 0 else "做空永续↓"
        lines.append(
            f"  {label:8s}  {dir_str}  费率={rate_ann:+.1f}%/年  权重={weight:.1%}"
        )
    return "\n".join(lines)
