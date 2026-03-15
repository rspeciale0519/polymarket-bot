"""
Orderbook state manager.

Maintains one Orderbook instance per market ticker. Handles Kalshi's
format where YES bids and NO bids are returned separately.
best_yes_ask = 100 - best_no_bid.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from engine.core.types import Orderbook, OrderbookLevel

logger = structlog.get_logger(__name__)


class OrderbookManager:
    """Manages orderbook state for all active markets."""

    def __init__(self) -> None:
        self._books: dict[str, Orderbook] = {}

    def get(self, ticker: str) -> Orderbook | None:
        return self._books.get(ticker)

    def get_or_create(self, ticker: str) -> Orderbook:
        if ticker not in self._books:
            self._books[ticker] = Orderbook(ticker=ticker)
        return self._books[ticker]

    def remove(self, ticker: str) -> None:
        self._books.pop(ticker, None)

    @property
    def active_tickers(self) -> list[str]:
        return list(self._books.keys())

    def apply_snapshot(self, ticker: str, msg: dict[str, Any]) -> Orderbook:
        """Apply a full orderbook snapshot from WebSocket."""
        book = self.get_or_create(ticker)

        orderbook_data = msg.get("orderbook_fp", msg.get("orderbook", msg))

        yes_bids = _parse_levels(orderbook_data.get("yes_dollars", []))
        no_bids = _parse_levels(orderbook_data.get("no_dollars", []))

        # YES asks are derived from NO bids: yes_ask = 100 - no_bid
        yes_asks = _no_bids_to_yes_asks(no_bids)

        book.yes_bids = sorted(yes_bids, key=lambda l: l.price_cents, reverse=True)
        book.yes_asks = sorted(yes_asks, key=lambda l: l.price_cents)
        book.last_updated = datetime.now(UTC)

        logger.debug(
            "orderbook.snapshot",
            ticker=ticker,
            bids=len(book.yes_bids),
            asks=len(book.yes_asks),
            mid=book.mid_price_cents(),
            spread=book.spread_cents(),
        )
        return book

    def apply_delta(self, ticker: str, msg: dict[str, Any]) -> Orderbook | None:
        """Apply an incremental orderbook delta from WebSocket."""
        book = self._books.get(ticker)
        if not book:
            logger.warning("orderbook.delta_no_book", ticker=ticker)
            return None

        delta = msg.get("msg", msg)

        # Process YES bid changes
        yes_changes = delta.get("yes_dollars", [])
        if yes_changes:
            book.yes_bids = _apply_level_changes(book.yes_bids, yes_changes)
            book.yes_bids.sort(key=lambda l: l.price_cents, reverse=True)

        # Process NO bid changes → convert to YES ask changes
        no_changes = delta.get("no_dollars", [])
        if no_changes:
            yes_ask_changes = [
                [str((100 - int(float(p) * 100)) / 100), q]
                for p, q in no_changes
            ]
            book.yes_asks = _apply_level_changes(book.yes_asks, yes_ask_changes)
            book.yes_asks.sort(key=lambda l: l.price_cents)

        book.last_updated = datetime.now(UTC)
        return book


def _parse_levels(raw_levels: list[list[str]]) -> list[OrderbookLevel]:
    """Parse [[price_str, quantity_str], ...] into OrderbookLevel list."""
    levels = []
    for item in raw_levels:
        if len(item) < 2:
            continue
        price_cents = int(float(item[0]) * 100)
        quantity = int(float(item[1]))
        if quantity > 0:
            levels.append(OrderbookLevel(price_cents=price_cents, quantity=quantity))
    return levels


def _no_bids_to_yes_asks(no_bids: list[OrderbookLevel]) -> list[OrderbookLevel]:
    """Convert NO-side bids to YES-side asks. yes_ask_price = 100 - no_bid_price."""
    return [
        OrderbookLevel(
            price_cents=100 - level.price_cents,
            quantity=level.quantity,
        )
        for level in no_bids
        if 100 - level.price_cents > 0
    ]


def _apply_level_changes(
    existing: list[OrderbookLevel],
    changes: list[list[str]],
) -> list[OrderbookLevel]:
    """Apply price level changes to an existing level list."""
    level_map: dict[int, int] = {l.price_cents: l.quantity for l in existing}

    for item in changes:
        if len(item) < 2:
            continue
        price_cents = int(float(item[0]) * 100)
        quantity = int(float(item[1]))

        if quantity <= 0:
            level_map.pop(price_cents, None)
        else:
            level_map[price_cents] = quantity

    return [
        OrderbookLevel(price_cents=p, quantity=q)
        for p, q in level_map.items()
    ]
