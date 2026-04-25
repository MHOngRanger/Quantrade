"""
IBKR 合成期权执行层（通过 ib_insync 连接 TWS/IB Gateway）

使用前提：
  1. TWS 或 IB Gateway 正在运行（默认端口 7497 paper / 7496 live）
  2. `uv add ib_insync` 已安装
  3. 强烈建议先用 paper trading 账户测试

合成空头（收取负费率时）：
  - 做多 Binance 永续
  - IBKR：卖出 ATM Call + 买入 ATM Put（同行权价，同到期日）

合成多头（收取正费率时）：
  - 做空 Binance 永续
  - IBKR：买入 ATM Call + 卖出 ATM Put
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

# ib_insync 是可选依赖，按需安装
try:
    from ib_insync import IB, Contract, Option, Order
    _IB_AVAILABLE = True
except ImportError:
    _IB_AVAILABLE = False


# ── ETF/股票到期权根代码映射 ─────────────────────────────
TICKER_MAP = {
    "AAPLUSDT":  "AAPL",
    "AMZNUSDT":  "AMZN",
    "AVGOUSDT":  "AVGO",
    "BABAUSDT":  "BABA",
    "COINUSDT":  "COIN",
    "CRCLUSDT":  "CRCL",
    "EWJUSDT":   "EWJ",
    "EWYUSDT":   "EWY",
    "GOOGLUSDT": "GOOGL",
    "HOODUSDT":  "HOOD",
    "INTCUSDT":  "INTC",
    "METAUSDT":  "META",
    "MSFTUSDT":  "MSFT",
    "MSTRUSDT":  "MSTR",
    "MUUSDT":    "MU",
    "NVDAUSDT":  "NVDA",
    "PAYPUSDT":  "PYPL",
    "PLTRUSDT":  "PLTR",
    "QQQUSDT":   "QQQ",
    "SNDKUSDT":  "SNDK",
    "SPYUSDT":   "SPY",
    "TSLAUSDT":  "TSLA",
    "TSMUSDT":   "TSM",
}


@dataclass
class SyntheticPosition:
    symbol: str          # 如 "SPY"
    direction: int       # +1 = 合成多头；-1 = 合成空头
    strike: float
    expiry: str          # YYYYMMDD
    contracts: int       # 张数（每张=100股）
    binance_symbol: str | None = None
    notional_usd: float | None = None


class IBKRExecutor:
    """
    IBKR 合成期权执行器。
    实盘前请充分测试！
    """

    def __init__(self, port: int = 7497, client_id: int = 10):
        if not _IB_AVAILABLE:
            raise ImportError("请先安装 ib_insync：uv add ib_insync")
        self.ib = IB()
        self.port = port
        self.client_id = client_id

    def connect(self) -> None:
        self.ib.connect("127.0.0.1", self.port, clientId=self.client_id)

    def disconnect(self) -> None:
        self.ib.disconnect()

    # ── 工具函数 ──────────────────────────────────────────

    def _next_monthly_expiry(self, after_days: int = 7) -> str:
        """返回距今至少 after_days 天的最近月度到期日（第三个周五）"""
        today = datetime.now(timezone.utc).date()
        target = today + timedelta(days=after_days)

        # 找当月或后续月份的第三个周五。
        year = target.year
        month = target.month
        for _ in range(6):
            month_days = calendar.monthcalendar(year, month)
            fridays = [week[calendar.FRIDAY] for week in month_days if week[calendar.FRIDAY] != 0]
            if len(fridays) >= 3:
                expiry = datetime(year, month, fridays[2], tzinfo=timezone.utc).date()
                if expiry >= target:
                    return expiry.strftime("%Y%m%d")
            month += 1
            if month == 13:
                month = 1
                year += 1
        raise ValueError("无法找到合适到期日")

    def _get_atm_strike(self, symbol: str) -> float:
        return self._get_atm_strike_with_fallback(symbol)

    def _get_atm_strike_with_fallback(
        self,
        symbol: str,
        reference_price: float | None = None,
    ) -> float:
        """获取当前市价并四舍五入到最近行权价（SPY/QQQ 以1美元为档）。"""
        contract = Contract(symbol=symbol, secType="STK", exchange="SMART", currency="USD")
        self.ib.qualifyContracts(contract)

        # Paper 账户常见情况是没有实时行情权限；先请求 delayed 数据，仍失败再用传入参考价。
        try:
            self.ib.reqMarketDataType(3)
        except Exception:
            pass

        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(1)

        candidates = [
            ticker.marketPrice(),
            ticker.last,
            ticker.close,
            ticker.bid,
            ticker.ask,
            reference_price,
        ]
        price = next(
            (float(p) for p in candidates if p is not None and math.isfinite(float(p)) and float(p) > 0),
            None,
        )
        if price is None:
            raise ValueError(f"无法获取 {symbol} 有效市价；可检查 IBKR 行情权限或传入 reference_price")

        # SPY/QQQ 期权行权价间距为1美元，其他为2.5或5美元
        step = 1.0 if symbol in ("SPY", "QQQ") else 2.5
        return round(price / step) * step

    # ── 主要操作 ──────────────────────────────────────────

    def open_synthetic(
        self,
        binance_symbol: str,
        direction: int,
        notional_usd: float,
        dry_run: bool = True,
        reference_price: float | None = None,
    ) -> SyntheticPosition | None:
        """
        开立合成期权头寸（对冲 Binance 永续的 Delta）。

        Args:
            binance_symbol: 如 "SPYUSDT"
            direction:      -1 = 收取负费率（long perp → 合成空头）
                            +1 = 收取正费率（short perp → 合成多头）
            notional_usd:   名义本金（美元）
            dry_run:        True 时仅打印，不实际下单

        Returns:
            SyntheticPosition 或 None（dry_run 时）
        """
        ticker  = TICKER_MAP.get(binance_symbol)
        if not ticker:
            raise ValueError(f"未找到 {binance_symbol} 对应的期权标的")

        strike  = self._get_atm_strike_with_fallback(ticker, reference_price=reference_price)
        expiry  = self._next_monthly_expiry()
        n_contr = max(1, int(notional_usd / (strike * 100)))

        # direction=-1: 合成空头 = 卖Call + 买Put
        # direction=+1: 合成多头 = 买Call + 卖Put
        call_action = "SELL" if direction < 0 else "BUY"
        put_action  = "BUY"  if direction < 0 else "SELL"

        print(f"[{'DRY RUN' if dry_run else 'LIVE'}] {ticker}  "
              f"strike={strike}  expiry={expiry}  contracts={n_contr}")
        print(f"  {call_action} {n_contr}x {ticker} {expiry} C{strike:.0f}")
        print(f"  {put_action}  {n_contr}x {ticker} {expiry} P{strike:.0f}")

        if dry_run:
            return SyntheticPosition(
                symbol=ticker,
                direction=direction,
                strike=strike,
                expiry=expiry,
                contracts=n_contr,
                binance_symbol=binance_symbol,
                notional_usd=notional_usd,
            )

        # ── 实盘下单（非 dry_run）──
        for right, action in [("C", call_action), ("P", put_action)]:
            opt = Option(ticker, expiry, strike, right, "SMART")
            self.ib.qualifyContracts(opt)
            order = Order(
                action=action,
                totalQuantity=n_contr,
                orderType="MKT",  # 实盘建议改用 LMT
            )
            trade = self.ib.placeOrder(opt, order)
            self.ib.sleep(1)
            print(f"  下单完成: {trade.orderStatus.status}")

        return SyntheticPosition(
            symbol=ticker,
            direction=direction,
            strike=strike,
            expiry=expiry,
            contracts=n_contr,
            binance_symbol=binance_symbol,
            notional_usd=notional_usd,
        )

    def close_synthetic(self, pos: SyntheticPosition, dry_run: bool = True) -> None:
        """平仓合成期权（反向操作）"""
        call_action = "BUY"  if pos.direction < 0 else "SELL"
        put_action  = "SELL" if pos.direction < 0 else "BUY"

        print(f"[{'DRY RUN' if dry_run else 'LIVE'}] 平仓 {pos.symbol}  "
              f"strike={pos.strike}  expiry={pos.expiry}")
        print(f"  {call_action} {pos.contracts}x {pos.symbol} {pos.expiry} C{pos.strike:.0f}")
        print(f"  {put_action}  {pos.contracts}x {pos.symbol} {pos.expiry} P{pos.strike:.0f}")

        if dry_run:
            return

        for right, action in [("C", call_action), ("P", put_action)]:
            opt = Option(pos.symbol, pos.expiry, pos.strike, right, "SMART")
            self.ib.qualifyContracts(opt)
            order = Order(action=action, totalQuantity=pos.contracts, orderType="MKT")
            self.ib.placeOrder(opt, order)
            self.ib.sleep(1)

    def roll_synthetic(
        self, pos: SyntheticPosition, dry_run: bool = True
    ) -> SyntheticPosition:
        """月度换期：平旧 + 开新"""
        self.close_synthetic(pos, dry_run=dry_run)
        new_expiry = self._next_monthly_expiry(after_days=7)
        new_pos = SyntheticPosition(
            pos.symbol, pos.direction, pos.strike, new_expiry, pos.contracts
        )
        # 重新下单新到期日
        for right, action in [
            ("C", "SELL" if pos.direction < 0 else "BUY"),
            ("P", "BUY"  if pos.direction < 0 else "SELL"),
        ]:
            print(f"  开新仓 {action} {new_pos.contracts}x "
                  f"{new_pos.symbol} {new_expiry} {right}{new_pos.strike:.0f}")
            if not dry_run:
                opt = Option(new_pos.symbol, new_expiry, new_pos.strike, right, "SMART")
                self.ib.qualifyContracts(opt)
                order = Order(action=action, totalQuantity=new_pos.contracts, orderType="MKT")
                self.ib.placeOrder(opt, order)
                self.ib.sleep(1)
        return new_pos

    def check_margin(self) -> dict:
        """查询 IBKR 账户保证金状态"""
        vals = {v.tag: v.value for v in self.ib.accountValues()}
        return {
            "net_liquidation":   float(vals.get("NetLiquidation", 0)),
            "available_funds":   float(vals.get("AvailableFunds", 0)),
            "excess_liquidity":  float(vals.get("ExcessLiquidity", 0)),
            "maintenance_margin": float(vals.get("MaintMarginReq", 0)),
        }
