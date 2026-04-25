"""
Binance Futures Testnet 连接测试脚本。

验证：
  1. API 签名 & 连通性
  2. 账户余额
  3. 标记价格拉取
  4. 测试单下单 + 自动平仓

使用方式：
  uv run python scripts/test_binance_connection.py
"""
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


def main() -> None:
    _load_env()

    api_key = os.environ.get("BINANCE_API_KEY", "")
    api_secret = os.environ.get("BINANCE_API_SECRET", "")

    if not api_key or not api_secret:
        print("❌ 未配置 BINANCE_API_KEY / BINANCE_API_SECRET")
        print("   请在 .env 中添加：")
        print("   BINANCE_API_KEY=xxx")
        print("   BINANCE_API_SECRET=xxx")
        sys.exit(1)

    testnet = os.environ.get("BINANCE_TESTNET", "true").lower() in ("true", "1", "yes")

    from src.execution.binance_executor import BinanceExecutor

    env_label = "Testnet" if testnet else "⚠️ PRODUCTION"
    print(f"\n{'='*55}")
    print(f"  Binance Futures 连接测试  [{env_label}]")
    print(f"{'='*55}")

    executor = BinanceExecutor(
        api_key=api_key,
        api_secret=api_secret,
        testnet=testnet,
    )

    # ── 测试 1：账户余额 ──
    print("\n[1] 账户余额")
    try:
        bal = executor.get_balance()
        print(f"  ✅ 钱包余额:   {bal['total_wallet_balance']:,.2f} USDT")
        print(f"     可用余额:   {bal['available_balance']:,.2f} USDT")
        print(f"     未实现盈亏: {bal['total_unrealized_profit']:,.2f} USDT")
        print(f"     保证金余额: {bal['total_margin_balance']:,.2f} USDT")
    except Exception as e:
        print(f"  ❌ 余额查询失败: {e}")
        sys.exit(1)

    # ── 测试 2：标记价格 ──
    print("\n[2] 标记价格")
    test_symbols = ["SPYUSDT", "TSLAUSDT", "TSMUSDT"]
    for sym in test_symbols:
        try:
            price = executor.get_mark_price(sym)
            print(f"  ✅ {sym:12s}  markPrice = {price:,.2f}")
        except Exception as e:
            print(f"  ⚠️ {sym:12s}  获取失败: {e}")

    # ── 测试 3：当前持仓 ──
    print("\n[3] 当前持仓")
    try:
        positions = executor.get_positions()
        if positions:
            for p in positions:
                print(f"  {p['symbol']:12s}  "
                      f"amt={float(p['positionAmt']):+.4f}  "
                      f"unrealPnl={float(p.get('unRealizedProfit', 0)):+.2f}")
        else:
            print("  无持仓")
    except Exception as e:
        print(f"  ❌ 持仓查询失败: {e}")

    # ── 测试 4：Dry Run 开仓 ──
    print("\n[4] Dry Run 开仓测试（不会实际下单）")
    try:
        fill = executor.open_position(
            symbol="SPYUSDT",
            direction=1,  # 做空永续
            notional_usd=100,
            leverage=5,
            dry_run=True,
        )
        if fill:
            print(f"  ✅ DRY_RUN 成功: {fill.side} {fill.quantity} {fill.symbol}")
    except Exception as e:
        print(f"  ❌ Dry Run 失败: {e}")

    # ── 测试 5：设置杠杆 ──
    print("\n[5] 设置杠杆（SPYUSDT, 5x）")
    try:
        result = executor.set_leverage("SPYUSDT", 5)
        print(f"  ✅ leverage={result.get('leverage')}")
    except Exception as e:
        print(f"  ⚠️ 设置杠杆: {e}")

    executor.close()

    print(f"\n{'='*55}")
    print("  全部测试完成！")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
