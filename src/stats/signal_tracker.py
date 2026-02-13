"""信号跟踪器 — 跟踪已推送信号的价格变化和最终结果"""
import json
import logging
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Dict, Optional, Tuple

from ..config import WeatherConfig
from ..models.market import Market

logger = logging.getLogger(__name__)


@dataclass
class TrackedSignal:
    """被跟踪的信号"""
    # 信号身份
    signal_id: str
    market_id: str
    token_id: str
    location: str
    date: str
    bucket_name: str
    forecast_temp: int
    market_url: str
    market_question: str

    # 价格跟踪
    signal_price: float
    current_price: float
    high_price: float
    low_price: float
    created_at: float
    last_updated: float

    # 推送去重
    alerted_take_profit: bool = False
    alerted_stop_loss: bool = False
    alerted_big_move_up: bool = False
    alerted_big_move_down: bool = False
    alerted_resolved: bool = False

    # 结果
    status: str = "active"
    resolution_price: float = 0.0
    resolved_at: float = 0.0
    forecast_correct: bool = False
    pnl_pct: float = 0.0


class SignalTracker:
    """信号跟踪器"""

    EXPIRY_HOURS = 24
    PRUNE_DAYS = 7
    BIG_MOVE_PCT = 0.20

    def __init__(self, filepath: str = "tracked_signals.json"):
        self.filepath = filepath
        self.signals: List[TrackedSignal] = []
        self.last_summary_ts: float = 0.0
        self._load()

    # ------------------------------------------------------------------
    # 信号管理
    # ------------------------------------------------------------------

    def add_signal(self, signal) -> None:
        """从 WeatherSignal 创建 TrackedSignal（同一 market_id active 时不重复记录）"""
        # 去重：同一市场已有 active 信号则跳过
        if any(s.market_id == signal.market_id and s.status == "active" for s in self.signals):
            logger.debug(f"Skip duplicate tracking for {signal.market_id}")
            return

        now = time.time()
        price = float(signal.price)
        tracked = TrackedSignal(
            signal_id=f"{signal.market_id}_{int(now)}",
            market_id=signal.market_id,
            token_id=signal.token_id,
            location=signal.location,
            date=signal.date,
            bucket_name=signal.bucket_name,
            forecast_temp=signal.forecast_temp,
            market_url=signal.market_url,
            market_question=signal.market_question,
            signal_price=price,
            current_price=price,
            high_price=price,
            low_price=price,
            created_at=now,
            last_updated=now,
        )
        self.signals.append(tracked)
        logger.info(f"Tracking signal: {signal.location} {signal.date} {signal.bucket_name} @ ${price}")

    # ------------------------------------------------------------------
    # 价格更新（复用已加载的市场数据，零额外 API 调用）
    # ------------------------------------------------------------------

    def update_prices(self, market_map: Dict[str, Market]) -> None:
        """批量更新活跃信号的价格"""
        now = time.time()
        for sig in self.signals:
            if sig.status != "active":
                continue

            market = market_map.get(sig.market_id)
            if not market:
                continue

            # 找到 YES outcome 的价格
            price = None
            for outcome in market.outcomes:
                if outcome.token_id == sig.token_id:
                    price = float(outcome.price)
                    break
            if price is None:
                yes = market.get_yes_outcome()
                if yes:
                    price = float(yes.price)

            if price is not None:
                sig.current_price = price
                sig.high_price = max(sig.high_price, price)
                sig.low_price = min(sig.low_price, price)
                sig.last_updated = now

    # ------------------------------------------------------------------
    # 结算 & 过期检测
    # ------------------------------------------------------------------

    def check_resolutions(self) -> None:
        """检测市场结算（价格 >= $0.99 或 <= $0.01）"""
        now = time.time()
        for sig in self.signals:
            if sig.status != "active":
                continue

            if sig.current_price >= 0.99:
                sig.status = "resolved_win"
                sig.forecast_correct = True
                sig.resolution_price = sig.current_price
                sig.resolved_at = now
                sig.pnl_pct = (sig.current_price - sig.signal_price) / sig.signal_price if sig.signal_price > 0 else 0
                logger.info(f"Signal resolved WIN: {sig.location} {sig.date} {sig.bucket_name}")

            elif sig.current_price <= 0.01:
                sig.status = "resolved_loss"
                sig.forecast_correct = False
                sig.resolution_price = sig.current_price
                sig.resolved_at = now
                sig.pnl_pct = (sig.current_price - sig.signal_price) / sig.signal_price if sig.signal_price > 0 else 0
                logger.info(f"Signal resolved LOSS: {sig.location} {sig.date} {sig.bucket_name}")

    def check_expirations(self) -> None:
        """24h 未结算的信号标记为 expired"""
        now = time.time()
        cutoff = now - (self.EXPIRY_HOURS * 3600)
        for sig in self.signals:
            if sig.status != "active":
                continue
            if sig.created_at < cutoff:
                sig.status = "expired"
                sig.resolution_price = sig.current_price
                sig.resolved_at = now
                sig.pnl_pct = (sig.current_price - sig.signal_price) / sig.signal_price if sig.signal_price > 0 else 0
                logger.info(f"Signal expired: {sig.location} {sig.date} {sig.bucket_name} pnl={sig.pnl_pct:.1%}")

    def mark_resolved(self, market_id: str, price: float, exit_type: str) -> None:
        """自动交易出场时同步标记（从 engine 调用）"""
        now = time.time()
        for sig in self.signals:
            if sig.market_id == market_id and sig.status == "active":
                sig.status = "resolved_win" if exit_type == "take_profit" else "resolved_loss"
                sig.resolution_price = price
                sig.resolved_at = now
                sig.pnl_pct = (price - sig.signal_price) / sig.signal_price if sig.signal_price > 0 else 0

    # ------------------------------------------------------------------
    # 告警检查
    # ------------------------------------------------------------------

    def check_alerts(self, config: WeatherConfig) -> List[Tuple[TrackedSignal, str]]:
        """检查需要推送的告警，返回 (信号, 告警类型) 列表"""
        alerts: List[Tuple[TrackedSignal, str]] = []

        for sig in self.signals:
            if sig.signal_price <= 0:
                continue

            pnl_pct = (sig.current_price - sig.signal_price) / sig.signal_price

            # 市场结算
            if sig.status in ("resolved_win", "resolved_loss") and not sig.alerted_resolved:
                sig.alerted_resolved = True
                alerts.append((sig, "resolved"))
                continue

            if sig.status != "active":
                continue

            # 止盈触发
            if pnl_pct >= config.take_profit_pct and not sig.alerted_take_profit:
                sig.alerted_take_profit = True
                alerts.append((sig, "take_profit"))

            # 止损触发
            elif pnl_pct <= -config.stop_loss_pct and not sig.alerted_stop_loss:
                sig.alerted_stop_loss = True
                alerts.append((sig, "stop_loss"))

            # 大幅上涨
            elif pnl_pct >= self.BIG_MOVE_PCT and not sig.alerted_big_move_up:
                sig.alerted_big_move_up = True
                alerts.append((sig, "big_move_up"))

            # 大幅下跌
            elif pnl_pct <= -self.BIG_MOVE_PCT and not sig.alerted_big_move_down:
                sig.alerted_big_move_down = True
                alerts.append((sig, "big_move_down"))

        return alerts

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def calculate_daily_summary(self, lookback_hours: int = 24) -> dict:
        """计算 24h 统计"""
        cutoff = time.time() - (lookback_hours * 3600)
        recent = [s for s in self.signals if s.created_at >= cutoff]
        resolved = [s for s in recent if s.status != "active"]
        active = [s for s in recent if s.status == "active"]

        wins = [s for s in resolved if s.status == "resolved_win"]
        losses = [s for s in resolved if s.status == "resolved_loss"]
        expired = [s for s in resolved if s.status == "expired"]

        returns = [s.pnl_pct for s in resolved]

        best = max(resolved, key=lambda s: s.pnl_pct, default=None)
        worst = min(resolved, key=lambda s: s.pnl_pct, default=None)

        return {
            "total": len(recent),
            "wins": len(wins),
            "losses": len(losses),
            "expired": len(expired),
            "active": len(active),
            "win_rate": len(wins) / max(len(wins) + len(losses), 1),
            "avg_return": sum(returns) / max(len(returns), 1),
            "best": best,
            "worst": worst,
        }

    def calculate_weekly_summary(self) -> dict:
        """计算 7 天统计"""
        cutoff = time.time() - (7 * 86400)
        week = [s for s in self.signals if s.created_at >= cutoff]
        resolved = [s for s in week if s.status in ("resolved_win", "resolved_loss")]
        wins = [s for s in resolved if s.status == "resolved_win"]

        return {
            "total": len(week),
            "resolved": len(resolved),
            "wins": len(wins),
            "win_rate": len(wins) / max(len(resolved), 1),
        }

    # ------------------------------------------------------------------
    # 日报推送控制
    # ------------------------------------------------------------------

    def should_push_summary(self) -> bool:
        """是否该推送日报（09:00 且间隔 >20h）"""
        now = time.time()
        hour = datetime.now(timezone.utc).hour
        # UTC 14:00 ≈ 北京 22:00 / 美东 09:00
        if hour != 14:
            return False
        if now - self.last_summary_ts < 72000:  # 20h
            return False
        # 至少有 1 个信号才推送
        return len(self.signals) > 0

    def mark_summary_pushed(self) -> None:
        self.last_summary_ts = time.time()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def save(self) -> None:
        """保存到 JSON"""
        try:
            data = {
                "last_summary_ts": self.last_summary_ts,
                "signals": [asdict(s) for s in self.signals],
            }
            with open(self.filepath, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save tracked signals: {e}")

    def _load(self) -> None:
        """从 JSON 加载"""
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
            self.last_summary_ts = data.get("last_summary_ts", 0.0)
            for item in data.get("signals", []):
                self.signals.append(TrackedSignal(**item))
            if self.signals:
                logger.info(f"Loaded {len(self.signals)} tracked signals")
            self._prune_old()
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to load tracked signals: {e}")

    def _prune_old(self) -> None:
        """清理结算超过 7 天的旧信号"""
        cutoff = time.time() - (self.PRUNE_DAYS * 86400)
        before = len(self.signals)
        self.signals = [
            s for s in self.signals
            if s.status == "active" or s.resolved_at == 0 or s.resolved_at > cutoff
        ]
        pruned = before - len(self.signals)
        if pruned > 0:
            logger.info(f"Pruned {pruned} old tracked signals")
