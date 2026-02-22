# Polymarket 天气交易系统

基于 NOAA 政府天气预报的 Polymarket 天气市场交易系统。利用 NOAA 预报数据（1-2 天准确率约 85%）作为客观锚点，对抗市场定价偏差，捕捉低估的温度区间。

## 策略流程

```
NOAA 预报更新 → 匹配温度区间 → 价格低于阈值 → 买入 YES → 市场修正 → 止盈/止损卖出
```

示例：NOAA 预报 NYC 37°F → 匹配 "36-37°F" 区间 → YES 价格 $0.12（低于阈值 $0.25）→ 买入 → 价格涨至 $0.16（+30%）→ 止盈。

两种模式：
- **信号模式**（默认）：扫描市场 → Telegram 推送信号，不执行交易
- **自动交易模式**：扫描 → 自动买入/卖出 → 止盈止损 → Telegram 推送结果

覆盖 6 城市：NYC、Chicago、Seattle、Atlanta、Dallas、Miami。每小时扫描，23:00-08:00 休眠。

## 安装运行

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 Polymarket API 密钥、Telegram token 等

# 运行
python -m src.main
```

关键 `.env` 配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WEATHER_ENABLED` | 启用天气策略 | `false` |
| `WEATHER_AUTO_TRADE` | 自动交易（关闭则仅推送信号） | `false` |
| `WEATHER_ENTRY_THRESHOLD` | 入场阈值（YES 价格低于此值买入） | `0.35` |
| `WEATHER_TAKE_PROFIT` | 止盈比例 | `0.30` |
| `WEATHER_STOP_LOSS` | 止损比例 | `0.25` |
| `WEATHER_MAX_POSITION` | 单笔最大仓位 USD | `5` |
| `WEATHER_LOCATIONS` | 城市列表（逗号分隔） | `NYC` |
| `DRY_RUN` | 模拟模式 | `true` |
| `TG_BOT_TOKEN` | Telegram Bot Token | |
| `TG_CHAT_ID` | Telegram 群组 ID | |

## 部署与监控（systemd）

详见 [DEPLOY.md](DEPLOY.md)。

```bash
# 服务状态
sudo systemctl status polymarket-weather

# 实时日志
sudo journalctl -u polymarket-weather -f

# 重启 / 停止
sudo systemctl restart polymarket-weather
sudo systemctl stop polymarket-weather

# 应用日志
tail -f arbitrage.log

# 调试模式
LOG_LEVEL=DEBUG python -m src.main
```

自动生成的数据文件（重启自动恢复）：
- `weather_positions.json` — 持仓记录
- `tracked_signals.json` — 信号跟踪
- `notify_cache.json` — 推送去重缓存
- `arbitrage.log` — 运行日志（10MB × 5 自动轮转）
