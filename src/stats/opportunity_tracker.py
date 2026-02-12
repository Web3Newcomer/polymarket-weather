"""套利机会统计追踪器"""
import json
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class OpportunityRecord:
    """单次套利机会记录"""
    timestamp: str
    market_id: str
    market_slug: str
    yes_price: float
    no_price: float
    total_cost: float
    profit_rate: float  # 百分比
    executed: bool = False


@dataclass
class HourlyStats:
    """每小时统计"""
    hour: str
    opportunities: int = 0
    avg_profit: float = 0.0
    max_profit: float = 0.0
    markets: List[str] = field(default_factory=list)


@dataclass
class DailyStats:
    """每日统计"""
    date: str
    total_opportunities: int = 0
    total_scans: int = 0
    total_markets_scanned: int = 0
    avg_profit: float = 0.0
    max_profit: float = 0.0
    unique_markets: int = 0
    hourly_distribution: Dict[int, int] = field(default_factory=dict)


class OpportunityTracker:
    """套利机会统计追踪器"""

    def __init__(self, data_dir: str = "stats_data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        # 内存中的统计
        self.opportunities: List[OpportunityRecord] = []
        self.scan_count = 0
        self.total_markets_scanned = 0

        # 按小时统计
        self.hourly_counts: Dict[str, int] = defaultdict(int)

        # 按市场统计
        self.market_counts: Dict[str, int] = defaultdict(int)

        # 利润分布
        self.profit_buckets: Dict[str, int] = defaultdict(int)

        # 加载历史数据
        self._load_today_data()
        self._last_save_ts = 0.0

    def _get_today_file(self) -> Path:
        """获取今日数据文件路径"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.data_dir / f"opportunities_{today}.json"

    def _load_today_data(self):
        """加载今日已有数据"""
        filepath = self._get_today_file()
        if filepath.exists():
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                    self.opportunities = [
                        OpportunityRecord(**r) for r in data.get("opportunities", [])
                    ]
                    self.scan_count = data.get("scan_count", 0)
                    self.total_markets_scanned = data.get("total_markets_scanned", 0)
                    logger.info(f"Loaded {len(self.opportunities)} opportunities from today")
            except Exception as e:
                logger.error(f"Failed to load today's data: {e}")

    def _save_data(self, force: bool = False):
        """保存数据到文件"""
        now = time.time()
        if not force and (now - self._last_save_ts) < 10:
            return

        filepath = self._get_today_file()
        data = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "scan_count": self.scan_count,
            "total_markets_scanned": self.total_markets_scanned,
            "opportunities": [asdict(o) for o in self.opportunities],
            "last_updated": datetime.now().isoformat()
        }
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            self._last_save_ts = now
        except Exception as e:
            logger.error(f"Failed to save data: {e}")

    def record_scan(self, markets_count: int):
        """记录一次扫描"""
        self.scan_count += 1
        self.total_markets_scanned += markets_count
        self._save_data()

    def record_opportunity(
        self,
        market_id: str,
        market_slug: str,
        yes_price: Decimal,
        no_price: Decimal,
        profit_rate: Decimal,
        executed: bool = False
    ):
        """记录发现的套利机会"""
        now = datetime.now()
        total_cost = float(yes_price + no_price)
        profit_pct = float(profit_rate * 100)

        record = OpportunityRecord(
            timestamp=now.isoformat(),
            market_id=market_id,
            market_slug=market_slug,
            yes_price=float(yes_price),
            no_price=float(no_price),
            total_cost=total_cost,
            profit_rate=profit_pct,
            executed=executed
        )

        self.opportunities.append(record)

        # 更新统计
        hour_key = now.strftime("%Y-%m-%d %H:00")
        self.hourly_counts[hour_key] += 1
        self.market_counts[market_slug] += 1

        # 利润分布桶
        bucket = self._get_profit_bucket(profit_pct)
        self.profit_buckets[bucket] += 1

        # 保存到文件
        self._save_data()

        # 记录日志
        logger.info(
            f"[OPPORTUNITY] {market_slug} | "
            f"YES={yes_price}, NO={no_price} | "
            f"Profit={profit_pct:.2f}% | "
            f"Executed={executed}"
        )

    def _get_profit_bucket(self, profit_pct: float) -> str:
        """获取利润分布桶"""
        if profit_pct < 0.5:
            return "0-0.5%"
        elif profit_pct < 1.0:
            return "0.5-1%"
        elif profit_pct < 2.0:
            return "1-2%"
        elif profit_pct < 3.0:
            return "2-3%"
        elif profit_pct < 5.0:
            return "3-5%"
        else:
            return "5%+"

    def get_summary(self) -> dict:
        """获取统计摘要"""
        if not self.opportunities:
            return {
                "total_opportunities": 0,
                "total_scans": self.scan_count,
                "total_markets_scanned": self.total_markets_scanned,
                "avg_profit": 0,
                "max_profit": 0,
                "unique_markets": 0,
                "opportunities_per_scan": 0,
                "hourly_distribution": {},
                "profit_distribution": {},
                "top_markets": []
            }

        profits = [o.profit_rate for o in self.opportunities]
        unique_markets = set(o.market_slug for o in self.opportunities)

        # 按小时分布
        hourly_dist = dict(self.hourly_counts)

        # 热门市场
        top_markets = sorted(
            self.market_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        return {
            "total_opportunities": len(self.opportunities),
            "total_scans": self.scan_count,
            "total_markets_scanned": self.total_markets_scanned,
            "avg_profit": sum(profits) / len(profits) if profits else 0,
            "max_profit": max(profits) if profits else 0,
            "min_profit": min(profits) if profits else 0,
            "unique_markets": len(unique_markets),
            "opportunities_per_scan": len(self.opportunities) / max(self.scan_count, 1),
            "hourly_distribution": hourly_dist,
            "profit_distribution": dict(self.profit_buckets),
            "top_markets": top_markets
        }

    def get_weekly_report(self) -> dict:
        """获取周报"""
        weekly_data = []
        today = datetime.now().date()

        for i in range(7):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            filepath = self.data_dir / f"opportunities_{date_str}.json"

            if filepath.exists():
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)
                        opportunities = data.get("opportunities", [])
                        profits = [o["profit_rate"] for o in opportunities]

                        weekly_data.append({
                            "date": date_str,
                            "opportunities": len(opportunities),
                            "scans": data.get("scan_count", 0),
                            "avg_profit": sum(profits) / len(profits) if profits else 0,
                            "max_profit": max(profits) if profits else 0
                        })
                except Exception as e:
                    logger.error(f"Failed to load {date_str}: {e}")
            else:
                weekly_data.append({
                    "date": date_str,
                    "opportunities": 0,
                    "scans": 0,
                    "avg_profit": 0,
                    "max_profit": 0
                })

        # 汇总
        total_opps = sum(d["opportunities"] for d in weekly_data)
        total_scans = sum(d["scans"] for d in weekly_data)
        all_profits = []
        for d in weekly_data:
            if d["opportunities"] > 0:
                all_profits.append(d["avg_profit"])

        return {
            "period": f"{weekly_data[-1]['date']} to {weekly_data[0]['date']}",
            "total_opportunities": total_opps,
            "total_scans": total_scans,
            "avg_opportunities_per_day": total_opps / 7,
            "avg_profit": sum(all_profits) / len(all_profits) if all_profits else 0,
            "daily_breakdown": weekly_data
        }

    def print_report(self):
        """打印统计报告"""
        summary = self.get_summary()

        report = f"""
========== 套利机会统计报告 ==========
日期: {datetime.now().strftime("%Y-%m-%d %H:%M")}

【总体统计】
  扫描次数: {summary['total_scans']}
  扫描市场总数: {summary['total_markets_scanned']}
  发现机会: {summary['total_opportunities']}
  每次扫描平均机会: {summary['opportunities_per_scan']:.4f}
  涉及市场数: {summary['unique_markets']}

【利润统计】
  平均利润率: {summary['avg_profit']:.2f}%
  最高利润率: {summary.get('max_profit', 0):.2f}%
  最低利润率: {summary.get('min_profit', 0):.2f}%

【利润分布】"""

        for bucket, count in sorted(summary.get('profit_distribution', {}).items()):
            report += f"\n  {bucket}: {count} 次"

        if not summary.get('profit_distribution'):
            report += "\n  (暂无数据)"

        report += "\n\n【热门市场 Top 10】"
        for market, count in summary.get('top_markets', []):
            report += f"\n  {market}: {count} 次"

        if not summary.get('top_markets'):
            report += "\n  (暂无数据)"

        report += "\n" + "=" * 40

        print(report)
        return report
