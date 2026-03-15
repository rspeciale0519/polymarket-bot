"""
Order reconciliation loop.

Periodically compares the engine's internal order state against Kalshi's
actual resting orders. Fixes discrepancies:
- Orphaned orders on Kalshi (not tracked by engine) → cancel
- Orders in engine state but not on Kalshi → remove from state
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from engine.api.kalshi_rest import KalshiRestClient
from engine.core.types import EngineConfig, Mode
from engine.execution.paper_executor import PaperExecutor

logger = structlog.get_logger(__name__)


class OrderReconciler:
    def __init__(
        self,
        config: EngineConfig,
        rest_client: KalshiRestClient,
        executor: Any,  # ExecutionAdapter — paper or live
    ) -> None:
        self._config = config
        self._rest = rest_client
        self._executor = executor

    async def run(self) -> None:
        """Run reconciliation loop."""
        while True:
            try:
                await asyncio.sleep(self._config.reconciliation_interval_seconds)
                await self.reconcile()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("reconciler.error")

    async def reconcile(self) -> None:
        """Single reconciliation pass."""
        if self._config.mode == Mode.PAPER:
            await self._reconcile_paper()
        else:
            await self._reconcile_live()

    async def _reconcile_paper(self) -> None:
        """Paper mode: just verify internal consistency."""
        if not isinstance(self._executor, PaperExecutor):
            return

        # Remove any filled orders still in the resting dict
        to_remove = []
        for oid, order in self._executor.resting_orders.items():
            if order.is_filled:
                to_remove.append(oid)

        for oid in to_remove:
            await self._executor.cancel_order(oid)

        if to_remove:
            logger.info("reconciler.paper_cleanup", removed=len(to_remove))

    async def _reconcile_live(self) -> None:
        """Live mode: compare engine state vs Kalshi API."""
        # Get actual resting orders from Kalshi
        kalshi_orders: dict[str, dict] = {}
        cursor = None
        while True:
            data = await self._rest.get_orders(status="resting", cursor=cursor)
            for order in data.get("orders", []):
                oid = order.get("order_id")
                if oid:
                    kalshi_orders[oid] = order
            cursor = data.get("cursor")
            if not cursor or not data.get("orders"):
                break

        # Get engine's tracked resting orders
        engine_orders = set()
        if hasattr(self._executor, "resting_orders"):
            engine_orders = set(self._executor.resting_orders.keys())
        elif hasattr(self._executor, "_tracked_order_ids"):
            engine_orders = set(self._executor._tracked_order_ids)

        kalshi_ids = set(kalshi_orders.keys())

        # Orphaned on Kalshi (not tracked by engine) → cancel
        orphaned = kalshi_ids - engine_orders
        for oid in orphaned:
            logger.warning("reconciler.orphaned_order", order_id=oid)
            await self._rest.cancel_order(oid)

        # Missing from Kalshi (engine thinks it's resting but it's not) → remove
        missing = engine_orders - kalshi_ids
        for oid in missing:
            logger.warning("reconciler.missing_order", order_id=oid)
            if hasattr(self._executor, "cancel_order"):
                await self._executor.cancel_order(oid)

        if orphaned or missing:
            logger.info(
                "reconciler.discrepancies",
                orphaned=len(orphaned),
                missing=len(missing),
            )
