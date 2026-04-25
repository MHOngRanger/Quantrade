"""
Binance USDⓈ-M 永续合约执行器。

纯 requests 实现，HMAC-SHA256 签名。
支持 testnet（demo-fapi.binance.com）和生产（fapi.binance.com）。

使用前提：
  1. .env 中配置 BINANCE_API_KEY / BINANCE_API_SECRET
  2. 首次使用生产环境需签署 TradFi 协议
  3. 强烈建议先用 Testnet 测试

信号方向映射（策略核心）：
  正费率 (direction=+1) → 做空永续 (SELL) → 收取费率
  负费率 (direction=-1) → 做多永续 (BUY)  → 收取费率
"""
from __future__ import annotations

import hashlib
import hmac
import math
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── 常量 ─────────────────────────────────────────────────
_TESTNET_BASE = "https://demo-fapi.binance.com"
_PRODUCTION_BASE = "https://fapi.binance.com"
_REQUEST_TIMEOUT = (5, 15)
_DEFAULT_RECV_WINDOW = 5000


@dataclass
class BinanceFill:
    """单次成交结果"""
    symbol: str
    side: str               # BUY / SELL
    quantity: float
    avg_price: float
    order_id: int
    status: str             # FILLED / NEW / ...


@dataclass(frozen=True)
class SymbolRules:
    """下单所需的最小交易规则。"""
    quantity_precision: int
    price_precision: int
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal


