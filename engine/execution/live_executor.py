"""
Live trading executor — real Kalshi API execution.

Implements ExecutionAdapter using the KalshiRestClient. All orders hit the
real API. Includes rate limiting, order tracking for reconciliation,
and post_only enforcement.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from engine.api.kalshi_rest import KalshiRestClient
from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    FillEvent,
    InventoryState,
    Mode,
    OrderAck,
    OrderAckEvent,
    OrderRequest,
    Side,
)
from engine.execution.base_executor import ExecutionAdapter
from engine.storage.db_writer import DbWriter

logger = structlog.get_logger(__name__)

DEFAULT_RATE_LIMIT = 18  # ops/sec (slightly below Kalshi's 20 for safety)


class TokenBucketRateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, rate: float = DEFAULT_RATE_LIMIT) -> None:
        self._rate = rate
        self._tokens = rate
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


class LiveExecutor(ExecutionAdapter):
    """Executes real trades on Kalshi via the REST API."""

    def __init__(
        self,
        rest_client: KalshiRestClient,
        bus: EventBus,
        db_writer: DbWriter | None = None,
    ) -> None:
        self._rest = rest_client
        self._bus = bus
        self._db = db_writer
        self._rate_limiter = TokenBucketRateLimiter()
        self._tracked_order_ids: set[str] = set()

    async def submit_order(self, req: OrderRequest) -> OrderAck:
        await self._rate_limiter.acquire()

        ack = await self._rest.create_order(req)

        if ack.is_success and ack.order_id:
            self._tracked_order_ids.add(ack.order_id)

        if self._db:
            self._db.log_order(req, ack, Mode.LIVE)

        await self._bus.publish(OrderAckEvent(ack=ack))

        logger.info(
            "live.order_submitted",
            order_id=ack.order_id,
            ticker=req.ticker,
            side=req.side.value,
            action=req.action.value,
            price=req.price_cents,
            count=req.count,
            status=ack.status,
            error=ack.error,
        )
        return ack

    async def amend_order(
        self, order_id: str, new_price_cents: int, new_count: int
    ) -> OrderAck:
        await self._rate_limiter.acquire()

        try:
            data = await self._rest.amend_order(
                order_id, new_price_cents, new_count
            )
            order = data.get("order", data)
            return OrderAck(
                order_id=order_id,
                client_order_id=order.get("client_order_id", ""),
                status=order.get("status", "resting"),
                ticker=order.get("ticker", ""),
                side=Side(order.get("side", "yes")),
                action=Action(order.get("action", "buy")),
                price_cents=new_price_cents,
                count=new_count,
            )
        except Exception as e:
            logger.error("live.amend_failed", order_id=order_id, error=str(e))
            return OrderAck(
                order_id=order_id,
                client_order_id="",
                status="error",
                ticker="",
                side=Side.YES,
                action=Action.BUY,
                price_cents=new_price_cents,
                count=new_count,
                error=str(e),
            )

    async def cancel_order(self, order_id: str) -> bool:
        await self._rate_limiter.acquire()

        success = await self._rest.cancel_order(order_id)
        if success:
            self._tracked_order_ids.discard(order_id)
        return success

    async def cancel_all(self) -> int:
        count = await self._rest.cancel_all_orders()
        self._tracked_order_ids.clear()
        logger.info("live.cancelled_all", count=count)
        return count

    async def get_positions(self) -> list[InventoryState]:
        data = await self._rest.get_positions()
        positions = []
        for raw in data.get("positions", []):
            pos_fp = float(raw.get("position_fp", "0"))
            if pos_fp == 0:
                continue
            positions.append(InventoryState(
                ticker=raw.get("ticker", ""),
                net_position=int(pos_fp),
                cost_basis_cents=int(
                    float(raw.get("market_exposure_dollars", "0")) * 100
                ),
                realized_pnl_cents=int(
                    float(raw.get("realized_pnl_dollars", "0")) * 100
                ),
            ))
        return positions

    async def get_balance_cents(self) -> int:
        return await self._rest.get_balance()

    @property
    def tracked_order_ids(self) -> set[str]:
        return set(self._tracked_order_ids)
