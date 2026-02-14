"""订单管理器"""
import logging
from decimal import Decimal
from dataclasses import dataclass

from ..config import Config
from .clob_client import ClobClient

logger = logging.getLogger(__name__)


@dataclass
class WeatherTradeResult:
    """天气交易执行结果"""
    success: bool
    shares: Decimal = Decimal("0")    # 成交份额
    avg_price: Decimal = Decimal("0")  # 成交均价
    error: str = ""
    order_id: str = ""                # 限价单 order ID


class OrderManager:
    """订单管理器"""

    def __init__(self, config: Config):
        self.config = config
        self.dry_run = config.dry_run
        self.clob = ClobClient(
            api_key=config.api.api_key,
            api_secret=config.api.api_secret,
            passphrase=config.api.passphrase,
            funder_address=config.api.funder_address
        )

    async def execute_weather_buy(
        self, token_id: str, amount: Decimal, price: Decimal = Decimal("0")
    ) -> WeatherTradeResult:
        """执行天气策略买入（限价 GTC 挂单）

        Args:
            token_id: YES token ID
            amount: 买入金额 USD
            price: 限价（来自扫描时的 CLOB 买价）
        """
        if self.dry_run:
            try:
                if price <= 0:
                    price_data = await self.clob.get_price(token_id, side="buy")
                    price = Decimal(str(price_data.get("price", "0.10")))
                shares = amount / price if price > 0 else Decimal("0")
                logger.info(
                    f"[DRY RUN] Weather BUY: {shares:.2f} shares @ ${price}"
                )
                return WeatherTradeResult(
                    success=True, shares=shares, avg_price=price
                )
            except Exception as e:
                logger.warning(f"[DRY RUN] Price fetch failed: {e}, using estimate")
                return WeatherTradeResult(
                    success=True,
                    shares=amount / Decimal("0.10"),
                    avg_price=Decimal("0.10"),
                )

        # 真实执行：限价 GTC 挂单
        if price <= 0:
            price_data = await self.clob.get_price(token_id, side="buy")
            price = Decimal(str(price_data.get("price", "0")))
            if price <= 0:
                return WeatherTradeResult(success=False, error="Cannot determine price")

        shares = amount / price
        result = await self.clob.place_order(
            token_id=token_id, side="BUY", price=price, size=shares, order_type="GTC"
        )
        if result.success:
            logger.info(
                f"Weather BUY limit order placed: {shares:.2f} shares @ ${price} (order: {result.order_id})"
            )
            return WeatherTradeResult(
                success=True,
                shares=shares,
                avg_price=price,
                order_id=result.order_id,
            )
        logger.error(f"Weather BUY failed: {result.error}")
        return WeatherTradeResult(success=False, error=result.error or "Unknown")

    async def execute_weather_sell(
        self, token_id: str, shares: Decimal, price: Decimal = Decimal("0")
    ) -> WeatherTradeResult:
        """执行天气策略卖出（限价 GTC 挂单）

        Args:
            token_id: YES token ID
            shares: 卖出份额
            price: 限价（来自当前市场价格）
        """
        if self.dry_run:
            try:
                if price <= 0:
                    price_data = await self.clob.get_price(token_id, side="sell")
                    price = Decimal(str(price_data.get("price", "0.50")))
                logger.info(
                    f"[DRY RUN] Weather SELL: {shares:.2f} shares @ ${price}"
                )
                return WeatherTradeResult(
                    success=True, shares=shares, avg_price=price
                )
            except Exception as e:
                logger.warning(f"[DRY RUN] Price fetch failed: {e}, using estimate")
                return WeatherTradeResult(
                    success=True, shares=shares, avg_price=Decimal("0.50")
                )

        # 真实执行：限价 GTC 挂单
        if price <= 0:
            price_data = await self.clob.get_price(token_id, side="sell")
            price = Decimal(str(price_data.get("price", "0")))
            if price <= 0:
                return WeatherTradeResult(success=False, error="Cannot determine price")

        result = await self.clob.place_order(
            token_id=token_id, side="SELL", price=price, size=shares, order_type="GTC"
        )
        if result.success:
            logger.info(
                f"Weather SELL limit order placed: {shares:.2f} shares @ ${price} (order: {result.order_id})"
            )
            return WeatherTradeResult(
                success=True,
                shares=shares,
                avg_price=price,
                order_id=result.order_id,
            )
        logger.error(f"Weather SELL failed: {result.error}")
        return WeatherTradeResult(success=False, error=result.error or "Unknown")

    async def close(self):
        """关闭客户端连接"""
        await self.clob.close()
