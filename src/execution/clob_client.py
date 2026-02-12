"""Polymarket CLOB API 客户端"""
import hashlib
import hmac
import time
import json
import logging
from decimal import Decimal
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

# Polymarket CLOB API 端点
CLOB_HOST = "https://clob.polymarket.com"


@dataclass
class OrderResult:
    """订单执行结果"""
    success: bool
    order_id: Optional[str] = None
    error: Optional[str] = None
    filled_size: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")


class ClobClient:
    """Polymarket CLOB API 客户端"""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        funder_address: str = ""
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.funder_address = funder_address
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _create_signature(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """创建 API 签名"""
        message = timestamp + method + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _get_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """获取认证请求头"""
        timestamp = str(int(time.time()))
        signature = self._create_signature(timestamp, method, path, body)
        return {
            "POLY_API_KEY": self.api_key,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": timestamp,
            "POLY_PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    async def get_server_time(self) -> int:
        """获取服务器时间"""
        session = await self._get_session()
        async with session.get(f"{CLOB_HOST}/time") as resp:
            return int(await resp.text())

    async def get_price(self, token_id: str, side: str = "buy") -> Dict[str, Any]:
        """获取代币价格"""
        session = await self._get_session()
        url = f"{CLOB_HOST}/price"
        params = {"token_id": token_id, "side": side}
        async with session.get(url, params=params) as resp:
            return await resp.json()

    async def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """获取订单簿"""
        session = await self._get_session()
        url = f"{CLOB_HOST}/book"
        params = {"token_id": token_id}
        async with session.get(url, params=params) as resp:
            return await resp.json()

    async def place_order(
        self,
        token_id: str,
        side: str,
        price: Decimal,
        size: Decimal,
        order_type: str = "GTC"
    ) -> OrderResult:
        """下单"""
        if not self.api_key:
            logger.error("API key not configured")
            return OrderResult(success=False, error="API key not configured")

        path = "/order"
        body = json.dumps({
            "tokenID": token_id,
            "side": side.upper(),
            "price": str(price),
            "size": str(size),
            "type": order_type,
            "funderAddress": self.funder_address or None
        })

        try:
            session = await self._get_session()
            headers = self._get_headers("POST", path, body)

            async with session.post(
                f"{CLOB_HOST}{path}",
                headers=headers,
                data=body
            ) as resp:
                data = await resp.json()

                if resp.status == 200:
                    logger.info(f"Order placed: {data.get('orderID')}")
                    return OrderResult(
                        success=True,
                        order_id=data.get("orderID"),
                        filled_size=Decimal(str(data.get("filledSize", 0)))
                    )
                else:
                    error = data.get("error", "Unknown error")
                    logger.error(f"Order failed: {error}")
                    return OrderResult(success=False, error=error)

        except Exception as e:
            logger.error(f"Order exception: {e}")
            return OrderResult(success=False, error=str(e))

    async def place_market_order(
        self,
        token_id: str,
        side: str,
        size: Decimal
    ) -> OrderResult:
        """市价单"""
        # 获取当前最优价格
        orderbook = await self.get_orderbook(token_id)

        if side.upper() == "BUY":
            asks = orderbook.get("asks", [])
            if not asks:
                return OrderResult(success=False, error="No asks available")
            price = Decimal(str(asks[0]["price"]))
        else:
            bids = orderbook.get("bids", [])
            if not bids:
                return OrderResult(success=False, error="No bids available")
            price = Decimal(str(bids[0]["price"]))

        return await self.place_order(token_id, side, price, size, "FOK")

    async def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        if not self.api_key:
            return False

        path = f"/order/{order_id}"
        try:
            session = await self._get_session()
            headers = self._get_headers("DELETE", path)

            async with session.delete(
                f"{CLOB_HOST}{path}",
                headers=headers
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            return False
