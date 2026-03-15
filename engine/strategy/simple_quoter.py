"""
Simple quoting strategy: midpoint + fixed spread.

This is the initial strategy that gets paper trades running immediately.
It will be replaced by the full Avellaneda-Stoikov model in Phase 4.

On each OrderbookUpdate:
  bid = mid_price - half_spread
  ask = mid_price + half_spread
  Clamp to [1, 99], enforce min_spread floor.
  Emit QuoteGenerated event.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    EngineConfig,
    OrderAck,
    OrderRequest,
    OrderbookUpdate,
    Quote,
    QuoteGenerated,
    Side,
)
from engine.execution.base_executor import ExecutionAdapter
from engine.risk.risk_engine import RiskEngine

logger = structlog.get_logger(__name__)

MIN_REPRICE_INTERVAL_MS = 500


class SimpleQuoter:
    """Posts two-sided quotes at midpoint +/- half spread."""

    def __init__(
        self,
        config: EngineConfig,
        bus: EventBus,
        executor: ExecutionAdapter,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self._config = config
        self._bus = bus
        self._executor = executor
        self._risk = risk_engine

        # Track resting orders per market: {ticker: (bid_order_id, ask_order_id)}
        self._resting: dict[str, tuple[str | None, str | None]] = {}
        self._last_quote_time: dict[str, float] = {}
        self._paused_markets: set[str] = set()

        self._bus.subscribe(OrderbookUpdate, self._on_orderbook_update)

    async def _on_orderbook_update(self, event: OrderbookUpdate) -> None:
        ticker = event.ticker
        book = event.orderbook

        if ticker in self._paused_markets:
            return

        # Rate limit: don't reprice faster than MIN_REPRICE_INTERVAL_MS
        now_ms = datetime.now(UTC).timestamp() * 1000
        last = self._last_quote_time.get(ticker, 0)
        if now_ms - last < MIN_REPRICE_INTERVAL_MS:
            return

        mid = book.mid_price_cents()
        if mid <= 0 or mid >= 100:
            return

        spread = max(self._config.min_spread_cents, 4)
        half_spread = spread / 2.0

        bid_price = max(1, int(mid - half_spread))
        ask_price = min(99, int(mid + half_spread))

        # Ensure minimum spread is maintained
        if ask_price - bid_price < self._config.min_spread_cents:
            ask_price = min(99, bid_price + self._config.min_spread_cents)

        quote = Quote(
            ticker=ticker,
            bid_price_cents=bid_price,
            bid_size=self._config.order_size,
            ask_price_cents=ask_price,
            ask_size=self._config.order_size,
            fair_value_cents=mid,
        )

        await self._manage_orders(quote)
        self._last_quote_time[ticker] = now_ms
        await self._bus.publish(QuoteGenerated(quote=quote))

    async def _manage_orders(self, quote: Quote) -> None:
        """Place or amend orders to match the desired quote."""
        existing = self._resting.get(quote.ticker, (None, None))
        bid_oid, ask_oid = existing

        # For simplicity in the initial quoter, cancel-replace on every reprice.
        # Phase 4's AS quoter will use amend for small price changes.
        if bid_oid:
            await self._executor.cancel_order(bid_oid)
        if ask_oid:
            await self._executor.cancel_order(ask_oid)

        # Place new bid
        bid_req = OrderRequest(
            ticker=quote.ticker,
            side=Side.YES,
            action=Action.BUY,
            count=quote.bid_size,
            price_cents=quote.bid_price_cents,
            post_only=True,
        )

        # Place new ask
        ask_req = OrderRequest(
            ticker=quote.ticker,
            side=Side.YES,
            action=Action.SELL,
            count=quote.ask_size,
            price_cents=quote.ask_price_cents,
            post_only=True,
        )

        # Risk check (if risk engine available)
        if self._risk:
            bid_violations = self._risk.check(bid_req)
            ask_violations = self._risk.check(ask_req)
            blocking_bid = [v for v in bid_violations if v.severity in ("block", "halt")]
            blocking_ask = [v for v in ask_violations if v.severity in ("block", "halt")]
        else:
            blocking_bid = []
            blocking_ask = []

        new_bid_id = None
        new_ask_id = None

        if not blocking_bid:
            bid_ack = await self._executor.submit_order(bid_req)
            if bid_ack.is_success:
                new_bid_id = bid_ack.order_id

        if not blocking_ask:
            ask_ack = await self._executor.submit_order(ask_req)
            if ask_ack.is_success:
                new_ask_id = ask_ack.order_id

        self._resting[quote.ticker] = (new_bid_id, new_ask_id)

    def pause_market(self, ticker: str) -> None:
        self._paused_markets.add(ticker)

    def resume_market(self, ticker: str) -> None:
        self._paused_markets.discard(ticker)

    async def cancel_all_quotes(self) -> int:
        """Cancel all resting quotes across all markets."""
        count = 0
        for ticker, (bid_oid, ask_oid) in list(self._resting.items()):
            if bid_oid:
                await self._executor.cancel_order(bid_oid)
                count += 1
            if ask_oid:
                await self._executor.cancel_order(ask_oid)
                count += 1
        self._resting.clear()
        return count

    @property
    def active_markets(self) -> list[str]:
        return [t for t, (b, a) in self._resting.items() if b or a]