class BinanceExecutor:
    """
    Binance USDⓈ-M 永续合约执行器。

    Args:
        api_key:    Binance API Key
        api_secret: Binance API Secret
        testnet:    True = 使用 Testnet（默认 True）
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        base_url: str | None = None,
        recv_window: int = _DEFAULT_RECV_WINDOW,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = (base_url or (_TESTNET_BASE if testnet else _PRODUCTION_BASE)).rstrip("/")
        self.recv_window = recv_window
        self.session = self._build_session()
        self._exchange_info: dict | None = None
        self._time_offset_ms: int | None = None

    def _build_session(self) -> requests.Session:
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST", "DELETE"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "User-Agent": "funding-arb/0.1",
        })
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    # ── 签名 ─────────────────────────────────────────────

    def _sign(self, params: dict) -> dict:
        """添加 timestamp 和 HMAC-SHA256 signature"""
        if not self.api_key or not self.api_secret:
            raise RuntimeError("未配置 BINANCE_API_KEY / BINANCE_API_SECRET，无法调用签名接口")

        if self._time_offset_ms is None:
            self.sync_time()

        params["timestamp"] = int(time.time() * 1000) + int(self._time_offset_ms or 0)
        params.setdefault("recvWindow", self.recv_window)
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        signed: bool = False,
    ) -> dict | list:
        params = dict(params or {})
        unsigned_params = dict(params)
        if signed:
            params = self._sign(params)

        url = f"{self.base_url}{path}"
        resp = self.session.request(
            method, url, params=params, timeout=_REQUEST_TIMEOUT,
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Binance API returned non-JSON response: {resp.text[:200]}") from exc

        if resp.status_code >= 400:
            code = data.get("code", resp.status_code)
            msg = data.get("msg", resp.text)
            if signed and code == -1021:
                self.sync_time()
                retry_params = self._sign(unsigned_params)
                retry_resp = self.session.request(
                    method, url, params=retry_params, timeout=_REQUEST_TIMEOUT,
                )
                try:
                    retry_data = retry_resp.json()
                except ValueError as exc:
                    raise RuntimeError(
                        f"Binance API returned non-JSON response: {retry_resp.text[:200]}"
                    ) from exc
                if retry_resp.status_code < 400:
                    return retry_data
                code = retry_data.get("code", retry_resp.status_code)
                msg = retry_data.get("msg", retry_resp.text)
            raise RuntimeError(f"Binance API error {code}: {msg}")

        return data

    def _get(self, path: str, params: dict | None = None, signed: bool = False):
        return self._request("GET", path, params, signed)

    def _post(self, path: str, params: dict | None = None, signed: bool = True):
        return self._request("POST", path, params, signed)

    def _delete(self, path: str, params: dict | None = None, signed: bool = True):
        return self._request("DELETE", path, params, signed)

    def sync_time(self) -> int:
        """同步 Binance server time，返回本地 timestamp 应增加的毫秒偏移。"""
        data = self._request("GET", "/fapi/v1/time", signed=False)
        server_time = int(data["serverTime"])
        local_time = int(time.time() * 1000)
        self._time_offset_ms = server_time - local_time
        return self._time_offset_ms

    # ── 交易信息 ─────────────────────────────────────────

    def _load_exchange_info(self) -> dict:
        if self._exchange_info is None:
            data = self._get("/fapi/v1/exchangeInfo")
            self._exchange_info = {
                s["symbol"]: s for s in data.get("symbols", [])
            }
        return self._exchange_info

    def get_symbol_rules(self, symbol: str) -> SymbolRules:
        """获取合约下单规则；testnet 无 TradFi 合约时用保守默认值。"""
        info = self._load_exchange_info()
        sym_info = info.get(symbol)
        if sym_info is None:
            return SymbolRules(
                quantity_precision=3,
                price_precision=2,
                step_size=Decimal("0.001"),
                min_qty=Decimal("0.001"),
                min_notional=Decimal("5"),
            )

        lot_filter = next(
            (f for f in sym_info.get("filters", []) if f.get("filterType") == "LOT_SIZE"),
            {},
        )
        notional_filter = next(
            (f for f in sym_info.get("filters", []) if f.get("filterType") in {"MIN_NOTIONAL", "NOTIONAL"}),
            {},
        )
        return SymbolRules(
            quantity_precision=int(sym_info.get("quantityPrecision", 3)),
            price_precision=int(sym_info.get("pricePrecision", 2)),
            step_size=Decimal(str(lot_filter.get("stepSize", "0.001"))),
            min_qty=Decimal(str(lot_filter.get("minQty", "0.001"))),
            min_notional=Decimal(str(notional_filter.get("notional", notional_filter.get("minNotional", "5")))),
        )

    def _format_quantity(self, symbol: str, quantity: float | Decimal) -> str:
        rules = self.get_symbol_rules(symbol)
        qty = Decimal(str(quantity))
        if rules.step_size > 0:
            qty = (qty / rules.step_size).to_integral_value(rounding=ROUND_DOWN) * rules.step_size
        quantized = qty.quantize(Decimal(1).scaleb(-rules.quantity_precision), rounding=ROUND_DOWN)
        return format(quantized.normalize(), "f")

    def _get_price_precision(self, symbol: str) -> int:
        """获取合约价格精度"""
        return self.get_symbol_rules(symbol).price_precision

    # ── 市场数据 ─────────────────────────────────────────

    def get_mark_price(self, symbol: str) -> float:
        """获取标记价格（Testnet 不支持 TradFi 合约时自动回退到生产公开接口）"""
        try:
            data = self._get("/fapi/v1/premiumIndex", {"symbol": symbol})
            return float(data["markPrice"])
        except RuntimeError:
            # Testnet 可能不支持该合约，用生产公开 API 兜底
            import requests as _req
            resp = _req.get(
                f"https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": symbol}, timeout=10,
            )
            resp.raise_for_status()
            return float(resp.json()["markPrice"])

    def get_ticker_price(self, symbol: str) -> float:
        """获取最新成交价"""
        data = self._get("/fapi/v1/ticker/price", {"symbol": symbol})
        return float(data["price"])

    # ── 账户 ─────────────────────────────────────────────

    def get_account(self) -> dict:
        """查询账户信息（余额、仓位等）"""
        return self._get("/fapi/v3/account", signed=True)

    def get_balance(self) -> dict:
        """简化的余额查询"""
        account = self.get_account()
        return {
            "total_wallet_balance": float(account.get("totalWalletBalance", 0)),
            "available_balance": float(account.get("availableBalance", 0)),
            "total_unrealized_profit": float(account.get("totalUnrealizedProfit", 0)),
            "total_margin_balance": float(account.get("totalMarginBalance", 0)),
        }

    def get_positions(self, symbol: str | None = None) -> list[dict]:
        """查询当前持仓"""
        params: dict = {}
        if symbol:
            params["symbol"] = symbol
        data = self._get("/fapi/v3/positionRisk", params=params, signed=True)
        # 只返回有仓位的
        return [
            p for p in data
            if float(p.get("positionAmt", 0)) != 0
        ]

    # ── 杠杆 ─────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int = 5) -> dict:
        """设置初始杠杆"""
        return self._post("/fapi/v1/leverage", {
            "symbol": symbol,
            "leverage": leverage,
        })

    # ── 下单 ─────────────────────────────────────────────

    def _calc_quantity(self, symbol: str, notional_usd: float) -> float:
        """根据名义本金和标记价格计算下单数量"""
        price = self.get_mark_price(symbol)
        if price <= 0 or not math.isfinite(price):
            raise ValueError(f"{symbol} 标记价格无效: {price}")
        rules = self.get_symbol_rules(symbol)
        raw_qty = Decimal(str(notional_usd)) / Decimal(str(price))
        quantity = Decimal(self._format_quantity(symbol, raw_qty))
        if quantity < rules.min_qty:
            return 0.0
        if rules.min_notional > 0 and quantity * Decimal(str(price)) < rules.min_notional:
            return 0.0
        return float(quantity)

    def open_position(
        self,
        symbol: str,
        direction: int,
        notional_usd: float,
        leverage: int = 5,
        dry_run: bool = True,
    ) -> BinanceFill | None:
        """
        开仓永续合约。

        Args:
            symbol:        如 "SPYUSDT"
            direction:     +1 = 正费率→做空(SELL)；-1 = 负费率→做多(BUY)
            notional_usd:  名义本金（美元）
            leverage:      杠杆倍数
            dry_run:       True 时仅打印，不实际下单

        Returns:
            BinanceFill 或 None（dry_run 时）
        """
        # direction=+1 → 做空永续收取正费率
        # direction=-1 → 做多永续收取负费率
        side = "SELL" if direction > 0 else "BUY"
        quantity = self._calc_quantity(symbol, notional_usd)

        if quantity <= 0:
            if dry_run:
                quantity = round(notional_usd / 100, 3)  # dry_run 兜底
            else:
                raise ValueError(f"{symbol} 计算出的下单数量为 0，notional={notional_usd}")

        label = symbol.replace("USDT", "")
        print(f"[{'DRY RUN' if dry_run else 'LIVE'}] Binance {label}  "
              f"side={side}  qty={quantity}  leverage={leverage}x  "
              f"notional={notional_usd:,.0f}")

        if dry_run:
            return BinanceFill(
                symbol=symbol,
                side=side,
                quantity=quantity,
                avg_price=0.0,
                order_id=0,
                status="DRY_RUN",
            )

        # 设置杠杆
        self.set_leverage(symbol, leverage)

        # 市价开仓
        resp = self._post("/fapi/v1/order", {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": self._format_quantity(symbol, quantity),
            "newOrderRespType": "RESULT",
        })

        avg_price = float(resp.get("avgPrice", 0))
        if avg_price == 0:
            avg_price = float(resp.get("price", 0))

        fill = BinanceFill(
            symbol=symbol,
            side=side,
            quantity=float(resp.get("executedQty", quantity)),
            avg_price=avg_price,
            order_id=int(resp.get("orderId", 0)),
            status=resp.get("status", "UNKNOWN"),
        )
        print(f"  ✅ Binance 成交: orderId={fill.order_id}  "
              f"qty={fill.quantity}  avgPrice={fill.avg_price}  "
              f"status={fill.status}")
        return fill

    def close_position(
        self,
        symbol: str,
        dry_run: bool = True,
        position_amt: float | None = None,
    ) -> BinanceFill | None:
        """
        平仓指定合约的全部仓位。

        通过查询当前仓位反向下单实现。
        """
        if position_amt is None:
            try:
                positions = self.get_positions(symbol)
            except RuntimeError:
                if dry_run:
                    positions = []
                else:
                    raise
            if not positions:
                if dry_run:
                    print(f"[DRY RUN] Binance 平仓 {symbol}  qty=UNKNOWN（未查询到线上仓位）")
                    return BinanceFill(
                        symbol=symbol,
                        side="UNKNOWN",
                        quantity=0.0,
                        avg_price=0.0,
                        order_id=0,
                        status="DRY_RUN",
                    )
                print(f"  Binance {symbol} 无持仓，跳过平仓")
                return None
            pos_amt = float(positions[0].get("positionAmt", 0))
        else:
            pos_amt = float(position_amt)

        if pos_amt == 0:
            print(f"  Binance {symbol} 持仓为 0，跳过平仓")
            return None

        # 反向平仓
        close_side = "SELL" if pos_amt > 0 else "BUY"
        close_qty = abs(pos_amt)
        close_qty_str = self._format_quantity(symbol, close_qty)

        label = symbol.replace("USDT", "")
        print(f"[{'DRY RUN' if dry_run else 'LIVE'}] Binance 平仓 {label}  "
              f"side={close_side}  qty={close_qty_str}")

        if dry_run:
            return BinanceFill(
                symbol=symbol,
                side=close_side,
                quantity=float(close_qty_str),
                avg_price=0.0,
                order_id=0,
                status="DRY_RUN",
            )

        resp = self._post("/fapi/v1/order", {
            "symbol": symbol,
            "side": close_side,
            "type": "MARKET",
            "quantity": close_qty_str,
            "reduceOnly": "true",
            "newOrderRespType": "RESULT",
        })

        avg_price = float(resp.get("avgPrice", 0))
        fill = BinanceFill(
            symbol=symbol,
            side=close_side,
            quantity=float(resp.get("executedQty", close_qty)),
            avg_price=avg_price,
            order_id=int(resp.get("orderId", 0)),
            status=resp.get("status", "UNKNOWN"),
        )
        print(f"  ✅ Binance 平仓成交: orderId={fill.order_id}  "
              f"qty={fill.quantity}  avgPrice={fill.avg_price}")
        return fill

    def close(self) -> None:
        """关闭 HTTP session"""
        self.session.close()
