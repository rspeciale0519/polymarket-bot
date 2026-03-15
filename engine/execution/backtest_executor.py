"""
Backtest executor — historical replay execution.

Same fill logic as paper executor but receives HistoricalTick events
from the backtest runner instead of live data. Uses a virtual clock
and virtual balance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog

from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    Fill,
    FillEvent,
    InventoryState,
    Orderbook,
    OrderAck,
    OrderRequest,
    Side,
    maker_fee_cents,
)
from engine.execution.base_executor import ExecutionAdapter

logger = structlog.get_logger(__name__)


class BacktestOrder:
    def __init__(self, req: OrderRequest, order_id: str) -> None:
        self.order_id = order_id
        self.client_order_id = req.client_order_id
        self.ticker = req.ticker
        self.side = req.side
        self.action = req.action
        self.price_cents = req.price_cents
        self.count = req.count
        self.remaining = req.count

    @property
    def is_filled(self) -> bool:
        return self.remaining <= 0


class BacktestExecutor(ExecutionAdapter):
    """Simulated execution for backtesting against historical data."""

    def __init__(
        self,
        bus: EventBus,
        starting_balance_cents: int = 10000,
    ) -> None:
        self._bus = bus
        self._balance_cents = starting_balance_cents
        self._initial_balance = starting_balance_cents
        self._resting_orders: dict[str, BacktestOrder] = {}
        self._positions: dict[str, InventoryState] = {}
        self._fills: list[Fill] = []
        self._virtual_time: datetime = datetime.now(UTC)

    def set_virtual_time(self, dt: datetime) -> None:
        self._virtual_time = dt

    async def submit_order(self, req: OrderRequest) -> OrderAck:
        order_id = f"bt-{uuid4().hex[:12]}"

        cost = req.count * req.price_cents
        if req.action == Action.BUY and cost > self._balance_cents:
            return OrderAck(
                order_id=order_id, client_order_id=req.client_order_id,
                status="rejected", ticker=req.ticker, side=req.side,
                action=req.action, price_cents=req.price_cents,
                count=req.count, error="Insufficient backtest balance",
            )

        order = BacktestOrder(req, order_id)
        self._resting_orders[order_id] = order

        return OrderAck(
            order_id=order_id, client_order_id=req.client_order_id,
            status="resting", ticker=req.ticker, side=req.side,
            action=req.action, price_cents=req.price_cents,
            count=req.count, remaining_count=req.count,
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
            order_id=order_id, client_order_id=order.client_order_id,
            status="resting", ticker=order.ticker, side=order.side,
            action=order.action, price_cents=new_price_cents,
            count=order.remaining, remaining_count=order.remaining,
        )

    async def cancel_order(self, order_id: str) -> bool:
        return self._resting_orders.pop(order_id, None) is not None

    async def cancel_all(self) -> int:
        count = len(self._resting_orders)
        self._resting_orders.clear()
        return count

    async def get_positions(self) -> list[InventoryState]:
        return [inv for inv in self._positions.values() if not inv.is_flat]

    async def get_balance_cents(self) -> int:
        return self._balance_cents

    # ------------------------------------------------------------------
    # Called by backtest runner on each historical tick
    # ------------------------------------------------------------------

    async def process_orderbook_tick(self, ticker: str, book: Orderbook) -> None:
        """Check fills against a historical orderbook snapshot."""
        to_remove: list[str] = []

        for oid, order in list(self._resting_orders.items()):
            if order.ticker != ticker or order.is_filled:
                if order.is_filled:
                    to_remove.append(oid)
                continue

            filled = self._check_fill(order, book)
            if filled:
                to_remove.append(oid)

        for oid in to_remove:
            self._resting_orders.pop(oid, None)

    def _check_fill(self, order: BacktestOrder, book: Orderbook) -> bool:
        if order.action == Action.BUY:
            best_ask = book.best_ask()
            if best_ask is None or best_ask > order.price_cents:
                return False
        else:
            best_bid = book.best_bid()
            if best_bid is None or best_bid < order.price_cents:
                return False

        fill_count = order.remaining
        fee = maker_fee_cents(fill_count, order.price_cents)

        if order.action == Action.BUY:
            self._balance_cents -= (fill_count * order.price_cents) + fee
        else:
            self._balance_cents += (fill_count * order.price_cents) - fee

        self._update_position(order, fill_count)

        fill = Fill(
            fill_id=f"bt-fill-{uuid4().hex[:12]}",
            order_id=order.order_id,
            ticker=order.ticker,
            side=order.side,
            action=order.action,
            count=fill_count,
            price_cents=order.price_cents,
            fee_cents=fee,
            is_maker=True,
            created_at=self._virtual_time,
        )
        self._fills.append(fill)

        import asyncio
        asyncio.create_task(self._bus.publish(FillEvent(fill=fill)))

        order.remaining = 0
        return True

    def _update_position(self, order: BacktestOrder, count: int) -> None:
        inv = self._positions.get(order.ticker)
        if not inv:
            inv = InventoryState(ticker=order.ticker)
            self._positions[order.ticker] = inv

        if order.action == Action.BUY:
            if order.side == Side.YES:
                inv.net_position += count
            else:
                inv.net_position -= count
            inv.cost_basis_cents += count * order.price_cents
        else:
            if order.side == Side.YES:
                inv.net_position -= count
            else:
                inv.net_position += count

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def total_fills(self) -> int:
        return len(self._fills)

    @property
    def total_fees_cents(self) -> int:
        return sum(f.fee_cents for f in self._fills)

    @property
    def net_pnl_cents(self) -> int:
        return self._balance_cents - self._initial_balance

    def get_equity_curve(self) -> list[tuple[datetime, int]]:
        """Returns (timestamp, balance_cents) for each fill."""
        curve: list[tuple[datetime, int]] = [
            (self._fills[0].created_at if self._fills else self._virtual_time,
             self._initial_balance)
        ]
        balance = self._initial_balance
        for fill in self._fills:
            if fill.action == Action.BUY:
                balance -= (fill.count * fill.price_cents) + fill.fee_cents
            else:
                balance += (fill.count * fill.price_cents) - fill.fee_cents
            curve.append((fill.created_at, balance))
        return curve
