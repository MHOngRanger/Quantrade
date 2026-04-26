"""
IBKR Paper 连接与合成期权对冲腿测试脚本。

验证：
  1. IB API 连通性
  2. 账户与保证金信息
  3. 股票/ETF 标的合约校验
  4. ATM Call/Put 期权合约校验
  5. 合成期权对冲腿 Dry Run 开仓 + 平仓

使用方式：
  uv run python scripts/test_ibkr_connection.py
  uv run python scripts/test_ibkr_connection.py --symbol TSLAUSDT --notional 20000
  uv run python scripts/test_ibkr_connection.py --reference-price 500
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _load_env() -> None:
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test IBKR hedge leg connection and dry-run orders.")
    parser.add_argument("--symbol", default="SPYUSDT", help="Binance TradFi symbol, e.g. SPYUSDT")
    parser.add_argument("--notional", type=float, default=10_000, help="Synthetic hedge notional in USD")
    parser.add_argument("--port", type=int, default=None, help="IBKR API port; default 4004 paper / 4003 live")
    parser.add_argument("--client-id", type=int, default=99, help="IBKR API client id")
    parser.add_argument("--live", action="store_true", help="Use live port default 4003 instead of paper 4004")
    parser.add_argument(
        "--reference-price",
        type=float,
        default=None,
        help="Fallback underlying price if market data permission is unavailable",
    )
    return parser


def _print_contract(label: str, contracts: list) -> None:
    if not contracts:
        print(f"  ❌ {label}: 未返回合约")
        return
    contract = contracts[0]
    print(
        f"  ✅ {label}: conId={contract.conId} "
        f"symbol={contract.symbol} exchange={contract.exchange} currency={contract.currency}"
    )


def _print_reference_price_hint(symbol: str) -> None:
    print("     当前 IBKR 会话可能没有实时/延时行情权限。")
    print(f"     可加参考价继续测试对冲腿，例如：--symbol {symbol} --reference-price 500")


def main() -> None:
    _load_env()
    args = _build_parser().parse_args()

    from ib_insync import Contract, Option

    from src.execution.ibkr import IBKRExecutor, TICKER_MAP

    port = args.port or (4003 if args.live else 4004)
    mode_label = "LIVE" if args.live else "Paper"

    print(f"\n{'='*60}")
    print(f"  IBKR 连接与对冲腿测试  [{mode_label} port={port}]")
    print(f"{'='*60}")

    ticker = TICKER_MAP.get(args.symbol)
    if not ticker:
        print(f"❌ {args.symbol} 未配置 IBKR 对冲映射")
        print(f"   可用示例: {', '.join(sorted(TICKER_MAP)[:8])} ...")
        sys.exit(1)

    executor = IBKRExecutor(port=port, client_id=args.client_id)
    ib = executor.ib

    try:
        # ── 测试 1：IB API 连接 ──
        print("\n[1] IB API 连接")
        try:
            executor.connect()
            print("  ✅ 已连接")
            print(f"     serverVersion: {ib.client.serverVersion()}")
            accounts = ib.managedAccounts()
            print(f"     accounts: {', '.join(accounts) if accounts else '<none>'}")
        except Exception as e:
            print(f"  ❌ 连接失败: {e}")
            sys.exit(1)

        # ── 测试 2：账户与保证金 ──
        print("\n[2] 账户与保证金")
        try:
            margin = executor.check_margin()
            print(f"  ✅ NetLiquidation:    {margin['net_liquidation']:,.2f}")
            print(f"     AvailableFunds:   {margin['available_funds']:,.2f}")
            print(f"     ExcessLiquidity:  {margin['excess_liquidity']:,.2f}")
            print(f"     MaintMarginReq:   {margin['maintenance_margin']:,.2f}")
        except Exception as e:
            print(f"  ⚠️ 保证金查询失败: {e}")

        # ── 测试 3：标的合约 ──
        print("\n[3] 标的合约校验")
        try:
            stock = Contract(symbol=ticker, secType="STK", exchange="SMART", currency="USD")
            stock_contracts = ib.qualifyContracts(stock)
            _print_contract(ticker, stock_contracts)
        except Exception as e:
            print(f"  ❌ {ticker} 合约校验失败: {e}")
            sys.exit(1)

        # ── 测试 4：生成合成期权对冲腿（Dry Run） ──
        print("\n[4] Dry Run 开仓测试：Binance short perp → IBKR 合成多头")
        try:
            long_pos = executor.open_synthetic(
                binance_symbol=args.symbol,
                direction=1,
                notional_usd=args.notional,
                dry_run=True,
                reference_price=args.reference_price,
            )
        except Exception as e:
            print(f"  ❌ 合成多头 Dry Run 失败: {e}")
            if args.reference_price is None:
                _print_reference_price_hint(args.symbol)
            sys.exit(1)

        print("\n[5] 期权合约校验")
        try:
            assert long_pos is not None
            call = Option(long_pos.symbol, long_pos.expiry, long_pos.strike, "C", "SMART")
            put = Option(long_pos.symbol, long_pos.expiry, long_pos.strike, "P", "SMART")
            call_contracts = ib.qualifyContracts(call)
            put_contracts = ib.qualifyContracts(put)
            _print_contract(f"{long_pos.symbol} {long_pos.expiry} C{long_pos.strike:g}", call_contracts)
            _print_contract(f"{long_pos.symbol} {long_pos.expiry} P{long_pos.strike:g}", put_contracts)
        except Exception as e:
            print(f"  ❌ 期权合约校验失败: {e}")
            sys.exit(1)

        print("\n[6] Dry Run 平仓测试：合成多头")
        try:
            executor.close_synthetic(long_pos, dry_run=True)
            print("  ✅ 平仓动作生成成功")
        except Exception as e:
            print(f"  ❌ 平仓 Dry Run 失败: {e}")

        print("\n[7] Dry Run 开仓测试：Binance long perp → IBKR 合成空头")
        try:
            short_pos = executor.open_synthetic(
                binance_symbol=args.symbol,
                direction=-1,
                notional_usd=args.notional,
                dry_run=True,
                reference_price=args.reference_price,
            )
            print("  ✅ 合成空头动作生成成功")
        except Exception as e:
            print(f"  ❌ 合成空头 Dry Run 失败: {e}")
            if args.reference_price is None:
                _print_reference_price_hint(args.symbol)
            sys.exit(1)

        print("\n[8] Dry Run 平仓测试：合成空头")
        try:
            executor.close_synthetic(short_pos, dry_run=True)
            print("  ✅ 平仓动作生成成功")
        except Exception as e:
            print(f"  ❌ 平仓 Dry Run 失败: {e}")

    finally:
        executor.disconnect()

    print(f"\n{'='*60}")
    print("  IBKR 对冲腿测试完成！")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
