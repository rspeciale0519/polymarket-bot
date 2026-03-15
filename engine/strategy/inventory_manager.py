"""
Inventory manager for the market making strategy.

Tracks position state per market and provides inventory metrics
needed by the quote generator (inventory ratio, flattening signals,
total exposure).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    EngineConfig,
    FillEvent,
    InventoryState,
    OrderbookUpdate,
    Side,
)

logger = structlog.get_logger(__name__)


class InventoryManager:
    """Tracks inventory per market for the strategy layer."""

    def __init__(self, config: EngineConfig, bus: EventBus) -> None:
        self._config = config
        self._bus = bus
        self._inventory: dict[str, InventoryState] = {}
        self._mid_prices: dict[str, float] = {}

        self._bus.subscribe(FillEvent, self._on_fill)
        self._bus.subscribe(OrderbookUpdate, self._on_orderbook_update)

    def get_inventory(self, ticker: str) -> InventoryState:
        if ticker not in self._inventory:
            self._inventory[ticker] = InventoryState(ticker=ticker)
        return self._inventory[ticker]

    def get_inventory_ratio(self, ticker: str) -> float:
        """Returns net_position / max_position, range [-1, 1]."""
        inv = self.get_inventory(ticker)
        max_pos = self._config.max_position_per_market
        if max_pos <= 0:
            return 0.0
        return max(-1.0, min(1.0, inv.net_position / max_pos))

    def should_flatten(self, ticker: str) -> bool:
        """Returns True if position is > 80% of max inventory."""
        inv = self.get_inventory(ticker)
        max_pos = self._config.max_position_per_market
        return abs(inv.net_position) > max_pos * 0.8

    def get_total_exposure_cents(self) -> int:
        """Total notional exposure across all markets."""
        total = 0
        for ticker, inv in self._inventory.items():
            mid = self._mid_prices.get(ticker, 50.0)
            total += abs(inv.net_position) * int(mid)
        return total

    def get_all_active(self) -> list[InventoryState]:
        """All non-flat positions."""
        return [inv for inv in self._inventory.values() if not inv.is_flat]

    async def _on_fill(self, event: FillEvent) -> None:
        fill = event.fill
        inv = self.get_inventory(fill.ticker)

        if fill.action == Action.BUY:
            if fill.side == Side.YES:
                inv.net_position += fill.count
            else:
                inv.net_position -= fill.count
            inv.cost_basis_cents += fill.count * fill.price_cents
        else:
            if fill.side == Side.YES:
                inv.net_position -= fill.count
            else:
                inv.net_position += fill.count

        logger.debug(
            "inventory.updated",
            ticker=fill.ticker,
            net_position=inv.net_position,
            ratio=self.get_inventory_ratio(fill.ticker),
        )

    async def _on_orderbook_update(self, event: OrderbookUpdate) -> None:
        self._mid_prices[event.ticker] = event.orderbook.mid_price_cents()
