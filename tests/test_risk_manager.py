"""风险管理器测试"""
import pytest
from decimal import Decimal

from src.config import RiskConfig
from src.execution.risk_manager import RiskManager


@pytest.fixture
def risk_manager():
    config = RiskConfig(
        min_profit_threshold=Decimal("0.005"),
        max_position_per_market=Decimal("100"),
        max_total_exposure=Decimal("1000"),
        order_size=Decimal("10")
    )
    return RiskManager(config)


def test_exposure_tracking(risk_manager):
    """测试敞口跟踪"""
    risk_manager.add_exposure("market-1", Decimal("50"))
    assert risk_manager.get_total_exposure() == Decimal("50")
    assert risk_manager.get_market_exposure("market-1") == Decimal("50")


def test_remove_exposure(risk_manager):
    """测试减少敞口"""
    risk_manager.add_exposure("market-1", Decimal("100"))
    risk_manager.remove_exposure("market-1", Decimal("30"))
    assert risk_manager.get_market_exposure("market-1") == Decimal("70")


def test_remove_exposure_clears_market(risk_manager):
    """测试敞口清零后移除市场"""
    risk_manager.add_exposure("market-1", Decimal("50"))
    risk_manager.remove_exposure("market-1", Decimal("50"))
    assert risk_manager.get_market_exposure("market-1") == Decimal("0")
    assert risk_manager.get_stats()["active_markets"] == 0


def test_stats(risk_manager):
    """测试统计"""
    risk_manager.add_exposure("m1", Decimal("10"))
    risk_manager.add_exposure("m2", Decimal("20"))
    stats = risk_manager.get_stats()
    assert stats["total_exposure"] == Decimal("30")
    assert stats["active_markets"] == 2
