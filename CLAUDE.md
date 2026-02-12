# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Weather trading bot for Polymarket prediction markets. Uses NOAA government weather forecasts as objective price anchors against Polymarket weather market pricing. Two modes: signal-only (default, Telegram push) and auto-trade (execute trades with stop-loss/take-profit). Written in Python with async/await throughout.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run in weather trading mode (primary mode, 1-hour scan intervals)
python -m src.main --mode weather

# Run in polling mode (60-second intervals, legacy arbitrage scan)
python -m src.main --mode poll

# Run in real-time WebSocket mode (legacy)
python -m src.main --mode realtime

# Run tests
pytest tests/
pytest tests/test_risk_manager.py          # single test file
pytest tests/test_risk_manager.py -k "test_name"  # single test
```

## Configuration

All config via environment variables loaded from `.env` by `src/config.py`. Key groups:

- **Polymarket API:** `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_PASSPHRASE`, `FUNDER_ADDRESS`
- **Weather strategy:** `WEATHER_ENABLED`, `WEATHER_AUTO_TRADE`, `WEATHER_ENTRY_THRESHOLD`, `WEATHER_EXIT_THRESHOLD`, `WEATHER_TAKE_PROFIT`, `WEATHER_STOP_LOSS`, `WEATHER_MAX_POSITION`, `WEATHER_MAX_TRADES`, `WEATHER_LOCATIONS`, `WEATHER_MIN_HOURS`
- **Telegram:** `TG_ENABLED`, `TG_BOT_TOKEN`, `TG_CHAT_ID`, `TG_TOPIC_ID`
- **General:** `DRY_RUN=true` (default)

## Architecture

**Entry point:** `src/main.py` → parses CLI `--mode` arg → creates `Engine` from config.

**Weather mode data flow:**
```
NOAA Weather API (forecast data)
  + Polymarket Gamma API (weather market prices)
  → WeatherStrategy (match NOAA forecast to temperature buckets, find underpriced YES tokens)
  → Signal-only: TelegramNotifier (push signal alerts)
  → Auto-trade: OrderManager (execute buy/sell) + TelegramNotifier (push trade results)
```

**Key directories:**
- `src/core/engine.py` — Main orchestration: `run_weather()` loop, position persistence, Telegram push methods
- `src/strategy/weather.py` — Weather strategy: scan entries (NOAA vs market price), scan exits (stop-loss/take-profit/threshold)
- `src/data/noaa_feed.py` — Async NOAA API client (6 cities: NYC, Chicago, Seattle, Atlanta, Dallas, Miami)
- `src/data/market_feed.py` — Polymarket Gamma API market data aggregator
- `src/execution/` — Order execution (`order_manager.py` with weather buy/sell), risk management, position tracking, CLOB client
- `src/notification/telegram.py` — Telegram push with 6-hour per-market cooldown (persisted to `notify_cache.json`)
- `src/models/` — Dataclass models for Market, Signal, Order
- `src/stats/opportunity_tracker.py` — Historical opportunity tracking

**Weather strategy logic:** NOAA forecasts are ~85% accurate for 1-2 day predictions. Strategy groups Polymarket weather markets by `event_slug`, parses temperature buckets from market questions (e.g. "34-35°F", "36°F or higher"), matches against NOAA forecast, and generates BUY signals when the matching bucket's YES price is below `entry_threshold`. Exit signals trigger on stop-loss, take-profit, or price reaching `exit_threshold`.

**Position persistence:** Open positions saved to `weather_positions.json` for restart recovery.

## Conventions

- Async-first: all I/O uses aiohttp/websockets with async/await
- Comments and docstrings are in Chinese
- Dataclasses for internal models, Pydantic for API responses
- Logging via `RotatingFileHandler` (10MB, 5 backups) to `arbitrage.log`
