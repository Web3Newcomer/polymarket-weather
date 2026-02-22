# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Weather trading bot for Polymarket prediction markets. Uses NOAA government weather forecasts as objective price anchors against Polymarket weather market pricing. Two modes: signal-only (default, Telegram push) and auto-trade (execute trades with stop-loss/take-profit). Written in Python with async/await throughout.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run weather trading bot (1-hour scan intervals)
python -m src.main

# Run with debug logging
LOG_LEVEL=DEBUG python -m src.main

# Run tests
pytest tests/
pytest tests/test_risk_manager.py          # single test file
pytest tests/test_risk_manager.py -k "test_name"  # single test
```

## Configuration

All config via environment variables loaded from `.env` by `src/config.py`. Key groups:

- **Polymarket API:** `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, `POLYMARKET_PASSPHRASE`, `POLYMARKET_FUNDER_ADDRESS`
- **Weather strategy:** `WEATHER_ENABLED`, `WEATHER_AUTO_TRADE`, `WEATHER_ENTRY_THRESHOLD`, `WEATHER_EXIT_THRESHOLD`, `WEATHER_TAKE_PROFIT`, `WEATHER_STOP_LOSS`, `WEATHER_MAX_POSITION`, `WEATHER_MAX_TRADES`, `WEATHER_LOCATIONS`, `WEATHER_MIN_HOURS`
- **Telegram:** `TG_BOT_TOKEN`, `TG_CHAT_ID`, `TG_TOPIC_ID` (Telegram is auto-enabled when `TG_BOT_TOKEN` is set)
- **General:** `DRY_RUN=true` (default), `LOG_LEVEL`, `LOG_FILE`

## Architecture

**Entry point:** `src/main.py` → `load_config()` → creates `Engine` → calls `engine.run_weather()`.

**Main loop (`Engine.run_weather`):** 1-hour scan cycle with sleep-time skip (23:00–08:00). Each cycle: refresh markets → scan entries → track signals → scan exits (auto-trade only). SIGINT triggers graceful `engine.stop()`.

**Data flow:**
```
NOAA Weather API (forecast data)
  + Polymarket Gamma API (weather market prices via events endpoint)
  → WeatherStrategy (match NOAA forecast to temperature buckets, find underpriced YES tokens)
  → Signal-only: TelegramNotifier (push signal alerts)
  → Auto-trade: OrderManager (limit GTC orders) + TelegramNotifier (push trade results)
```

**Key modules:**
- `src/core/engine.py` — Orchestration: `run_weather()` loop, position/signal persistence, all Telegram push methods, notify dedup (6h cooldown via `notify_cache.json`)
- `src/strategy/weather.py` — `WeatherStrategy`: `scan_entries()` (NOAA vs market price), `scan_exits()` (stop-loss/take-profit/threshold). Parses temperature buckets from market questions via regex. NOAA forecasts pre-fetched in parallel per cycle.
- `src/data/noaa_feed.py` — Async NOAA API client, 2-step fetch (grid lookup → forecast). 6 cities with airport weather stations.
- `src/data/market_feed.py` — Polymarket Gamma API market data aggregator
- `src/data/rest_client.py` — Low-level Gamma API REST client
- `src/execution/order_manager.py` — `execute_weather_buy/sell()` with dry-run support. Uses limit GTC orders via CLOB.
- `src/execution/clob_client.py` — Polymarket CLOB API client (order placement, price queries)
- `src/stats/signal_tracker.py` — Tracks all signals post-push: price updates (reuses loaded market data), resolution detection ($1/$0), expiry (24h), alerts (take-profit/stop-loss/big-move), daily summary (09:00 ET). Persisted to `tracked_signals.json`.
- `src/notification/telegram.py` — Telegram push with markdown formatting

**Auto-generated files (gitignored):**
- `weather_positions.json` — Open positions for restart recovery
- `tracked_signals.json` — Signal tracking with price history
- `notify_cache.json` — Telegram push dedup timestamps

## Conventions

- Async-first: all I/O uses aiohttp with async/await
- Comments and docstrings are in Chinese (中文)
- Dataclasses for all internal models (`WeatherSignal`, `WeatherPosition`, `TrackedSignal`, etc.)
- Orders use limit GTC (Good-Til-Cancelled) to avoid spread slippage
- CLOB real buy price preferred over Gamma probability price for entry signals
- Logging via `RotatingFileHandler` (10MB, 5 backups) to `arbitrage.log`
