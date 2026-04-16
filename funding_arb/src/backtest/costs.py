"""
成本模型：统一管理期货手续费、期权买卖价差、借贷成本
所有费率均为名义本金的小数（非百分比）
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class CostModel:
    """
    资金费率套利全成本模型。

    Attributes:
        futures_fee:       Binance 期货每次开仓（双腿）手续费，默认 0.1%
        opt_spread_normal: 期权买卖价差（平静市场，单次开仓），默认 0.023%
        opt_spread_stress: 期权买卖价差（高波动市场），默认 0.072%
        opt_roll_monthly:  期权月度换期成本（平静市场），默认 0.026%/月
        borrow_annual:     现货/融券借贷年化成本，默认 0.5%
        cooldown_periods:  平仓后冷却期（单位：8h 周期），默认 2
        stress_cutoff:     高波动判定分界日期（str），用于区分平静/冲击期
    """
    futures_fee:       float = 0.001     # 0.10% / 开仓
    opt_spread_normal: float = 0.00023   # 0.023% / 开仓
    opt_spread_stress: float = 0.00072   # 0.072% / 开仓
    opt_roll_monthly:  float = 0.00026   # 0.026% / 月
    borrow_annual:     float = 0.005     # 0.5%  / 年
    cooldown_periods:  int   = 2
    stress_cutoff:     str   = "2026-04-02"

    # ── 衍生属性 ──────────────────────────────────────────

    @property
    def borrow_per_8h(self) -> float:
        return self.borrow_annual / (365 * 3)

    @property
    def opt_roll_per_8h(self) -> float:
        """月度换期成本摊销到每个 8h 周期"""
        return self.opt_roll_monthly / (30 * 3)

    def open_cost(self, is_stress: bool = False) -> float:
        """单次开仓总成本（期货 + 期权价差）"""
        spread = self.opt_spread_stress if is_stress else self.opt_spread_normal
        return self.futures_fee + spread

    def running_cost_per_8h(self) -> float:
        """持仓期间每8h的运营成本（借贷 + 期权换期摊销）"""
        return self.borrow_per_8h + self.opt_roll_per_8h

    def running_cost(self, hours: float = 8.0) -> float:
        """按持仓小时数折算运营成本。"""
        if hours <= 0:
            return 0.0
        return self.running_cost_per_8h() * (hours / 8.0)


# 默认实例，可直接导入使用
DEFAULT = CostModel()
