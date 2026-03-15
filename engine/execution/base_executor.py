"""
Abstract execution adapter interface.

All three modes (Live, Paper, Backtest) implement this interface.
The strategy, risk engine, and order management hold a reference to
ExecutionAdapter only — they never branch on mode.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from engine.core.types import InventoryState, OrderAck, OrderRequest


class ExecutionAdapter(ABC):
    @abstractmethod
    async def submit_order(self, req: OrderRequest) -> OrderAck:
        """Submit a new order."""
        ...

    @abstractmethod
    async def amend_order(
        self, order_id: str, new_price_cents: int, new_count: int
    ) -> OrderAck:
        """Amend an existing resting order (preserves queue position)."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order. Returns True if successful."""
        ...

    @abstractmethod
    async def cancel_all(self) -> int:
        """Cancel all resting orders. Returns count cancelled."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[InventoryState]:
        """Get current open positions."""
        ...

    @abstractmethod
    async def get_balance_cents(self) -> int:
        """Get available balance in cents."""
        ...
