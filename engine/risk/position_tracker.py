"""
Aggregated position tracker.

Listens to FillEvent on the event bus, maintains InventoryState per market,
and pushes updates to the risk engine and database.
"""

from __future__ import annotations

import structlog

from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    FillEvent,
    InventoryState,
    Mode,
    OrderbookUpdate,
    Side,
)
from engine.risk.risk_engine import RiskEngine
from engine.storage.db_writer import DbWriter

logger = structlog.get_logger(__name__)


class PositionTracker:
    def __init__(
        self,
        bus: EventBus,
        risk_engine: RiskEngine,
        db_writer: DbWriter | None = None,
        mode: Mode = Mode.PAPER,
    ) -> None:
        self._bus = bus
        self._risk = risk_engine
        self._db = db_writer
        self._mode = mode
        self._positions: dict[str, InventoryState] = {}

        self._bus.subscribe(FillEvent, self._on_fill)
        self._bus.subscribe(OrderbookUpdate, self._on_orderbook_update)

    async def _on_fill(self, event: FillEvent) -> None:
        fill = event.fill
        inv = self._positions.get(fill.ticker)
        if not inv:
            inv = InventoryState(ticker=fill.ticker)
            self._positions[fill.ticker] = inv

        prev_position = inv.net_position

        # Update net position
        if fill.action == Action.BUY:
            if fill.side == Side.YES:
                inv.net_position += fill.count
            else:
                inv.net_position -= fill.count
        else:  # SELL
            if fill.side == Side.YES:
                inv.net_position -= fill.count
            else:
                inv.net_position += fill.count

        # Track cost basis
        if fill.action == Action.BUY:
            inv.cost_basis_cents += fill.count * fill.price_cents
        else:
            # Realize P&L on closing trades
            if prev_position != 0:
                avg_cost = inv.cost_basis_cents / max(abs(prev_position), 1)
                pnl = int((fill.price_cents - avg_cost) * fill.count)
                if fill.side == Side.NO:
                    pnl = -pnl
                inv.realized_pnl_cents += pnl
                self._risk.add_realized_pnl(pnl)

                # Update fill with P&L
                fill.pnl_cents = pnl

        # Push to risk engine
        self._risk.update_position(inv)

        # Write to DB
        if self._db:
            self._db.update_position(
                ticker=inv.ticker,
                title="",
                side="YES" if inv.net_position > 0 else "NO",
                size=abs(inv.net_position),
                entry_price_cents=_avg_cost(inv),
                current_price_cents=fill.price_cents,
                unrealized_pnl_cents=inv.unrealized_pnl_cents,
                is_open=not inv.is_flat,
            )
            self._db.log_fill(fill, self._mode)

        logger.info(
            "position_tracker.fill",
            ticker=fill.ticker,
            action=fill.action.value,
            side=fill.side.value,
            count=fill.count,
            price=fill.price_cents,
            net_position=inv.net_position,
            realized_pnl=inv.realized_pnl_cents,
        )

    async def _on_orderbook_update(self, event: OrderbookUpdate) -> None:
        """Update unrealized P&L based on current mid price."""
        inv = self._positions.get(event.ticker)
        if not inv or inv.is_flat:
            return

        mid = event.orderbook.mid_price_cents()
        avg_cost = _avg_cost(inv)

        if inv.net_position > 0:
            inv.unrealized_pnl_cents = int((mid - avg_cost) * abs(inv.net_position))
        else:
            inv.unrealized_pnl_cents = int((avg_cost - mid) * abs(inv.net_position))

    def get_position(self, ticker: str) -> InventoryState | None:
        return self._positions.get(ticker)

    def get_all_positions(self) -> list[InventoryState]:
        return [inv for inv in self._positions.values() if not inv.is_flat]

    def get_total_unrealized_pnl_cents(self) -> int:
        return sum(inv.unrealized_pnl_cents for inv in self._positions.values())

    def get_total_realized_pnl_cents(self) -> int:
        return sum(inv.realized_pnl_cents for inv in self._positions.values())


def _avg_cost(inv: InventoryState) -> float:
    if inv.is_flat:
        return 0.0
    return inv.cost_basis_cents / max(abs(inv.net_position), 1)
