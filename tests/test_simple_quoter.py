"""Tests for the simple quoter strategy."""

import asyncio

import pytest

from engine.core.event_bus import EventBus
from engine.core.types import (
    EngineConfig,
    Orderbook,
    OrderbookLevel,
    OrderbookUpdate,
    QuoteGenerated,
)
from engine.execution.paper_executor import PaperExecutor
from engine.strategy.simple_quoter import SimpleQuoter


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def config():
    return EngineConfig(min_spread_cents=4, order_size=5)


@pytest.fixture
def executor(bus):
    return PaperExecutor(bus=bus, starting_balance_cents=100000)


@pytest.fixture
def quoter(config, bus, executor):
    return SimpleQuoter(config=config, bus=bus, executor=executor)


@pytest.mark.asyncio
async def test_quoter_generates_orders_on_update(quoter, bus, executor):
    """Quoter should place bid + ask orders on orderbook update."""
    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(48, 100)],
        yes_asks=[OrderbookLevel(52, 100)],
    )
    await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
    await bus.drain()
    await asyncio.sleep(0.1)

    # Should have 2 resting orders (bid + ask)
    assert executor.resting_order_count == 2


@pytest.mark.asyncio
async def test_quoter_emits_quote_event(quoter, bus):
    """Quoter should publish QuoteGenerated events."""
    quotes_received = []

    async def on_quote(event: QuoteGenerated):
        quotes_received.append(event.quote)

    bus.subscribe(QuoteGenerated, on_quote)

    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(45, 100)],
        yes_asks=[OrderbookLevel(55, 100)],
    )
    await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
    await bus.drain()
    await asyncio.sleep(0.1)
    await bus.drain()

    assert len(quotes_received) == 1
    q = quotes_received[0]
    assert q.ticker == "TEST"
    assert q.bid_price_cents < q.ask_price_cents
    assert q.ask_price_cents - q.bid_price_cents >= 4  # min spread


@pytest.mark.asyncio
async def test_quoter_clamps_prices(bus, executor):
    """Prices should be clamped to [1, 99]."""
    config = EngineConfig(min_spread_cents=4, order_size=5)
    quoter = SimpleQuoter(config=config, bus=bus, executor=executor)

    quotes = []
    async def on_quote(e: QuoteGenerated):
        quotes.append(e.quote)
    bus.subscribe(QuoteGenerated, on_quote)

    # Book near the extremes
    book = Orderbook(
        ticker="EDGE",
        yes_bids=[OrderbookLevel(97, 100)],
        yes_asks=[OrderbookLevel(99, 100)],
    )
    await bus.publish(OrderbookUpdate(ticker="EDGE", orderbook=book))
    await bus.drain()
    await asyncio.sleep(0.1)
    await bus.drain()

    assert len(quotes) == 1
    assert quotes[0].bid_price_cents >= 1
    assert quotes[0].ask_price_cents <= 99


@pytest.mark.asyncio
async def test_quoter_pause_resume(quoter, bus, executor):
    """Paused markets should not generate quotes."""
    quoter.pause_market("TEST")

    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(48, 100)],
        yes_asks=[OrderbookLevel(52, 100)],
    )
    await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
    await bus.drain()
    await asyncio.sleep(0.1)

    assert executor.resting_order_count == 0

    # Resume and verify it works again
    quoter.resume_market("TEST")
    await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
    await bus.drain()
    await asyncio.sleep(0.1)

    assert executor.resting_order_count == 2


@pytest.mark.asyncio
async def test_cancel_all_quotes(quoter, bus, executor):
    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(48, 100)],
        yes_asks=[OrderbookLevel(52, 100)],
    )
    await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
    await bus.drain()
    await asyncio.sleep(0.1)

    cancelled = await quoter.cancel_all_quotes()
    assert cancelled == 2
    assert executor.resting_order_count == 0
