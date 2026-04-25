"""
独立监控脚本：每8小时自动运行一次，扫描信号并输出事件

使用方式：
  uv run python scripts/monitor_loop.py                        # 持续运行（每8h触发）
  uv run python scripts/monitor_loop.py --once                 # 立即运行一次后退出
  uv run python scripts/monitor_loop.py --once --execute       # 双腿自动执行（dry_run）
  uv run python scripts/monitor_loop.py --once --execute --no-dry-run   # 真实下单
  uv run python scripts/monitor_loop.py --once --execute --binance-only # 仅 Binance 腿
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 将 src 目录加入路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.execution.ibkr import IBKRExecutor
from src.execution.binance_executor import BinanceExecutor
from src.execution.orchestrator import Orchestrator
from src.execution.paper import (
    binance_position_amt,
    default_state_path,
    load_state,
    plan_actions,
    record_close,
    record_open,
    record_open_binance,
    save_state,
    summarize_state,
)
from src.monitor.scanner import scan, load_last_snapshot, diff_snapshots


def _load_env() -> None:
    """简单的 .env 加载（避免引入 python-dotenv 依赖）"""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def run_once(
    *,
    threshold: float = 0.0001,
    execute: bool = False,
    dry_run: bool = True,
    total_notional_usd: float = 10_000,
    cooldown_hours: float = 16.0,
    ibkr_port: int = 4004,
    client_id: int = 10,
    state_path: Path | None = None,
    account_mode: str = "paper",
    binance_only: bool = False,
    binance_testnet: bool = True,
    leverage: int = 5,
) -> None:
    now = datetime.now(timezone.utc)
    prev = load_last_snapshot()
    curr = scan(threshold=threshold, verbose=True)
    events = diff_snapshots(prev, curr)
    if events:
        print(f"\n变动事件：")
        for e in events:
            print(f"  {e}")
    else:
        print("\n  无变动")

    state_path = state_path or default_state_path()
    state = load_state(state_path)
    print(f"\n{summarize_state(state, now)}")

    actions = plan_actions(
        state=state,
        signals=curr["signals"],
        now=now,
        total_notional_usd=total_notional_usd,
        cooldown_hours=cooldown_hours,
    )
    if actions:
        print("\n执行计划：")
        for action in actions:
            print(f"  {action.describe()}")
    else:
        print("\n执行计划：无")

    if not execute:
        print(f"\n状态文件：{state_path}")
        return

    actionable = [action for action in actions if action.kind in {"open", "close"}]
    if not actionable:
        save_state(state, state_path)
        print(f"\n无可执行动作，状态已同步到：{state_path}")
        return

    # ── 初始化执行器 ──
    _load_env()
    binance_key = os.environ.get("BINANCE_API_KEY", "")
    binance_secret = os.environ.get("BINANCE_API_SECRET", "")

    if not dry_run and (not binance_key or not binance_secret):
        print("\n❌ 未配置 BINANCE_API_KEY / BINANCE_API_SECRET，请在 .env 中添加")
        return

    bn_executor = BinanceExecutor(
        api_key=binance_key,
        api_secret=binance_secret,
        testnet=binance_testnet,
    )

    # Binance 余额检查。dry-run 且无密钥时跳过，保证本地演练可运行。
    if binance_key and binance_secret:
        try:
            bal = bn_executor.get_balance()
            env_label = "Testnet" if binance_testnet else "Production"
            print(
                f"\nBinance ({env_label}) 账户："
                f" 余额={bal['total_wallet_balance']:,.2f}"
                f" 可用={bal['available_balance']:,.2f}"
            )
        except Exception as e:
            print(f"\n⚠️ Binance 账户查询失败: {e}")
    else:
        print("\nBinance：未配置密钥，当前仅支持 dry-run")

    mode_str = f"{'DRY_RUN' if dry_run else 'LIVE'}"

    if binance_only:
        # 仅 Binance 腿
        print(f"\n执行模式：Binance-only [{mode_str}]")
        for action in actionable:
            if action.kind == "close":
                amount = (
                    binance_position_amt(action.position.direction, action.position.binance_quantity)
                    if action.position
                    else None
                )
                bn_executor.close_position(action.symbol, dry_run=dry_run, position_amt=amount)
                record_close(
                    state,
                    symbol=action.symbol,
                    closed_at=now,
                    cooldown_hours=cooldown_hours,
                )
                save_state(state, state_path)
                continue

            if action.kind == "open":
                fill = bn_executor.open_position(
                    symbol=action.symbol,
                    direction=int(action.direction or 0),
                    notional_usd=float(action.notional_usd or 0),
                    leverage=leverage,
                    dry_run=dry_run,
                )
                record_open_binance(
                    state,
                    symbol=action.symbol,
                    direction=int(action.direction or 0),
                    notional_usd=float(action.notional_usd or 0),
                    opened_at=now,
                    opened_rate_ann=float(action.rate_ann or 0),
                    signal_weight=float(action.weight or 0),
                    binance_order_id=fill.order_id if fill else None,
                    binance_quantity=fill.quantity if fill else None,
                    binance_side=fill.side if fill else None,
                )
                save_state(state, state_path)
        bn_executor.close()
        print(f"\n执行完成，状态已写入：{state_path}")
        return

    # 双腿执行
    print(f"\n执行模式：双腿 Binance + IBKR [{mode_str}]")
    ibkr_executor = IBKRExecutor(port=ibkr_port, client_id=client_id)
    ibkr_connected = False

    try:
        ibkr_executor.connect()
        ibkr_connected = True
        margin = ibkr_executor.check_margin()
        print(
            f"IBKR 账户："
            f" net_liq={margin['net_liquidation']:,.0f}"
            f" available={margin['available_funds']:,.0f}"
        )
    except Exception as e:
        print(f"\n⚠️ IBKR 连接失败: {e}")
        print("  将仅执行 Binance 腿")
        ibkr_connected = False

    orch = Orchestrator(binance=bn_executor, ibkr=ibkr_executor)

    try:
        for action in actionable:
            if action.kind == "close":
                if action.position is None:
                    print(f"  ⚠️ {action.symbol} 缺少仓位信息，跳过")
                    continue

                if ibkr_connected and action.position.contracts > 0:
                    result = orch.close_dual(
                        symbol=action.symbol,
                        ibkr_position=action.position.to_synthetic(),
                        dry_run=dry_run,
                    )
                    success = result.success
                else:
                    amount = binance_position_amt(action.position.direction, action.position.binance_quantity)
                    bn_executor.close_position(action.symbol, dry_run=dry_run, position_amt=amount)
                    success = True

                if success:
                    record_close(
                        state,
                        symbol=action.symbol,
                        closed_at=now,
                        cooldown_hours=cooldown_hours,
                    )
                    save_state(state, state_path)

            elif action.kind == "open":
                if ibkr_connected:
                    result = orch.open_dual(
                        symbol=action.symbol,
                        direction=int(action.direction or 0),
                        notional_usd=float(action.notional_usd or 0),
                        leverage=leverage,
                        dry_run=dry_run,
                    )
                    if result.success and result.ibkr_position:
                        record_open(
                            state,
                            symbol=action.symbol,
                            position=result.ibkr_position,
                            opened_at=now,
                            opened_rate_ann=float(action.rate_ann or 0),
                            signal_weight=float(action.weight or 0),
                        )
                        # 记录 Binance 腿信息
                        pos = state.positions.get(action.symbol)
                        if pos and result.binance_fill:
                            pos.binance_order_id = result.binance_fill.order_id
                            pos.binance_quantity = result.binance_fill.quantity
                            pos.binance_side = result.binance_fill.side
                        save_state(state, state_path)
                    continue

                fill = bn_executor.open_position(
                    symbol=action.symbol,
                    direction=int(action.direction or 0),
                    notional_usd=float(action.notional_usd or 0),
                    leverage=leverage,
                    dry_run=dry_run,
                )
                record_open_binance(
                    state,
                    symbol=action.symbol,
                    direction=int(action.direction or 0),
                    notional_usd=float(action.notional_usd or 0),
                    opened_at=now,
                    opened_rate_ann=float(action.rate_ann or 0),
                    signal_weight=float(action.weight or 0),
                    binance_order_id=fill.order_id if fill else None,
                    binance_quantity=fill.quantity if fill else None,
                    binance_side=fill.side if fill else None,
                )
                save_state(state, state_path)

        print(f"\n执行完成，状态已写入：{state_path}")
    finally:
        if ibkr_connected:
            ibkr_executor.disconnect()
        bn_executor.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="资金费率监控 + 双腿执行")
    parser.add_argument("--once",      action="store_true", help="运行一次后退出")
    parser.add_argument("--threshold", type=float, default=0.0001, help="入场阈值")
    parser.add_argument("--interval",  type=int,   default=8 * 3600, help="扫描间隔（秒）")
    parser.add_argument("--execute",   action="store_true", help="执行交易（默认 dry_run）")
    parser.add_argument("--no-dry-run", action="store_true", help="关闭 dry_run，真实下单")
    parser.add_argument("--notional",  type=float, default=10_000, help="总名义本金（按权重分配）")
    parser.add_argument("--leverage",  type=int, default=5, help="Binance 杠杆倍数")
    parser.add_argument("--cooldown-hours", type=float, default=16.0, help="平仓后冷却时长")
    parser.add_argument("--client-id", type=int, default=10, help="IBKR API client id")
    parser.add_argument("--ibkr-port", type=int, default=None, help="手动指定 IBKR API 端口")
    parser.add_argument("--live",      action="store_true", help="连接 live 端口（默认 paper）")
    parser.add_argument("--binance-only", action="store_true", help="仅执行 Binance 腿")
    parser.add_argument("--binance-live", action="store_true", help="使用 Binance 生产环境（默认 Testnet）")
    parser.add_argument("--state-path", type=Path, default=default_state_path(), help="本地状态文件路径")
    args = parser.parse_args()
    ibkr_port = args.ibkr_port or (4003 if args.live else 4004)
    account_mode = "live" if args.live else "paper"
    dry_run = not args.no_dry_run

    common_kwargs = dict(
        threshold=args.threshold,
        execute=args.execute,
        dry_run=dry_run,
        total_notional_usd=args.notional,
        cooldown_hours=args.cooldown_hours,
        ibkr_port=ibkr_port,
        client_id=args.client_id,
        state_path=args.state_path,
        account_mode=account_mode,
        binance_only=args.binance_only,
        binance_testnet=not args.binance_live,
        leverage=args.leverage,
    )

    if args.once:
        run_once(**common_kwargs)
        return

    # 持续运行
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        print("请先安装 apscheduler：uv add apscheduler")
        sys.exit(1)

    scheduler = BlockingScheduler()
    scheduler.add_job(
        lambda: run_once(**common_kwargs),
        "interval",
        seconds=args.interval,
        id="funding_scan",
    )
    print(f"监控启动，每 {args.interval//3600} 小时扫描一次（Ctrl+C 停止）")
    run_once(**common_kwargs)
    scheduler.start()


if __name__ == "__main__":
    main()
