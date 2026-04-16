# funding_arb — 资金费率套利子项目

## 项目简介

针对 **Binance TradFi 永续合约**（11 只美股类合约）的 Delta 中性资金费率套利策略。

- **Binance 腿**：永续合约方向随费率符号动态调整（正费率→空永续；负费率→多永续）
- **IBKR 腿**：合成期权对冲 Delta（ATM Call/Put，最近月到期，Portfolio Margin）
- **信号周期**：每 8 小时（Binance TradFi 结算周期）

## 合约标的

| Binance | IBKR | 类型 |
|---|---|---|
| SPYUSDT | SPY | ETF |
| QQQUSDT | QQQ | ETF |
| TSLAUSDT | TSLA | 个股 |
| NVDAUSDT | NVDA | 个股 |
| METAUSDT | META | 个股 |
| GOOGLUSDT | GOOGL | 个股 |
| AMZNUSDT | AMZN | 个股 |
| TSMUSDT | TSM | 个股 |
| MSTRUSDT | MSTR | 个股 |
| COINUSDT | COIN | 个股 |
| AAPLUSDT | AAPL | 个股 |

## 项目结构

```
funding_arb/
├── src/
│   ├── data/
│   │   ├── binance.py     # 拉取费率数据 + Parquet 缓存
│   │   └── okx.py         # OKX 备用数据源
│   ├── backtest/
│   │   ├── engine.py      # 回测循环（信号→仓位→P&L）
│   │   ├── costs.py       # 成本模型（期货费/期权价差/借贷/换期）
│   │   └── metrics.py     # Sharpe、最大回撤、年化收益
│   ├── signal/
│   │   └── generator.py   # 多标的信号：阈值过滤 + 强度加权
│   ├── monitor/
│   │   └── scanner.py     # 实时扫描：拉取 premiumIndex，生成快照
│   └── execution/
│       └── ibkr.py        # IBKR 合成期权建仓/平仓/换月
├── notebooks/
│   ├── 01_backtest_binance_tradfi.ipynb   # 主回测 + 敏感性分析
│   ├── 02_backtest_comparison.ipynb       # 各合约对比 + 组合分析
│   └── 03_live_signal_dashboard.ipynb    # 实时信号看板
├── scripts/
│   └── monitor_loop.py    # 可独立运行的监控脚本（每8h触发）
└── data/                  # Parquet 缓存（已 gitignore）
```

## 常用命令

```bash
# 进入项目目录
cd /home/lucas/Trade/Quantrade/funding_arb

# 安装依赖
uv sync

# 立即扫描一次当前信号
uv run python scripts/monitor_loop.py --once

# 持续监控（每8小时）
uv run python scripts/monitor_loop.py

# 运行 Jupyter Notebook
uv run jupyter notebook

# 验证导入正常
uv run python -c "from src.data.binance import load_all; print('OK')"

# 强制刷新全量数据缓存
uv run python -c "from src.data.binance import load_all; load_all(refresh=True)"
```

## 成本模型

| 项目 | 数值 | 说明 |
|---|---|---|
| Binance 期货手续费 | 0.10%/次开仓 | 双腿（开/平各0.05%） |
| IBKR 期权买卖价差（平静期） | 0.023%/次 | ATM 合成期权 |
| IBKR 期权买卖价差（高波动期） | 0.072%/次 | 关税冲击等事件 |
| 期权月度换期 | 0.026%/月 | 摊销到每8h周期 |
| 借贷成本 | 0.5%/年 | 现货/融券利息 |
| 冷却期 | 2个8h周期 | 平仓后不立即再开 |

**高波动分界日**：2026-04-02（特朗普关税冲击）

## 资本结构

```
名义本金 $1
├── Binance 保证金：20%（5x 杠杆）
└── IBKR 期权保证金：12%（Portfolio Margin）
    ────────────────────
    总所需资本：32% → 有效杠杆 3.1x
```

## IBKR 执行注意事项

1. 需要 IBKR Portfolio Margin 账户（最低净值 $110,000）
2. 先在 Paper Trading 账户测试
3. TWS 或 IB Gateway 需在本地运行（默认 port 7497 for paper, 7496 for live）
4. 安装 `ib_insync`：`uv add ib_insync`
5. 安装 `apscheduler`（监控脚本用）：`uv add apscheduler`

## 回测结果摘要（2026-01 上线至今）

| 时期 | 年化收益 | 夏普 | 最大回撤 |
|---|---|---|---|
| 全样本 | ~141% | >2 | <5% |
| 正常期（上线~4月） | ~113% | >2 | <3% |
| 关税冲击期（4月~） | ~235% | >3 | <5% |

> 注：高波动期费率极端，收益被放大但成本也同步提升（期权价差×3x）

## 主要依赖

- `pandas`, `numpy` — 数据处理
- `requests` — Binance/OKX API
- `pyarrow` — Parquet 缓存
- `matplotlib` — 可视化
- `ib_insync` — IBKR 执行层（可选，`uv add ib_insync`）
- `apscheduler` — 定时监控（可选，`uv add apscheduler`）
- `jupyter` — Notebook 运行
