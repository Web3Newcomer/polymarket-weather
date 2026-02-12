"""风险管理器测试"""
import pytest
from decimal import Decimal

from src.config import RiskConfig
from src.models.market import Market, Outcome, MarketType
from src.models.signal import ArbitrageSignal
from src.execution.risk_manager import RiskManager


@pytest.fixture
def risk_config():
    return RiskConfig(
        min_profit_threshold=Decimal("0.005"),
        max_position_per_market=Decimal("100"),
        max_total_exposure=Decimal("1000"),
        order_size=Decimal("10")
    )


@pytest.fixture
def risk_manager(risk_config):
    return RiskManager(risk_config)


@pytest.fixture
def valid_signal():
    market = Market(
        condition_id="test-market",
        question="Test?",
        outcomes=[
            Outcome(token_id="yes", name="Yes", price=Decimal("0.45")),
            Outcome(token_id="no", name="No", price=Decimal("0.52")),
        ],
        market_type=MarketType.BINARY,
        slug="test-market",
        active=True
    )
    return ArbitrageSignal(
        market=market,
        strategy_name="binary_completeness",
        expected_profit=Decimal("0.03"),
        total_cost=Decimal("0.97"),
        orders=[]
    )


def test_validate_signal_approved(risk_manager, valid_signal):
    """测试有效信号通过验证"""
    assert risk_manager.validate_signal(valid_signal) is True


def test_reject_low_profit(risk_manager, valid_signal):
    """测试低利润信号被拒绝"""
    valid_signal.expected_profit = Decimal("0.001")
    assert risk_manager.validate_signal(valid_signal) is False


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


def test_stats_tracking(risk_manager, valid_signal):
    """测试统计跟踪"""
    risk_manager.validate_signal(valid_signal)
    stats = risk_manager.get_stats()
    assert stats["signals_received"] == 1
    assert stats["signals_approved"] == 1
