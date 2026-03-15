"""Tests for backtest executor, data loader, and backtest runner."""

import asyncio
from datetime import UTC, datetime

import pytest

from engine.backtest.backtest_runner import (
    BacktestRunner,
    _compute_max_drawdown,
    _compute_sharpe,
)
from engine.backtest.data_loader import HistoricalDataset, HistoricalTick, _parse_candlestick
from engine.core.event_bus import EventBus
from engine.core.types import (
    Action,
    EngineConfig,
    Orderbook,
    OrderbookLevel,
    OrderRequest,
    Side,
)
from engine.execution.backtest_executor import BacktestExecutor


# ---------------------------------------------------------------------------
# BacktestExecutor tests
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def bt_executor(bus):
    return BacktestExecutor(bus=bus, starting_balance_cents=10000)


@pytest.mark.asyncio
async def test_bt_submit_order(bt_executor):
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=50,
    )
    ack = await bt_executor.submit_order(req)
    assert ack.is_success
    assert ack.status == "resting"


@pytest.mark.asyncio
async def test_bt_insufficient_balance(bus):
    executor = BacktestExecutor(bus=bus, starting_balance_cents=100)
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=10, price_cents=50,
    )
    ack = await executor.submit_order(req)
    assert not ack.is_success


@pytest.mark.asyncio
async def test_bt_fill_on_tick(bt_executor, bus):
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=48,
    )
    await bt_executor.submit_order(req)

    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(47, 100)],
        yes_asks=[OrderbookLevel(48, 100)],
    )
    await bt_executor.process_orderbook_tick("TEST", book)
    await bus.drain()
    await asyncio.sleep(0.1)

    assert bt_executor.total_fills == 1
    assert bt_executor._balance_cents < 10000


@pytest.mark.asyncio
async def test_bt_no_fill_when_spread_wide(bt_executor):
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=48,
    )
    await bt_executor.submit_order(req)

    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(46, 100)],
        yes_asks=[OrderbookLevel(52, 100)],
    )
    await bt_executor.process_orderbook_tick("TEST", book)
    assert bt_executor.total_fills == 0


@pytest.mark.asyncio
async def test_bt_equity_curve(bt_executor, bus):
    req = OrderRequest(
        ticker="TEST", side=Side.YES, action=Action.BUY,
        count=5, price_cents=50,
    )
    await bt_executor.submit_order(req)

    book = Orderbook(
        ticker="TEST",
        yes_bids=[OrderbookLevel(49, 100)],
        yes_asks=[OrderbookLevel(50, 100)],
    )
    await bt_executor.process_orderbook_tick("TEST", book)
    await bus.drain()
    await asyncio.sleep(0.1)

    curve = bt_executor.get_equity_curve()
    assert len(curve) >= 2
    assert curve[0][1] == 10000  # starting balance


@pytest.mark.asyncio
async def test_bt_cancel_all(bt_executor):
    for i in range(3):
        await bt_executor.submit_order(OrderRequest(
            ticker=f"T-{i}", side=Side.YES, action=Action.BUY,
            count=1, price_cents=50,
        ))
    count = await bt_executor.cancel_all()
    assert count == 3


# ---------------------------------------------------------------------------
# Data loader / parsing tests
# ---------------------------------------------------------------------------

class TestParseCandlestick:
    def test_valid_candle(self):
        candle = {
            "end_period_ts": 1703000000,
            "yes_bid": {"close": "0.48"},
            "yes_ask": {"close": "0.52"},
            "price": {"close": "0.50"},
            "volume_fp": "250.00",
            "open_interest_fp": "1200.00",
        }
        tick = _parse_candlestick("TEST", candle)
        assert tick is not None
        assert tick.ticker == "TEST"
        assert tick.yes_bid_cents == 48
        assert tick.yes_ask_cents == 52
        assert tick.volume == 250

    def test_missing_timestamp(self):
        candle = {"yes_bid": {"close": "0.50"}, "yes_ask": {"close": "0.52"}}
        tick = _parse_candlestick("TEST", candle)
        assert tick is None

    def test_bid_ask_sanity(self):
        """Bid should always be less than ask."""
        candle = {
            "end_period_ts": 1703000000,
            "yes_bid": {"close": "0.55"},
            "yes_ask": {"close": "0.50"},
            "price": {"close": "0.52"},
        }
        tick = _parse_candlestick("TEST", candle)
        assert tick is not None
        assert tick.yes_ask_cents > tick.yes_bid_cents


class TestHistoricalTick:
    def test_to_orderbook(self):
        tick = HistoricalTick(
            timestamp=datetime.now(UTC),
            ticker="TEST",
            yes_bid_cents=48,
            yes_ask_cents=52,
        )
        book = tick.to_orderbook()
        assert book.ticker == "TEST"
        assert book.best_bid() == 48
        assert book.best_ask() == 52


class TestHistoricalDataset:
    def test_duration(self):
        now = datetime.now(UTC)
        ds = HistoricalDataset(
            ticker="TEST",
            series_ticker="SERIES",
            start_time=now,
            end_time=datetime.fromtimestamp(now.timestamp() + 7200, tz=UTC),
        )
        assert abs(ds.duration_hours - 2.0) < 0.01


# ---------------------------------------------------------------------------
# Stats helper tests
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_no_drawdown(self):
        now = datetime.now(UTC)
        curve = [(now, 100), (now, 110), (now, 120)]
        dd_cents, dd_pct = _compute_max_drawdown(curve)
        assert dd_cents == 0

    def test_simple_drawdown(self):
        now = datetime.now(UTC)
        curve = [(now, 100), (now, 120), (now, 90), (now, 110)]
        dd_cents, dd_pct = _compute_max_drawdown(curve)
        assert dd_cents == 30  # 120 → 90
        assert abs(dd_pct - 25.0) < 0.1  # 30/120 = 25%

    def test_empty_curve(self):
        dd_cents, dd_pct = _compute_max_drawdown([])
        assert dd_cents == 0


class TestSharpe:
    def test_positive_returns(self):
        now = datetime.now(UTC)
        curve = [(now, 100), (now, 102), (now, 104), (now, 106)]
        sharpe = _compute_sharpe(curve)
        assert sharpe > 0

    def test_negative_returns(self):
        now = datetime.now(UTC)
        curve = [(now, 100), (now, 98), (now, 96), (now, 94)]
        sharpe = _compute_sharpe(curve)
        assert sharpe < 0

    def test_empty_curve(self):
        assert _compute_sharpe([]) == 0.0
