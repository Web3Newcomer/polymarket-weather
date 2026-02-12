"""主入口"""
import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import signal as sig
import sys

from .config import load_config, LogConfig
from .core.engine import Engine


def setup_logging(log_config: LogConfig):
    """配置日志（带轮转功能）"""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_config.level))

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_config.file,
        maxBytes=log_config.max_bytes,
        backupCount=log_config.backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(getattr(logging, log_config.level))
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Polymarket Weather Trading Bot")
    return parser.parse_args()


async def main():
    """主函数"""
    args = parse_args()
    config = load_config()
    setup_logging(config.log)

    engine = Engine(config)

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(sig.SIGINT, lambda: asyncio.create_task(engine.stop()))

    await engine.run_weather()


if __name__ == "__main__":
    asyncio.run(main())
