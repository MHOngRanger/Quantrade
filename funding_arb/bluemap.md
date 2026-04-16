# 跨市场对冲交易系统（Cross-Market Hedging Bot）开发蓝图

## 1. 项目背景与总体架构

本项目旨在开发一个跨传统金融（IBKR）与加密货币（Binance）的**自动化量化对冲系统**。核心策略为：捕获资金费率（Funding Rate），通过在两端同时建仓/平仓来保持 Delta 中性。

**核心技术栈强制要求：**

* **语言：** Python 3.10+
* **并发模型：** 严格要求使用 `asyncio`。严禁在主事件循环中使用任何阻塞型（Blocking）代码（如 `time.sleep`, `requests`）。
* **传统金融端 (Leg A)：** IBKR (Interactive Brokers)。使用 `ib_insync` 库连接运行在本地/云端 Docker 中的 IB Gateway。
* **加密货币端 (Leg B)：** Binance U-Margined Futures（U本位合约）。使用 `ccxt.async_support` 进行交互。
* **部署环境：** Google Cloud Platform (GCP) Ubuntu Linux, Docker 环境。
* **配置管理：** 使用 `.env` 文件隔离所有敏感数据（API Keys, 账户名, 端口, IP）。

---

## 2. 工程实施的四个阶段 (The 4-Stage Plan)

请严格按照以下四个阶段逐步交付代码。

### 阶段一：Testnet 联调与异步并发基石 (The Async Foundation)

**目标：** 在纯测试环境中跑通双线连接，验证 `asyncio` 并发发单逻辑。忽略价格脱节问题。

**环境：** * Leg A: IBKR Paper Account (端口通常为 4002)

* Leg B: Binance USDS-M Futures Testnet (`exchange.set_sandbox_mode(True)`)

**开发任务：**

1. 编写基础连接模块：异步连接 IB Gateway 和币安 Testnet，确保网络畅通且能获取账户 Balance。
2. 编写合约验证模块：使用 `ib.qualifyContractsAsync` 验证 IBKR 期权/现货合约；获取币安永续合约基本信息（精度、最小下单量）。
3. **核心并发发单逻辑：** 编写一个 `async def execute_hedge(ib_order, binance_order)` 函数，使用 `asyncio.gather` 尝试同时发送两腿订单。
4. **异常处理（初级）：** 捕获网络断开异常，确保进程安全退出。

---

### 阶段二：读真写假与影子撮合 (Dry-Run & Shadow Matching)

**目标：** 接入真实市场行情，验证策略逻辑（如计算资金费率和理论 PnL），在本地模拟执行以计算理论滑点。

**环境：**

* Leg A: IBKR Paper Account (拉取真实延时/实时数据)
* Leg B: Binance 实盘 API (仅读取数据，无写入权限的 API Key)

**开发任务：**

1. 实时数据流：订阅币安的实时 Order Book 和 Funding Rate；获取 IBKR 的 Bid/Ask。
2. **影子撮合引擎 (Shadow Engine)：** * **严禁**向币安发送真实 `create_order` 请求。
   * 编写模拟撮合逻辑：根据请求下达的 Order Size，去查询最新的 Order Book，按照盘口深度计算出“模拟成交均价”（模拟真实滑点）。
3. 状态记录：将虚拟仓位、理论对冲敞口（Delta）记录到本地内存或 SQLite 数据库中。
4. 监控日志：输出每小时的理论资金费率收益及虚拟滑点损耗。

---

### 阶段三：极小资金实弹测试 (Penny Testing)

**目标：** 在真实的生产网络和撮合引擎中，验证毫秒级延迟、API 频率限制（Rate Limits）以及单腿风险（Legging Risk）的应急处理。

**环境：**

* Leg A: IBKR Live Account (实盘端口，极小真实资金)
* Leg B: Binance Live API (实盘，极小真实资金)

**开发任务：**

1. **订单尺寸硬编码：** 在代码最底层拦截器中，强制将所有下单请求修改为交易所允许的**最小单位**（例如币安的 `0.001 BTC`，IBKR 的 `1 股/张`）。
2. **高级单腿风险控制 (Crucial)：** * 当一腿成交，另一腿如果发生网络超时或被 Binance 节流（Rate Limited）怎么办？
   * 编写 Fallback 逻辑：启动重试机制，若 3 秒内仍未成交，立刻以市价单（Market Order）强行平掉已成交的那一腿，并触发飞书/Telegram/Email 严重报警。
3. 日志完善：记录订单发送、交易所返回确认的具体时间戳（精确到毫秒），以便后续分析两端网络延迟差。

---

### 阶段四：生产上线与动态缩放 (Production & Scale)

**目标：** 放大资金池，进入无人值守的长期稳定运行状态。

**开发任务：**

1. **头寸与资金管理模块：** 移除最小单位硬编码，接入基于账户权益（Equity）百分比的动态仓位计算逻辑。
2. **Margin 监控：** 实时计算双边的保证金维持率，设定距离爆仓线 20% 时触发自动平仓对冲。
3. 优雅重启与会话恢复：支持程序崩溃重启后，能够从交易所读取最新真实仓位，自动对齐（Reconciliation）内部状态，而不是盲目继续发单。
