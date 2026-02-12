"""配置管理模块"""
import os
from dataclasses import dataclass, field
from decimal import Decimal
from dotenv import load_dotenv


@dataclass
class APIConfig:
    """Polymarket API 配置"""
    api_key: str
    api_secret: str
    passphrase: str
    funder_address: str

    # API 端点
    rest_url: str = "https://clob.polymarket.com"
    ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    gamma_url: str = "https://gamma-api.polymarket.com"


@dataclass
class RiskConfig:
    """风险管理配置"""
    min_profit_threshold: Decimal  # 最小利润阈值
    max_position_per_market: Decimal  # 单市场最大仓位
    max_total_exposure: Decimal  # 总敞口上限
    order_size: Decimal  # 单次订单大小


@dataclass
class WeatherConfig:
    """天气策略配置"""
    enabled: bool = False
    auto_trade: bool = False            # 自动交易开关，默认关闭（只推送信号）
    entry_threshold: float = 0.25       # 买入阈值（YES 价格低于此值时买入）
    exit_threshold: float = 0.65        # 卖出阈值（YES 价格高于此值时卖出）
    take_profit_pct: float = 0.50       # 止盈比例（50%）
    stop_loss_pct: float = 0.25         # 止损比例（25%）
    max_position_usd: Decimal = Decimal("5")  # 单笔最大仓位 USD
    max_trades_per_scan: int = 3        # 每次扫描最大交易数
    locations: list = field(default_factory=lambda: ["NYC"])  # 活跃城市
    min_hours_to_resolution: int = 2    # 距结算最少小时数
    min_tick_size: float = 0.01         # 最小可交易价格


@dataclass
class TelegramConfig:
    """Telegram 通知配置"""
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    topic_id: str = ""  # 群组话题ID


@dataclass
class LogConfig:
    """日志配置"""
    level: str = "INFO"
    file: str = "arbitrage.log"
    max_bytes: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5  # 保留5个备份文件


@dataclass
class Config:
    """主配置类"""
    api: APIConfig
    risk: RiskConfig
    weather: WeatherConfig
    telegram: TelegramConfig
    log: LogConfig
    dry_run: bool  # 模拟模式
    log_level: str  # 保留向后兼容


def load_config() -> Config:
    """从环境变量加载配置"""
    load_dotenv()

    api_config = APIConfig(
        api_key=os.getenv("POLYMARKET_API_KEY", ""),
        api_secret=os.getenv("POLYMARKET_API_SECRET", ""),
        passphrase=os.getenv("POLYMARKET_PASSPHRASE", ""),
        funder_address=os.getenv("POLYMARKET_FUNDER_ADDRESS", ""),
    )

    risk_config = RiskConfig(
        min_profit_threshold=Decimal(os.getenv("MIN_PROFIT_THRESHOLD", "0.005")),
        max_position_per_market=Decimal(os.getenv("MAX_POSITION_PER_MARKET", "100")),
        max_total_exposure=Decimal(os.getenv("MAX_TOTAL_EXPOSURE", "1000")),
        order_size=Decimal(os.getenv("ORDER_SIZE", "10")),
    )

    # 天气策略配置
    locations_str = os.getenv("WEATHER_LOCATIONS", "NYC")
    weather_locations = [loc.strip() for loc in locations_str.split(",") if loc.strip()]

    weather_config = WeatherConfig(
        enabled=os.getenv("WEATHER_ENABLED", "false").lower() == "true",
        auto_trade=os.getenv("WEATHER_AUTO_TRADE", "false").lower() == "true",
        entry_threshold=float(os.getenv("WEATHER_ENTRY_THRESHOLD", "0.35")),
        exit_threshold=float(os.getenv("WEATHER_EXIT_THRESHOLD", "0.65")),
        take_profit_pct=float(os.getenv("WEATHER_TAKE_PROFIT", "0.50")),
        stop_loss_pct=float(os.getenv("WEATHER_STOP_LOSS", "0.25")),
        max_position_usd=Decimal(os.getenv("WEATHER_MAX_POSITION", "5")),
        max_trades_per_scan=int(os.getenv("WEATHER_MAX_TRADES", "3")),
        locations=weather_locations,
        min_hours_to_resolution=int(os.getenv("WEATHER_MIN_HOURS", "2")),
    )

    telegram_config = TelegramConfig(
        enabled=os.getenv("TG_BOT_TOKEN", "") != "",
        bot_token=os.getenv("TG_BOT_TOKEN", ""),
        chat_id=os.getenv("TG_CHAT_ID", ""),
        topic_id=os.getenv("TG_TOPIC_ID", ""),
    )

    log_config = LogConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        file=os.getenv("LOG_FILE", "arbitrage.log"),
        max_bytes=int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024))),
        backup_count=int(os.getenv("LOG_BACKUP_COUNT", "5")),
    )

    return Config(
        api=api_config,
        risk=risk_config,
        weather=weather_config,
        telegram=telegram_config,
        log=log_config,
        dry_run=os.getenv("DRY_RUN", "true").lower() == "true",
        log_level=log_config.level,  # 保留向后兼容
    )
