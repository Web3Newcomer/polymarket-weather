"""NOAA 天气预报数据源"""
import asyncio
import logging
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class NOAAFeed:
    """异步 NOAA 天气预报客户端"""

    NOAA_API_BASE = "https://api.weather.gov"

    # 支持的城市（与 Polymarket 天气市场对应的气象站）
    LOCATIONS = {
        "NYC": {"lat": 40.7769, "lon": -73.8740, "name": "New York City (LaGuardia)"},
        "Chicago": {"lat": 41.9742, "lon": -87.9073, "name": "Chicago (O'Hare)"},
        "Seattle": {"lat": 47.4502, "lon": -122.3088, "name": "Seattle (Sea-Tac)"},
        "Atlanta": {"lat": 33.6407, "lon": -84.4277, "name": "Atlanta (Hartsfield)"},
        "Dallas": {"lat": 32.8998, "lon": -97.0403, "name": "Dallas (DFW)"},
        "Miami": {"lat": 25.7959, "lon": -80.2870, "name": "Miami (MIA)"},
    }

    HEADERS = {
        "User-Agent": "PolymarketWeatherBot/1.0",
        "Accept": "application/geo+json",
    }

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._timeout = aiohttp.ClientTimeout(total=30, connect=15)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout, headers=self.HEADERS
            )
        return self._session

    async def get_forecast(self, location: str) -> Dict[str, Dict]:
        """获取某城市的天气预报

        Args:
            location: 城市名（如 "NYC"）

        Returns:
            {"2026-02-13": {"high": 34, "low": 22}, ...}
            失败返回空 dict
        """
        if location not in self.LOCATIONS:
            logger.warning(f"Unknown location: {location}")
            return {}

        loc = self.LOCATIONS[location]

        # 第一步：获取 grid 信息
        points_url = f"{self.NOAA_API_BASE}/points/{loc['lat']},{loc['lon']}"
        points_data = await self._fetch_json(points_url)

        if not points_data or "properties" not in points_data:
            logger.warning(f"Failed to get NOAA grid for {location}")
            return {}

        forecast_url = points_data["properties"].get("forecast")
        if not forecast_url:
            logger.warning(f"No forecast URL for {location}")
            return {}

        # 第二步：获取预报数据
        forecast_data = await self._fetch_json(forecast_url)
        if not forecast_data or "properties" not in forecast_data:
            logger.warning(f"Failed to get NOAA forecast for {location}")
            return {}

        # 解析预报周期
        periods = forecast_data["properties"].get("periods", [])
        forecasts: Dict[str, Dict] = {}

        for period in periods:
            start_time = period.get("startTime", "")
            if not start_time:
                continue

            date_str = start_time[:10]  # "2026-02-13"
            temp = period.get("temperature")
            is_daytime = period.get("isDaytime", True)

            if date_str not in forecasts:
                forecasts[date_str] = {"high": None, "low": None}

            if is_daytime:
                forecasts[date_str]["high"] = temp
            else:
                forecasts[date_str]["low"] = temp

        logger.info(f"NOAA forecast for {location}: {len(forecasts)} days")
        return forecasts

    async def _fetch_json(self, url: str) -> Optional[dict]:
        """带重试的 JSON 请求"""
        session = await self._get_session()

        for attempt in range(3):
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.warning(
                        f"NOAA API {resp.status} (attempt {attempt + 1}/3): {url}"
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(
                    f"NOAA request failed (attempt {attempt + 1}/3): {e}"
                )
            if attempt < 2:
                await asyncio.sleep(5)

        return None

    async def close(self):
        """关闭连接"""
        if self._session and not self._session.closed:
            await self._session.close()
