"""Tests for the paper trading executor."""

import asyncio

import pytest

from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    Fill,
    FillEvent,
    Orderbook,
    OrderbookLevel,
    OrderbookUpdate,
    OrderRequest,
    Side,
)
from engine.execution.paper_executor import PaperExecutor


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def executor(bus):
    return PaperExecutor(bus=bus, starting_balance_cents=10000)


@pytest.mark.asyncio
async def test_submit_order(executor):
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=50,
    )
    ack = await executor.submit_order(req)
    assert ack.is_success
    assert ack.status == "resting"
    assert executor.resting_order_count == 1


@pytest.mark.asyncio
async def test_submit_order_insufficient_balance(bus):
    executor = PaperExecutor(bus=bus, starting_balance_cents=100)
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=10, price_cents=50,  # cost = 500 > 100
    )
    ack = await executor.submit_order(req)
    assert not ack.is_success
    assert ack.status == "rejected"


@pytest.mark.asyncio
async def test_cancel_order(executor):
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=50,
    )
    ack = await executor.submit_order(req)
    result = await executor.cancel_order(ack.order_id)
    assert result is True
    assert executor.resting_order_count == 0


@pytest.mark.asyncio
async def test_cancel_all(executor):
    for i in range(3):
        await executor.submit_order(OrderRequest(
            ticker=f"TEST-{i}", side=Side.YES, action=Action.BUY,
            count=1, price_cents=50,
        ))
    assert executor.resting_order_count == 3
    count = await executor.cancel_all()
    assert count == 3
    assert executor.resting_order_count == 0


@pytest.mark.asyncio
async def test_fill_on_orderbook_update(executor, bus):
    """A resting buy order should fill when the ask drops to its price."""
    fills_received: list[Fill] = []

    async def on_fill(event: FillEvent):
        fills_received.append(event.fill)

    bus.subscribe(FillEvent, on_fill)

    # Place a buy order at 48 cents
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=48,
    )
    await executor.submit_order(req)

    # Orderbook update with ask at 48 (crosses our bid)
    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(47, 100)],
        yes_asks=[OrderbookLevel(48, 100)],
    )
    await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
    await bus.drain()

    # Allow fill event to propagate
    await asyncio.sleep(0.1)
    await bus.drain()

    assert executor.resting_order_count == 0
    assert len(fills_received) == 1
    assert fills_received[0].ticker == "TEST"
    assert fills_received[0].count == 5
    assert fills_received[0].is_maker is True


@pytest.mark.asyncio
async def test_no_fill_when_spread_too_wide(executor, bus):
    """Buy at 48 should NOT fill when best ask is 52."""
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=48,
    )
    await executor.submit_order(req)

    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(47, 100)],
        yes_asks=[OrderbookLevel(52, 100)],  # ask too high
    )
    await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
    await bus.drain()

    assert executor.resting_order_count == 1  # still resting


@pytest.mark.asyncio
async def test_balance_decreases_on_buy_fill(executor, bus):
    initial_balance = await executor.get_balance_cents()

    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=50,
    )
    await executor.submit_order(req)

    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(49, 100)],
        yes_asks=[OrderbookLevel(50, 100)],
    )
    await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
    await bus.drain()
    await asyncio.sleep(0.1)

    new_balance = await executor.get_balance_cents()
    # Balance should decrease by (5 * 50) + maker_fee
    assert new_balance < initial_balance


@pytest.mark.asyncio
async def test_amend_order(executor):
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=50,
    )
    ack = await executor.submit_order(req)

    amend_ack = await executor.amend_order(ack.order_id, 48, 5)
    assert amend_ack.is_success
    assert amend_ack.price_cents == 48


@pytest.mark.asyncio
async def test_get_positions_empty(executor):
    positions = await executor.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_sell_fill(executor, bus):
    """A resting sell order should fill when the bid rises to its price."""
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.SELL,
        count=3, price_cents=55,
    )
    await executor.submit_order(req)

    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(55, 100)],
        yes_asks=[OrderbookLevel(60, 100)],
    )
    await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
    await bus.drain()
    await asyncio.sleep(0.1)

    assert executor.resting_order_count == 0
