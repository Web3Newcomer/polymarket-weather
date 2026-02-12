"""REST API 客户端"""
import asyncio
import json
import logging
import aiohttp
from decimal import Decimal
from typing import List, Dict, Any, Optional

from ..config import APIConfig
from ..models.market import Market, Outcome, MarketType

logger = logging.getLogger(__name__)


class RESTClient:
    """Polymarket REST API 客户端"""

    def __init__(self, config: APIConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._timeout = aiohttp.ClientTimeout(total=60, connect=30)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_markets(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """获取活跃市场列表（带重试）"""
        session = await self._get_session()
        url = f"{self.config.gamma_url}/markets"
        params = {"limit": limit, "offset": offset, "active": "true", "closed": "false"}

        for attempt in range(3):
            try:
                async with session.get(url, params=params) as resp:
                    return await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"API request failed (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    await asyncio.sleep(5)
        return []

    async def get_markets_raw(self, limit: int = 100, pages: int = 10) -> List[Dict[str, Any]]:
        """获取原始市场数据（用于筛选）"""
        all_markets = []
        for page in range(pages):
            offset = page * limit
            data = await self.get_markets(limit, offset)
            if not data:
                break
            all_markets.extend(data)
        return all_markets

    async def get_events_by_tag(self, tag_slug: str, limit: int = 50) -> List[Dict[str, Any]]:
        """通过 tag_slug 获取事件列表（含内嵌市场数据）"""
        session = await self._get_session()
        url = f"{self.config.gamma_url}/events"
        all_events = []

        for offset in range(0, 500, limit):
            params = {
                "limit": limit, "offset": offset,
                "active": "true", "closed": "false",
                "tag_slug": tag_slug,
            }
            for attempt in range(3):
                try:
                    async with session.get(url, params=params) as resp:
                        data = await resp.json()
                        break
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(f"Events API failed (attempt {attempt + 1}/3): {e}")
                    if attempt < 2:
                        await asyncio.sleep(5)
                    data = []

            if not data:
                break
            all_events.extend(data)

        return all_events

    async def get_market_prices(self, token_id: str) -> Dict[str, Any]:
        """获取市场价格"""
        session = await self._get_session()
        url = f"{self.config.rest_url}/prices"
        params = {"token_id": token_id}

        async with session.get(url, params=params) as resp:
            return await resp.json()

    def parse_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """解析市场数据为 Market 对象"""
        try:
            # 解析 JSON 字符串
            outcomes_str = data.get("outcomes", "[]")
            prices_str = data.get("outcomePrices", "[]")
            tokens_str = data.get("clobTokenIds", "[]")

            outcome_names = json.loads(outcomes_str)
            prices = json.loads(prices_str)
            token_ids = json.loads(tokens_str)

            # 跳过无效数据
            if len(outcome_names) != len(prices):
                return None
            if len(token_ids) != len(outcome_names):
                return None

            # 构建 outcomes
            outcomes = []
            for i, name in enumerate(outcome_names):
                price = Decimal(str(prices[i])) if prices[i] else Decimal("0")
                outcomes.append(Outcome(
                    token_id=token_ids[i],
                    name=name,
                    price=price
                ))

            if len(outcomes) == 2:
                market_type = MarketType.BINARY
            else:
                market_type = MarketType.MULTI_OUTCOME

            return Market(
                condition_id=data.get("conditionId", ""),
                question=data.get("question", ""),
                outcomes=outcomes,
                market_type=market_type,
                slug=data.get("slug", ""),
                event_slug=self._get_event_slug(data),
                active=data.get("active", True)
            )
        except Exception:
            return None

    def _get_event_slug(self, data: Dict[str, Any]) -> str:
        """从 events 字段提取 event_slug"""
        events = data.get("events", [])
        if events and isinstance(events, list):
            return events[0].get("slug", "")
        return ""
