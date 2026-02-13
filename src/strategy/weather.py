"""天气交易策略"""
import asyncio
import re
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Tuple, Callable, Awaitable

from ..config import WeatherConfig
from ..data.noaa_feed import NOAAFeed
from ..models.market import Market

logger = logging.getLogger(__name__)


WEATHER_KEYWORDS = [
    "temperature", "°f", "highest temp", "lowest temp",
    "high temp", "low temp", "weather",
]

LOCATION_ALIASES = {
    "nyc": "NYC", "new york": "NYC", "laguardia": "NYC", "la guardia": "NYC",
    "chicago": "Chicago", "o'hare": "Chicago", "ohare": "Chicago",
    "seattle": "Seattle", "sea-tac": "Seattle",
    "atlanta": "Atlanta", "hartsfield": "Atlanta",
    "dallas": "Dallas", "dfw": "Dallas",
    "miami": "Miami",
}


@dataclass
class WeatherSignal:
    """天气交易信号"""
    market_id: str           # condition_id
    token_id: str            # YES token_id（用于下单）
    action: str              # "BUY" 或 "SELL"
    price: Decimal           # 当前 YES 价格
    amount: Decimal          # 交易金额 USD
    location: str            # 城市
    date: str                # 预报日期
    forecast_temp: int       # NOAA 预报温度
    bucket_name: str         # 匹配的温度区间名
    reasoning: str           # 交易理由
    exit_type: str = ""      # "take_profit" | "stop_loss" | "exit_threshold" | ""
    market_url: str = ""     # 市场链接
    market_question: str = ""  # 市场问题


@dataclass
class WeatherPosition:
    """天气持仓记录（用于止盈止损跟踪）"""
    market_id: str
    token_id: str
    entry_price: Decimal     # 买入价格
    shares: Decimal          # 持有份额
    cost: Decimal            # 买入花费
    location: str
    date: str
    bucket_name: str
    market_url: str = ""
    market_question: str = ""
    created_at: float = 0    # 时间戳


