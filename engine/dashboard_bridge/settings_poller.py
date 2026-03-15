"""
Settings poller — watches the bot_settings DB table for changes.

Polls every N seconds. When values change, publishes ConfigChanged
event so the engine can hot-reload without restart.
"""

from __future__ import annotations

import asyncio

import structlog

from engine.core.config import apply_db_settings
from engine.core.event_bus import EventBus
from engine.core.types import ConfigChanged, EngineConfig
from engine.storage.db_writer import DbWriter

logger = structlog.get_logger(__name__)


class SettingsPoller:
    def __init__(
        self,
        config: EngineConfig,
        bus: EventBus,
        db_writer: DbWriter,
    ) -> None:
        self._config = config
        self._bus = bus
        self._db = db_writer
        self._last_settings: dict[str, str] = {}

    async def run(self) -> None:
        """Poll settings table in a loop."""
        while True:
            try:
                await asyncio.sleep(self._config.settings_poll_interval_seconds)
                await self._poll()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("settings_poller.error")

    async def _poll(self) -> None:
        settings = await self._db.read_settings()
        if not settings:
            return

        # Detect changes
        changed_keys = []
        for key, value in settings.items():
            if key in ("id", "updated_at"):
                continue
            old_value = self._last_settings.get(key)
            if old_value != value:
                changed_keys.append(key)

        if not changed_keys:
            return

        logger.info("settings_poller.changes_detected", keys=changed_keys)

        # Apply changes to config
        apply_db_settings(self._config, settings)
        self._last_settings = settings

        # Publish event
        await self._bus.publish(ConfigChanged(changed_keys=changed_keys))
