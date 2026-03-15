"""
Paper trading executor.

Simulates order execution against live orderbook data. Maintains an
in-memory book of resting paper orders and fills them when the live
orderbook would have crossed the order price. Applies maker fees.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog

from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    Fill,
    FillEvent,
    InventoryState,
    Mode,
    Orderbook,
    OrderAck,
    OrderbookUpdate,
    OrderRequest,
    Side,
    maker_fee_cents,
)
from engine.execution.base_executor import ExecutionAdapter

logger = structlog.get_logger(__name__)


class PaperOrder:
    def __init__(self, req: OrderRequest, order_id: str) -> None:
        self.order_id = order_id
        self.client_order_id = req.client_order_id
        self.ticker = req.ticker
        self.side = req.side
        self.action = req.action
        self.price_cents = req.price_cents
        self.count = req.count
        self.remaining = req.count
        self.created_at = datetime.now(UTC)

    @property
    def is_filled(self) -> bool:
        return self.remaining <= 0


class PaperExecutor(ExecutionAdapter):
    def __init__(
        self,
        bus: EventBus,
        starting_balance_cents: int = 10000,
    ) -> None:
        self._bus = bus
        self._balance_cents = starting_balance_cents
        self._resting_orders: dict[str, PaperOrder] = {}
        self._positions: dict[str, InventoryState] = {}
        self._fills: list[Fill] = []

        # Subscribe to orderbook updates to check for fills
        self._bus.subscribe(OrderbookUpdate, self._on_orderbook_update)

    async def submit_order(self, req: OrderRequest) -> OrderAck:
        order_id = f"paper-{uuid4().hex[:12]}"

        # Check if we have enough balance
        cost = req.count * req.price_cents
        if req.action == Action.BUY and cost > self._balance_cents:
            return OrderAck(
                order_id=order_id,
                client_order_id=req.client_order_id,
                status="rejected",
                ticker=req.ticker,
                side=req.side,
                action=req.action,
                price_cents=req.price_cents,
                count=req.count,
                error="Insufficient paper balance",
            )

        paper_order = PaperOrder(req, order_id)
        self._resting_orders[order_id] = paper_order

        logger.info(
            "paper.order_placed",
            order_id=order_id,
            ticker=req.ticker,
            side=req.side.value,
            action=req.action.value,
            price=req.price_cents,
            count=req.count,
        )

        return OrderAck(
            order_id=order_id,
            client_order_id=req.client_order_id,
            status="resting",
            ticker=req.ticker,
            side=req.side,
            action=req.action,
            price_cents=req.price_cents,
            count=req.count,
            remaining_count=req.count,
        )

    async def amend_order(
        self, order_id: str, new_price_cents: int, new_count: int
    ) -> OrderAck:
        order = self._resting_orders.get(order_id)
        if not order:
            return OrderAck(
                order_id=order_id, client_order_id="", status="error",
                ticker="", side=Side.YES, action=Action.BUY,
                price_cents=new_price_cents, count=new_count,
                error="Order not found",
            )

        order.price_cents = new_price_cents
        order.remaining = min(new_count, order.remaining)
        return OrderAck(
            order_id=order_id,
            client_order_id=order.client_order_id,
            status="resting",
            ticker=order.ticker,
            side=order.side,
            action=order.action,
            price_cents=new_price_cents,
            count=order.remaining,
            remaining_count=order.remaining,
        )

    async def cancel_order(self, order_id: str) -> bool:
        if order_id in self._resting_orders:
            del self._resting_orders[order_id]
            return True
        return False

    async def cancel_all(self) -> int:
        count = len(self._resting_orders)
        self._resting_orders.clear()
        logger.info("paper.cancelled_all", count=count)
        return count

    async def get_positions(self) -> list[InventoryState]:
        return [inv for inv in self._positions.values() if not inv.is_flat]

    async def get_balance_cents(self) -> int:
        return self._balance_cents

    # ------------------------------------------------------------------
    # Fill simulation
    # ------------------------------------------------------------------

    async def _on_orderbook_update(self, event: OrderbookUpdate) -> None:
        """Check if any paper orders would fill against the live book."""
        book = event.orderbook
        orders_to_remove: list[str] = []

        for order_id, order in list(self._resting_orders.items()):
            if order.ticker != event.ticker:
                continue
            if order.is_filled:
                orders_to_remove.append(order_id)
                continue

            filled = self._check_fill(order, book)
            if filled:
                orders_to_remove.append(order_id)

        for oid in orders_to_remove:
            self._resting_orders.pop(oid, None)

    def _check_fill(self, order: PaperOrder, book: Orderbook) -> bool:
        """Check if this order would fill against the current book."""
        if order.action == Action.BUY:
            # Buy order fills when the ask is at or below our bid price
            best_ask = book.best_ask()
            if best_ask is None:
                return False
            if best_ask > order.price_cents:
                return False
        else:
            # Sell order fills when the bid is at or above our ask price
            best_bid = book.best_bid()
            if best_bid is None:
                return False
            if best_bid < order.price_cents:
                return False

        # Simulate fill
        fill_count = order.remaining
        fee = maker_fee_cents(fill_count, order.price_cents)

        # Update balance
        if order.action == Action.BUY:
            self._balance_cents -= (fill_count * order.price_cents) + fee
        else:
            self._balance_cents += (fill_count * order.price_cents) - fee

        # Update position
        self._update_position(order, fill_count)

        # Create fill event
        fill = Fill(
            fill_id=f"paper-fill-{uuid4().hex[:12]}",
            order_id=order.order_id,
            ticker=order.ticker,
            side=order.side,
            action=order.action,
            count=fill_count,
            price_cents=order.price_cents,
            fee_cents=fee,
            is_maker=True,
        )
        self._fills.append(fill)

        logger.info(
            "paper.fill",
            order_id=order.order_id,
            ticker=order.ticker,
            side=order.side.value,
            action=order.action.value,
            price=order.price_cents,
            count=fill_count,
            fee=fee,
            balance=self._balance_cents,
        )

        # Publish fill event async
        import asyncio
        asyncio.create_task(self._bus.publish(FillEvent(fill=fill)))

        order.remaining = 0
        return True

    def _update_position(self, order: PaperOrder, fill_count: int) -> None:
        """Update tracked position after a fill."""
        inv = self._positions.get(order.ticker)
        if not inv:
            inv = InventoryState(ticker=order.ticker)
            self._positions[order.ticker] = inv

        if order.action == Action.BUY:
            if order.side == Side.YES:
                inv.net_position += fill_count
            else:
                inv.net_position -= fill_count
            inv.cost_basis_cents += fill_count * order.price_cents
        else:
            if order.side == Side.YES:
                inv.net_position -= fill_count
            else:
                inv.net_position += fill_count
            # Realize P&L on closing trades
            avg_cost = (
                inv.cost_basis_cents / max(abs(inv.net_position) + fill_count, 1)
            )
            pnl = int((order.price_cents - avg_cost) * fill_count)
            if order.side == Side.NO:
                pnl = -pnl
            inv.realized_pnl_cents += pnl

    @property
    def resting_order_count(self) -> int:
        return len(self._resting_orders)

    @property
    def resting_orders(self) -> dict[str, PaperOrder]:
        return dict(self._resting_orders)
