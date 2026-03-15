"""Tests for the inventory manager."""

import asyncio

import pytest

from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    EngineConfig,
    Fill,
    FillEvent,
    Orderbook,
    OrderbookLevel,
    OrderbookUpdate,
    Side,
)
from engine.strategy.inventory_manager import InventoryManager


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def config():
    return EngineConfig(max_position_per_market=10)


@pytest.fixture
def mgr(config, bus):
    return InventoryManager(config=config, bus=bus)


class TestInventoryRatio:
    def test_flat_is_zero(self, mgr):
        assert mgr.get_inventory_ratio("TEST") == 0.0

    @pytest.mark.asyncio
    async def test_buy_increases_ratio(self, mgr, bus):
        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST",
            side=Side.YES, action=Action.BUY, count=5,
            price_cents=50, fee_cents=0, is_maker=True,
        )
        await bus.publish(FillEvent(fill=fill))
        await bus.drain()
        assert mgr.get_inventory_ratio("TEST") == 0.5  # 5/10

    @pytest.mark.asyncio
    async def test_sell_decreases_ratio(self, mgr, bus):
        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST",
            side=Side.YES, action=Action.SELL, count=3,
            price_cents=50, fee_cents=0, is_maker=True,
        )
        await bus.publish(FillEvent(fill=fill))
        await bus.drain()
        assert mgr.get_inventory_ratio("TEST") == -0.3  # -3/10

    @pytest.mark.asyncio
    async def test_ratio_clamped(self, mgr, bus):
        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST",
            side=Side.YES, action=Action.BUY, count=15,
            price_cents=50, fee_cents=0, is_maker=True,
        )
        await bus.publish(FillEvent(fill=fill))
        await bus.drain()
        assert mgr.get_inventory_ratio("TEST") == 1.0  # clamped


class TestShouldFlatten:
    @pytest.mark.asyncio
    async def test_below_threshold(self, mgr, bus):
        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST",
            side=Side.YES, action=Action.BUY, count=7,
            price_cents=50, fee_cents=0, is_maker=True,
        )
        await bus.publish(FillEvent(fill=fill))
        await bus.drain()
        assert not mgr.should_flatten("TEST")  # 7/10 = 70% < 80%

    @pytest.mark.asyncio
    async def test_above_threshold(self, mgr, bus):
        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST",
            side=Side.YES, action=Action.BUY, count=9,
            price_cents=50, fee_cents=0, is_maker=True,
        )
        await bus.publish(FillEvent(fill=fill))
        await bus.drain()
        assert mgr.should_flatten("TEST")  # 9/10 = 90% > 80%


class TestMidPriceTracking:
    @pytest.mark.asyncio
    async def test_tracks_mid_price(self, mgr, bus):
        book = Orderbook(
            ticker="TEST",
            yes_bids=[OrderbookLevel(48, 100)],
            yes_asks=[OrderbookLevel(52, 100)],
        )
        await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
        await bus.drain()
        assert mgr._mid_prices.get("TEST") == 50.0


class TestTotalExposure:
    @pytest.mark.asyncio
    async def test_exposure_calculation(self, mgr, bus):
        # Buy 5 YES in TEST at 50c
        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST",
            side=Side.YES, action=Action.BUY, count=5,
            price_cents=50, fee_cents=0, is_maker=True,
        )
        await bus.publish(FillEvent(fill=fill))
        await bus.drain()

        # Update mid price
        book = Orderbook(
            ticker="TEST",
            yes_bids=[OrderbookLevel(48, 100)],
            yes_asks=[OrderbookLevel(52, 100)],
        )
        await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
        await bus.drain()

        exposure = mgr.get_total_exposure_cents()
        assert exposure == 5 * 50  # 5 contracts * 50c mid
