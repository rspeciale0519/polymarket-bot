"""Tests for the signal integrator."""

import asyncio

import pytest

from engine.core.event_bus import EventBus
from engine.core.types import (
    EngineConfig,
    Orderbook,
    OrderbookLevel,
    OrderbookUpdate,
)
from engine.strategy.signal_integrator import SignalIntegrator


@pytest.fixture
def bus():
    return EventBus()


class TestDirectionalSkew:
    def test_zero_weight_returns_zero(self, bus):
        config = EngineConfig(signal_weight=0.0)
        si = SignalIntegrator(config=config, bus=bus)
        assert si.get_directional_skew_cents("TEST") == 0.0

    def test_nonzero_weight_with_signal(self, bus):
        config = EngineConfig(signal_weight=0.5)
        si = SignalIntegrator(config=config, bus=bus)
        # Manually set a signal
        signal = si.get_signal("TEST")
        signal.combined = 0.8
        skew = si.get_directional_skew_cents("TEST")
        # 0.8 * 0.5 * 5.0 = 2.0 cents
        assert abs(skew - 2.0) < 0.01


class TestTradeRecording:
    def test_buy_momentum(self, bus):
        config = EngineConfig(signal_weight=1.0)
        si = SignalIntegrator(config=config, bus=bus)
        for _ in range(10):
            si.record_trade("TEST", is_buy=True, price_cents=50)
        signal = si.get_signal("TEST")
        assert signal.trade_momentum > 0  # bullish

    def test_sell_momentum(self, bus):
        config = EngineConfig(signal_weight=1.0)
        si = SignalIntegrator(config=config, bus=bus)
        for _ in range(10):
            si.record_trade("TEST", is_buy=False, price_cents=50)
        signal = si.get_signal("TEST")
        assert signal.trade_momentum < 0  # bearish

    def test_mixed_trades_neutral(self, bus):
        config = EngineConfig(signal_weight=1.0)
        si = SignalIntegrator(config=config, bus=bus)
        for i in range(10):
            si.record_trade("TEST", is_buy=(i % 2 == 0), price_cents=50)
        signal = si.get_signal("TEST")
        assert abs(signal.trade_momentum) < 0.3  # roughly neutral


class TestOrderbookImbalance:
    @pytest.mark.asyncio
    async def test_bid_heavy_imbalance(self, bus):
        config = EngineConfig(signal_weight=1.0)
        si = SignalIntegrator(config=config, bus=bus)

        book = Orderbook(
            ticker="TEST",
            yes_bids=[OrderbookLevel(48, 1000), OrderbookLevel(47, 500)],
            yes_asks=[OrderbookLevel(52, 100), OrderbookLevel(53, 50)],
        )
        await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
        await bus.drain()

        signal = si.get_signal("TEST")
        assert signal.volume_imbalance > 0.5  # bid heavy

    @pytest.mark.asyncio
    async def test_ask_heavy_imbalance(self, bus):
        config = EngineConfig(signal_weight=1.0)
        si = SignalIntegrator(config=config, bus=bus)

        book = Orderbook(
            ticker="TEST",
            yes_bids=[OrderbookLevel(48, 50)],
            yes_asks=[OrderbookLevel(52, 1000), OrderbookLevel(53, 500)],
        )
        await bus.publish(OrderbookUpdate(ticker="TEST", orderbook=book))
        await bus.drain()

        signal = si.get_signal("TEST")
        assert signal.volume_imbalance < -0.5  # ask heavy


class TestReset:
    def test_reset_clears_state(self, bus):
        config = EngineConfig(signal_weight=1.0)
        si = SignalIntegrator(config=config, bus=bus)
        for _ in range(10):
            si.record_trade("TEST", is_buy=True, price_cents=50)
        si.reset("TEST")
        signal = si.get_signal("TEST")
        assert signal.combined == 0.0
