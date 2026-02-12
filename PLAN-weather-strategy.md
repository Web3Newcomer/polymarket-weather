# 天气策略重构方案

## 背景

现有的 swing trading 策略（多模型 LLM 辩论）信号质量差，几乎全部输出 BUY NO。根本原因是 LLM 在没有硬数据锚点的情况下做主观判断，容易产生一致性偏差。

参考 Simmer 的 weather_trader.py 策略思路，用 NOAA 政府天气预报数据（1-2天预测准确率~85%）作为客观锚点，对抗 Polymarket 天气市场的定价偏差。

**核心原则：不依赖 Simmer SDK，只借鉴策略方法，用我们自己的 Polymarket CLOB 直连执行交易。**

---

## 运行模式

系统有两种运行模式，通过 `WEATHER_AUTO_TRADE` 控制：

### 信号模式（默认）
- `WEATHER_AUTO_TRADE=false`
- 扫描市场 → 生成信号 → **只推送到 Telegram，不执行交易**
- 用户看到信号后自行决定是否手动交易
- 适合初期验证策略、不想承担自动交易风险的场景

### 自动交易模式
- `WEATHER_AUTO_TRADE=true`
- 扫描市场 → 生成信号 → **自动执行交易** → 推送交易结果到 Telegram
- 每个持仓自动跟踪止盈止损，触发时自动平仓
- 所有交易操作（买入、卖出、止盈、止损）都推送到 Telegram

---

## 策略逻辑

```
每个扫描周期：
1. 从 Polymarket Gamma API 获取天气相关市场（按关键词筛选）
2. 解析市场事件名 → 提取城市、日期、高温/低温
3. 调用 NOAA API 获取该城市该日期的天气预报
4. 找到预报温度对应的温度区间 bucket（如 "34-35°F"）
5. 入场判断：该 bucket 的 YES 价格 < 入场阈值（默认 0.15）→ 生成 BUY 信号
6. 出场判断：
   a. 正常出场：持仓价格 > 出场阈值（默认 0.45）→ 生成 SELL 信号
   b. 止盈：持仓浮盈 ≥ 止盈比例（默认 50%）→ 生成 SELL 信号
   c. 止损：持仓浮亏 ≥ 止损比例（默认 20%）→ 生成 SELL 信号
7. 安全检查：滑点、距结算时间、极端价格等
8. 信号模式 → Telegram 推送信号
   自动交易模式 → 执行交易 → Telegram 推送交易结果
```

---

## Telegram 推送设计

### 信号推送（两种模式都会发）

```
🌤️ 天气交易信号

📍 城市: NYC
📅 日期: 2026-02-13
🌡️ NOAA预报: 34°F
📊 匹配区间: 34-35°F
💰 当前价格: $0.12
📈 建议操作: 买入 YES

🔗 查看市场
```

### 交易执行推送（仅自动交易模式）

买入成功：
```
✅ 交易执行 - 买入

📍 NYC 2026-02-13 | 34-35°F
💰 买入价: $0.12
📦 数量: 83.3 shares
💵 花费: $10.00
🎯 止盈: $0.18 (+50%)
🛑 止损: $0.096 (-20%)

🔗 查看市场
```

止盈触发：
```
🎯 止盈触发

📍 NYC 2026-02-13 | 34-35°F
💰 买入价: $0.12 → 当前: $0.19
📦 卖出: 83.3 shares
💵 盈利: +$5.83 (+58.3%)

🔗 查看市场
```

止损触发：
```
🛑 止损触发

📍 NYC 2026-02-13 | 34-35°F
💰 买入价: $0.12 → 当前: $0.09
📦 卖出: 83.3 shares
💵 亏损: -$2.50 (-25.0%)

🔗 查看市场
```

正常出场（价格达到出场阈值）：
```
📤 正常出场

📍 NYC 2026-02-13 | 34-35°F
💰 买入价: $0.12 → 当前: $0.48
📦 卖出: 83.3 shares
💵 盈利: +$30.00 (+300.0%)

🔗 查看市场
```

---

