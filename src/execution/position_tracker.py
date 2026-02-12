"""持仓跟踪器"""
import logging
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """单个持仓"""
    market_id: str
    market_slug: str
    yes_shares: Decimal = Decimal("0")
    no_shares: Decimal = Decimal("0")
    cost_basis: Decimal = Decimal("0")
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Trade:
    """交易记录"""
    market_id: str
    side: str
    price: Decimal
    size: Decimal
    timestamp: datetime = field(default_factory=datetime.now)


class PositionTracker:
    """持仓跟踪器"""

    def __init__(self):
        self._positions: Dict[str, Position] = {}
        self._trades: List[Trade] = []
        self._total_pnl = Decimal("0")

    def add_position(self, market_id: str, slug: str,
                     yes_shares: Decimal, no_shares: Decimal,
                     cost: Decimal):
        """添加持仓"""
        if market_id in self._positions:
            pos = self._positions[market_id]
            pos.yes_shares += yes_shares
            pos.no_shares += no_shares
            pos.cost_basis += cost
        else:
            self._positions[market_id] = Position(
                market_id=market_id,
                market_slug=slug,
                yes_shares=yes_shares,
                no_shares=no_shares,
                cost_basis=cost
            )
        logger.info(f"Position added: {slug}")

    def record_trade(self, market_id: str, side: str,
                     price: Decimal, size: Decimal):
        """记录交易"""
        trade = Trade(
            market_id=market_id,
            side=side,
            price=price,
            size=size
        )
        self._trades.append(trade)

    def get_position(self, market_id: str) -> Position:
        """获取持仓"""
        return self._positions.get(market_id)

    def get_all_positions(self) -> List[Position]:
        """获取所有持仓"""
        return list(self._positions.values())

    def get_total_cost(self) -> Decimal:
        """获取总成本"""
        return sum(p.cost_basis for p in self._positions.values())

    def get_summary(self) -> dict:
        """获取统计摘要"""
        return {
            "positions": len(self._positions),
            "trades": len(self._trades),
            "total_cost": self.get_total_cost()
        }
