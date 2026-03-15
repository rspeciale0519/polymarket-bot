"""
PostgreSQL writer via asyncpg.

Handles all database writes from the engine. Uses a batch insert buffer
that flushes every second or when the buffer is full. Schema is owned
by Prisma on the Next.js side — this module writes raw SQL.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import asyncpg
import structlog

from engine.core.types import Fill, Mode, OrderAck, OrderRequest

logger = structlog.get_logger(__name__)

FLUSH_INTERVAL_SECONDS = 1.0
MAX_BUFFER_SIZE = 100


class DbWriter:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._buffer: list[tuple[str, list[Any]]] = []
        self._flush_lock = asyncio.Lock()

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._database_url, min_size=2, max_size=10
        )
        logger.info("db_writer.connected")

    async def close(self) -> None:
        await self.flush()
        if self._pool:
            await self._pool.close()

    # ------------------------------------------------------------------
    # Flush loop (run as asyncio task)
    # ------------------------------------------------------------------

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            await self.flush()

    async def flush(self) -> None:
        async with self._flush_lock:
            if not self._buffer or not self._pool:
                return

            batch = self._buffer[:]
            self._buffer.clear()

        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    for sql, params in batch:
                        await conn.execute(sql, *params)
            logger.debug("db_writer.flushed", count=len(batch))
        except Exception:
            logger.exception("db_writer.flush_error", count=len(batch))
            # Re-add failed items to buffer for next flush
            async with self._flush_lock:
                self._buffer = batch + self._buffer

    def _enqueue(self, sql: str, params: list[Any]) -> None:
        self._buffer.append((sql, params))
        if len(self._buffer) >= MAX_BUFFER_SIZE:
            asyncio.create_task(self.flush())

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    def log_order(self, req: OrderRequest, ack: OrderAck, mode: Mode) -> None:
        sql = """
            INSERT INTO orders (
                id, external_order_id, ticker, side, action,
                price_cents, size, status, mode, client_order_id,
                created_at, updated_at
            ) VALUES (
                gen_random_uuid(), $1, $2, $3, $4,
                $5, $6, $7, $8, $9,
                $10, $10
            )
            ON CONFLICT (external_order_id) DO UPDATE SET
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
        """
        now = _utcnow()
        self._enqueue(sql, [
            ack.order_id or req.client_order_id,
            req.ticker,
            req.side.value,
            req.action.value,
            req.price_cents,
            req.count,
            ack.status,
            mode.value,
            req.client_order_id,
            now,
        ])

    def log_fill(self, fill: Fill, mode: Mode) -> None:
        sql = """
            INSERT INTO fills (
                id, order_id, ticker, side, action,
                count, price_cents, fee_cents, is_maker,
                pnl_cents, mode, created_at
            ) VALUES (
                gen_random_uuid(), $1, $2, $3, $4,
                $5, $6, $7, $8,
                $9, $10, $11
            )
        """
        self._enqueue(sql, [
            fill.order_id,
            fill.ticker,
            fill.side.value,
            fill.action.value,
            fill.count,
            fill.price_cents,
            fill.fee_cents,
            fill.is_maker,
            fill.pnl_cents,
            mode.value,
            fill.created_at,
        ])

    def log_portfolio_snapshot(
        self,
        balance_cents: int,
        equity_cents: int,
        open_pnl_cents: int,
        realized_pnl_cents: int,
        num_positions: int,
        num_open_orders: int,
        mode: Mode,
    ) -> None:
        sql = """
            INSERT INTO portfolio_snapshots (
                id, balance_cents, equity_cents, open_pnl_cents,
                realized_pnl_cents, total_pnl_cents,
                num_positions, num_open_orders, mode, snapshot_at
            ) VALUES (
                gen_random_uuid(), $1, $2, $3,
                $4, $5,
                $6, $7, $8, $9
            )
        """
        self._enqueue(sql, [
            balance_cents,
            equity_cents,
            open_pnl_cents,
            realized_pnl_cents,
            open_pnl_cents + realized_pnl_cents,
            num_positions,
            num_open_orders,
            mode.value,
            _utcnow(),
        ])

    def update_engine_status(
        self,
        mode: Mode,
        is_running: bool,
        is_paused: bool,
        connected: bool,
        active_markets: list[str],
        circuit_breaker_state: str = "ok",
        circuit_breaker_reason: str | None = None,
    ) -> None:
        sql = """
            INSERT INTO engine_status (
                id, mode, is_running, is_paused, connected,
                active_markets, circuit_breaker_state, circuit_breaker_reason,
                last_heartbeat_at
            ) VALUES (
                'singleton', $1, $2, $3, $4,
                $5, $6, $7,
                $8
            )
            ON CONFLICT (id) DO UPDATE SET
                mode = EXCLUDED.mode,
                is_running = EXCLUDED.is_running,
                is_paused = EXCLUDED.is_paused,
                connected = EXCLUDED.connected,
                active_markets = EXCLUDED.active_markets,
                circuit_breaker_state = EXCLUDED.circuit_breaker_state,
                circuit_breaker_reason = EXCLUDED.circuit_breaker_reason,
                last_heartbeat_at = EXCLUDED.last_heartbeat_at
        """
        self._enqueue(sql, [
            mode.value,
            is_running,
            is_paused,
            connected,
            json.dumps(active_markets),
            circuit_breaker_state,
            circuit_breaker_reason,
            _utcnow(),
        ])

    def log_notification(
        self, notif_type: str, title: str, message: str
    ) -> None:
        sql = """
            INSERT INTO notifications (id, type, title, message, read, created_at)
            VALUES (gen_random_uuid(), $1, $2, $3, false, $4)
        """
        self._enqueue(sql, [notif_type, title, message, _utcnow()])

    def update_position(
        self,
        ticker: str,
        title: str,
        side: str,
        size: int,
        entry_price_cents: int,
        current_price_cents: int,
        unrealized_pnl_cents: int,
        is_open: bool,
    ) -> None:
        sql = """
            INSERT INTO positions (
                id, ticker, title, side, size,
                entry_price_cents, current_price_cents,
                unrealized_pnl_cents, is_open,
                opened_at, updated_at
            ) VALUES (
                gen_random_uuid(), $1, $2, $3, $4,
                $5, $6, $7, $8, $9, $9
            )
            ON CONFLICT (ticker) DO UPDATE SET
                side = EXCLUDED.side,
                size = EXCLUDED.size,
                current_price_cents = EXCLUDED.current_price_cents,
                unrealized_pnl_cents = EXCLUDED.unrealized_pnl_cents,
                is_open = EXCLUDED.is_open,
                updated_at = EXCLUDED.updated_at
        """
        self._enqueue(sql, [
            ticker, title, side, size,
            entry_price_cents, current_price_cents,
            unrealized_pnl_cents, is_open, _utcnow(),
        ])

    # ------------------------------------------------------------------
    # Read methods (for settings polling and reconciliation)
    # ------------------------------------------------------------------

    async def read_settings(self) -> dict[str, str]:
        if not self._pool:
            return {}
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM bot_settings WHERE id = 'singleton'"
                )
                if not row:
                    return {}
                return {k: str(v) for k, v in dict(row).items() if v is not None}
        except Exception:
            logger.exception("db_writer.read_settings_error")
            return {}

    async def read_market_configs(self) -> list[dict[str, Any]]:
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM market_configs")
                return [dict(r) for r in rows]
        except Exception:
            logger.exception("db_writer.read_market_configs_error")
            return []


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
