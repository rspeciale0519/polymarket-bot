"""
Telegram notifications
"""

import logging
import asyncio
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send notifications via Telegram"""
    
    def __init__(self, token: str, chat_id: str):
        self.bot = Bot(token=token)
        self.chat_id = chat_id
    
    async def send(self, message: str) -> bool:
        """Send message to Telegram chat"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown"
            )
            logger.info(f"Telegram message sent")
            return True
        
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return False
    
    async def send_alert(self, title: str, message: str) -> bool:
        """Send alert (high priority)"""
        full_msg = f"🚨 **{title}**\n{message}"
        return await self.send(full_msg)
    
    async def send_trade_notification(
        self,
        trader_name: str,
        market: str,
        side: str,
        size: float,
        price: float
    ) -> bool:
        """Send trade notification"""
        msg = (
            f"📊 **Copy Trade**\n"
            f"Trader: {trader_name}\n"
            f"Market: {market}\n"
            f"Action: {side} {size:.1f}x @ ${price:.2f}"
        )
        return await self.send(msg)
