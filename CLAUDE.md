# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

基于《Quant Roadmap Ultimate Edition》第13章的量化交易策略研究项目，实现并回测了该章节列出的5类核心策略：**配对交易、套利、做市商、动量、季节性**。

## 常用命令

```bash
# 启动 Jupyter 交互式环境
uv run jupyter notebook

# 命令行执行单个策略（含输出）
uv run jupyter nbconvert --to notebook --execute notebooks/01_pairs_trading.ipynb --inplace

# 批量执行所有策略
for nb in notebooks/0*.ipynb; do
  uv run jupyter nbconvert --to notebook --execute "$nb" --inplace
done

# 添加新依赖
uv add <包名>
```

## 项目结构

```
Quantrade/
├── notebooks/                        # 每个策略一个 notebook
│   ├── 01_pairs_trading.ipynb        # 配对交易（协整统计套利，美股）
│   ├── 02_momentum.ipynb             # 横截面动量（S&P500）
│   ├── 03_seasonality.ipynb          # 季节性效应（SPY）
│   ├── 04_funding_arbitrage.ipynb    # 资金费率套利（Binance API）
│   └── 05_market_making.ipynb        # 做市商模拟（Avellaneda-Stoikov）
├── assets/                           # 输出图表
├── pyproject.toml                    # uv 依赖管理
└── RoadmapUltimateEdition.pdf        # 参考文献
```

## 策略设计说明

### 01 — 配对交易（统计套利）
- **数据**：yfinance 日线，同行业股票对（KO/PEP、GS/MS、XOM/CVX 等）
- **信号**：Engle-Granger 协整检验 → OLS 对冲比率 → 价差滚动 Z-score
- **入场/出场**：|Z| > 2.0 入场，|Z| < 0.5 离场，|Z| > 3.5 止损
- **成本**：每腿 10 bps

### 02 — 横截面动量
- **数据**：yfinance 月线，~100 只 S&P500 大盘股
- **信号**：12-1 月累计收益率（跳过最近1月以规避短期反转）
- **组合**：多头前20% + 空头后20%，等权，月度再平衡
- **成本**：每腿 10 bps

### 03 — 季节性
- **数据**：SPY 日线（1993年至今）
- **规律**：月份效应、星期效应、月末月初效应（±4天）、"五月卖出"
- **综合信号**：多条件评分之和 ≥ 2 时持仓

### 04 — 资金费率套利（加密货币）
- **数据**：Binance 公开 API（`fapi.binance.com/fapi/v1/fundingRate`）+ yfinance BTC 现货
- **信号**：7日滚动平均8小时资金费率 > 0.01% → 建立 Delta 中性头寸（做多现货 + 做空永续合约）
- **收益**：资金费收入 − 5% 年化借贷成本 − 4 bps 手续费

### 05 — 做市商（Avellaneda-Stoikov 模型）
- **数据**：yfinance BTC-USD 1分钟 K 线（最近7天，若无数据自动生成模拟数据）
- **模型**：`预留价格 = 中间价 − q·γ·σ²·τ`，`最优价差 = γ·σ²·τ + (2/γ)·ln(1 + γ/κ)`
- **成交模型**：K 线高低点触及报价时视为成交
- **风控**：最大库存 ±5 BTC，每次 0.01 BTC

## 数据来源

| 策略 | 数据源 | 费用 |
|---|---|---|
| 美股（日线/月线） | `yfinance` | 免费 |
| BTC 现货（日线/1分钟） | `yfinance` | 免费 |
| BTC 资金费率 | Binance Futures 公开 API | 免费 |

## 主要依赖

- `yfinance` — 行情数据下载
- `statsmodels` — 协整检验（Engle-Granger）、OLS 回归
- `scipy` — 季节性显著性 t 检验
- `pandas`、`numpy` — 数据处理
- `matplotlib` — 可视化

## 注意事项

- yfinance ≥ 1.x 对单标的下载也可能返回 MultiIndex 列，代码已作兼容处理（`squeeze()` / `droplevel`）
- Binance API 在某些网络环境下无法访问，策略04有合成数据 fallback
- 所有回测均已扣除估算交易成本，但未考虑滑点和市场冲击
