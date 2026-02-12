"""风险管理器"""
import logging
from decimal import Decimal
from typing import Dict, Set

from ..config import RiskConfig

logger = logging.getLogger(__name__)


class RiskManager:
    """风险管理器"""

    def __init__(self, config: RiskConfig):
        self.config = config
        self._total_exposure = Decimal("0")
        self._market_exposures: Dict[str, Decimal] = {}
        self._active_markets: Set[str] = set()

    def add_exposure(self, market_id: str, amount: Decimal):
        """增加敞口"""
        self._total_exposure += amount
        current = self._market_exposures.get(market_id, Decimal("0"))
        self._market_exposures[market_id] = current + amount
        self._active_markets.add(market_id)

    def remove_exposure(self, market_id: str, amount: Decimal):
        """减少敞口"""
        self._total_exposure = max(Decimal("0"), self._total_exposure - amount)
        if market_id in self._market_exposures:
            new_val = self._market_exposures[market_id] - amount
            if new_val <= 0:
                del self._market_exposures[market_id]
                self._active_markets.discard(market_id)
            else:
                self._market_exposures[market_id] = new_val

    def get_total_exposure(self) -> Decimal:
        """获取总敞口"""
        return self._total_exposure

    def get_market_exposure(self, market_id: str) -> Decimal:
        """获取单市场敞口"""
        return self._market_exposures.get(market_id, Decimal("0"))

    def get_stats(self) -> dict:
        """获取风险统计"""
        return {
            "total_exposure": self._total_exposure,
            "active_markets": len(self._active_markets),
        }
