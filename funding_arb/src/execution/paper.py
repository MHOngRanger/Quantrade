"""
Paper-trading orchestration helpers.

负责：
  1. 持久化本地仓位状态
  2. 根据信号生成开/平/跳过计划
  3. 在执行成功后更新状态和冷却期
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from .ibkr import SyntheticPosition, TICKER_MAP

_STATE_PATH = Path(__file__).parent.parent.parent / "data" / "paper_positions.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ManagedPosition:
    binance_symbol: str
    ibkr_symbol: str
    direction: int
    strike: float
    expiry: str
    contracts: int
    notional_usd: float
    opened_at: str
    opened_rate_ann: float
    signal_weight: float
    # Binance 腿信息
    binance_order_id: int | None = None
    binance_quantity: float | None = None
    binance_side: str | None = None        # BUY / SELL

    def to_synthetic(self) -> SyntheticPosition:
        return SyntheticPosition(
            symbol=self.ibkr_symbol,
            direction=self.direction,
            strike=self.strike,
            expiry=self.expiry,
            contracts=self.contracts,
            binance_symbol=self.binance_symbol,
            notional_usd=self.notional_usd,
        )

    @classmethod
    def from_synthetic(
        cls,
        binance_symbol: str,
        pos: SyntheticPosition,
        opened_at: datetime,
        opened_rate_ann: float,
        signal_weight: float,
    ) -> "ManagedPosition":
        return cls(
            binance_symbol=binance_symbol,
            ibkr_symbol=pos.symbol,
            direction=pos.direction,
            strike=pos.strike,
            expiry=pos.expiry,
            contracts=pos.contracts,
            notional_usd=float(pos.notional_usd or 0),
            opened_at=opened_at.astimezone(timezone.utc).isoformat(),
            opened_rate_ann=float(opened_rate_ann),
            signal_weight=float(signal_weight),
        )


@dataclass
class PaperState:
    positions: dict[str, ManagedPosition] = field(default_factory=dict)
    cooldowns: dict[str, str] = field(default_factory=dict)
    updated_at: str | None = None

    def cooldown_until(self, symbol: str) -> datetime | None:
        raw = self.cooldowns.get(symbol)
        if not raw:
            return None
        return datetime.fromisoformat(raw)

    def is_in_cooldown(self, symbol: str, now: datetime) -> bool:
        until = self.cooldown_until(symbol)
        return until is not None and until > now

    def prune(self, now: datetime) -> None:
        expired = [sym for sym, raw in self.cooldowns.items() if datetime.fromisoformat(raw) <= now]
        for sym in expired:
            self.cooldowns.pop(sym, None)


@dataclass
class PlannedAction:
    kind: str
    symbol: str
    reason: str
    direction: int | None = None
    rate_ann: float | None = None
    weight: float | None = None
    notional_usd: float | None = None
    position: ManagedPosition | None = None
    cooldown_until: str | None = None

    def describe(self) -> str:
        label = self.symbol.replace("USDT", "")
        if self.kind == "open":
            side = "做空永续/合成多头" if (self.direction or 0) > 0 else "做多永续/合成空头"
            return (
                f"[开仓] {label}  {side}  年化={self.rate_ann:+.1f}%  "
                f"权重={self.weight:.1%}  名义={self.notional_usd:,.0f}  原因={self.reason}"
            )
        if self.kind == "close":
            return f"[平仓] {label}  原因={self.reason}"
        if self.kind == "skip":
            return f"[跳过] {label}  冷却至 {self.cooldown_until}  原因={self.reason}"
        return f"[{self.kind}] {label}  原因={self.reason}"


def binance_position_amt(direction: int, quantity: float | None) -> float | None:
    """
    将策略方向转换为 Binance 持仓数量符号。

    direction=+1 表示正费率、做空永续，所以 Binance positionAmt 为负；
    direction=-1 表示负费率、做多永续，所以 Binance positionAmt 为正。
    """
    if quantity is None:
        return None
    return -abs(float(quantity)) if direction > 0 else abs(float(quantity))


def default_state_path() -> Path:
    return _STATE_PATH


def load_state(path: Path | None = None) -> PaperState:
    state_path = path or _STATE_PATH
    if not state_path.exists():
        return PaperState()

    with open(state_path) as f:
        payload = json.load(f)

    positions = {
        sym: ManagedPosition(**raw)
        for sym, raw in payload.get("positions", {}).items()
    }
    return PaperState(
        positions=positions,
        cooldowns=dict(payload.get("cooldowns", {})),
        updated_at=payload.get("updated_at"),
    )


def save_state(state: PaperState, path: Path | None = None) -> None:
    state_path = path or _STATE_PATH
    state.updated_at = _utc_now().isoformat()
    state_path.parent.mkdir(exist_ok=True)
    payload = {
        "positions": {sym: asdict(pos) for sym, pos in state.positions.items()},
        "cooldowns": state.cooldowns,
        "updated_at": state.updated_at,
    }
    with open(state_path, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def plan_actions(
    *,
    state: PaperState,
    signals: dict[str, dict[str, Any]],
    now: datetime,
    total_notional_usd: float,
    cooldown_hours: float = 16.0,
) -> list[PlannedAction]:
    """
    根据信号和现有仓位生成计划。

    规则：
      - 有仓位且信号消失 -> 平仓
      - 有仓位且方向反转 -> 平仓，进入冷却
      - 无仓位且有信号且不在冷却 -> 开仓
      - 无仓位但仍在冷却 -> 跳过
    """
    state.prune(now)
    actions: list[PlannedAction] = []

    all_symbols = sorted(set(state.positions) | set(signals))
    for symbol in all_symbols:
        position = state.positions.get(symbol)
        signal = signals.get(symbol)

        if position and signal is None:
            actions.append(PlannedAction(kind="close", symbol=symbol, reason="signal_exit", position=position))
            continue

        if position and signal is not None and position.direction != int(signal["direction"]):
            actions.append(PlannedAction(kind="close", symbol=symbol, reason="direction_flip", position=position))
            continue

        if position is None and signal is not None:
            if state.is_in_cooldown(symbol, now):
                cooldown_until = state.cooldowns[symbol]
                actions.append(
                    PlannedAction(
                        kind="skip",
                        symbol=symbol,
                        reason=f"cooldown_{cooldown_hours:g}h",
                        direction=int(signal["direction"]),
                        rate_ann=float(signal["rate_ann"]),
                        weight=float(signal["weight"]),
                        cooldown_until=cooldown_until,
                    )
                )
                continue

            actions.append(
                PlannedAction(
                    kind="open",
                    symbol=symbol,
                    reason="new_signal",
                    direction=int(signal["direction"]),
                    rate_ann=float(signal["rate_ann"]),
                    weight=float(signal["weight"]),
                    notional_usd=float(total_notional_usd) * float(signal["weight"]),
                )
            )

    return actions


def record_open(
    state: PaperState,
    *,
    symbol: str,
    position: SyntheticPosition,
    opened_at: datetime,
    opened_rate_ann: float,
    signal_weight: float,
) -> None:
    state.cooldowns.pop(symbol, None)
    state.positions[symbol] = ManagedPosition.from_synthetic(
        binance_symbol=symbol,
        pos=position,
        opened_at=opened_at,
        opened_rate_ann=opened_rate_ann,
        signal_weight=signal_weight,
    )


def record_open_binance(
    state: PaperState,
    *,
    symbol: str,
    direction: int,
    notional_usd: float,
    opened_at: datetime,
    opened_rate_ann: float,
    signal_weight: float,
    binance_order_id: int | None = None,
    binance_quantity: float | None = None,
    binance_side: str | None = None,
) -> None:
    """记录仅 Binance 腿仓位，便于后续按信号平仓/冷却。"""
    state.cooldowns.pop(symbol, None)
    state.positions[symbol] = ManagedPosition(
        binance_symbol=symbol,
        ibkr_symbol=TICKER_MAP.get(symbol, symbol.replace("USDT", "")),
        direction=direction,
        strike=0.0,
        expiry="",
        contracts=0,
        notional_usd=float(notional_usd),
        opened_at=opened_at.astimezone(timezone.utc).isoformat(),
        opened_rate_ann=float(opened_rate_ann),
        signal_weight=float(signal_weight),
        binance_order_id=binance_order_id,
        binance_quantity=binance_quantity,
        binance_side=binance_side,
    )


def record_close(
    state: PaperState,
    *,
    symbol: str,
    closed_at: datetime,
    cooldown_hours: float,
) -> None:
    state.positions.pop(symbol, None)
    cooldown_until = closed_at + timedelta(hours=cooldown_hours)
    state.cooldowns[symbol] = cooldown_until.astimezone(timezone.utc).isoformat()


def summarize_state(state: PaperState, now: datetime) -> str:
    state.prune(now)
    lines: list[str] = []

    if state.positions:
        lines.append("当前本地仓位：")
        for symbol, pos in sorted(state.positions.items()):
            label = symbol.replace("USDT", "")
            if pos.contracts > 0:
                side = "合成多头" if pos.direction > 0 else "合成空头"
                lines.append(
                    f"  {label:8s} {side:6s}  {pos.contracts}张  "
                    f"strike={pos.strike:.2f}  expiry={pos.expiry}  名义={pos.notional_usd:,.0f}"
                )
            else:
                perp_side = "空永续" if pos.direction > 0 else "多永续"
                qty = "" if pos.binance_quantity is None else f" qty={pos.binance_quantity:g}"
                lines.append(f"  {label:8s} Binance-{perp_side:4s}{qty}  名义={pos.notional_usd:,.0f}")
    else:
        lines.append("当前本地仓位：无")

    active_cooldowns = [
        (symbol, raw)
        for symbol, raw in sorted(state.cooldowns.items())
        if datetime.fromisoformat(raw) > now
    ]
    if active_cooldowns:
        lines.append("冷却中：")
        for symbol, raw in active_cooldowns:
            lines.append(f"  {symbol.replace('USDT', ''):8s} until {raw}")

    return "\n".join(lines)


def validate_symbol(symbol: str) -> None:
    if symbol not in TICKER_MAP:
        raise ValueError(f"未配置 {symbol} 的 IBKR 对冲映射")
