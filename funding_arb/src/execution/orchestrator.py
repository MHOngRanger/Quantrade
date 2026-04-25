"""
双腿编排器：协调 Binance 永续 + IBKR 合成期权的同步开/平仓。

开仓流程：Binance 先开 → IBKR 再开（Binance 失败则不开 IBKR）
平仓流程：IBKR 先平 → Binance 再平
异常回滚：Binance 成功 + IBKR 失败 → 立即平 Binance
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .binance_executor import BinanceExecutor, BinanceFill
from .ibkr import IBKRExecutor, SyntheticPosition, TICKER_MAP


@dataclass
class DualLegResult:
    """双腿操作结果"""
    symbol: str
    action: str              # "open" / "close"
    success: bool
    binance_fill: BinanceFill | None = None
    ibkr_position: SyntheticPosition | None = None
    error: str | None = None


class Orchestrator:
    """
    双腿编排器。

    Args:
        binance: BinanceExecutor 实例
        ibkr:    IBKRExecutor 实例
    """

    def __init__(self, binance: BinanceExecutor, ibkr: IBKRExecutor):
        self.binance = binance
        self.ibkr = ibkr

    def open_dual(
        self,
        symbol: str,
        direction: int,
        notional_usd: float,
        leverage: int = 5,
        dry_run: bool = True,
    ) -> DualLegResult:
        """
        同步开仓双腿。

        Args:
            symbol:        Binance 合约代码，如 "SPYUSDT"
            direction:     +1 = 正费率（空永续+合成多头）；-1 = 负费率（多永续+合成空头）
            notional_usd:  名义本金
            leverage:      Binance 杠杆倍数
            dry_run:       True 时仅打印

        Returns:
            DualLegResult
        """
        print(f"\n{'='*50}")
        print(f"  双腿开仓: {symbol}  direction={direction:+d}  "
              f"notional=${notional_usd:,.0f}")
        print(f"{'='*50}")

        if symbol not in TICKER_MAP:
            msg = f"IBKR 未配置 {symbol} 的股票/ETF期权对冲映射；请使用 Binance-only 或新增对冲实现"
            print(f"  ⚠️ {msg}")
            return DualLegResult(symbol=symbol, action="open", success=False, error=msg)

        # ── 第1腿：Binance 永续 ──
        binance_fill: BinanceFill | None = None
        try:
            binance_fill = self.binance.open_position(
                symbol=symbol,
                direction=direction,
                notional_usd=notional_usd,
                leverage=leverage,
                dry_run=dry_run,
            )
        except Exception as e:
            msg = f"Binance 开仓失败: {e}"
            print(f"  ❌ {msg}")
            return DualLegResult(
                symbol=symbol, action="open", success=False, error=msg,
            )

        # ── 第2腿：IBKR 合成期权 ──
        ibkr_pos: SyntheticPosition | None = None
        try:
            reference_price: float | None = None
            if dry_run:
                try:
                    reference_price = self.binance.get_mark_price(symbol)
                except Exception:
                    reference_price = None

            ibkr_pos = self.ibkr.open_synthetic(
                binance_symbol=symbol,
                direction=direction,
                notional_usd=notional_usd,
                dry_run=dry_run,
                reference_price=reference_price,
            )
        except Exception as e:
            msg = f"IBKR 开仓失败: {e}"
            print(f"  ❌ {msg}")

            # 回滚：平掉已开的 Binance 仓位
            if not dry_run and binance_fill and binance_fill.status != "DRY_RUN":
                print(f"  🔄 回滚: 平仓 Binance {symbol}")
                try:
                    self.binance.close_position(symbol, dry_run=False)
                    print(f"  ✅ Binance 回滚成功")
                except Exception as rollback_err:
                    print(f"  ⚠️ Binance 回滚失败: {rollback_err}")
                    msg += f" | 回滚失败: {rollback_err}"

            return DualLegResult(
                symbol=symbol, action="open", success=False,
                binance_fill=binance_fill, error=msg,
            )

        print(f"  ✅ 双腿开仓完成")
        return DualLegResult(
            symbol=symbol,
            action="open",
            success=True,
            binance_fill=binance_fill,
            ibkr_position=ibkr_pos,
        )

    def close_dual(
        self,
        symbol: str,
        ibkr_position: SyntheticPosition | None = None,
        dry_run: bool = True,
    ) -> DualLegResult:
        """
        同步平仓双腿。

        Args:
            symbol:         Binance 合约代码
            ibkr_position:  IBKR 合成期权仓位（用于精确平仓）
            dry_run:        True 时仅打印
        """
        print(f"\n{'='*50}")
        print(f"  双腿平仓: {symbol}")
        print(f"{'='*50}")

        errors: list[str] = []

        # ── 第1腿：IBKR 平仓 ──
        if ibkr_position:
            try:
                self.ibkr.close_synthetic(ibkr_position, dry_run=dry_run)
            except Exception as e:
                msg = f"IBKR 平仓失败: {e}"
                print(f"  ❌ {msg}")
                errors.append(msg)
        else:
            print(f"  ⚠️ 无 IBKR 仓位信息，跳过 IBKR 平仓")

        # ── 第2腿：Binance 平仓 ──
        binance_fill: BinanceFill | None = None
        try:
            binance_fill = self.binance.close_position(symbol, dry_run=dry_run)
        except Exception as e:
            msg = f"Binance 平仓失败: {e}"
            print(f"  ❌ {msg}")
            errors.append(msg)

        success = len(errors) == 0
        if success:
            print(f"  ✅ 双腿平仓完成")
        else:
            print(f"  ⚠️ 双腿平仓部分失败: {'; '.join(errors)}")

        return DualLegResult(
            symbol=symbol,
            action="close",
            success=success,
            binance_fill=binance_fill,
            error="; ".join(errors) if errors else None,
        )
