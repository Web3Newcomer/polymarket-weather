"""持仓跟踪器测试"""
import pytest
from decimal import Decimal

from src.execution.position_tracker import PositionTracker


@pytest.fixture
def tracker():
    return PositionTracker()


def test_add_position(tracker):
    """测试添加持仓"""
    tracker.add_position(
        market_id="market-1",
        slug="test-market",
        yes_shares=Decimal("10"),
        no_shares=Decimal("10"),
        cost=Decimal("9.7")
    )
    
    pos = tracker.get_position("market-1")
    assert pos is not None
    assert pos.yes_shares == Decimal("10")
    assert pos.no_shares == Decimal("10")
    assert pos.cost_basis == Decimal("9.7")


def test_accumulate_position(tracker):
    """测试累加持仓"""
    tracker.add_position("market-1", "test", Decimal("5"), Decimal("5"), Decimal("5"))
    tracker.add_position("market-1", "test", Decimal("5"), Decimal("5"), Decimal("5"))

    pos = tracker.get_position("market-1")
    assert pos.yes_shares == Decimal("10")
    assert pos.cost_basis == Decimal("10")


def test_record_trade(tracker):
    """测试记录交易"""
    tracker.record_trade("market-1", "YES", Decimal("0.45"), Decimal("10"))
    summary = tracker.get_summary()
    assert summary["trades"] == 1


def test_get_total_cost(tracker):
    """测试获取总成本"""
    tracker.add_position("m1", "s1", Decimal("1"), Decimal("1"), Decimal("10"))
    tracker.add_position("m2", "s2", Decimal("1"), Decimal("1"), Decimal("20"))
    assert tracker.get_total_cost() == Decimal("30")
