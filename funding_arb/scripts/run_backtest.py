"""
资金费率套利回测脚本。

使用方式：
  uv run python scripts/run_backtest.py
  uv run python scripts/run_backtest.py --refresh
  uv run python scripts/run_backtest.py --threshold 0.00015 --leverage 4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.engine import run, sensitivity
from src.backtest.metrics import print_summary
from src.data.binance import load_all


def _describe_panel(wide: pd.DataFrame) -> None:
    print("数据样本")
    print(f"  起点: {wide.index.min()}")
    print(f"  终点: {wide.index.max()}")
    print(f"  周期数: {len(wide)}")
    print(f"  合约数: {wide.shape[1]}")
    print(f"  平均活跃合约数: {wide.notna().sum(axis=1).mean():.2f}")

    print("\n各合约覆盖度")
    counts = wide.notna().sum().sort_values(ascending=False)
    for symbol, count in counts.items():
        first_valid = wide[symbol].dropna().index.min()
        last_valid = wide[symbol].dropna().index.max()
        print(f"  {symbol:9s}  {count:4d}  {first_valid} -> {last_valid}")


def main() -> None:
    parser = argparse.ArgumentParser(description="资金费率套利回测")
    parser.add_argument("--refresh", action="store_true", help="强制刷新本地缓存")
    parser.add_argument("--threshold", type=float, default=0.0001, help="入场阈值")
    parser.add_argument("--leverage", type=float, default=5.0, help="Binance 杠杆倍数")
    parser.add_argument("--track-err-std", type=float, default=0.001, help="Delta 追踪误差标准差")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--skip-sensitivity", action="store_true", help="跳过敏感性分析")
    args = parser.parse_args()

    wide = load_all(refresh=args.refresh)
    if wide.empty:
        raise SystemExit("未加载到任何 funding 数据")

    _describe_panel(wide)

    equity, trades = run(
        wide,
        threshold=args.threshold,
        max_leverage=args.leverage,
        track_err_std=args.track_err_std,
        seed=args.seed,
    )

    print("\n主回测")
    print_summary(equity, label="all_sample")
    print(f"开仓/换向次数: {len(trades)}")

    if not trades.empty:
        print("\n最高年化费率交易")
        top = trades.reindex(trades["rate_ann"].abs().sort_values(ascending=False).index).head(10)
        print(
            top[["ts", "symbol", "event", "direction", "rate_ann", "notional", "open_cost"]]
            .to_string(index=False)
        )

    if args.skip_sensitivity:
        return

    print("\n敏感性分析")
    sens = sensitivity(
        wide,
        thresholds=[0.00005, 0.0001, 0.00015, 0.0002],
        leverages=[3.0, 4.0, 5.0],
        track_err_std=args.track_err_std,
        seed=args.seed,
    )
    sens = sens.sort_values(["ann_ret_%", "sharpe"], ascending=False)
    print(sens.head(12).to_string(index=False))


if __name__ == "__main__":
    main()
