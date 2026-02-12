"""核心引擎"""
import asyncio
import json
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict

from ..config import Config
from ..data.market_feed import MarketFeed
from ..data.noaa_feed import NOAAFeed
from ..execution.risk_manager import RiskManager
from ..execution.order_manager import OrderManager
from ..stats.opportunity_tracker import OpportunityTracker
from ..notification.telegram import TelegramNotifier, TelegramConfig
from ..strategy.weather import WeatherStrategy, WeatherSignal, WeatherPosition

logger = logging.getLogger(__name__)

WEATHER_POSITIONS_FILE = "weather_positions.json"


class Engine:
    """交易引擎"""

    def __init__(self, config: Config):
        self.config = config
        self.market_feed = MarketFeed(config.api)
        self.risk_manager = RiskManager(config.risk)
        self.order_manager = OrderManager(config)
        self.tracker = OpportunityTracker()
        self._running = False

        # 初始化 Telegram 通知
        if config.telegram.enabled:
            tg_config = TelegramConfig(
                bot_token=config.telegram.bot_token,
                chat_id=config.telegram.chat_id,
                topic_id=config.telegram.topic_id,
            )
            self.notifier = TelegramNotifier(tg_config)
            logger.info("Telegram notifier enabled")
        else:
            self.notifier = None

        # 推送去重缓存 {market_id: timestamp}
        self._notify_cooldown = 6 * 3600  # 6小时冷却
        self._notify_cache_file = "notify_cache.json"
        self._notified_markets: Dict[str, float] = self._load_notify_cache()

        # 睡眠时间配置 (23:00 - 08:00 不扫描)
        self._sleep_start = 23
        self._sleep_end = 8

    def _load_notify_cache(self) -> Dict[str, float]:
        """从文件加载推送缓存"""
        try:
            with open(self._notify_cache_file, 'r') as f:
                cache = json.load(f)
                now = time.time()
                return {k: v for k, v in cache.items() if now - v < self._notify_cooldown}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_notify_cache(self):
        """保存推送缓存到文件"""
        try:
            with open(self._notify_cache_file, 'w') as f:
                json.dump(self._notified_markets, f)
        except Exception as e:
            logger.warning(f"Failed to save notify cache: {e}")

    def _is_sleep_time(self) -> bool:
        """检查是否在睡眠时间"""
        hour = datetime.now().hour
        if self._sleep_start > self._sleep_end:
            return hour >= self._sleep_start or hour < self._sleep_end
        else:
            return self._sleep_start <= hour < self._sleep_end

    # ------------------------------------------------------------------
    # 天气持仓持久化
    # ------------------------------------------------------------------

    def _load_weather_positions(self) -> List[WeatherPosition]:
        """从文件加载天气持仓"""
        try:
            with open(WEATHER_POSITIONS_FILE, 'r') as f:
                data = json.load(f)
                return [
                    WeatherPosition(
                        market_id=p["market_id"],
                        token_id=p["token_id"],
                        entry_price=Decimal(p["entry_price"]),
                        shares=Decimal(p["shares"]),
                        cost=Decimal(p["cost"]),
                        location=p["location"],
                        date=p["date"],
                        bucket_name=p["bucket_name"],
                        market_url=p.get("market_url", ""),
                        market_question=p.get("market_question", ""),
                        created_at=p.get("created_at", 0),
                    )
                    for p in data
                ]
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load weather positions: {e}")
            return []

    def _save_weather_positions(self, positions: List[WeatherPosition]):
        """保存天气持仓到文件"""
        try:
            data = [
                {
                    "market_id": p.market_id,
                    "token_id": p.token_id,
                    "entry_price": str(p.entry_price),
                    "shares": str(p.shares),
                    "cost": str(p.cost),
                    "location": p.location,
                    "date": p.date,
                    "bucket_name": p.bucket_name,
                    "market_url": p.market_url,
                    "market_question": p.market_question,
                    "created_at": p.created_at,
                }
                for p in positions
            ]
            with open(WEATHER_POSITIONS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save weather positions: {e}")

    # ------------------------------------------------------------------
    # Telegram 推送
    # ------------------------------------------------------------------

    def _send_weather_signal(self, signal: WeatherSignal):
        """推送天气交易信号（两种模式都调用）"""
        if not self.notifier:
            return

        # 去重检查
        now = time.time()
        last_notify = self._notified_markets.get(signal.market_id, 0)
        if now - last_notify < self._notify_cooldown:
            logger.debug(f"Skip duplicate signal notification for {signal.market_id}")
            return

        action_cn = "买入 YES" if signal.action == "BUY" else "卖出"
        tp_pct = self.config.weather.take_profit_pct
        sl_pct = self.config.weather.stop_loss_pct
        tp_price = signal.price * (1 + Decimal(str(tp_pct)))
        sl_price = signal.price * (1 - Decimal(str(sl_pct)))
        msg = (
            f"🌤️ *天气交易信号*\n\n"
            f"📍 城市: {signal.location}\n"
            f"📅 日期: {signal.date}\n"
            f"🌡️ NOAA预报: {signal.forecast_temp}°F\n"
            f"📊 匹配区间: {signal.bucket_name}\n"
            f"💰 当前价格: ${signal.price}\n"
            f"🎯 止盈: ${tp_price:.3f} (+{tp_pct:.0%})\n"
            f"🛑 止损: ${sl_price:.3f} (-{sl_pct:.0%})\n"
            f"📈 建议操作: {action_cn}\n\n"
            f"🔗 [查看市场]({signal.market_url})"
        )
        if self.notifier.send(msg):
            self._notified_markets[signal.market_id] = now
            self._save_notify_cache()

    def _send_trade_combined(
        self, signal: WeatherSignal, shares: Decimal, avg_price: Decimal,
        take_profit: Decimal, stop_loss: Decimal
    ):
        """推送合并消息：信号 + 交易执行（自动交易模式）"""
        if not self.notifier:
            return

        # 去重检查
        now = time.time()
        last_notify = self._notified_markets.get(signal.market_id, 0)
        if now - last_notify < self._notify_cooldown:
            logger.debug(f"Skip duplicate notification for {signal.market_id}")
            return

        tp_pct = self.config.weather.take_profit_pct
        sl_pct = self.config.weather.stop_loss_pct
        msg = (
            f"✅ *天气交易 - 买入*\n\n"
            f"📍 城市: {signal.location}\n"
            f"📅 日期: {signal.date}\n"
            f"🌡️ NOAA预报: {signal.forecast_temp}°F\n"
            f"📊 匹配区间: {signal.bucket_name}\n"
            f"💰 买入价: ${avg_price:.3f}\n"
            f"📦 数量: {shares:.1f} shares\n"
            f"💵 花费: ${signal.amount}\n"
            f"🎯 止盈: ${take_profit:.3f} (+{tp_pct:.0%})\n"
            f"🛑 止损: ${stop_loss:.3f} (-{sl_pct:.0%})\n\n"
            f"🔗 [查看市场]({signal.market_url})"
        )
        if self.notifier.send(msg):
            self._notified_markets[signal.market_id] = now
            self._save_notify_cache()

    def _send_exit_result(
        self, position: WeatherPosition, current_price: Decimal, exit_type: str
    ):
        """推送出场结果（仅自动交易模式）"""
        if not self.notifier:
            return

        pnl = (current_price - position.entry_price) * position.shares
        pnl_pct = (
            (current_price - position.entry_price) / position.entry_price
            if position.entry_price > 0 else Decimal("0")
        )

        emoji_map = {
            "take_profit": "🎯 *止盈触发*",
            "stop_loss": "🛑 *止损触发*",
            "exit_threshold": "📤 *正常出场*",
        }
        title = emoji_map.get(exit_type, "📤 *出场*")

        if pnl >= 0:
            pnl_str = f"+${pnl:.2f} (+{pnl_pct:.1%})"
            pnl_label = "盈利"
        else:
            pnl_str = f"-${abs(pnl):.2f} ({pnl_pct:.1%})"
            pnl_label = "亏损"

        msg = (
            f"{title}\n\n"
            f"📍 {position.location} {position.date} | {position.bucket_name}\n"
            f"💰 买入价: ${position.entry_price} → 当前: ${current_price}\n"
            f"📦 卖出: {position.shares:.1f} shares\n"
            f"💵 {pnl_label}: {pnl_str}\n\n"
            f"🔗 [查看市场]({position.market_url})"
        )
        self.notifier.send(msg)

    # ------------------------------------------------------------------
    # 天气交易模式
    # ------------------------------------------------------------------

    async def run_weather(self, interval: int = 3600):
        """运行天气交易模式"""
        if not self.config.weather.enabled:
            logger.error("Weather strategy not enabled (set WEATHER_ENABLED=true)")
            return

        self._running = True
        mode_str = "AUTO-TRADE" if self.config.weather.auto_trade else "SIGNAL-ONLY"
        logger.info(f"Starting weather mode [{mode_str}]...")
        logger.info(f"Dry run: {self.config.dry_run}")
        logger.info(f"Locations: {self.config.weather.locations}")
        logger.info(f"Entry: <${self.config.weather.entry_threshold} | "
                     f"Exit: >${self.config.weather.exit_threshold}")

        if self.config.weather.auto_trade:
            logger.info(f"Take profit: +{self.config.weather.take_profit_pct:.0%} | "
                         f"Stop loss: -{self.config.weather.stop_loss_pct:.0%}")

        # 初始化
        noaa_feed = NOAAFeed()

        async def _fetch_clob_price(token_id: str, side: str) -> Optional[Decimal]:
            """从 CLOB 获取真实买/卖价"""
            price_data = await self.order_manager.clob.get_price(token_id, side=side)
            p = price_data.get("price")
            return Decimal(str(p)) if p else None

        strategy = WeatherStrategy(self.config.weather, noaa_feed, price_fetcher=_fetch_clob_price)

        # 加载已有持仓
        positions = self._load_weather_positions()
        if positions:
            logger.info(f"Loaded {len(positions)} existing weather positions")

        try:
            while self._running:
                # 睡眠时间检查
                if self._is_sleep_time():
                    logger.info("Sleep time (23:00-08:00), skipping scan...")
                    await asyncio.sleep(interval)
                    continue

                # 刷新天气市场（通过 events API 高效获取）
                await self.market_feed.refresh_weather_markets()
                all_markets = self.market_feed.get_all_markets()
                logger.info(f"Loaded {len(all_markets)} markets")

                # 清除预报缓存
                strategy.clear_cache()

                # --- 入场扫描 ---
                entry_signals = await strategy.scan_entries(all_markets)
                logger.info(f"Entry signals: {len(entry_signals)}")

                trades_this_scan = 0
                for signal in entry_signals:
                    # 自动交易模式：执行买入，合并推送
                    if self.config.weather.auto_trade:
                        result = await self.order_manager.execute_weather_buy(
                            token_id=signal.token_id,
                            amount=signal.amount,
                        )
                        if result.success:
                            trades_this_scan += 1
                            # 记录持仓
                            pos = WeatherPosition(
                                market_id=signal.market_id,
                                token_id=signal.token_id,
                                entry_price=result.avg_price,
                                shares=result.shares,
                                cost=signal.amount,
                                location=signal.location,
                                date=signal.date,
                                bucket_name=signal.bucket_name,
                                market_url=signal.market_url,
                                market_question=signal.market_question,
                                created_at=time.time(),
                            )
                            positions.append(pos)
                            self._save_weather_positions(positions)

                            # 计算止盈止损价格，合并推送信号+交易
                            tp_price = result.avg_price * Decimal(
                                str(1 + self.config.weather.take_profit_pct)
                            )
                            sl_price = result.avg_price * Decimal(
                                str(1 - self.config.weather.stop_loss_pct)
                            )
                            self._send_trade_combined(
                                signal, result.shares, result.avg_price, tp_price, sl_price
                            )

                            # 记录敞口
                            self.risk_manager.add_exposure(
                                signal.market_id, signal.amount
                            )
                        else:
                            logger.error(f"Weather BUY failed: {result.error}")
                    else:
                        # 信号模式：只推送信号
                        self._send_weather_signal(signal)

                # --- 出场扫描（仅自动交易模式） ---
                if self.config.weather.auto_trade and positions:
                    exit_signals = await strategy.scan_exits(positions, all_markets)
                    logger.info(f"Exit signals: {len(exit_signals)}")

                    for signal in exit_signals:
                        # 找到对应持仓
                        pos = next(
                            (p for p in positions if p.market_id == signal.market_id),
                            None,
                        )
                        if not pos:
                            continue

                        result = await self.order_manager.execute_weather_sell(
                            token_id=pos.token_id,
                            shares=pos.shares,
                        )
                        if result.success:
                            # 推送出场结果
                            self._send_exit_result(
                                pos, result.avg_price, signal.exit_type
                            )
                            # 移除持仓
                            positions = [
                                p for p in positions
                                if p.market_id != signal.market_id
                            ]
                            self._save_weather_positions(positions)

                            # 移除敞口
                            self.risk_manager.remove_exposure(
                                signal.market_id, pos.cost
                            )
                        else:
                            logger.error(f"Weather SELL failed: {result.error}")

                # 扫描摘要
                logger.info(
                    f"Scan complete: {len(all_markets)} markets, "
                    f"{len(entry_signals)} entry signals, "
                    f"{trades_this_scan} trades, "
                    f"{len(positions)} open positions"
                )

                await asyncio.sleep(interval)

        finally:
            await noaa_feed.close()

    async def stop(self):
        """停止引擎"""
        self._running = False
        await self.market_feed.close()
        await self.order_manager.close()
        logger.info("Engine stopped")

    def get_stats(self) -> dict:
        """获取引擎统计信息"""
        return {
            "risk": self.risk_manager.get_stats(),
            "positions": self.order_manager.get_positions_summary(),
            "markets_loaded": len(self.market_feed.get_all_markets()),
            "dry_run": self.config.dry_run,
            "opportunities": self.tracker.get_summary()
        }

    def print_stats_report(self):
        """打印统计报告"""
        return self.tracker.print_report()

    def get_weekly_report(self) -> dict:
        """获取周报"""
        return self.tracker.get_weekly_report()