## 文件变更清单

### 新增文件

#### 1. `src/data/noaa_feed.py` — NOAA 天气数据源

异步版本的 NOAA API 客户端，复用现有的 aiohttp 模式。

```python
class NOAAFeed:
    """NOAA 天气预报数据源"""

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

    async def get_forecast(self, location: str) -> dict[str, dict]:
        """获取某城市的天气预报
        返回: {"2026-02-13": {"high": 34, "low": 22}, ...}
        """

    async def close(self):
        """关闭 aiohttp session"""
```

关键点：
- NOAA API 免费，无需 API key，只需设置 User-Agent
- 两步请求：先 `/points/{lat},{lon}` 获取 grid，再请求 forecast URL
- 预报缓存：同一城市同一扫描周期内只请求一次（缓存在内存中，每周期刷新）
- 请求头需要 `User-Agent` 和 `Accept: application/geo+json`

#### 2. `src/strategy/weather.py` — 天气交易策略

核心策略类，替代现有的 `swing_trading.py`。

```python
@dataclass
class WeatherSignal:
    """天气交易信号"""
    market_id: str           # condition_id
    token_id: str            # YES token_id（用于下单）
    action: str              # "BUY" 或 "SELL"
    price: Decimal           # 当前价格
    amount: Decimal          # 交易金额（USD）
    location: str            # 城市
    date: str                # 预报日期
    forecast_temp: int       # NOAA 预报温度
    bucket_name: str         # 匹配的温度区间名
    reasoning: str           # 交易理由
    market_url: str = ""     # 市场链接
    market_question: str = ""  # 市场问题（用于推送）


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
    """天气交易策略"""

    def __init__(self, config: WeatherConfig, noaa_feed: NOAAFeed):
        self.config = config
        self.noaa = noaa_feed
        self._forecast_cache: dict[str, dict] = {}

    async def scan_entries(self, markets: list[Market]) -> list[WeatherSignal]:
        """扫描入场机会"""

    async def scan_exits(
        self, positions: list[WeatherPosition], markets: list[Market]
    ) -> list[WeatherSignal]:
        """扫描出场机会
        检查三种出场条件：
        1. 价格 ≥ exit_threshold → 正常出场
        2. 浮盈 ≥ take_profit_pct → 止盈
        3. 浮亏 ≥ stop_loss_pct → 止损
        """

    def clear_cache(self):
        """清除预报缓存（每个扫描周期开始时调用）"""
```

从 Simmer weather_trader.py 移植的关键函数（改为类方法）：
- `_parse_weather_event(event_name)` → 解析事件名，提取城市/日期/metric
- `_parse_temperature_bucket(outcome_name)` → 解析温度区间 "34-35°F" → (34, 35)
- `_is_weather_market(question)` → 关键词判断是否天气市场
- `_check_safeguards(market, price)` → 安全检查（极端价格、距结算时间等）

### 修改文件

#### 3. `src/config.py` — 配置管理

- 将 `SwingConfig` 替换为 `WeatherConfig`
- 移除 LLM API key 相关配置（anthropic_api_key, openai_api_key, gemini_api_key, debate_enabled）
- 移除 `ScreenerConfig`
- 新增天气策略环境变量（见下方环境变量章节）
- `Config` 主类中 `swing: SwingConfig` → `weather: WeatherConfig`，移除 `screener`

```python
@dataclass
class WeatherConfig:
    """天气策略配置"""
    enabled: bool = False
    auto_trade: bool = False            # 自动交易开关，默认关闭（只推送信号）
    entry_threshold: float = 0.15       # 买入阈值
    exit_threshold: float = 0.45        # 卖出阈值
    take_profit_pct: float = 0.50       # 止盈比例（50%）
    stop_loss_pct: float = 0.20         # 止损比例（20%）
    max_position_usd: Decimal = Decimal("10")
    max_trades_per_scan: int = 5
    locations: list[str] = field(default_factory=lambda: ["NYC"])
    min_hours_to_resolution: int = 2
    min_tick_size: float = 0.01
```

