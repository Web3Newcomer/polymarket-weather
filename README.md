# Polymarket 天气交易系统

基于 NOAA 政府天气预报的 Polymarket 天气市场交易系统。利用 NOAA 预报数据（1-2 天准确率约 85%）作为客观锚点，对抗市场定价偏差，捕捉低估的温度区间。

## 功能特性

- **NOAA 预报驱动**: 使用美国国家气象局官方预报数据，无需 LLM 主观判断
- **双模式运行**: 信号推送模式（默认）+ 自动交易模式（可选）
- **6 城市覆盖**: NYC、Chicago、Seattle、Atlanta、Dallas、Miami
- **自动止盈止损**: 可配置的止盈/止损比例，持仓自动跟踪
- **Telegram 推送**: 信号通知、交易执行、出场结果（含盈亏）实时推送
- **持仓持久化**: 重启后自动恢复持仓，不丢失交易状态
- **智能调度**: 睡眠时间自动暂停（23:00-08:00），去重防止重复推送

## 目录

- [策略原理](#策略原理)
- [系统架构](#系统架构)
- [安装配置](#安装配置)
- [使用方法](#使用方法)
- [运行模式](#运行模式)
- [Telegram 推送](#telegram-推送)
- [配置参数](#配置参数)
- [风险管理](#风险管理)

---

## 策略原理

### 核心思路

Polymarket 上有大量天气温度市场，例如：

```
事件: "Highest temperature in NYC on February 13?"

市场1: "33°F or below"     → YES $0.02
市场2: "34-35°F"           → YES $0.08
市场3: "36-37°F"           → YES $0.48  ← NOAA 预报 37°F，市场低估
市场4: "38-39°F"           → YES $0.30
市场5: "40-41°F"           → YES $0.08
市场6: "42-43°F"           → YES $0.03
市场7: "44°F or higher"    → YES $0.01
```

NOAA 预报 37°F → 匹配区间 "36-37°F" → 当前 YES 价格 $0.48 → 如果低于入场阈值则买入。

### 为什么有效？

| 传统 LLM 策略 | NOAA 天气策略 |
|---------------|--------------|
| 主观判断，容易产生共识偏差 | 客观数据锚点，NOAA 1-2 天准确率 ~85% |
| 信号质量不稳定 | 预报准确度可量化 |
| 需要多个付费 LLM API | 免费政府 API，无需 API Key |
| 适用范围广但精度低 | 专注天气市场，精度高 |

### 盈利逻辑

```
1. NOAA 预报更新 → 系统识别匹配的温度区间
2. 该区间 YES 价格低于阈值 → 买入（市场尚未充分反映预报）
3. 随着预报时间临近，市场逐渐修正定价
4. 价格上涨到出场阈值 / 触发止盈 → 卖出获利
```

---

## 系统架构

```
polymarket-swing-master/
├── src/
│   ├── main.py                 # 程序入口
│   ├── config.py               # 配置管理（环境变量）
│   ├── core/
│   │   └── engine.py           # 核心引擎（扫描循环、持仓管理、Telegram 推送）
│   ├── data/
│   │   ├── noaa_feed.py        # NOAA 天气预报 API 客户端
│   │   ├── market_feed.py      # Polymarket 市场数据聚合
│   │   └── rest_client.py      # Gamma API REST 客户端
│   ├── strategy/
│   │   └── weather.py          # 天气交易策略（入场/出场扫描）
│   ├── execution/
│   │   ├── order_manager.py    # 订单管理（天气买卖）
│   │   ├── clob_client.py      # Polymarket CLOB 下单客户端
│   │   ├── risk_manager.py     # 风险控制（敞口限制）
│   │   └── position_tracker.py # 持仓跟踪
│   ├── notification/
│   │   └── telegram.py         # Telegram 推送
│   ├── models/                 # 数据模型（Market, Signal, Order）
│   └── stats/
│       └── opportunity_tracker.py  # 机会统计
├── weather_positions.json      # 天气持仓记录（自动生成）
├── notify_cache.json           # 推送去重缓存（自动生成）
└── .env                        # 环境配置
```

### 数据流

```
┌─────────────────┐     ┌─────────────────┐
│   NOAA API      │     │  Gamma API      │
│ (天气预报数据)   │     │ (天气市场价格)   │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
          ┌─────────────────────┐
          │  WeatherStrategy    │
          │                     │
          │  1. 筛选天气市场     │
          │  2. 按事件分组       │
          │  3. 获取 NOAA 预报   │
          │  4. 匹配温度区间     │
          │  5. 价格低于阈值?    │
          └──────────┬──────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
  ┌──────────────┐    ┌──────────────────┐
  │ 信号推送模式  │    │  自动交易模式     │
  │              │    │                  │
  │ Telegram     │    │ OrderManager     │
  │ 推送信号     │    │ 执行买入/卖出     │
  │              │    │       ↓          │
  │              │    │ 持仓跟踪         │
  │              │    │ 止盈/止损检测     │
  │              │    │       ↓          │
  │              │    │ Telegram 推送    │
  │              │    │ 交易结果+盈亏    │
  └──────────────┘    └──────────────────┘
```

---

## 安装配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
# Polymarket API（自动交易模式需要）
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
POLYMARKET_PASSPHRASE=your_passphrase
POLYMARKET_FUNDER_ADDRESS=your_wallet_address

# 天气策略
WEATHER_ENABLED=true                # 启用天气策略
WEATHER_AUTO_TRADE=false            # 自动交易（默认关闭，仅推送信号）
WEATHER_ENTRY_THRESHOLD=0.25        # 入场阈值（YES 价格低于此值时买入）
WEATHER_EXIT_THRESHOLD=0.65         # 出场阈值（YES 价格高于此值时卖出）
WEATHER_TAKE_PROFIT=0.50            # 止盈比例（50%）
WEATHER_STOP_LOSS=0.25              # 止损比例（25%）
WEATHER_MAX_POSITION=5              # 单笔最大仓位 USD
WEATHER_MAX_TRADES=3                # 每次扫描最大交易数
WEATHER_LOCATIONS=NYC,Chicago,Seattle,Atlanta,Dallas,Miami
WEATHER_MIN_HOURS=2                 # 距结算最少小时数

# Telegram 推送
TG_BOT_TOKEN=your_bot_token        # 从 @BotFather 获取
TG_CHAT_ID=your_chat_id            # 群组/频道 ID
TG_TOPIC_ID=your_topic_id          # 可选，群组话题 ID

# 运行模式
DRY_RUN=true                        # 模拟模式（默认开启）
LOG_LEVEL=INFO
```

---

## 使用方法

### 启动命令

```bash
# 启动天气交易（1 小时扫描间隔）
python -m src.main

# 后台运行
nohup python -m src.main > arbitrage.log 2>&1 &
```

### 关闭进程

```bash
# 前台运行：Ctrl+C

# 查找并关闭
ps aux | grep "src.main"
kill <PID>

# 一键关闭
pkill -f "src.main"
```

---

## 运行模式

### 信号推送模式（默认）

`WEATHER_AUTO_TRADE=false`

只扫描市场、匹配 NOAA 预报、生成信号，通过 Telegram 推送。不执行任何交易。

适合：观察策略效果、手动决策交易。

### 自动交易模式

`WEATHER_AUTO_TRADE=true`

在信号推送的基础上，自动执行买入/卖出，并跟踪持仓的止盈止损。

**完整交易流程：**

```
每小时扫描
    │
    ▼
┌─────────────────────────────────────┐
│ 1. 加载天气市场（Gamma events API）  │
│ 2. 获取 NOAA 预报（6 城市）          │
│ 3. 匹配温度区间                      │
└──────────────┬──────────────────────┘
               │
    ┌──────────┴──────────┐
    ▼                     ▼
┌────────────┐    ┌──────────────┐
│  入场扫描   │    │  出场扫描     │
│            │    │              │
│ 预报匹配   │    │ 遍历持仓      │
│ 价格<阈值  │    │ 检查当前价格  │
│     ↓      │    │     ↓        │
│ 执行买入   │    │ 止盈: +50%   │
│ 记录持仓   │    │ 止损: -20%   │
│ Telegram   │    │ 阈值: >$0.45 │
│ 推送买入   │    │     ↓        │
│            │    │ 执行卖出     │
│            │    │ Telegram     │
│            │    │ 推送盈亏     │
└────────────┘    └──────────────┘
```

### 日志输出示例

```
2026-02-12 16:17:34 - INFO - Starting weather mode [AUTO-TRADE]...
2026-02-12 16:17:34 - INFO - Dry run: True
2026-02-12 16:17:34 - INFO - Locations: ['NYC', 'Chicago', 'Seattle', 'Atlanta', 'Dallas', 'Miami']
2026-02-12 16:17:34 - INFO - Entry: <$0.55 | Exit: >$0.45
2026-02-12 16:17:34 - INFO - Take profit: +50% | Stop loss: -20%
2026-02-12 16:17:38 - INFO - Loaded 290 weather markets from 56 events
2026-02-12 16:17:41 - INFO - NOAA forecast for NYC: 7 days
2026-02-12 16:17:41 - INFO - BUY signal: NYC 2026-02-12 36-37°F @ $0.545
2026-02-12 16:17:42 - INFO - [DRY RUN] Weather BUY: 20.00 shares @ $0.5
2026-02-12 16:17:44 - INFO - SELL signal (exit_threshold): NYC 36-37°F @ $0.545 (entry: $0.5)
2026-02-12 16:17:44 - INFO - [DRY RUN] Weather SELL: 20.00 shares @ $0.6
2026-02-12 16:17:45 - INFO - Scan complete: 290 markets, 5 entry signals, 5 trades, 3 open positions
```

---

## Telegram 推送

### 配置

```bash
TG_BOT_TOKEN=your_bot_token    # 从 @BotFather 获取
TG_CHAT_ID=your_chat_id        # 群组/频道 ID（负数）
TG_TOPIC_ID=your_topic_id      # 可选，群组话题 ID
```

### 推送类型

系统根据不同事件推送不同格式的消息：

#### 1. 交易信号（两种模式都推送）

```
🌤️ 天气交易信号

📍 城市: NYC
📅 日期: 2026-02-13
🌡️ NOAA预报: 37°F
📊 匹配区间: 36-37°F
💰 当前价格: $0.12
📈 建议操作: 买入 YES

🔗 查看市场
```

#### 2. 交易执行（仅自动交易模式）

```
✅ 交易执行 - 买入

📍 NYC 2026-02-13 | 36-37°F
💰 买入价: $0.12
📦 数量: 83.3 shares
💵 花费: $10
🎯 止盈: $0.180 (+50%)
🛑 止损: $0.096 (-20%)

🔗 查看市场
```

#### 3. 出场结果（仅自动交易模式）

```
🎯 止盈触发

📍 NYC 2026-02-13 | 36-37°F
💰 买入价: $0.12 → 当前: $0.20
📦 卖出: 83.3 shares
💵 盈利: +$6.66 (+66.7%)

🔗 查看市场
```

### 推送规则

| 条件 | 值 |
|------|-----|
| 去重冷却 | 同一市场 6 小时内不重复推送 |
| 扫描间隔 | 1 小时 |
| 睡眠时间 | 23:00 - 08:00 不扫描 |
| 缓存持久化 | `notify_cache.json`，重启后保留 |

---

## 配置参数

### 天气策略参数

| 参数 | 环境变量 | 说明 | 默认值 |
|------|---------|------|--------|
| 启用策略 | `WEATHER_ENABLED` | 是否启用天气策略 | `false` |
| 自动交易 | `WEATHER_AUTO_TRADE` | 自动执行交易（关闭则仅推送信号） | `false` |
| 入场阈值 | `WEATHER_ENTRY_THRESHOLD` | YES 价格低于此值时生成买入信号 | `0.25` |
| 出场阈值 | `WEATHER_EXIT_THRESHOLD` | YES 价格高于此值时触发出场 | `0.65` |
| 止盈比例 | `WEATHER_TAKE_PROFIT` | 浮盈达到此比例时止盈 | `0.50` (50%) |
| 止损比例 | `WEATHER_STOP_LOSS` | 浮亏达到此比例时止损 | `0.25` (25%) |
| 单笔仓位 | `WEATHER_MAX_POSITION` | 单笔最大投入 USD | `5` |
| 扫描交易数 | `WEATHER_MAX_TRADES` | 每次扫描最多执行交易数 | `3` |
| 活跃城市 | `WEATHER_LOCATIONS` | 逗号分隔的城市列表 | `NYC` |
| 最少时间 | `WEATHER_MIN_HOURS` | 距结算最少小时数 | `2` |

### 支持的城市

| 城市 | 配置值 | 气象站 |
|------|--------|--------|
| 纽约 | `NYC` | LaGuardia Airport |
| 芝加哥 | `Chicago` | O'Hare Airport |
| 西雅图 | `Seattle` | Sea-Tac Airport |
| 亚特兰大 | `Atlanta` | Hartsfield Airport |
| 达拉斯 | `Dallas` | DFW Airport |
| 迈阿密 | `Miami` | MIA Airport |

### Telegram 参数

| 参数 | 环境变量 | 说明 |
|------|---------|------|
| Bot Token | `TG_BOT_TOKEN` | 从 @BotFather 获取 |
| Chat ID | `TG_CHAT_ID` | 群组/频道 ID |
| Topic ID | `TG_TOPIC_ID` | 可选，群组话题 ID |

### 通用参数

| 参数 | 环境变量 | 说明 | 默认值 |
|------|---------|------|--------|
| 模拟模式 | `DRY_RUN` | 不执行真实交易 | `true` |
| 日志级别 | `LOG_LEVEL` | INFO / DEBUG | `INFO` |
| 日志文件 | `LOG_FILE` | 日志文件路径 | `arbitrage.log` |

---

## 风险管理

### 入场条件

1. NOAA 预报温度落在某个温度区间内
2. 该区间的 YES 价格低于入场阈值（默认 $0.15）
3. 价格不低于最小 tick（$0.01）且不高于 $0.99
4. 未超过每次扫描最大交易数限制

### 出场条件（按优先级）

| 条件 | 触发规则 | 说明 |
|------|---------|------|
| 止损 | 浮亏 ≥ 25% | 及时止损，控制单笔亏损 |
| 止盈 | 浮盈 ≥ 50% | 锁定利润 |
| 阈值出场 | 价格 ≥ $0.65 | 正常获利了结 |

### 持仓持久化

- 持仓保存在 `weather_positions.json`
- 每次买入/卖出后自动更新
- 程序重启后自动加载，不丢失交易状态
- 文件损坏时降级为空持仓，记录警告日志

### 风险提示

1. **预报偏差** — NOAA 1-2 天准确率约 85%，仍有 15% 概率预报不准
2. **市场流动性** — 天气市场流动性较低，大单可能滑点
3. **阈值设置** — 入场阈值过高会增加交易频率但降低胜率
4. **网络依赖** — 依赖 NOAA API 和 Polymarket API 的可用性

### 建议配置

**保守策略（推荐新手）：**
```bash
WEATHER_AUTO_TRADE=false        # 先观察信号质量
WEATHER_ENTRY_THRESHOLD=0.25    # 只在明显低估时提示
DRY_RUN=true
```

**稳健策略：**
```bash
WEATHER_AUTO_TRADE=true
WEATHER_ENTRY_THRESHOLD=0.25
WEATHER_MAX_POSITION=5
WEATHER_TAKE_PROFIT=0.50
WEATHER_STOP_LOSS=0.25
DRY_RUN=false
```

**激进策略：**
```bash
WEATHER_AUTO_TRADE=true
WEATHER_ENTRY_THRESHOLD=0.45
WEATHER_MAX_POSITION=25
WEATHER_MAX_TRADES=10
WEATHER_TAKE_PROFIT=0.30
WEATHER_STOP_LOSS=0.15
DRY_RUN=false
```

---

## 监控与调试

### 查看日志

```bash
# 实时查看
tail -f arbitrage.log

# 只看交易相关
grep -E "(BUY signal|SELL signal|Weather BUY|Weather SELL|Scan complete)" arbitrage.log

# 只看 NOAA 预报
grep "NOAA" arbitrage.log

# 查看推送状态
grep "Telegram" arbitrage.log
```

### 查看持仓

```bash
cat weather_positions.json
```

### 查看推送缓存

```bash
cat notify_cache.json
```

### 调试模式

```bash
LOG_LEVEL=DEBUG python -m src.main
```

---

## 数据源

| 数据类型 | 来源 | 费用 |
|----------|------|------|
| 天气预报 | NOAA (api.weather.gov) | 免费，无需 API Key |
| 市场数据 | Polymarket Gamma API | 免费 |
| 订单执行 | Polymarket CLOB API | 需要 API 凭证 |

---

## 免责声明

本项目仅供学习和研究目的。使用本软件进行交易的风险由用户自行承担。NOAA 预报数据不保证 100% 准确，交易结果不构成投资建议。