class WeatherStrategy:
    """天气交易策略 - 使用 NOAA 预报对抗 Polymarket 天气市场定价"""

    def __init__(self, config: WeatherConfig, noaa_feed: NOAAFeed,
                 price_fetcher: Optional[Callable[[str, str], Awaitable[Optional[Decimal]]]] = None):
        self.config = config
        self.noaa = noaa_feed
        self._forecast_cache: Dict[str, Dict] = {}
        self._price_fetcher = price_fetcher

    async def scan_entries(self, markets: List[Market]) -> List[WeatherSignal]:
        """扫描入场机会"""
        # 1. 筛选天气市场
        weather_markets = [m for m in markets if self._is_weather_market(m.question)]
        if not weather_markets:
            logger.info("No weather markets found")
            return []

        logger.info(f"Found {len(weather_markets)} weather markets")

        # 2. 按事件分组（同一天气事件下的多个温度区间）
        event_groups: Dict[str, List[Market]] = {}
        for m in weather_markets:
            key = m.event_slug or m.condition_id
            if key not in event_groups:
                event_groups[key] = []
            event_groups[key].append(m)

        logger.info(f"Grouped into {len(event_groups)} weather events")

        # 3. 预取所有需要的城市 NOAA 预报（并行请求）
        needed_locations = set()
        for event_slug, group in event_groups.items():
            event_info = self._parse_weather_event(group[0].question)
            if event_info and event_info["location"] in self.config.locations:
                needed_locations.add(event_info["location"])

        fetch_locations = [loc for loc in needed_locations if loc not in self._forecast_cache]
        if fetch_locations:
            results = await asyncio.gather(
                *(self.noaa.get_forecast(loc) for loc in fetch_locations),
                return_exceptions=True,
            )
            for loc, result in zip(fetch_locations, results):
                if isinstance(result, Exception):
                    logger.warning(f"NOAA fetch failed for {loc}: {result}")
                    self._forecast_cache[loc] = {}
                else:
                    self._forecast_cache[loc] = result

        signals: List[WeatherSignal] = []
        trades_count = 0

        for event_slug, group in event_groups.items():
            if trades_count >= self.config.max_trades_per_scan:
                break

            # 3. 解析事件信息
            event_info = self._parse_weather_event(group[0].question)
            if not event_info:
                continue

            location = event_info["location"]
            date_str = event_info["date"]
            metric = event_info["metric"]

            # 4. 检查是否在活跃城市列表
            if location not in self.config.locations:
                continue

            # 5. 获取 NOAA 预报（已预取）
            forecasts = self._forecast_cache.get(location, {})
            day_forecast = forecasts.get(date_str, {})
            forecast_temp = day_forecast.get(metric)

            if forecast_temp is None:
                logger.debug(f"No NOAA forecast for {location} {date_str} {metric}")
                continue

            logger.info(f"NOAA: {location} {date_str} {metric}={forecast_temp}°F")

            # 6. 在该事件的所有市场中找到匹配的温度区间
            for market in group:
                if trades_count >= self.config.max_trades_per_scan:
                    break

                bucket = self._parse_temperature_bucket(market.question)
                if not bucket:
                    continue

                low, high = bucket
                if not (low <= forecast_temp <= high):
                    continue

                # 找到匹配的 bucket，检查 YES 价格
                yes_outcome = market.get_yes_outcome()
                if not yes_outcome:
                    continue

                # 优先用 CLOB 真实买价，fallback 到 Gamma 概率价
                price = yes_outcome.price
                if self._price_fetcher:
                    try:
                        clob_price = await self._price_fetcher(yes_outcome.token_id, "buy")
                        if clob_price is not None and clob_price > 0:
                            price = clob_price
                    except Exception as e:
                        logger.debug(f"CLOB price fetch failed for {market.slug}: {e}")

                # 安全检查
                ok, reason = self._check_safeguards(price)
                if not ok:
                    logger.debug(f"Safeguard blocked {market.slug}: {reason}")
                    continue

                # 价格低于入场阈值 → 生成买入信号
                if float(price) < self.config.entry_threshold:
                    bucket_name = self._format_bucket_name(market.question, low, high)
                    signal = WeatherSignal(
                        market_id=market.condition_id,
                        token_id=yes_outcome.token_id,
                        action="BUY",
                        price=price,
                        amount=self.config.max_position_usd,
                        location=location,
                        date=date_str,
                        forecast_temp=forecast_temp,
                        bucket_name=bucket_name,
                        reasoning=f"NOAA预报{forecast_temp}°F，区间{bucket_name}价格${price}低于阈值${self.config.entry_threshold}",
                        market_url=market.url,
                        market_question=market.question,
                    )
                    signals.append(signal)
                    trades_count += 1
                    logger.info(
                        f"BUY signal: {location} {date_str} {bucket_name} @ ${price}"
                    )

        return signals

    async def scan_exits(
        self, positions: List[WeatherPosition], markets: List[Market]
    ) -> List[WeatherSignal]:
        """扫描出场机会（止盈/止损/正常出场）"""
        if not positions:
            return []

        # 构建 market_id → Market 的映射
        market_map = {m.condition_id: m for m in markets}

        signals: List[WeatherSignal] = []

        for pos in positions:
            market = market_map.get(pos.market_id)
            if not market:
                logger.debug(f"Market {pos.market_id} not found, skipping exit check")
                continue

            # 获取当前价格
            current_price = None
            for outcome in market.outcomes:
                if outcome.token_id == pos.token_id:
                    current_price = outcome.price
                    break

            if current_price is None:
                yes_outcome = market.get_yes_outcome()
                if yes_outcome:
                    current_price = yes_outcome.price
                else:
                    continue

            # 计算浮盈浮亏
            if pos.entry_price <= 0:
                continue
            pnl_pct = float((current_price - pos.entry_price) / pos.entry_price)

            exit_type = ""
            reasoning = ""

            # 检查出场条件（按优先级）
            if pnl_pct <= -self.config.stop_loss_pct:
                exit_type = "stop_loss"
                reasoning = f"止损触发: 浮亏{pnl_pct:.1%}，超过止损线-{self.config.stop_loss_pct:.0%}"
            elif pnl_pct >= self.config.take_profit_pct:
                exit_type = "take_profit"
                reasoning = f"止盈触发: 浮盈{pnl_pct:.1%}，达到止盈线+{self.config.take_profit_pct:.0%}"
            elif float(current_price) >= self.config.exit_threshold:
                exit_type = "exit_threshold"
                reasoning = f"正常出场: 价格${current_price}达到出场阈值${self.config.exit_threshold}"

            if exit_type:
                signal = WeatherSignal(
                    market_id=pos.market_id,
                    token_id=pos.token_id,
                    action="SELL",
                    price=current_price,
                    amount=Decimal("0"),  # 卖出时按份额
                    location=pos.location,
                    date=pos.date,
                    forecast_temp=0,
                    bucket_name=pos.bucket_name,
                    reasoning=reasoning,
                    exit_type=exit_type,
                    market_url=pos.market_url,
                    market_question=pos.market_question,
                )
                signals.append(signal)
                logger.info(
                    f"SELL signal ({exit_type}): {pos.location} {pos.date} "
                    f"{pos.bucket_name} @ ${current_price} (entry: ${pos.entry_price})"
                )

        return signals

    def clear_cache(self):
        """清除预报缓存（每个扫描周期开始时调用）"""
        self._forecast_cache.clear()

    @staticmethod
    def _is_weather_market(question: str) -> bool:
        """判断是否为天气市场"""
        q = question.lower()
        return any(kw in q for kw in WEATHER_KEYWORDS)

    @staticmethod
    def _parse_weather_event(event_name: str) -> Optional[Dict]:
        """解析天气事件名，提取城市/日期/指标"""
        if not event_name:
            return None

        event_lower = event_name.lower()

        # 判断高温/低温
        if "highest" in event_lower or "high temp" in event_lower:
            metric = "high"
        elif "lowest" in event_lower or "low temp" in event_lower:
            metric = "low"
        else:
            metric = "high"

        # 匹配城市
        location = None
        for alias, loc in LOCATION_ALIASES.items():
            if alias in event_lower:
                location = loc
                break

        if not location:
            return None

        # 匹配日期 "on January 15" 格式
        month_day_match = re.search(
            r'on\s+([a-zA-Z]+)\s+(\d{1,2})', event_name, re.IGNORECASE
        )
        if not month_day_match:
            return None

        month_name = month_day_match.group(1).lower()
        day = int(month_day_match.group(2))

        month_map = {
            "january": 1, "jan": 1, "february": 2, "feb": 2,
            "march": 3, "mar": 3, "april": 4, "apr": 4,
            "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
            "august": 8, "aug": 8, "september": 9, "sep": 9,
            "october": 10, "oct": 10, "november": 11, "nov": 11,
            "december": 12, "dec": 12,
        }

        month = month_map.get(month_name)
        if not month:
            return None

        now = datetime.now(timezone.utc)
        year = now.year
        try:
            target_date = datetime(year, month, day, tzinfo=timezone.utc)
            if target_date < now - timedelta(days=30):
                year += 1
            date_str = f"{year}-{month:02d}-{day:02d}"
        except ValueError:
            return None

        return {"location": location, "date": date_str, "metric": metric}

    @staticmethod
    def _parse_temperature_bucket(text: str) -> Optional[Tuple[int, int]]:
        """解析温度区间

        支持格式:
        - "34-35°F" → (34, 35)
        - "36°F or higher" → (36, 999)
        - "32°F or below" → (-999, 32)
        """
        if not text:
            return None

        # "X or below / or less"
        below_match = re.search(
            r'(\d+)\s*°?[fF]?\s*(or below|or less)', text, re.IGNORECASE
        )
        if below_match:
            return (-999, int(below_match.group(1)))

        # "X or higher / or above / or more"
        above_match = re.search(
            r'(\d+)\s*°?[fF]?\s*(or higher|or above|or more)', text, re.IGNORECASE
        )
        if above_match:
            return (int(above_match.group(1)), 999)

        # "X-Y" 范围
        range_match = re.search(r'(\d+)\s*[-–to]+\s*(\d+)', text)
        if range_match:
            low, high = int(range_match.group(1)), int(range_match.group(2))
            return (min(low, high), max(low, high))

        return None

    @staticmethod
    def _format_bucket_name(question: str, low: int, high: int) -> str:
        """格式化温度区间名称"""
        if low == -999:
            return f"{high}°F or below"
        if high == 999:
            return f"{low}°F or higher"
        return f"{low}-{high}°F"

    def _check_safeguards(self, price: Decimal) -> Tuple[bool, str]:
        """安全检查"""
        price_f = float(price)

        if price_f < self.config.min_tick_size:
            return False, f"Price ${price_f} below min tick ${self.config.min_tick_size}"

        if price_f > (1 - self.config.min_tick_size):
            return False, f"Price ${price_f} above max tradeable"

        return True, ""
