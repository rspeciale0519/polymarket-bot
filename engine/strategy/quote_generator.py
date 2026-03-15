"""
Full quote generation pipeline using Avellaneda-Stoikov model.

Replaces simple_quoter.py. On each OrderbookUpdate:
  orderbook → inventory ratio → dynamic gamma → AS reservation price
  → AS spread → signal skew → inventory skew → clamp [1,99]
  → enforce min spread → emit Quote

Uses order amendment for small price changes (preserves queue position).
Falls back to cancel-replace for large moves.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import structlog

from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    EngineConfig,
    MarketPaused,
    MarketResolved,
    MarketResumed,
    OrderAck,
    OrderbookUpdate,
    OrderRequest,
    Quote,
    QuoteGenerated,
    Side,
)
from engine.execution.base_executor import ExecutionAdapter
from engine.risk.circuit_breakers import CircuitBreakerManager
from engine.risk.risk_engine import RiskEngine
from engine.strategy.avellaneda_stoikov import compute_quotes
from engine.strategy.inventory_manager import InventoryManager
from engine.strategy.signal_integrator import SignalIntegrator

logger = structlog.get_logger(__name__)

MIN_REPRICE_INTERVAL_MS = 500
AMEND_THRESHOLD_CENTS = 3


class QuoteGenerator:
    """Generates two-sided quotes using the AS model."""

    def __init__(
        self,
        config: EngineConfig,
        bus: EventBus,
        executor: ExecutionAdapter,
        risk_engine: RiskEngine,
        inventory_mgr: InventoryManager,
        signal_integrator: SignalIntegrator,
        circuit_breakers: CircuitBreakerManager | None = None,
    ) -> None:
        self._config = config
        self._bus = bus
        self._executor = executor
        self._risk = risk_engine
        self._inventory = inventory_mgr
        self._signals = signal_integrator
        self._breakers = circuit_breakers

        # Resting orders: {ticker: (bid_order_id, ask_order_id)}
        self._resting: dict[str, tuple[str | None, str | None]] = {}
        # Last quote prices: {ticker: (bid_cents, ask_cents)}
        self._last_quotes: dict[str, tuple[int, int]] = {}
        self._last_reprice_ms: dict[str, float] = {}
        self._paused_markets: set[str] = set()
        # Market expiry times: {ticker: seconds remaining}
        self._time_remaining: dict[str, float] = {}

        self._bus.subscribe(OrderbookUpdate, self._on_orderbook_update)
        self._bus.subscribe(MarketResolved, self._on_market_resolved)
        self._bus.subscribe(MarketPaused, self._on_market_paused)
        self._bus.subscribe(MarketResumed, self._on_market_resumed)

    def set_time_remaining(self, ticker: str, fraction: float) -> None:
        """Set time remaining as fraction [0, 1] for a market."""
        self._time_remaining[ticker] = max(0.0, min(1.0, fraction))

    async def _on_orderbook_update(self, event: OrderbookUpdate) -> None:
        ticker = event.ticker
        book = event.orderbook

        if ticker in self._paused_markets:
            return

        if self._risk.is_halted:
            return

        # Rate limit
        now_ms = time.monotonic() * 1000
        last = self._last_reprice_ms.get(ticker, 0)
        if now_ms - last < MIN_REPRICE_INTERVAL_MS:
            return

        mid = book.mid_price_cents()
        if mid <= 1 or mid >= 99:
            return

        # Gather inputs
        inv_ratio = self._inventory.get_inventory_ratio(ticker)
        signal_skew = self._signals.get_directional_skew_cents(ticker)
        t_remaining = self._time_remaining.get(ticker, 0.5)
        spread_mult = self._breakers.spread_multiplier if self._breakers else 1.0

        if spread_mult <= 0:
            # Circuit breaker says pull all quotes
            await self._cancel_market_quotes(ticker)
            return

        # Compute quotes via AS model
        bid_cents, ask_cents, fair_value = compute_quotes(
            mid_price=mid,
            inventory_ratio=inv_ratio,
            gamma=self._config.base_gamma,
            sigma=self._config.sigma,
            time_remaining=t_remaining,
            kappa=1.5,  # Will be calibrated from data post-launch
            min_spread_cents=self._config.min_spread_cents,
            signal_skew=signal_skew,
            spread_multiplier=spread_mult,
        )

        quote = Quote(
            ticker=ticker,
            bid_price_cents=bid_cents,
            bid_size=self._config.order_size,
            ask_price_cents=ask_cents,
            ask_size=self._config.order_size,
            fair_value_cents=fair_value,
        )

        await self._manage_orders(quote)
        self._last_reprice_ms[ticker] = now_ms
        await self._bus.publish(QuoteGenerated(quote=quote))

    async def _manage_orders(self, quote: Quote) -> None:
        """Place, amend, or replace orders to match desired quote."""
        ticker = quote.ticker
        existing = self._resting.get(ticker, (None, None))
        bid_oid, ask_oid = existing
        last = self._last_quotes.get(ticker, (0, 0))
        last_bid, last_ask = last

        new_bid_oid = bid_oid
        new_ask_oid = ask_oid

        # Decide: amend or cancel-replace for bid
        bid_delta = abs(quote.bid_price_cents - last_bid) if last_bid else 99
        if bid_oid and bid_delta <= AMEND_THRESHOLD_CENTS and bid_delta > 0:
            ack = await self._executor.amend_order(
                bid_oid, quote.bid_price_cents, quote.bid_size
            )
            if not ack.is_success:
                new_bid_oid = await self._place_bid(quote)
        elif bid_delta > 0 or not bid_oid:
            if bid_oid:
                await self._executor.cancel_order(bid_oid)
            new_bid_oid = await self._place_bid(quote)

        # Decide: amend or cancel-replace for ask
        ask_delta = abs(quote.ask_price_cents - last_ask) if last_ask else 99
        if ask_oid and ask_delta <= AMEND_THRESHOLD_CENTS and ask_delta > 0:
            ack = await self._executor.amend_order(
                ask_oid, quote.ask_price_cents, quote.ask_size
            )
            if not ack.is_success:
                new_ask_oid = await self._place_ask(quote)
        elif ask_delta > 0 or not ask_oid:
            if ask_oid:
                await self._executor.cancel_order(ask_oid)
            new_ask_oid = await self._place_ask(quote)

        self._resting[ticker] = (new_bid_oid, new_ask_oid)
        self._last_quotes[ticker] = (quote.bid_price_cents, quote.ask_price_cents)

    async def _place_bid(self, quote: Quote) -> str | None:
        req = OrderRequest(
            ticker=quote.ticker, side=Side.YES, action=Action.BUY,
            count=quote.bid_size, price_cents=quote.bid_price_cents,
            post_only=True,
        )
        violations = self._risk.check(req)
        if any(v.severity in ("block", "halt") for v in violations):
            return None
        ack = await self._executor.submit_order(req)
        return ack.order_id if ack.is_success else None

    async def _place_ask(self, quote: Quote) -> str | None:
        req = OrderRequest(
            ticker=quote.ticker, side=Side.YES, action=Action.SELL,
            count=quote.ask_size, price_cents=quote.ask_price_cents,
            post_only=True,
        )
        violations = self._risk.check(req)
        if any(v.severity in ("block", "halt") for v in violations):
            return None
        ack = await self._executor.submit_order(req)
        return ack.order_id if ack.is_success else None

    async def _cancel_market_quotes(self, ticker: str) -> None:
        existing = self._resting.get(ticker, (None, None))
        for oid in existing:
            if oid:
                await self._executor.cancel_order(oid)
        self._resting[ticker] = (None, None)

    async def _on_market_resolved(self, event: MarketResolved) -> None:
        await self._cancel_market_quotes(event.ticker)
        self._paused_markets.add(event.ticker)

    async def _on_market_paused(self, event: MarketPaused) -> None:
        await self._cancel_market_quotes(event.ticker)
        self._paused_markets.add(event.ticker)

    async def _on_market_resumed(self, event: MarketResumed) -> None:
        self._paused_markets.discard(event.ticker)

    def pause_market(self, ticker: str) -> None:
        self._paused_markets.add(ticker)

    def resume_market(self, ticker: str) -> None:
        self._paused_markets.discard(ticker)

    async def cancel_all_quotes(self) -> int:
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

    @property
    def resting_order_count(self) -> int:
        return sum(
            (1 if b else 0) + (1 if a else 0)
            for b, a in self._resting.values()
        )