#### 4. `src/core/engine.py` — 核心引擎

大幅简化，移除 swing/debate/screener 相关逻辑：

- 移除 `_init_strategies()` 中的 `SwingTradingStrategy` 和 `BinaryArbitrageStrategy`
- 移除 `_ensure_screener()`、`_build_dynamic_weights()`
- 移除 `_get_swing_context()`、`_build_swing_context()`
- 移除 `_scan_with_screening()`、`_analyze_single_market()`
- 移除 `_scan_swing_markets()`、`run_swing()`
- 移除 `_format_reasoning()`

新增：

```python
# 天气持仓文件（持久化，重启后恢复）
WEATHER_POSITIONS_FILE = "weather_positions.json"

async def run_weather(self, interval: int = 3600):
    """运行天气交易模式"""
    # 1. 初始化 NOAAFeed + WeatherStrategy
    # 2. 从文件加载已有持仓（weather_positions.json）
    # 3. 主循环：
    #    a. 睡眠时间检查
    #    b. 从 Gamma API 获取市场
    #    c. strategy.clear_cache()
    #    d. entry_signals = strategy.scan_entries(weather_markets)
    #    e. exit_signals = strategy.scan_exits(positions, weather_markets)
    #    f. 对每个信号：
    #       - 推送信号到 Telegram（两种模式都推）
    #       - 如果 auto_trade=true：
    #         - 风控检查 → 执行交易
    #         - 买入成功 → 记录持仓（含 entry_price）→ 推送交易结果
    #         - 卖出成功 → 移除持仓 → 推送盈亏结果
    #       - 保存持仓到文件
    #    g. 等待 interval
```

Telegram 推送方法：

```python
def _send_weather_signal(self, signal: WeatherSignal):
    """推送天气交易信号（信号模式 + 自动交易模式都调用）"""

def _send_trade_executed(self, signal: WeatherSignal, shares: Decimal, take_profit: Decimal, stop_loss: Decimal):
    """推送交易执行结果（仅自动交易模式）"""

def _send_exit_result(self, position: WeatherPosition, current_price: Decimal, exit_type: str):
    """推送出场结果（仅自动交易模式）
    exit_type: "take_profit" | "stop_loss" | "exit_threshold"
    """
```

持仓持久化：

```python
def _load_weather_positions(self) -> list[WeatherPosition]:
    """从 weather_positions.json 加载持仓"""

def _save_weather_positions(self, positions: list[WeatherPosition]):
    """保存持仓到 weather_positions.json"""
```

#### 5. `src/main.py` — 入口

- `--mode` 选项改为 `poll | realtime | weather`（`swing` → `weather`）
- `weather` 模式调用 `engine.run_weather()`

#### 6. `src/execution/order_manager.py` — 订单管理器

- 新增 `execute_weather_buy(token_id, amount)` 和 `execute_weather_sell(token_id, shares)` 方法
- 天气策略只买卖单边（BUY YES 或 SELL YES），不需要现有的双边套利逻辑
- dry_run 模式下记录模拟交易
- 返回执行结果（成交份额、成交价格）供 engine 记录持仓和推送

```python
@dataclass
class WeatherTradeResult:
    """天气交易执行结果"""
    success: bool
    shares: Decimal = Decimal("0")    # 成交份额
    avg_price: Decimal = Decimal("0") # 成交均价
    error: str = ""

async def execute_weather_buy(self, token_id: str, amount: Decimal) -> WeatherTradeResult:
    """执行天气策略买入"""

async def execute_weather_sell(self, token_id: str, shares: Decimal) -> WeatherTradeResult:
    """执行天气策略卖出"""
```

### 删除文件

以下文件将被删除，不再需要：

