"""市场数据聚合器"""
import logging
from typing import Dict, List, Optional, Tuple

from ..config import APIConfig
from ..models.market import Market, Outcome
from .rest_client import RESTClient

logger = logging.getLogger(__name__)


class MarketFeed:
    """市场数据聚合器"""

    def __init__(self, config: APIConfig):
        self.config = config
        self.rest_client = RESTClient(config)
        self._markets: Dict[str, Market] = {}
        self._token_to_market: Dict[str, Tuple[Market, Outcome]] = {}

    def get_all_markets(self) -> List[Market]:
        """获取所有市场"""
        return list(self._markets.values())

    def get_market(self, condition_id: str) -> Optional[Market]:
        """获取单个市场"""
        return self._markets.get(condition_id)

    async def refresh_weather_markets(self) -> int:
        """通过 events API 高效加载天气市场"""
        try:
            events = await self.rest_client.get_events_by_tag("weather")
            if not events:
                return 0

            self._markets.clear()
            self._token_to_market.clear()
            count = 0
            for event in events:
                event_slug = event.get("slug", "")
                for item in event.get("markets", []):
                    market = self.rest_client.parse_market(item)
                    if market:
                        # 从 event 层传入 slug（市场内嵌数据没有 events 字段）
                        if not market.event_slug and event_slug:
                            market.event_slug = event_slug
                        self._markets[market.condition_id] = market
                        for outcome in market.outcomes:
                            self._token_to_market[outcome.token_id] = (market, outcome)
                        count += 1

            logger.info(f"Loaded {count} weather markets from {len(events)} events")
            return count
        except Exception as e:
            logger.error(f"Failed to refresh weather markets: {e}")
            return 0

    async def close(self):
        """关闭连接"""
        await self.rest_client.close()
