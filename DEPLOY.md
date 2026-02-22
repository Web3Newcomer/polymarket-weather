# Polymarket Weather Bot 部署指南（Ubuntu VPS）

## 前置条件

- Ubuntu 22.04+ VPS
- Python 3.8+
- 有 sudo 权限的用户

## 1. 服务器初始化

```bash
# 创建部署用户
sudo useradd -m -s /bin/bash deploy

# 安装 Python
sudo apt update && sudo apt install -y python3 python3-venv git
```

## 2. 上传代码

**方式 A：Git 克隆**
```bash
sudo -u deploy git clone <repo-url> /home/deploy/polymarket-weather
```

**方式 B：本地 rsync**
```bash
rsync -avz --exclude='.env' --exclude='__pycache__' --exclude='.git' \
  ./ deploy@<vps-ip>:/home/deploy/polymarket-weather/
```

## 3. 安装依赖

```bash
sudo -u deploy bash -c '
  cd /home/deploy/polymarket-weather
  python3 -m venv venv
  venv/bin/pip install -r requirements.txt
'
```

## 4. 配置环境变量

```bash
# 从本地安全传输 .env 文件
scp .env deploy@<vps-ip>:/home/deploy/polymarket-weather/.env
```

关键配置项（编辑 `.env`）：

| 变量 | 说明 | 示例 |
|------|------|------|
| `POLYMARKET_API_KEY` | API 密钥 | |
| `POLYMARKET_API_SECRET` | API 密钥 | |
| `POLYMARKET_PASSPHRASE` | 口令 | |
| `DRY_RUN` | 模拟模式 | `true` / `false` |
| `WEATHER_AUTO_TRADE` | 自动交易 | `false`（先用信号模式验证） |
| `TG_BOT_TOKEN` | Telegram 机器人 | |
| `TG_CHAT_ID` | Telegram 群组 | |

## 5. 安装 systemd 服务

```bash
sudo cp /home/deploy/polymarket-weather/polymarket-weather.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polymarket-weather
sudo systemctl start polymarket-weather
```

## 6. 验证运行

```bash
# 查看服务状态
sudo systemctl status polymarket-weather

# 实时日志
sudo journalctl -u polymarket-weather -f

# 应用日志
tail -f /home/deploy/polymarket-weather/arbitrage.log
```

## 日常运维

```bash
# 停止服务
sudo systemctl stop polymarket-weather

# 重启服务
sudo systemctl restart polymarket-weather

# 更新代码并重启
sudo -u deploy bash -c 'cd /home/deploy/polymarket-weather && git pull && venv/bin/pip install -r requirements.txt'
sudo systemctl restart polymarket-weather
```

## 数据文件

以下文件由程序自动生成，重启后自动恢复：

- `weather_positions.json` — 持仓记录
- `tracked_signals.json` — 信号跟踪
- `notify_cache.json` — 推送去重缓存
- `arbitrage.log` — 运行日志（自动轮转，10MB × 5）

## 故障排查

```bash
# 服务启动失败
sudo journalctl -u polymarket-weather --no-pager -n 50

# 手动测试运行
sudo -u deploy bash -c 'cd /home/deploy/polymarket-weather && venv/bin/python -m src.main'

# 检查 .env 是否加载
sudo -u deploy bash -c 'cd /home/deploy/polymarket-weather && venv/bin/python -c "from src.config import load_config; c=load_config(); print(c.weather.enabled)"'
```