| 文件 | 原因 |
|------|------|
| `src/analysis/debate.py` | LLM 多模型辩论，不再使用 |
| `src/analysis/llm_analyzer.py` | LLM 单模型分析，不再使用 |
| `src/analysis/market_screener.py` | 通用市场筛选器，天气策略不需要 |
| `src/analysis/signal_generator.py` | 波段信号生成器，被 WeatherStrategy 替代 |
| `src/strategy/swing_trading.py` | 波段交易策略，被 WeatherStrategy 替代 |
| `src/strategy/binary_arb.py` | 二元套利策略，不再使用 |
| `src/data/price_feed.py` | BTC 价格源，天气策略不需要 |
| `src/data/news_feed.py` | 新闻源，天气策略不需要 |

### 保留不变的文件

| 文件 | 说明 |
|------|------|
| `src/data/rest_client.py` | Polymarket Gamma API 客户端，用于获取市场数据 |
| `src/data/market_feed.py` | 市场数据聚合器，用于加载和缓存市场 |
| `src/data/websocket_client.py` | WebSocket 客户端（realtime 模式） |
| `src/execution/clob_client.py` | Polymarket CLOB 下单客户端 |
| `src/execution/risk_manager.py` | 风控管理器（仓位限制、敞口控制） |
| `src/execution/position_tracker.py` | 持仓跟踪器 |
| `src/notification/telegram.py` | Telegram 推送 |
| `src/models/market.py` | Market/Outcome 数据模型 |
| `src/models/order.py` | Order 数据模型 |
| `src/stats/opportunity_tracker.py` | 机会统计跟踪 |
| `src/strategy/base.py` | 策略基类 |

---

## 环境变量变更

### 移除

```
ANTHROPIC_API_KEY
OPENAI_API_KEY
GEMINI_API_KEY
DEBATE_ENABLED
SWING_ENABLED
SWING_CONFIDENCE_THRESHOLD
SWING_TAKE_PROFIT
SWING_STOP_LOSS
SWING_MAX_POSITION
SWING_TOTAL_EXPOSURE
SWING_MAX_HOLD_DAYS
TARGET_MARKETS
SCREENER_MIN_VOLUME_24H
SCREENER_MIN_LIQUIDITY
SCREENER_MIN_SCORE
SCREENER_TOP_N
SCREENER_DATA_BACKED_ONLY
```

### 新增

```
WEATHER_ENABLED=true              # 启用天气策略
WEATHER_AUTO_TRADE=false          # 自动交易开关（默认关闭，只推送信号）
WEATHER_ENTRY_THRESHOLD=0.15      # 入场阈值（价格低于此值买入）
WEATHER_EXIT_THRESHOLD=0.45       # 出场阈值（价格高于此值卖出）
WEATHER_TAKE_PROFIT=0.50          # 止盈比例（50%浮盈时卖出）
WEATHER_STOP_LOSS=0.20            # 止损比例（20%浮亏时卖出）
WEATHER_MAX_POSITION=10           # 单笔最大仓位 USD
WEATHER_MAX_TRADES=5              # 每次扫描最大交易数
WEATHER_LOCATIONS=NYC             # 活跃城市，逗号分隔
WEATHER_MIN_HOURS=2               # 距结算最少小时数
```

### 保留

```
POLYMARKET_API_KEY / API_SECRET / PASSPHRASE / FUNDER_ADDRESS
TG_BOT_TOKEN / TG_CHAT_ID / TG_TOPIC_ID
DRY_RUN
LOG_LEVEL
MIN_PROFIT_THRESHOLD / MAX_POSITION_PER_MARKET / MAX_TOTAL_EXPOSURE / ORDER_SIZE
```

---

## 止盈止损机制

### 实现方式

不使用外部服务监控，而是在每个扫描周期内自行检查：

```python
# 在 WeatherStrategy.scan_exits() 中
for position in positions:
    current_price = get_current_price(position.token_id)
    pnl_pct = (current_price - position.entry_price) / position.entry_price

    if pnl_pct >= config.take_profit_pct:
        # 止盈：浮盈达到 50%
        yield WeatherSignal(action="SELL", reasoning="止盈触发")

    elif pnl_pct <= -config.stop_loss_pct:
        # 止损：浮亏达到 20%
        yield WeatherSignal(action="SELL", reasoning="止损触发")

    elif current_price >= config.exit_threshold:
        # 正常出场：价格达到出场阈值
        yield WeatherSignal(action="SELL", reasoning="达到出场阈值")
```

