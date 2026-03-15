"""
Telegram bot for alerts and manual commands.

Outbound: fill alerts, circuit breaker alerts, daily P&L, milestone, status.
Inbound: /status, /pause, /resume, /risk, /positions.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

import structlog

logger = structlog.get_logger(__name__)

# Avoid hard dependency on telegram lib — gracefully degrade if not configured
try:
    from telegram import Bot, Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
    )
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False


class TelegramNotifier:
    """Sends notifications and handles commands via Telegram."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id
        self._enabled = bool(token and chat_id and HAS_TELEGRAM)
        self._bot: Any = None
        self._app: Any = None

        # Command callbacks (set by engine)
        self._on_pause: Callable[[], Coroutine] | None = None
        self._on_resume: Callable[[], Coroutine] | None = None
        self._get_status: Callable[[], Coroutine] | None = None
        self._get_risk: Callable[[], Coroutine] | None = None
        self._get_positions: Callable[[], Coroutine] | None = None

        if self._enabled:
            self._bot = Bot(token=token)

    def set_callbacks(
        self,
        on_pause: Callable | None = None,
        on_resume: Callable | None = None,
        get_status: Callable | None = None,
        get_risk: Callable | None = None,
        get_positions: Callable | None = None,
    ) -> None:
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._get_status = get_status
        self._get_risk = get_risk
        self._get_positions = get_positions

    async def send(self, message: str) -> bool:
        """Send a message to the configured chat."""
        if not self._enabled:
            logger.debug("telegram.disabled", message=message[:50])
            return False

        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=message,
                parse_mode=None,  # plain text avoids markdown parsing issues
            )
            return True
        except Exception:
            logger.exception("telegram.send_error")
            return False

    async def send_fill_alert(self, formatted_fill: str) -> None:
        await self.send(f"Trade Filled\n{formatted_fill}")

    async def send_circuit_breaker_alert(self, reason: str) -> None:
        await self.send(f"CIRCUIT BREAKER TRIPPED\n{reason}")

    async def send_daily_report(self, report: str) -> None:
        await self.send(f"Daily Report\n{report}")

    async def send_milestone(self, days: int, target: int) -> None:
        await self.send(
            f"Paper Trading Milestone\n"
            f"Profitable for {days}/{target} days!\n"
            f"System recommends reviewing live mode."
        )

    async def send_connection_status(self, connected: bool, detail: str = "") -> None:
        status = "Connected" if connected else "Disconnected"
        msg = f"WebSocket {status}"
        if detail:
            msg += f"\n{detail}"
        await self.send(msg)

    async def run(self) -> None:
        """Run the Telegram bot with command handlers (long-polling)."""
        if not self._enabled or not HAS_TELEGRAM:
            logger.info("telegram.not_configured")
            # Keep the task alive but do nothing
            while True:
                await asyncio.sleep(3600)
            return

        self._app = Application.builder().token(self._token).build()

        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("pause", self._cmd_pause))
        self._app.add_handler(CommandHandler("resume", self._cmd_resume))
        self._app.add_handler(CommandHandler("risk", self._cmd_risk))
        self._app.add_handler(CommandHandler("positions", self._cmd_positions))
        self._app.add_handler(CommandHandler("help", self._cmd_help))

        logger.info("telegram.starting_polling")
        try:
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)

            # Keep running
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            if self._app.updater.running:
                await self._app.updater.stop()
            if self._app.running:
                await self._app.stop()
            await self._app.shutdown()

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _cmd_status(self, update: Any, context: Any) -> None:
        if self._get_status:
            text = await self._get_status()
        else:
            text = "Status callback not configured"
        await update.message.reply_text(text)

    async def _cmd_pause(self, update: Any, context: Any) -> None:
        if self._on_pause:
            await self._on_pause()
            await update.message.reply_text("Engine paused")
        else:
            await update.message.reply_text("Pause not configured")

    async def _cmd_resume(self, update: Any, context: Any) -> None:
        if self._on_resume:
            await self._on_resume()
            await update.message.reply_text("Engine resumed")
        else:
            await update.message.reply_text("Resume not configured")

    async def _cmd_risk(self, update: Any, context: Any) -> None:
        if self._get_risk:
            text = await self._get_risk()
        else:
            text = "Risk callback not configured"
        await update.message.reply_text(text)

    async def _cmd_positions(self, update: Any, context: Any) -> None:
        if self._get_positions:
            text = await self._get_positions()
        else:
            text = "Positions callback not configured"
        await update.message.reply_text(text)

    async def _cmd_help(self, update: Any, context: Any) -> None:
        await update.message.reply_text(
            "Commands:\n"
            "/status - Engine status\n"
            "/pause - Pause trading\n"
            "/resume - Resume trading\n"
            "/risk - Risk utilization\n"
            "/positions - Open positions\n"
            "/help - This message"
        )
