"""
实时监控器：每8小时拉取最新费率，输出信号快照
可独立运行，也可被 scripts/monitor_loop.py 调用
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..data.binance import fetch_current_rates, EQUITY_SYMBOLS
from ..signal.generator import generate, format_signals

_SNAPSHOT_PATH = Path(__file__).parent.parent.parent / "data" / "last_snapshot.json"


def scan(
    threshold: float = 0.0001,
    verbose: bool = True,
) -> dict:
    """
    拉取实时费率 → 生成信号 → 输出快照。

    Returns:
        snapshot dict with keys: ts, signals, rates
    """
    now = datetime.now(timezone.utc)
    rates_df = fetch_current_rates(EQUITY_SYMBOLS)

    # 构造单行宽表供 signal generator 使用
    wide_now = rates_df["current_rate"].to_frame().T
    wide_now.index = pd.DatetimeIndex([now])

    signals = generate(wide_now, threshold=threshold)

    snapshot = {
        "ts":      now.isoformat(),
        "signals": {
            sym: {"direction": d, "weight": w, "rate_ann": r}
            for sym, (d, w, r) in signals.items()
        },
        "rates": rates_df[["current_rate", "next_rate", "current_ann", "next_ann"]]
                 .round(4).to_dict(),
    }

    if verbose:
        print(f"\n{'='*55}")
        print(f"  Funding Rate Scanner  {now.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*55}")
        print(f"\n当前信号（阈值={threshold*100:.4f}%/8h = {threshold*3*365*100:.1f}%年化）：")
        print(format_signals(signals))
        print(f"\n全合约实时费率：")
        for sym, row in rates_df.iterrows():
            label = sym.replace("USDT", "")
            star  = " ◄" if sym in signals else ""
            print(f"  {label:8s}  当前={row['current_ann']:+7.1f}%  "
                  f"下期={row['next_ann']:+7.1f}%{star}")

    # 保存快照
    _SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    with open(_SNAPSHOT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)

    return snapshot


def load_last_snapshot() -> dict | None:
    """读取上次快照"""
    if not _SNAPSHOT_PATH.exists():
        return None
    with open(_SNAPSHOT_PATH) as f:
        return json.load(f)


def diff_snapshots(prev: dict | None, curr: dict) -> list[str]:
    """
    对比新旧快照，返回事件列表：
    - 新开仓 / 新平仓 / 方向反转
    """
    events = []
    if prev is None:
        return events

    prev_sigs = prev.get("signals", {})
    curr_sigs = curr.get("signals", {})

    for sym in set(list(prev_sigs) + list(curr_sigs)):
        label = sym.replace("USDT", "")
        p = prev_sigs.get(sym)
        c = curr_sigs.get(sym)
        if p is None and c is not None:
            events.append(f"[新开仓] {label}  {c['rate_ann']:+.1f}%/年")
        elif p is not None and c is None:
            events.append(f"[平仓]   {label}")
        elif p is not None and c is not None and p["direction"] != c["direction"]:
            events.append(f"[换向]   {label}  {p['rate_ann']:+.1f}% → {c['rate_ann']:+.1f}%")

    return events
