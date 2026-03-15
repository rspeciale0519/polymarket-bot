"""
Integration tests — verify full engine wiring and event flow.

Tests that all components connect correctly through the event bus
and that the quote generation pipeline works end-to-end.
"""

import asyncio

import pytest

from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    ConnectionLost,
    EngineConfig,
    Fill,
    FillEvent,
    MarketPaused,
    MarketResolved,
    MarketResumed,
    Mode,
    Orderbook,
    OrderbookLevel,
    OrderbookUpdate,
    OrderRequest,
    QuoteGenerated,
    Side,
)
from engine.execution.paper_executor import PaperExecutor
from engine.risk.circuit_breakers import CircuitBreakerManager
from engine.risk.position_tracker import PositionTracker
from engine.risk.risk_engine import RiskEngine
from engine.strategy.inventory_manager import InventoryManager
from engine.strategy.quote_generator import QuoteGenerator
from engine.strategy.signal_integrator import SignalIntegrator


def _make_config(**overrides) -> EngineConfig:
    defaults = {
        "mode": Mode.PAPER,
        "max_position_per_market": 20,
        "global_exposure_limit_cents": 50000,
        "daily_loss_limit_cents": 5000,
        "min_spread_cents": 3,
        "order_size": 5,
        "base_gamma": 0.3,
        "sigma": 0.15,
        "signal_weight": 0.0,
        "paper_starting_capital_cents": 100000,
    }
    defaults.update(overrides)
    return EngineConfig(**defaults)