### 持仓持久化

自动交易模式下，持仓信息保存到 `weather_positions.json`，格式：

```json
[
  {
    "market_id": "0x...",
    "token_id": "12345",
    "entry_price": "0.12",
    "shares": "83.33",
    "cost": "10.00",
    "location": "NYC",
    "date": "2026-02-13",
    "bucket_name": "34-35°F",
    "market_url": "https://polymarket.com/event/...",
    "market_question": "What will be the highest temperature...",
    "created_at": 1739404800
  }
]
```

重启后自动加载，继续跟踪止盈止损。

---

## 天气市场筛选逻辑

Polymarket 天气市场没有专门的 tag，需要通过 `question` 字段关键词匹配：

```python
WEATHER_KEYWORDS = [
    "temperature", "°F", "°f",
    "highest temp", "lowest temp",
    "high temp", "low temp",
    "weather",
]

def _is_weather_market(question: str) -> bool:
    q = question.lower()
    return any(kw.lower() in q for kw in WEATHER_KEYWORDS)
```

从 Gamma API 获取市场后，先用关键词过滤出天气市场，再按事件分组处理。

---

## 多结果市场处理

天气市场通常是多结果市场（multi-outcome），不是二元市场。例如一个 "NYC 2月13日最高温" 事件下有多个温度区间：
- "32-33°F" → YES/NO
- "34-35°F" → YES/NO
- "36°F or higher" → YES/NO
- ...

每个温度区间是一个独立的二元市场（有自己的 condition_id 和 token_id）。策略只需要找到 NOAA 预报温度匹配的那个 bucket，然后买入该 bucket 的 YES。

现有的 `Market` 模型和 `rest_client.py` 已经支持解析这些市场，不需要修改。

---

## 实施顺序

1. **新增 `src/data/noaa_feed.py`** — NOAA API 客户端
2. **新增 `src/strategy/weather.py`** — 天气策略（含 WeatherConfig、WeatherSignal、WeatherPosition）
3. **修改 `src/config.py`** — 替换配置（SwingConfig → WeatherConfig，移除 ScreenerConfig）
4. **修改 `src/execution/order_manager.py`** — 新增天气交易执行方法
5. **修改 `src/core/engine.py`** — 替换主循环，新增持仓管理和 Telegram 推送逻辑
6. **修改 `src/main.py`** — 更新 CLI 模式（swing → weather）
7. **删除废弃文件** — debate.py, llm_analyzer.py, market_screener.py, signal_generator.py, swing_trading.py, binary_arb.py, price_feed.py, news_feed.py
8. **更新 `.env.example`** — 环境变量文档
9. **更新测试** — 新增天气策略测试，删除旧测试
10. **更新 `CLAUDE.md`** — 反映新架构

---

## 依赖变更

### 无需新增

NOAA API 用 aiohttp 请求即可，不需要额外依赖。现有依赖（aiohttp, pydantic, websockets）天气策略都会用到。

---

## 风险与注意事项

1. **NOAA API 限流**：无官方限流文档，但建议每个城市每周期只请求一次（缓存）
2. **NOAA API 可用性**：偶尔会 503，需要重试机制（已有 rest_client 的重试模式可参考）
3. **天气市场季节性**：某些季节可能没有活跃的天气市场，策略应优雅处理空结果
4. **温度区间解析**：需要处理多种格式（"34-35°F"、"36°F or higher"、"32°F or below"）
5. **时区**：NOAA 返回的是本地时间，Polymarket 市场结算可能用 UTC，需要注意对齐
6. **多结果市场**：确保从 Gamma API 能正确获取到天气市场的所有 outcome 及其价格
7. **止盈止损精度**：扫描间隔为 1 小时，极端行情下实际触发价格可能偏离阈值，这是轮询模式的固有限制
8. **持仓文件损坏**：weather_positions.json 读写需要异常处理，损坏时应能优雅降级（清空持仓，日志告警）
