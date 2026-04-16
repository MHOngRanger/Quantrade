"""
独立监控脚本：每8小时自动运行一次，扫描信号并输出事件

使用方式：
  uv run python scripts/monitor_loop.py                        # 持续运行（每8h触发）
  uv run python scripts/monitor_loop.py --once                 # 立即运行一次后退出
  uv run python scripts/monitor_loop.py --once --execute       # IBKR paper 自动执行
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# 将 src 目录加入路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.execution.ibkr import IBKRExecutor
from src.execution.paper import (
    default_state_path,
    load_state,
    plan_actions,
    record_close,
    record_open,
    save_state,
    summarize_state,
)
from src.monitor.scanner import scan, load_last_snapshot, diff_snapshots


def run_once(
    *,
    threshold: float = 0.0001,
    execute: bool = False,
    total_notional_usd: float = 10_000,
    cooldown_hours: float = 16.0,
    ibkr_port: int = 7497,
    client_id: int = 10,
    state_path: Path | None = None,
    account_mode: str = "paper",
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

    print(f"\n执行模式：IBKR {account_mode}")
    print("注意：当前只会执行 IBKR 对冲腿，Binance 腿仍需你手动或另行接入。")

    executor = IBKRExecutor(port=ibkr_port, client_id=client_id)
    connected = False
    try:
        executor.connect()
        connected = True
        margin = executor.check_margin()
        print(
            "\nIBKR 账户："
            f" net_liq={margin['net_liquidation']:,.0f}"
            f" available={margin['available_funds']:,.0f}"
            f" excess={margin['excess_liquidity']:,.0f}"
        )

        for action in actions:
            if action.kind == "skip":
                continue

            if action.kind == "close":
                if action.position is None:
                    raise ValueError(f"{action.symbol} 缺少可平仓仓位")
                executor.close_synthetic(action.position.to_synthetic(), dry_run=False)
                record_close(
                    state,
                    symbol=action.symbol,
                    closed_at=now,
                    cooldown_hours=cooldown_hours,
                )
                save_state(state, state_path)
                continue

            if action.kind == "open":
                pos = executor.open_synthetic(
                    binance_symbol=action.symbol,
                    direction=int(action.direction or 0),
                    notional_usd=float(action.notional_usd or 0),
                    dry_run=False,
                )
                if pos is None:
                    raise RuntimeError(f"{action.symbol} 开仓未返回仓位")
                record_open(
                    state,
                    symbol=action.symbol,
                    position=pos,
                    opened_at=now,
                    opened_rate_ann=float(action.rate_ann or 0),
                    signal_weight=float(action.weight or 0),
                )
                save_state(state, state_path)

        print(f"\n执行完成，状态已写入：{state_path}")
    finally:
        if connected:
            executor.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="资金费率监控")
    parser.add_argument("--once",      action="store_true", help="运行一次后退出")
    parser.add_argument("--threshold", type=float, default=0.0001, help="入场阈值")
    parser.add_argument("--interval",  type=int,   default=8 * 3600, help="扫描间隔（秒）")
    parser.add_argument("--execute",   action="store_true", help="连接 IBKR paper 自动执行对冲腿")
    parser.add_argument("--notional",  type=float, default=10_000, help="总名义本金（按权重分配）")
    parser.add_argument("--cooldown-hours", type=float, default=16.0, help="平仓后冷却时长")
    parser.add_argument("--client-id", type=int, default=10, help="IBKR API client id")
    parser.add_argument("--ibkr-port", type=int, default=None, help="手动指定 IBKR API 端口")
    parser.add_argument("--live",      action="store_true", help="连接 live 端口（默认 paper 7497）")
    parser.add_argument("--state-path", type=Path, default=default_state_path(), help="本地状态文件路径")
    args = parser.parse_args()
    ibkr_port = args.ibkr_port or (7496 if args.live else 7497)
    account_mode = "live" if args.live else "paper"

    if args.once:
        run_once(
            threshold=args.threshold,
            execute=args.execute,
            total_notional_usd=args.notional,
            cooldown_hours=args.cooldown_hours,
            ibkr_port=ibkr_port,
            client_id=args.client_id,
            state_path=args.state_path,
            account_mode=account_mode,
        )
        return

    # 持续运行
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        print("请先安装 apscheduler：uv add apscheduler")
        sys.exit(1)

    scheduler = BlockingScheduler()
    scheduler.add_job(
        lambda: run_once(
            threshold=args.threshold,
            execute=args.execute,
            total_notional_usd=args.notional,
            cooldown_hours=args.cooldown_hours,
            ibkr_port=ibkr_port,
            client_id=args.client_id,
            state_path=args.state_path,
            account_mode=account_mode,
        ),
        "interval",
        seconds=args.interval,
        id="funding_scan",
    )
    print(f"监控启动，每 {args.interval//3600} 小时扫描一次（Ctrl+C 停止）")
    run_once(
        threshold=args.threshold,
        execute=args.execute,
        total_notional_usd=args.notional,
        cooldown_hours=args.cooldown_hours,
        ibkr_port=ibkr_port,
        client_id=args.client_id,
        state_path=args.state_path,
        account_mode=account_mode,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