class TestFullPipeline:
    """Test the complete flow: orderbook update → quote → order → fill."""

    @pytest.mark.asyncio
    async def test_orderbook_update_triggers_quote(self):
        """An orderbook update should produce a QuoteGenerated event."""
        config = _make_config()
        bus = EventBus()
        executor = PaperExecutor(bus=bus, starting_balance_cents=100000)
        risk = RiskEngine(config)
        inventory = InventoryManager(config=config, bus=bus)
        signals = SignalIntegrator(config=config, bus=bus)
        breakers = CircuitBreakerManager(bus=bus, risk_engine=risk)

        quoter = QuoteGenerator(
            config=config, bus=bus, executor=executor,
            risk_engine=risk, inventory_mgr=inventory,
            signal_integrator=signals, circuit_breakers=breakers,
        )

        quotes_received: list = []

        async def on_quote(event: QuoteGenerated):
            quotes_received.append(event.quote)

        bus.subscribe(QuoteGenerated, on_quote)

        book = Orderbook(
            ticker="TEST-MKT",
            yes_bids=[OrderbookLevel(45, 200)],
            yes_asks=[OrderbookLevel(55, 200)],
        )
        await bus.publish(OrderbookUpdate(ticker="TEST-MKT", orderbook=book))
        await bus.drain()
        await asyncio.sleep(0.1)
        await bus.drain()

        assert len(quotes_received) == 1
        q = quotes_received[0]
        assert q.ticker == "TEST-MKT"
        assert 1 <= q.bid_price_cents < q.ask_price_cents <= 99
        assert q.ask_price_cents - q.bid_price_cents >= config.min_spread_cents

    @pytest.mark.asyncio
    async def test_quote_places_orders_in_executor(self):
        """Quotes should result in resting orders in the paper executor."""
        config = _make_config()
        bus = EventBus()
        executor = PaperExecutor(bus=bus, starting_balance_cents=100000)
        risk = RiskEngine(config)
        inventory = InventoryManager(config=config, bus=bus)
        signals = SignalIntegrator(config=config, bus=bus)

        quoter = QuoteGenerator(
            config=config, bus=bus, executor=executor,
            risk_engine=risk, inventory_mgr=inventory,
            signal_integrator=signals,
        )

        book = Orderbook(
            ticker="TEST-MKT",
            yes_bids=[OrderbookLevel(45, 200)],
            yes_asks=[OrderbookLevel(55, 200)],
        )
        await bus.publish(OrderbookUpdate(ticker="TEST-MKT", orderbook=book))
        await bus.drain()
        await asyncio.sleep(0.1)

        assert executor.resting_order_count >= 2  # bid + ask

    @pytest.mark.asyncio
    async def test_fill_updates_position_tracker(self):
        """A fill event should update the position tracker."""
        config = _make_config()
        bus = EventBus()
        risk = RiskEngine(config)
        tracker = PositionTracker(
            bus=bus, risk_engine=risk, mode=Mode.PAPER,
        )

        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST-MKT",
            side=Side.YES, action=Action.BUY, count=5,
            price_cents=50, fee_cents=1, is_maker=True,
        )
        await bus.publish(FillEvent(fill=fill))
        await bus.drain()

        positions = tracker.get_all_positions()
        assert len(positions) == 1
        assert positions[0].ticker == "TEST-MKT"
        assert positions[0].net_position == 5

    @pytest.mark.asyncio
    async def test_fill_updates_risk_engine(self):
        """Fills should propagate to the risk engine's position tracking."""
        config = _make_config()
        bus = EventBus()
        risk = RiskEngine(config)
        tracker = PositionTracker(
            bus=bus, risk_engine=risk, mode=Mode.PAPER,
        )

        fill = Fill(
            fill_id="f1", order_id="o1", ticker="TEST-MKT",
            side=Side.YES, action=Action.BUY, count=5,
            price_cents=50, fee_cents=1, is_maker=True,
        )
        await bus.publish(FillEvent(fill=fill))
        await bus.drain()

        assert "TEST-MKT" in risk.positions
        assert risk.positions["TEST-MKT"].net_position == 5

    @pytest.mark.asyncio
    async def test_risk_blocks_over_inventory(self):
        """Risk engine should block orders that exceed inventory limits."""
        config = _make_config(max_position_per_market=5)
        bus = EventBus()
        executor = PaperExecutor(bus=bus, starting_balance_cents=100000)
        risk = RiskEngine(config)
        inventory = InventoryManager(config=config, bus=bus)
        signals = SignalIntegrator(config=config, bus=bus)

        quoter = QuoteGenerator(
            config=config, bus=bus, executor=executor,
            risk_engine=risk, inventory_mgr=inventory,
            signal_integrator=signals,
        )

        # Simulate existing large position
        from engine.core.types import InventoryState
        risk.update_position(InventoryState(ticker="TEST-MKT", net_position=5))

        # Try to place a buy order — should be blocked
        req = OrderRequest(
            ticker="TEST-MKT", side=Side.YES, action=Action.BUY,
            count=3, price_cents=50,
        )
        violations = risk.check(req)
        blocked = [v for v in violations if v.severity in ("block", "halt")]
        assert len(blocked) > 0

    @pytest.mark.asyncio
    async def test_market_resolved_stops_quoting(self):
        """A MarketResolved event should stop the quoter from quoting that market."""
        config = _make_config()
        bus = EventBus()
        executor = PaperExecutor(bus=bus, starting_balance_cents=100000)
        risk = RiskEngine(config)
        inventory = InventoryManager(config=config, bus=bus)
        signals = SignalIntegrator(config=config, bus=bus)

        quoter = QuoteGenerator(
            config=config, bus=bus, executor=executor,
            risk_engine=risk, inventory_mgr=inventory,
            signal_integrator=signals,
        )

        # First, generate a quote
        book = Orderbook(
            ticker="RESOLVED-MKT",
            yes_bids=[OrderbookLevel(45, 200)],
            yes_asks=[OrderbookLevel(55, 200)],
        )
        await bus.publish(OrderbookUpdate(ticker="RESOLVED-MKT", orderbook=book))
        await bus.drain()
        await asyncio.sleep(0.1)

        initial_orders = executor.resting_order_count

        # Now resolve the market
        await bus.publish(MarketResolved(ticker="RESOLVED-MKT", result="yes"))
        await bus.drain()
        await asyncio.sleep(0.1)

        # Send another orderbook update — should be ignored
        await bus.publish(OrderbookUpdate(ticker="RESOLVED-MKT", orderbook=book))
        await bus.drain()
        await asyncio.sleep(0.6)  # past reprice interval
        await bus.drain()

        # Orders should have been cancelled (market resolved handler)
        # and no new orders placed
        assert executor.resting_order_count <= initial_orders

    @pytest.mark.asyncio
    async def test_circuit_breaker_halts_trading(self):
        """Circuit breaker halt should prevent new quotes."""
        config = _make_config()
        bus = EventBus()
        executor = PaperExecutor(bus=bus, starting_balance_cents=100000)
        risk = RiskEngine(config)
        inventory = InventoryManager(config=config, bus=bus)
        signals = SignalIntegrator(config=config, bus=bus)
        breakers = CircuitBreakerManager(bus=bus, risk_engine=risk)

        quoter = QuoteGenerator(
            config=config, bus=bus, executor=executor,
            risk_engine=risk, inventory_mgr=inventory,
            signal_integrator=signals, circuit_breakers=breakers,
        )

        # Halt the engine
        risk.halt("test halt")

        # Send an orderbook update — should not generate quotes
        book = Orderbook(
            ticker="HALTED-MKT",
            yes_bids=[OrderbookLevel(45, 200)],
            yes_asks=[OrderbookLevel(55, 200)],
        )
        await bus.publish(OrderbookUpdate(ticker="HALTED-MKT", orderbook=book))
        await bus.drain()
        await asyncio.sleep(0.1)

        assert executor.resting_order_count == 0

    @pytest.mark.asyncio
    async def test_inventory_skew_affects_quotes(self):
        """Long inventory should skew quotes downward."""
        config = _make_config(signal_weight=0.0)
        bus = EventBus()
        executor = PaperExecutor(bus=bus, starting_balance_cents=100000)
        risk = RiskEngine(config)
        inventory = InventoryManager(config=config, bus=bus)
        signals = SignalIntegrator(config=config, bus=bus)

        quoter = QuoteGenerator(
            config=config, bus=bus, executor=executor,
            risk_engine=risk, inventory_mgr=inventory,
            signal_integrator=signals,
        )

        # Simulate long inventory via a fill
        fill = Fill(
            fill_id="f1", order_id="o1", ticker="SKEW-MKT",
            side=Side.YES, action=Action.BUY, count=15,
            price_cents=50, fee_cents=1, is_maker=True,
        )
        await bus.publish(FillEvent(fill=fill))
        await bus.drain()

        # Capture quotes
        quotes_flat: list = []
        quotes_long: list = []

        async def capture(event: QuoteGenerated):
            if event.quote.ticker == "SKEW-MKT":
                quotes_long.append(event.quote)

        bus.subscribe(QuoteGenerated, capture)

        book = Orderbook(
            ticker="SKEW-MKT",
            yes_bids=[OrderbookLevel(48, 200)],
            yes_asks=[OrderbookLevel(52, 200)],
        )
        await bus.publish(OrderbookUpdate(ticker="SKEW-MKT", orderbook=book))
        await bus.drain()
        await asyncio.sleep(0.1)
        await bus.drain()

        assert len(quotes_long) == 1
        q = quotes_long[0]
        # With long inventory, fair value should be below midpoint (50)
        assert q.fair_value_cents < 50.0


class TestEventBusWiring:
    """Test that all expected subscribers are connected."""

    @pytest.mark.asyncio
    async def test_multiple_subscribers_on_fill(self):
        """Both position tracker and circuit breakers listen to fills."""
        config = _make_config()
        bus = EventBus()
        risk = RiskEngine(config)
        tracker = PositionTracker(bus=bus, risk_engine=risk, mode=Mode.PAPER)
        breakers = CircuitBreakerManager(bus=bus, risk_engine=risk)

        # FillEvent should have at least 2 subscribers
        fill_subs = bus._subscribers.get(FillEvent, [])
        assert len(fill_subs) >= 2

    @pytest.mark.asyncio
    async def test_connection_lost_subscribed(self):
        """CircuitBreakerManager subscribes to ConnectionLost."""
        config = _make_config()
        bus = EventBus()
        risk = RiskEngine(config)
        breakers = CircuitBreakerManager(bus=bus, risk_engine=risk)

        subs = bus._subscribers.get(ConnectionLost, [])
        assert len(subs) >= 1
