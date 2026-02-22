"""天气策略入场过滤测试"""
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from src.config import WeatherConfig
from src.strategy.weather import WeatherStrategy
from src.data.noaa_feed import NOAAFeed
from src.models.market import Market, Outcome, MarketType


def _make_config(**overrides) -> WeatherConfig:
    defaults = dict(
        enabled=True, locations=["NYC"],
        entry_threshold=0.25, min_entry_price=0.05,
        min_hours_to_resolution=2,
    )
    defaults.update(overrides)
    return WeatherConfig(**defaults)


def _make_market(date_str: str, low: int, high: int, yes_price: float) -> Market:
    bucket = f"{low}-{high}°F" if high < 999 else f"{low}°F or higher"
    question = f"Will the highest temperature at NYC on {date_str} be {bucket}?"
    return Market(
        condition_id="cond-1",
        question=question,
        outcomes=[Outcome(token_id="tok-yes", name="Yes", price=Decimal(str(yes_price)))],
        market_type=MarketType.BINARY,
        slug="test-market",
        event_slug="test-event",
    )


class FakeNOAA:
    """伪造 NOAA feed"""
    def __init__(self, temp: int):
        self.temp = temp

    async def get_forecast(self, location):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        return {tomorrow: {"high": self.temp, "low": self.temp - 10}}


def _tomorrow_str() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


def _tomorrow_month_day() -> str:
    d = datetime.now(timezone.utc) + timedelta(days=1)
    return d.strftime("%B %d").replace(" 0", " ")


@pytest.mark.asyncio
async def test_min_entry_price_blocks_cheap():
    """价格低于 min_entry_price 不开仓"""
    config = _make_config(min_entry_price=0.05, entry_threshold=0.25)
    strategy = WeatherStrategy(config, FakeNOAA(50))

    date_label = _tomorrow_month_day()
    date_str = _tomorrow_str()
    market = Market(
        condition_id="cond-1",
        question=f"Will the highest temperature at NYC on {date_label} be 45-55°F?",
        outcomes=[Outcome(token_id="tok-yes", name="Yes", price=Decimal("0.03"))],
        market_type=MarketType.BINARY, slug="s", event_slug="e",
    )
    signals = await strategy.scan_entries([market])
    assert len(signals) == 0


@pytest.mark.asyncio
async def test_min_entry_price_allows_normal():
    """价格高于 min_entry_price 且低于 entry_threshold 正常开仓"""
    config = _make_config(min_entry_price=0.05, entry_threshold=0.25)
    strategy = WeatherStrategy(config, FakeNOAA(50))

    date_label = _tomorrow_month_day()
    market = Market(
        condition_id="cond-1",
        question=f"Will the highest temperature at NYC on {date_label} be 45-55°F?",
        outcomes=[Outcome(token_id="tok-yes", name="Yes", price=Decimal("0.10"))],
        market_type=MarketType.BINARY, slug="s", event_slug="e",
    )
    signals = await strategy.scan_entries([market])
    assert len(signals) == 1
    assert signals[0].action == "BUY"


@pytest.mark.asyncio
async def test_resolution_too_close_blocks():
    """距结算时间不足 min_hours 不开仓"""
    config = _make_config(min_hours_to_resolution=48)
    strategy = WeatherStrategy(config, FakeNOAA(50))

    date_label = _tomorrow_month_day()
    market = Market(
        condition_id="cond-1",
        question=f"Will the highest temperature at NYC on {date_label} be 45-55°F?",
        outcomes=[Outcome(token_id="tok-yes", name="Yes", price=Decimal("0.10"))],
        market_type=MarketType.BINARY, slug="s", event_slug="e",
    )
    signals = await strategy.scan_entries([market])
    assert len(signals) == 0


@pytest.mark.asyncio
async def test_resolution_far_enough_allows():
    """距结算时间充足正常开仓"""
    config = _make_config(min_hours_to_resolution=2)
    strategy = WeatherStrategy(config, FakeNOAA(50))

    date_label = _tomorrow_month_day()
    market = Market(
        condition_id="cond-1",
        question=f"Will the highest temperature at NYC on {date_label} be 45-55°F?",
        outcomes=[Outcome(token_id="tok-yes", name="Yes", price=Decimal("0.10"))],
        market_type=MarketType.BINARY, slug="s", event_slug="e",
    )
    signals = await strategy.scan_entries([market])
    assert len(signals) == 1
