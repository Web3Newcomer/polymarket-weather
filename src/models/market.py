"""市场数据模型"""
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import List, Optional


class MarketType(Enum):
    """市场类型"""
    BINARY = "binary"
    MULTI_OUTCOME = "multi"


@dataclass
class Outcome:
    """市场结果选项"""
    token_id: str
    name: str
    price: Decimal

    @property
    def is_yes(self) -> bool:
        return self._normalized_name == "YES"

    @property
    def is_no(self) -> bool:
        return self._normalized_name == "NO"

    @property
    def _normalized_name(self) -> str:
        return self.name.strip().upper()


@dataclass
class Market:
    """市场模型"""
    condition_id: str
    question: str
    outcomes: List[Outcome]
    market_type: MarketType
    slug: str = ""
    event_slug: str = ""
    active: bool = True

    @property
    def is_binary(self) -> bool:
        return self.market_type == MarketType.BINARY

    @property
    def total_price(self) -> Decimal:
        """所有选项价格总和"""
        return sum(o.price for o in self.outcomes)

    @property
    def url(self) -> str:
        """市场链接: /event/{event_slug}/{slug}"""
        if self.event_slug:
            return f"https://polymarket.com/event/{self.event_slug}/{self.slug}"
        return f"https://polymarket.com/event/{self.slug}"

    def get_yes_outcome(self) -> Optional[Outcome]:
        """返回 YES outcome（若存在）"""
        for outcome in self.outcomes:
            if outcome.is_yes:
                return outcome
        # 少数市场可能没有明确 YES，按价格最高的 outcome 推测
        if self.is_binary and self.outcomes:
            return max(self.outcomes, key=lambda o: o.price)
        return None

    def get_no_outcome(self) -> Optional[Outcome]:
        """返回 NO outcome（若存在）"""
        for outcome in self.outcomes:
            if outcome.is_no:
                return outcome

        if self.is_binary and len(self.outcomes) == 2:
            yes = self.get_yes_outcome()
            if yes:
                for outcome in self.outcomes:
                    if outcome is not yes:
                        return outcome
            return self.outcomes[0]
        return None

    def get_outcome_by_token(self, token_id: str) -> Optional[Outcome]:
        """根据 token_id 查找 outcome"""
        for outcome in self.outcomes:
            if outcome.token_id == token_id:
                return outcome
        return None
