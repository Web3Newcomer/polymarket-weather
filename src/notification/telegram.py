"""Telegram 通知模块"""
import logging
import httpx
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig:
    """Telegram 配置"""
    bot_token: str
    chat_id: str
    topic_id: str = ""
    enabled: bool = True


class TelegramNotifier:
    """Telegram 通知器"""

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.url = self.BASE_URL.format(token=config.bot_token)

    def send(self, message: str) -> bool:
        """发送消息"""
        if not self.config.enabled:
            return False

        try:
            payload = {
                "chat_id": self.config.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            # 支持群组话题
            if self.config.topic_id:
                payload["message_thread_id"] = int(self.config.topic_id)

            resp = httpx.post(self.url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Telegram message sent, length: {len(message)}")
                return True
            else:
                logger.error(f"Telegram error: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False
